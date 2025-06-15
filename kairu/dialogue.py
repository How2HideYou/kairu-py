from collections.abc import Callable, Hashable, Sequence
from dataclasses import dataclass
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from wx import Frame, Panel, Sizer, Colour


ButtonKeyOrCallback = Hashable|Callable[[], Any]

@dataclass(frozen=True, slots=True)
class Message:
    """
    吹き出しに表示できるメッセージ
    """

    msg:     str
    "メッセージ本文"

    color:   tuple[int, int, int] | int | str | None = None
    "メッセージテキストの色"

    buttons: Sequence[tuple[str, ButtonKeyOrCallback]] = ()
    "((ボタンテキスト, クリック時にコールバックに渡されるキーもしくは実行されるコールバック), ...)"

    width:   int = 0
    "吹き出しの幅(ピクセル)"

    @property
    def wx_colour(self) -> Optional['Colour']:
        from wx import Colour
        match self.color:
            case None:         return None
            case tuple() as t: return Colour(*t)
            case int()   as i: return Colour(*i.to_bytes(length=3, byteorder='big')) # Colour() にintを入力すると、なぜかBGRとして扱われてしまうが、それ以外だとRGBとして扱われる
            case str()   as s: return Colour(*int(s.removeprefix('#'), base=16).to_bytes(length=3, byteorder='big'))
            case invalid:      raise  TypeError(type(invalid))


FrameInitializer = Callable[['Frame', 'Panel', 'Sizer'], Any]


__all__ = ('ButtonKeyOrCallback', 'Message', 'FrameInitializer')