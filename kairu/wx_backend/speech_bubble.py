from typing import Any, Literal, Optional
from functools import lru_cache
from collections.abc import Callable, Hashable, Iterable, Sequence

import wx
from wx.lib.expando import ExpandoTextCtrl, EVT_ETC_LAYOUT_NEEDED

from ..dialogue import FrameInitializer, Message
from .._util import BITMAP_DRAW_OFFSET, IS_WINDOWS


_RADIUS = 10
_CONTENT_OFFSET = 8
_TIP_HEIGHT = 17
_TIP_WIDTH  = 10

_BG_COLOR = (0xfd, 0xff, 0xd4)
_BG_COLOR_DARK_MODE = (0x11, 0x22, 0x88)


@lru_cache(maxsize=1)
def bg_color():
    is_light = IS_WINDOWS or not wx.SystemSettings().GetAppearance().IsDark()
    return wx.Colour(*_BG_COLOR) if is_light else wx.Colour(*_BG_COLOR_DARK_MODE)


class SpeechBubbleFrame(wx.Frame):
    """
    吹き出しのウィンドウ
    """
    background: Optional[wx.Bitmap]
    region:     Optional[wx.Region]
    root_panel: wx.Panel
    root_sizer: wx.Sizer

    text_ctrl:     Optional[ExpandoTextCtrl] = None
    buttons:       Sequence[wx.Button] = []
    buttons_sizer: wx.Sizer

    _visibility_flags: list[bool]
    """
    このリストの全ての要素が`True`の場合のみ、吹き出しが表示される。
    `[表示する状態になっているかどうか, いずれかのウィンドウがフォーカスされているかどうか]`を表している。
    """


    def __init__(self, parent:wx.Frame, frame_initializer:Optional[FrameInitializer]=None):

        super().__init__(parent=parent, style=wx.FRAME_SHAPED|wx.SIMPLE_BORDER|wx.STAY_ON_TOP, title='Speech Bubble', pos=wx.Point(10, 10))
        self.background = None
        self.region = None
        parent.Bind(wx.EVT_MOVE, self._OnParentMove)
        self.Bind(wx.EVT_PAINT, self._OnPaint)

        self._reset_root_panel()

        if frame_initializer:
            frame_initializer(self, self.root_panel, self.root_sizer)
        else:
            self._add_text_box()
            self.buttons_sizer = wx.WrapSizer()
            self.root_sizer.Add(self.buttons_sizer)

        self._visibility_flags = [True, wx.App.Get().IsActive()]

        self.SetAutoLayout(True)
        self.update_size()


    def _reset_root_panel(self):
        self.root_panel = wx.Panel(self, pos=wx.Point(_CONTENT_OFFSET, _CONTENT_OFFSET))
        self.root_panel.SetBackgroundColour(bg_color())
        self.root_sizer = wx.BoxSizer(orient=wx.VERTICAL)
        self.root_panel.SetSizer(self.root_sizer)


    def _add_text_box(self):
        self.text_ctrl = ExpandoTextCtrl(self.root_panel, value='', style=wx.TE_MULTILINE, size=wx.Size(224, -1))
        self.text_ctrl.SetBackgroundColour(bg_color())
        self.Bind(EVT_ETC_LAYOUT_NEEDED, self._OnRefit, self.text_ctrl)
        self.root_sizer.Add(self.text_ctrl, 0, wx.EXPAND)


    def _OnRefit(self, event=None):
        self.update_size()


    def _OnPaint(self, event=None):
        if self.background:
            dc = wx.BufferedPaintDC(self)
            dc = wx.GCDC(dc)
            dc.Clear()
            dc.DrawBitmap(self.background, wx.Point(*BITMAP_DRAW_OFFSET))
            reg = self.region
            if reg:
                wx.CallAfter(lambda: self.SetShape(reg))


    def _OnParentMove(self, event=None):
        self.SetPosition(wx.Point(self.Parent.Position.x + 0, self.Parent.Position.y - self.background.Height if self.background else 0))


    def update_size(self):
        """
        吹き出しの大きさを変えるときに、呼び出さなければならない。
        吹き出しの大きさを自動的に調整し、背景を再生成する。
        """
        self.root_sizer.Fit(self)
        size = self.GetSize()
        self.background, self.region = _generate_bubble_background(size.x, size.y)
        self.SetSize(size.x + _CONTENT_OFFSET * 2, size.y + _CONTENT_OFFSET * 2 + _TIP_HEIGHT)
        self.root_panel.SetSize(size)
        self._OnParentMove()
        self.Refresh()


    def set_components(self, components:Iterable):
        self.root_sizer.Clear()
        for comp in components:
            self.root_sizer.Add(comp)
        self.update_size()


    def say(self, msg:str|Message, button_callback:Optional[Callable[[str, Hashable], Any]]=None):

        if self.text_ctrl == None:
            raise RuntimeError('メッセージ用のTextCtrlが存在しません')

        if isinstance(msg, str):
            msg = Message(msg)

        resized = False
        if msg.width > 0 and self.text_ctrl:
            self.text_ctrl.SetInitialSize(wx.Size(msg.width, -1))
            resized = True

        if self.buttons or msg.buttons:
            # ボタンをすべて消去
            self.buttons_sizer.Clear(True)

            # 新しくボタンを追加
            for button_text, user_obj in msg.buttons:
                button = wx.Button(self.root_panel, label=button_text)
                button.SetBackgroundColour(bg_color())
                def _button_callback(_, _button_text=button_text, _user_obj=user_obj):
                    if callable(button_callback):
                        button_callback(_button_text, _user_obj)
                button.Bind(wx.EVT_BUTTON, _button_callback)
                self.buttons_sizer.Add(button)

            self.buttons_sizer.Layout()
            self.root_sizer.Layout()
            resized = True

        self.text_ctrl.SetValue(msg.msg)

        if resized:
            self.Fit()
            self.update_size()
            self._OnParentMove()
            self.Refresh()

        colour = msg.wx_colour
        if colour:
            self.text_ctrl.SetForegroundColour(colour)

        self.set_visibility_flag(True)


    def set_visibility_flag(self, value:bool, *, flag:Literal[0,1]=0):
        self._visibility_flags[flag] = value
        if all(self._visibility_flags):
            self.Show()
        else:
            self.Hide()


def _generate_bubble_background(width:int, height:int) -> tuple[wx.Bitmap, wx.Region]:
    """
    吹き出しの背景と、ウィンドウの形状を表す`Region`を生成する
    """

    rect_w = width  + _CONTENT_OFFSET*2
    rect_h = height + _CONTENT_OFFSET*2
    bm =  wx.Bitmap(width=rect_w, height=rect_h + _TIP_HEIGHT)
    mdc = wx.MemoryDC(bm)

    mdc.SetBrush(wx.Brush(bg_color()))
    mdc.SetPen  (wx.Pen(wx.Colour(1, 1, 1)))
    mdc.DrawRoundedRectangle(0, 0, rect_w, rect_h, _RADIUS)

    tip_points = [wx.Point(x, y) for x, y in ((0, 0), (0, _TIP_HEIGHT), (_TIP_WIDTH, -1))]
    mdc.SetPen  (wx.Pen(bg_color()))
    mdc.DrawPolygon(tip_points, rect_w // 2, rect_h - 1)
    mdc.SetPen  (wx.Pen(wx.Colour(1, 1, 1)))
    mdc.DrawLines  (tip_points , rect_w // 2, rect_h - 1)

    return bm, wx.Region(bm, transColour=wx.Colour(0))


__all__ = ('SpeechBubbleFrame', )