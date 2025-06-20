from collections.abc import Callable, Coroutine, Generator, Hashable, Iterator
import itertools
import threading
from typing import Any, Optional, TYPE_CHECKING, TypeVar
from random import Random
import logging
from dataclasses import dataclass
import asyncio

from .dialogue import ButtonKeyOrCallback, Message
from .structs import AnimInfo, USE_RETURN_ANIMATION, FrameInfo
from ._util import done_future, report_errors

if TYPE_CHECKING:
    from typing_extensions import Self


_LOG = logging.getLogger(__name__)

_INF = float('inf')


StopAnimation: object = 'Stop Animation'
"アニメーションだけをキャンセルする目的で、`CancelledError`の引数に使う。"

Stop: object = 'Stop'
"`AnimController`を停止させる目的で、`CancelledError`の引数に使う。"


_X = TypeVar('_X')

@dataclass(repr=False, eq=False)
class AsyncEventLoopHolder:
    event_loop:        Optional[asyncio.AbstractEventLoop] = None
    event_loop_thread: Optional[threading.Thread] = None


    def start(self):
        """
        イベントループを起動する。
        メインスレッドをブロックしないように、新しいスレッドからイベントループを開始する。
        """

        if self.event_loop or self.event_loop_thread:
            raise RuntimeError('イベントループはすでに設定されています')

        self.event_loop = asyncio.get_event_loop()
        def _async_thread():
            asyncio.set_event_loop(self.event_loop)
            assert self.event_loop
            self.event_loop.run_forever()
        self.event_loop_thread = threading.Thread(target=_async_thread, daemon=True, name='Animation')
        self.event_loop_thread.start()
        asyncio.set_event_loop(self.event_loop)


    def create_task(self, coro:Coroutine[Any, Any, _X]) -> asyncio.Future[_X]:
        """
        スレッドセーフにコルーチンの実行を開始する。このメソッドがあるので、`asyncio.create_task`は使ってはならない。
        """
        if not (self.event_loop and self.event_loop_thread):
            raise RuntimeError('イベントループが起動されていません')

        if threading.current_thread() is self.event_loop_thread:
            # event_loopのスレッドから呼び出された
            #LOG.info(f'event_loopのスレッドから呼び出されました: {coro}')
            return self.event_loop.create_task(coro)
        else:
            # ほかのスレッドから呼び出された
            #LOG.info(f'他のスレッドから呼び出されました: {coro}')
            return asyncio.wrap_future(asyncio.run_coroutine_threadsafe(coro, self.event_loop), loop=self.event_loop)


    def create_future(self) -> asyncio.Future:
        if not (self.event_loop and self.event_loop_thread):
            raise RuntimeError('イベントループが起動されていません')
        return self.event_loop.create_future()


class GUIBackend(AsyncEventLoopHolder):
    """
    フレームの表示、音声再生、吹き出しの描画を担当する。
    """

    def play_frame(self, anim:AnimInfo, frame:FrameInfo, frame_idx:int) -> None:
        """
        指定されたフレームに表示を切り替え、frameで指定された音声を再生する。
        """
        raise NotImplementedError()

    def say(self, msg:Message, button_callback:Optional[Callable[[str, Hashable], Any]]=None) -> None:
        """
        吹き出しを表示する。
        `msg`に`buttons`が含まれていて、ボタンが押された場合には`button_callback`を呼び出さなければならない。
        """
        raise NotImplementedError('このバックエンドでは吹き出しの表示がサポートされていません')


@dataclass(repr=False, eq=False, slots=True)
class AnimationTask:
    anim_ctrl:            'AnimController'
    task:                  asyncio.Future[bool]
    animation:             Optional[AnimInfo]
    no_wait:               bool
    requests_exit_on_exit: bool = False

    def request_exit(self) -> 'Self':
        """
        このアニメーションの終了をリクエストする。
        自分自身を返すため、`await animation_task.request_exit()`はアニメーションの終了をリクエストして終了を待機することを意味する。
        """
        self.anim_ctrl.request_exit()
        return self

    def request_exit_on_exit(self) -> 'Self':
        "`async with`から脱出する際にアニメーションの終了をリクエストするようにする"
        self.requests_exit_on_exit = True
        return self

    def __await__(self) -> Generator[None, None, bool]:
        "アニメーションの再生が終了するのを待機する"
        if self.no_wait:
            return done_future(False).__await__()
        return self.task.__await__()

    async def __aenter__(self) -> 'Self':
        return self

    async def __aexit__(self, exception_type, exception, traceback) -> None:
        if self.requests_exit_on_exit:
            self.request_exit()
        await self

    def __str__(self) -> str:
        return f'{self.__class__.__name__}({self.animation.name if self.animation else "<None>"})'


@dataclass(repr=False, eq=False, slots=True)
class SayTask:
    anim_ctrl:'AnimController'
    task:      asyncio.Future[Optional[Hashable]]

    def __await__(self):
        """
        ボタンがある場合には、いずれかのボタンが押されるまで待機し、押されたボタンのtupleの2つ目のオブジェクトが返される。
        ボタンがない場合には、即座に`None`が返される。
        """
        return self.task.__await__()

    async def __aenter__(self) -> 'Self':
        return self

    async def __aexit__(self, exception_type, exception, traceback) -> None:
        await self.task


@dataclass(repr=False, eq=False, slots=True, init=False)
class AnimController:
    """
    本体ウィンドウのアニメーションの制御を行う。
    """

    backend:        GUIBackend

    rand:           Random
    anim_infos:     dict[str, AnimInfo]
    state_infos:    dict[str, list[str]]
    speed:          float # 速度の逆数
    no_idle:        bool
    idle_all_anims: bool
    do_not_skip_zero_duration_frames: bool

    exit_requested: bool

    _anim_task: AnimationTask
    _say_task:  SayTask


    def __init__(self,
        backend:        GUIBackend,
        anim_infos:     dict[str, AnimInfo],
        state_infos:    dict[str, list[str]],
        *,
        rand:           Optional[Random] = None,
        speed:          float = 1,
        no_idle:        bool = False,
        idle_all_anims: bool = False,
        do_not_skip_zero_duration_frames: bool = False, # 長さがゼロのフレームであっても描画するかどうか
        **_
    ):
        self.backend = backend
        self.anim_infos = anim_infos
        self.state_infos = state_infos

        self.rand = rand or Random()
        self.speed = speed
        self.no_idle = no_idle
        self.idle_all_anims = idle_all_anims
        self.do_not_skip_zero_duration_frames = do_not_skip_zero_duration_frames
        self.exit_requested = False

        self._anim_task = AnimationTask(self, done_future(False), None, False)
        self._say_task  = SayTask(self, done_future(None))


    @report_errors(_LOG)
    async def __play(self, anim:AnimInfo, play_idle_animation_afterwards:bool, start_delay:float, starting_frame:int, jump_sequence:Optional[Iterator[int]], reappear:bool) -> bool:
        def random_infinite_iterator():
            while True: yield self.rand.randrange(0, 100)

        jump_sequence = itertools.chain(jump_sequence, random_infinite_iterator()) if jump_sequence else random_infinite_iterator()

        try:
            # なぜか、sleep中にcancelが入ってもsleepが終了するまで待ってしまうので、
            # 細かく区切ることで無理やりこの現象を回避している
            while start_delay > 0:
                duration = min(0.05, start_delay)
                await asyncio.sleep(duration)
                start_delay -= duration

            _LOG.info(f'アニメーションを再生します: {anim.name}')

            frame_idx = starting_frame
            while True:
                frame = anim.frames[frame_idx]
                sleep_seconds = frame.duration_centiseconds * self.speed / 100
                if sleep_seconds > 0 or self.do_not_skip_zero_duration_frames:
                    # フレームを書き換え、音を再生する
                    self.backend.play_frame(anim, frame, frame_idx)
                await asyncio.sleep(sleep_seconds)

                # ジャンプ処理
                if self.exit_requested and frame.exit_index >= 0:
                    frame_idx = frame.exit_index
                else:
                    jump_dest = frame.pick_jump_destination(next(jump_sequence))
                    frame_idx = frame_idx + 1 if jump_dest is None else jump_dest

                if frame_idx >= len(anim.frames):
                    # アニメーションが終了した
                    if anim.transition_type == USE_RETURN_ANIMATION:
                        return await self.__play(self.anim_infos[anim.return_anim_name], play_idle_animation_afterwards, 0, 0, jump_sequence, reappear)
                    else:
                        break

            # reappearがTrueかつ消滅するアニメーションなら、出現アニメーションを再生する
            if reappear and anim.name in ('HIDE', 'GOODBYE') and 'SHOWING' in self.state_infos:
                show_anim = self.search_animation('#SHOWING')
                if show_anim: await self.__play(show_anim, False, 0.5, 0, jump_sequence, False)

            if play_idle_animation_afterwards and not self.no_idle:
                self._play_idle_animation_later()
            return True

        except asyncio.CancelledError as ce:
            if StopAnimation in ce.args:
                _LOG.info(f'アニメーションの再生が中断されました')
                return False
            elif Stop in ce.args:
                _LOG.info(f'アニメーションの再生が中断されました')
                return False
            else:
                _LOG.exception('アニメーションの再生で例外が発生しました')
                _LOG.error(ce.args)
                raise

        finally:
            self.exit_requested = False
            _LOG.info(f'アニメーションの再生が終了しました')


    def play_animation(
            self, anim:AnimInfo|str|None,
            *,
            not_awaitable:bool=False,
            start_delay:float=0,
            starting_frame:int=0,
            jump_sequence:Optional[Iterator[int]]=None,
            reappear:bool=False,
            _stop:bool=True
        ) -> AnimationTask:
        """
        アニメーションを再生し、**終了を待たずに** `AnimationTask`を返す。
        終了を待機するには、`await`する。

        **なお、`async`なコンテキストで実行されなければならない。**

        :param AnimInfo|str|None anim: `AnimInfo`、アニメーション名、#state名、`None`のいずれか。`#`で始まる文字列を入力した場合、そのstate名に属するランダムなアニメーションが選ばれる。
        :param bool not_awaitable: `=False` `True`の場合、`await`されても再生の終了を待たずにすぐに復帰する。
        :param float start_delay: `=0` アニメーションの再生を開始するまでの秒数。
        :param Optional[Iterator[int]] jump_sequence: `=None` 分岐先の決定に使われる`0`~`100`の整数のイテレーター。枯渇したらランダムな整数が使われる。
        :param bool reappear: `=False` 非表示になるアニメーションを再生し終わった後、出現するアニメーションを再生するかどうか。
        """
        if starting_frame:
            _LOG.info(starting_frame)
        if _stop: self.stop_animation(StopAnimation)
        anim = self.search_animation(anim)
        self.exit_requested = False
        task = self.backend.create_task(self.__play(anim, True, start_delay, starting_frame, jump_sequence, reappear)) if anim else done_future(False)
        self._anim_task = AnimationTask(self, task, anim, not_awaitable)
        _LOG.info(anim.name if anim else '<None>')
        return self._anim_task


    def _play_idle_animation_later(self):
        if self.idle_all_anims:
            idle_animations = tuple(self.anim_infos.values())
        else:
            idle_animations = tuple(filter(lambda n: n.name.lower().startswith('idle'), self.anim_infos.values()))
        if idle_animations:
            self.play_animation(
                self.rand.choice(idle_animations),
                not_awaitable=True,
                start_delay=self.rand.uniform(1, 4),
                reappear=True,
                _stop=False
            )


    def stop_animation(self, msg:object=None) -> None:
        self._anim_task.task.cancel(msg)


    def request_exit(self) -> bool:
        """
        現在のアニメーションを終了するように要求する。
        return: アニメーションが停止中か
        """
        self.exit_requested = True
        return self._anim_task.task.done()


    def search_animation(self, anim_info_or_name_or_state_name:AnimInfo|str|None) -> Optional[AnimInfo]:
        if anim_info_or_name_or_state_name is None:
            return None
        if isinstance(anim_info_or_name_or_state_name, AnimInfo):
            return anim_info_or_name_or_state_name

        anim_name = anim_info_or_name_or_state_name
        if anim_name and anim_name.startswith('#'):
            state_name = anim_name[1:]
            names = self.state_infos.get(state_name)
            if not names:
                _LOG.error(f'state名 {state_name} は存在しません')
                anim_name = None
            else:
                anim_name = self.rand.choice(names)

        if anim_name:
            anim_info = self.anim_infos.get(anim_name)
            if anim_info:
                return anim_info
            else:
                _LOG.error(f'アニメーション名 {anim_name} は存在しません')

        return None


    def say(self, msg:Optional[str|Message]) -> SayTask:
        """
        吹き出しを表示する。
        `await`することで、ボタンがあればいずれかが押されるまで待機することができる。

        なお、`msg`のボタンのコールバックは **wxPythonのスレッドから実行される**。
        """

        agent = self.backend
        button_signal:asyncio.Future[Optional[ButtonKeyOrCallback]] = done_future(None)
        if msg:
            if isinstance(msg, Message):
                if msg.buttons:
                    button_signal = self.backend.create_future()
            else:
                msg = Message(msg)

            def _button_callback(button_text:str, value:ButtonKeyOrCallback):
                if callable(value):
                    value()
                else:
                    print(value)
                # TODO: ボタンを非表示にするのではなく、無効化
                button_signal.set_result(value)

            agent.say(msg, _button_callback)

        self._say_task = SayTask(self, button_signal)
        return self._say_task


    async def interrupt(self) -> None:
        self.stop_animation(Stop)
        self._say_task.task.cancel(Stop)


__all__ = ('StopAnimation', 'Stop', 'GUIBackend', 'AnimationTask', 'SayTask', 'AnimController')