from collections.abc import Callable, Generator
from contextlib import contextmanager
from functools import wraps
import logging
from typing import Any, Generic, ParamSpec, TypeVar

import wx


_LOG = logging.getLogger(__name__)

_P = TypeVar('_P', bound=wx.Window)
class SinglePanelFrame(wx.Frame, Generic[_P]):
    panel: _P

    def __init__(self, panel_factory:Callable[[wx.Frame], _P], *wx_args, **wx_kwargs):
        super().__init__(*wx_args, **wx_kwargs)
        self.panel = panel_factory(self)


def button(parent:wx.Window, label:str, action:Callable[[], Any], **kwargs):
    btn = wx.Button(parent, label=label, **kwargs)
    btn.Bind(wx.EVT_BUTTON, lambda _:action())
    return btn


_SIZER = TypeVar('_SIZER', bound=wx.Sizer)

class SizerStack:
    owner: wx.Window
    stack: list[wx.Sizer] = []

    def __init__(self, owner:wx.Window):
        self.owner = owner

    @property
    def top(self) -> wx.Sizer:
        if self.stack:
            return self.stack[-1]
        else:
            raise IndexError('Sizerがありません')

    @property
    def Add(self):
        return self.top.Add

    @contextmanager
    def sizer(self, sizer:_SIZER, **kwargs) -> Generator[_SIZER, None, None]:
        try:
            is_root = not self.stack

            if is_root:
                self.owner.SetSizer(sizer)
                if kwargs:
                    _LOG.warning('ルートsizerのオプションを**kwargsで指定することはできません')
            else:
                self.top.Add(sizer, **kwargs)

            self.stack.append(sizer)
            yield sizer

            if is_root:
                self.owner.SetAutoLayout(True)
                sizer.Fit(self.owner)
        finally:
            self.stack.pop()

_PS = ParamSpec('_PS')

def wrap_with_callafter(func:Callable[_PS, Any]) -> Callable[_PS, None]:
    @wraps(func)
    def _wrapper(*args:_PS.args, **kwargs:_PS.kwargs) -> None:
        if not wx.IsMainThread(): # type: ignore 型アノテーションが間違っている
            wx.CallAfter(func, *args, **kwargs)
        else:
            func(*args, **kwargs)
    return _wrapper


class FloatSliderWithLabel(wx.Control):
    slider:   wx.Slider
    division: int

    def __init__(self, root_panel:wx.Window, min:float, max:float, value:float, division:int=100, format:str='%1.2f'):
        super().__init__(root_panel)
        self.division = division
        self.SetSizer(sizer := wx.BoxSizer())
        sizer.Add(label := wx.StaticText(self, label=format % value), border=8, flag=wx.ALIGN_CENTER_VERTICAL|wx.RIGHT)
        self.slider = wx.Slider(self, minValue=int(min*division), maxValue=int(max*division), value=int(value*division))
        sizer.Add(self.slider)
        self.slider.Bind(wx.EVT_SLIDER, lambda _: label.SetLabel(format % self.Value))

    @property
    def Value(self) -> float:
        return self.slider.GetValue() / self.division
    
    @Value.setter
    def Value(self, value:float):
        self.slider.Value = value # type: ignore