from typing import Optional
from itertools import pairwise
import math

import wx

from ..anim_controller import AnimController
from ..structs import AnimInfo, BranchInfo


class AnimationVisualizer(wx.Panel):
    anim_controller:          AnimController
    root_sizer:               wx.Sizer
    anim_info:                Optional[AnimInfo] = None
    node_entries:             list[tuple[wx.Button, list[BranchInfo]]] = []
    frame_index_to_node_index:list[int] = []

    _last_anim_info:          Optional[AnimInfo] = None
    _playing_node_index:      int = -1

    def __init__(self, parent:wx.Frame, anim_controller:AnimController):
        super().__init__(parent)
        self.anim_controller = anim_controller

        self.root_sizer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(self.root_sizer)

        self.Bind(wx.EVT_PAINT, self.OnPaint)

    def OnPaint(self, _=None):
        if self.anim_info:
            margin = self.GetSize().x // 2
            dc = wx.PaintDC(self)
            dc.Clear()
            gc:wx.GraphicsContext = wx.GraphicsContext.Create(dc)
            assert gc
            gc.SetPen(wx.BLACK_PEN)

            for i, (btn0, end_branch_info) in enumerate(self.node_entries):
                for branch_info in end_branch_info:
                    target_index = self.frame_index_to_node_index[branch_info.jump_target_idx]
                    is_forward = target_index > i

                    btn1 = self.node_entries[target_index][0]
                    pos0 = btn0.Position + wx.Point(btn0.GetSize().x if is_forward else 0, btn1.GetSize().y - 2) # type: ignore # ボタンの右下もしくは左下
                    pos1 = btn1.Position + wx.Point(btn1.GetSize().x if is_forward else 0, 2) # type: ignore # ボタンの右上もしくは左上
                    control_offset = math.ceil((pos1.y - pos0.y) / self.root_sizer.GetSize().y * margin)

                    path:wx.GraphicsPath = gc.CreatePath()
                    path.MoveToPoint(pos0.x, pos0.y)
                    path.AddCurveToPoint(
                        pos0.x + control_offset, pos0.y,
                        pos1.x + control_offset, pos1.y,
                        pos1.x, pos1.y
                    )

                    gc.StrokePath(path)

            gc.Flush()


    def tick(self, playing_anim:AnimInfo, frame_idx:int) -> bool:
        if self._last_anim_info != playing_anim:
            self._last_anim_info = playing_anim
            if playing_anim:
                self.set_anim(playing_anim)
            return True

        self.set_playing_frame_index(frame_idx)
        return False


    def set_anim(self, anim_info:AnimInfo):
        self.anim_info = anim_info
        self.root_sizer.Clear(True)
        self.node_entries.clear()
        self.frame_index_to_node_index.clear()
        self._playing_node_index = -1
        self.root_sizer.Add(wx.StaticText(self, label=anim_info.name))

        node_indices = set([0, len(anim_info.frames)])
        for i, frame in enumerate(anim_info.frames):
            if frame.branch_infos:
                node_indices.add(i + 1)
                for branch in frame.branch_infos:
                    node_indices.add(branch.jump_target_idx)

        node_indices = sorted(node_indices)
        for i, (start, end_plus_one) in enumerate(pairwise(node_indices)):
            end = end_plus_one - 1
            branch_infos = anim_info.frames[end].branch_infos

            duration = sum( f.duration_centiseconds for f in anim_info.frames[start:end_plus_one] )
            btn = wx.Button(self, label=f'Frame {start}: {duration}')
            btn.Bind(wx.EVT_BUTTON, lambda *_, __start=start: self.anim_controller.play_animation(anim_info, starting_frame=__start))
            self.root_sizer.Add(btn, border=120, flag=wx.LEFT|wx.RIGHT)
            self.node_entries.append((btn, branch_infos))
            if sum( branch.prob_percent for branch in branch_infos ) >= 100:
                self.root_sizer.AddSpacer(15)

            for _ in range(start, end_plus_one):
                self.frame_index_to_node_index.append(i)

        self.root_sizer.Layout()
        self.Fit()
        self.Refresh()


    def set_playing_frame_index(self, index:int):
        node_index = self.frame_index_to_node_index[index] if 0 <= index < len(self.frame_index_to_node_index) else -1
        if self._playing_node_index != node_index:
            if self._playing_node_index >= 0:
                self.node_entries[self._playing_node_index][0].SetBackgroundColour(wx.WHITE)
            self.node_entries[node_index][0].SetBackgroundColour(wx.RED)
            self._playing_node_index = node_index
            self.Refresh()
