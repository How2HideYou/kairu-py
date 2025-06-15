from abc import ABC, abstractmethod
from collections.abc import Iterator
import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..agent_window import AgentFrame


class ChatBackendError(Exception):
    "返事の生成中にエラーが発生したことを示す。"
    error_msg: str

    def __init__(self, error_msg:str):
        self.error_msg = error_msg

class ChatBackend(ABC):
    """
    1. インスタンスが生成される(`__init__`)
    2. バックエンドスレッドでモデルやサブプロセスなどの初期化が行われる(`init_backend`)。
    3. [送信]ボタンが押されると、`get_response`が呼び出され、メッセージが吹き出しに書き込まれていく。
    """

    @abstractmethod
    def __init__(self, agent:'AgentFrame', model:str):
        ...

    def init_backend(self) -> None:
        """
        AIモデルの読み込みや、サブプロセスの起動などの時間のかかる処理をここで行う。
        チャットバックエンド専用の独立したスレッドで実行される。
        このメソッドが完了したら、準備が完了した合図である。
        """
        pass

    @abstractmethod
    def respond(self, prompt_by_user:str, output:asyncio.Queue[str]) -> None:
        """
        メッセージを送信し、返事をもらう。

        出力されたメッセージの**差分**を`output`に書き込んでいく。
        エラーが発生した場合、それを説明させるメッセージを引数にもつ`ChatBackendError`を`raise`する。
        なお、`output`にはサイズの上限がないので、`put_nowait`を使うと良い。
        なお、チャットバックエンド専用の独立したスレッドで実行される。
        """
        ...

    def has_options_dialog(self) -> bool:
        "[オプション]ボタンを有効にするかどうか"
        return False

    def show_options_dialog(self) -> None:
        "[オプション]ボタンが押されると呼び出される。"
        pass


class IteratorChatBackend(ChatBackend):

    @abstractmethod
    def get_response(self, prompt_by_user:str) -> Iterator[str]:
        ...

    def respond(self, prompt_by_user:str, output:asyncio.Queue[str]):
        try:
            for delta in self.get_response(prompt_by_user):
                output.put_nowait(delta)
        except Exception as error:
            raise ChatBackendError('メッセージの生成に失敗しました。') from error


class RepeatingDummyChatBackend(IteratorChatBackend):
    "入力をオウム返しするだけ"

    delay:float
    interval:float

    def __init__(self, agent:'AgentFrame', model:str, delay:float=0.5, interval:float=0.05):
        self.delay = delay
        self.interval = interval

    def get_response(self, prompt_by_user: str) -> Iterator[str]:
        import time
        print(self.delay)
        time.sleep(self.delay)
        for letter in prompt_by_user:
            yield letter
            time.sleep(self.interval)


__all__ = ('ChatBackendError', 'ChatBackend', 'IteratorChatBackend', 'RepeatingDummyChatBackend')