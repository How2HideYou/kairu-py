import random
from collections.abc import Callable, Coroutine, Hashable
from typing import Any, Optional
import logging
import asyncio

import wx
import wx.adv

from ..dialogue import FrameInitializer, Message
from ..acs_file import AcsFile
from ..anim_controller import AnimController, AnimationBackend
from ..structs import AnimInfo, FrameInfo
from .speech_bubble import SpeechBubbleFrame
from ._wx_util import SinglePanelFrame, wrap_with_callafter
from .._util import ImageDecompressionInterrupt, BITMAP_DRAW_OFFSET, report_errors
from .animation_visualizer import AnimationVisualizer


_LOG = logging.getLogger(__name__)


class AgentFrame(wx.Frame, AnimationBackend):
    acs:           AcsFile
    sprites:       list[wx.Bitmap]
    sounds:        list[Optional[wx.adv.Sound]]
    anim_ctrl:     AnimController
    speech_bubble: Optional[SpeechBubbleFrame] = None # 必要に応じて生成される
    mute:          bool

    _is_shown:         bool = False
    _last_region:      Any  = None
    _repaint_required: bool = True
    _frame_cache:      dict[int, tuple[list[wx.Bitmap], wx.Region]]
    _drag_delta:       tuple[int, int]
    _frame_info:       Optional[FrameInfo] # 表示中のフレーム

    visualizer: Optional[SinglePanelFrame[AnimationVisualizer]] = None

    def __init__(self, parent, acs:str|AcsFile, *, mute:bool=False, **anim_kwargs):
        super(wx.Frame, self).__init__(parent, style=wx.FRAME_SHAPED|wx.SIMPLE_BORDER|wx.STAY_ON_TOP)
        super(AnimationBackend, self).__init__()

        self._drag_delta = (0, 0)
        self.acs = acs if isinstance(acs, AcsFile) else AcsFile.from_file(acs, decompression_progress_gui=False)
        spritesheet_img = wx.Image(self.acs.spritesheet_path)
        spritesheet_img.ConvertAlphaToMask()
        spritesheet_bitmap:wx.Bitmap = spritesheet_img.ConvertToBitmap()
        self.sprites = [ spritesheet_bitmap.GetSubBitmap(wx.Rect(*box)) for box in self.acs.sprite_boxes ]
        self._frame_cache = {}

        loc_info = self.acs.localized_info()
        if loc_info:
            self.SetTitle(loc_info.name)
        size = self.acs.character_info.character_size
        self.SetSize(*size)

        size_half = wx.Point(size[0] // 2, size[1] // 2)
        self.SetPosition(wx.GetMousePosition() - size_half) # type: ignore

        self.anim_ctrl = AnimController(self, self.acs.anim_infos, self.acs.character_info.state_infos, **anim_kwargs)
        self._frame_info = None
        self.mute = mute

        self.sounds = []
        for sound_path in self.acs.sound_paths:
            sound = None
            if sound_path:
                try:
                    sound = wx.adv.Sound(sound_path)
                except Exception as e:
                    _LOG.error(f'音声ファイル {sound_path} を読み込めませんでした', exc_info=True)
            self.sounds.append(sound)

        self.Bind(wx.EVT_CLOSE,        self._OnClose)
        self.Bind(wx.EVT_PAINT,        self._OnPaint)
        self.Bind(wx.EVT_MOTION,       self._OnMouseMove)
        self.Bind(wx.EVT_LEFT_DOWN,    self._OnLeftDown)
        self.Bind(wx.EVT_LEFT_UP,      self._OnLeftUp)
        self.Bind(wx.EVT_LEFT_DCLICK,  self._OnDoubleClick)
        self.Bind(wx.EVT_RIGHT_DOWN,   self._OnRightClick)
        self.Bind(wx.EVT_RIGHT_DCLICK, self._OnRightDoubleClick)

        app:wx.App = wx.App.Get()
        app.Bind(wx.EVT_ACTIVATE_APP, self._OnActivate)

        """
        def reset_window_shape():
            self.SetShape(wx.Region())
        if wx.Platform == "__WXGTK__":
            self.Bind(wx.EVT_WINDOW_CREATE, reset_window_shape)
        else:
            reset_window_shape()
        """

        # 初めて描画が実行されるまでagentを非表示にする。
        # Show()を実行せずに非表示のままだと、そもそも形状を変える処理を含むOnPaintが呼び出されないので、表示はするが透明にしておく。
        self.SetTransparent(0)


    def _OnClose(self, event=None):
        wx.Exit()


    def _get_frame_bitmaps_and_region(self, frameinfo:FrameInfo) -> tuple[list[wx.Bitmap], wx.Region]:
        frame_id = id(frameinfo)
        if frame_id in self._frame_cache:
            return self._frame_cache[frame_id]
        else:
            bitmaps = [ self.sprites[frameimage.image_idx] for frameimage in frameinfo.frame_images ]
            if bitmaps:
                regions = [ wx.Region(bitmap) for bitmap in bitmaps]
                for region in regions[1:]:
                    regions[0].Union(region)
                region = regions[0]
            else:
                region = wx.Region(0, 0, 1, 1)
            self._frame_cache[frame_id] = bitmaps, region
            return bitmaps, region

    def _OnPaint(self, event=None):
        if self._frame_info == None:
            return

        bitmaps, region = self._get_frame_bitmaps_and_region(self._frame_info)

        if region != self._last_region:
            self._repaint_required = True

        if self._repaint_required:
            dc = wx.BufferedPaintDC(self)
            dc = wx.GCDC(dc)
            dc.Clear()
            for bitmap in reversed(bitmaps):
                dc.DrawBitmap(bitmap, *BITMAP_DRAW_OFFSET, useMask=len(bitmaps) != 1) # 画像が1枚だけなら、マスクを使って描画する必要はない
            self._repaint_required = False # 画像の描画が必要以上に行われるのを防ぐ

        if region != self._last_region:
            self._last_region = region
            # SetShapeが呼び出されると、ペイントイベントが生成されるので、OnPaintが再び呼び出される。
            self.SetShape(region)
            self._repaint_required = True

        if not self._is_shown:
            # 初めて描画が実行されたので、表示する。
            self.SetTransparent(255)
            self._is_shown = True


    @wrap_with_callafter
    def play_frame(self, anim:AnimInfo, frame:FrameInfo, frame_idx:int):
        self._frame_info = frame
        self.Refresh(False)
        if not self.mute and ( 0 <= frame.audio_idx < 65535 ):
            sound = self.sounds[frame.audio_idx]
            if sound:
                sound.Play()
        if self.visualizer:
            self.visualizer.panel.tick(anim, frame_idx)


    def _OnLeftDown(self, evt):
        self.CaptureMouse()
        x, y = self.ClientToScreen(evt.GetPosition())
        originx, originy = self.GetPosition()
        dx = x - originx
        dy = y - originy
        self._drag_delta = ((dx, dy))


    def _OnLeftUp(self, evt):
        if self.HasCapture():
            self.ReleaseMouse()


    def _OnMouseMove(self, evt):
        if evt.Dragging() and evt.LeftIsDown():
            x, y = self.ClientToScreen(evt.GetPosition())
            fp = (x - self._drag_delta[0], y - self._drag_delta[1])
            self.Move(fp) # type: ignore


    def _OnDoubleClick(self, evt):
        async def _async_func():
            self.anim_ctrl.play_animation(random.choice(tuple(self.acs.anim_infos.values())), reappear=True)
        self.create_task(_async_func())


    def _OnRightClick(self, evt):
        self.anim_ctrl.request_exit()


    def _OnRightDoubleClick(self, evt):
        self.goodbye()


    def _OnActivate(self, evt:wx.ActivateEvent):
        if self.speech_bubble:
            self.speech_bubble.set_visibility_flag(evt.GetActive(), flag=1)


    @wrap_with_callafter
    def goodbye(self):
        self.hide_speech_bubble()
        # 他のウィンドウを全て閉じる
        for window in wx.GetTopLevelWindows(): # type: ignore
            if window is not self:
                window.Hide()

        async def _goodbye():
            await self.anim_ctrl.interrupt()
            await self.anim_ctrl.play_animation('GOODBYE')
            wx.CallAfter(self.Close)

        self.create_task(_goodbye())


    @wrap_with_callafter
    def say(self, msg:str|Message, button_callback:Optional[Callable[[str, Hashable], Any]]=None):
        if self.speech_bubble and self.speech_bubble.text_ctrl:
            self.speech_bubble.say(msg, button_callback)
        else:
            if self.speech_bubble:
                self.speech_bubble.Hide()
                self.speech_bubble.DestroyChildren()
                self.speech_bubble.Destroy()
            self.speech_bubble = SpeechBubbleFrame(parent=self)
            self.speech_bubble.say(msg, button_callback)


    @wrap_with_callafter
    def hide_speech_bubble(self):
        if self.speech_bubble:
            self.speech_bubble.set_visibility_flag(False)


    @wrap_with_callafter
    def recreate_speech_bubble(self, frame_initializer:FrameInitializer):
        if self.speech_bubble:
            self.speech_bubble.set_visibility_flag(False, flag=1)
            self.speech_bubble.DestroyChildren()
            self.speech_bubble.Destroy()
        self.speech_bubble = SpeechBubbleFrame(self, frame_initializer)
        self.speech_bubble.set_visibility_flag(True)


    @report_errors(_LOG)
    async def show_all_animations_speech_bubble(self, *_):
        assert asyncio.get_running_loop() is asyncio.get_event_loop()
        assert asyncio.get_running_loop() is self.event_loop
        _LOG.info(self.acs.character_info.state_infos)
        self.anim_ctrl.no_idle = True
        await self.anim_ctrl.play_animation('GREETING')
        await self.anim_ctrl.say(Message('再生したいアニメーションのボタンをクリックしてください', width=500, buttons=tuple(
            (anim_name, lambda anim_name=anim_name: self.anim_ctrl.play_animation(anim_name)) for anim_name in self.acs.anim_infos.keys()
        )))


    @wrap_with_callafter
    def show_visualizer(self):
        self.visualizer = SinglePanelFrame(lambda f: AnimationVisualizer(f, self.anim_ctrl), parent=self)
        self.visualizer.Fit()
        self.visualizer.Show()


    @classmethod
    def run(cls, acs:str|AcsFile, action:Optional[Callable[['AgentFrame', AnimController], Coroutine]]=None, **anim_kwargs):
        """
        Officeアシスタントを召喚し、閉じられるまで待機する。
        wxの仕様上、このメソッドはメインスレッドから呼び出さなければならない。
        """

        try:
            app = wx.App.Get() or wx.App()
            agent = cls(None, acs, **anim_kwargs)

            agent.start()
            if callable(action):
                agent.create_task(action(agent, agent.anim_ctrl))
            agent.Show()

            if anim_kwargs.get('animation_test'):
                agent.acs.dump_animations()

            r"""
            from .gif_export_backend import GifExportBackend
            gif_backend = GifExportBackend(agent.acs, agent)
            gif_anim_cont = AnimController(gif_backend, agent.acs.anim_infos, agent.anim_cont.state_infos, speed=0, no_idle=True, do_not_skip_frames=True)
            async def _(): return await gif_anim_cont.play_animation('GREETING')
            def after_playing(*_):
                gif_backend.frames[0].save('test.gif', 'gif', save_all=True, append_images=gif_backend.frames[1:])
            asyncio.run_coroutine_threadsafe(_(), gif_backend.event_loop).add_done_callback(after_playing)
            """

            app.MainLoop()

        except ImageDecompressionInterrupt as e:
            _LOG.error(e)


__all__ = ('AgentFrame', )