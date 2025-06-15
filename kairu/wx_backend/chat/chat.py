from concurrent.futures import ThreadPoolExecutor
import asyncio
from collections.abc import Callable, Coroutine
from typing import Any, Optional
import logging
import argparse
import json

import wx

from ...anim_controller import AnimController
from ...dialogue import Message
from ..speech_bubble import bg_color
from ..agent_window import AgentFrame
from .._wx_util import button, SizerStack
from .chat_backend import ChatBackend, ChatBackendError


_LOG = logging.getLogger(__name__)


def _drain(q:asyncio.Queue[str]) -> str:
    "今すぐ読み取れる分だけ`q`から文字列を読み取って結合する"

    buffer = ''
    while not q.empty():
        buffer += q.get_nowait()
    return buffer


async def agent_main(agent:AgentFrame, backend_executor:ThreadPoolExecutor, backend_type:Callable[[AgentFrame, str], ChatBackend], model:str, startup_animation:str, **backend_kwargs) -> None:

    backend = backend_type(agent, model, **backend_kwargs)

    input_queue = asyncio.Queue[str]()

    def set_up_how_can_i_help_you_speech_bubble(frame:wx.Frame, root_panel:wx.Panel, root_sizer:wx.Sizer):
        sizers = SizerStack(root_panel)

        with sizers.sizer(root_sizer):
            title_label = wx.StaticText(root_panel, label='何について調べますか？') # 残念ながらfont引数は無いようだ
            title_label.SetFont(wx.Font(13, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL, faceName='MS Sans Serif'))
            sizers.Add(title_label)
            sizers.top.AddSpacer(10)

            input_ctrl = wx.TextCtrl(root_panel, value='', style=wx.TE_MULTILINE|wx.TE_PROCESS_ENTER, size=wx.Size(210, 40))
            sizers.Add(input_ctrl, 1, flag=wx.EXPAND)
            sizers.top.AddSpacer(6)

            with sizers.sizer(wx.BoxSizer()):
                options_button = button(root_panel, 'オプション', backend.show_options_dialog)
                if not backend.has_options_dialog():
                    options_button.Disable()
                options_button.SetBackgroundColour(bg_color())
                sizers.Add(options_button, proportion=1)

                sizers.top.AddStretchSpacer()

                def _button_callback():
                    input_queue.put_nowait(input_ctrl.Value)
                    agent.hide_speech_bubble()
                send_button = button(root_panel, '送信', _button_callback)
                send_button.SetBackgroundColour(bg_color())
                sizers.Add(send_button, proportion=1)

            input_ctrl.Bind(wx.EVT_TEXT_ENTER, lambda e: _button_callback())

    # 初期化処理(backendスレッド)と登場のアニメーション
    anim_ctrl = agent.anim_ctrl
    init_future = asyncio.wrap_future(backend_executor.submit(backend.init_backend))
    await anim_ctrl.play_animation(startup_animation)
    if not init_future.done():
        async with anim_ctrl.play_animation('THINKING').request_exit_on_exit(), anim_ctrl.say('初期化中...'):
            await init_future
    else:
        await init_future

    while True:
        # 「何について調べますか?」の吹き出しを表示
        wx.CallAfter(agent.recreate_speech_bubble, set_up_how_can_i_help_you_speech_bubble)

        # ユーザが[送信]を押すのを待機
        user_prompt = await input_queue.get()
        thinking_anim = anim_ctrl.play_animation('THINKING')
        response_queue = asyncio.Queue()
        # backendスレッドで返事を生成
        response_future = backend_executor.submit(backend.respond, user_prompt, response_queue)
        full_msg = ''

        # 返事を表示していく
        while not response_future.done() or not response_queue.empty():
            delta = _drain(response_queue)
            if delta:
                if thinking_anim:
                    await thinking_anim.request_exit()
                    anim_ctrl.play_animation('EXPLAIN')
                    thinking_anim = None
                full_msg += delta
                anim_ctrl.say(full_msg)

            await asyncio.sleep(0.1)

        # 返事の生成で発生したエラーの確認・処理
        try:
            if thinking_anim:
                await thinking_anim.request_exit()
            response_future.result(0)
        except ChatBackendError as cbe:
            _LOG.exception('チャットバックエンドでエラーが発生しました')
            async with anim_ctrl.play_animation('EXPLAIN', not_awaitable=True):
                choice = await anim_ctrl.say(Message(str(cbe.error_msg), color='#ff0000', buttons=(('OK', 'OK'), ('終了', 'goodbye'))))
                if choice == 'goodbye':
                    break
        else:
            # 正常に返事が終了
            await anim_ctrl.say(Message(full_msg, buttons=(('OK', 'OK'),)))

    wx.CallAfter(agent.goodbye)


def start(
    acs_path:          str,
    backend_type:      Optional[Callable[[AgentFrame, str], ChatBackend]] = None, # Noneなら吹き出しを表示しない
    model:             Optional[str] = None, # Noneなら吹き出しを表示しない
    *, 
    base_url:          Optional[str] = None,
    log_level:         str = 'INFO',
    stdout:            bool = False,
    backend_kwargs:    Optional[dict[str, Any]]|str = None,
    startup_animation: str = 'GREETING',
    **kwargs
):
    import sys
    log_config: dict[str, Any] = {
        'level': log_level
    }
    if stdout: log_config['stream'] = sys.stdout
    logging.basicConfig(**log_config)

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix='Chat-Backend') as backend_executor:
        action: Callable[[AgentFrame, AnimController], Coroutine]
        if backend_type is None or not model or kwargs.get('no_speech_bubble'):
            async def _greeting(a, ac:AnimController):
                ac.play_animation(startup_animation) # 吹き出しなしで起動。チャットはできない
            action = _greeting
        elif kwargs.get('animation_test'):
            action = AgentFrame.show_all_animations_speech_bubble
        else:
            if backend_kwargs and isinstance(backend_kwargs, str):
                _backend_kwargs = json.loads(backend_kwargs)
            else:
                _backend_kwargs = backend_kwargs or {}
            if base_url:
                _backend_kwargs["base_url"] = base_url
            
            action = lambda a, ac: agent_main(a, backend_executor, backend_type, model, startup_animation, **_backend_kwargs)
        AgentFrame.run(acs_path, action, **kwargs)


from .chat_backend import RepeatingDummyChatBackend
from .langchain_backend import OpenAILangChainChatBackend, OllamaLangChainChatBackend, GoogleGenAILangChainChatBackend

BACKEND_TYPES = {
    'openai': OpenAILangChainChatBackend,
    'ollama': OllamaLangChainChatBackend,
    'google': GoogleGenAILangChainChatBackend,
    'repeat': RepeatingDummyChatBackend,
    'none':   None
}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('acs_path',                 nargs='?',             default='DOLPHIN.ACS', help='読み込むACSファイルを指定します')
    parser.add_argument('backend-type',             nargs='?',             choices=BACKEND_TYPES.keys())
    parser.add_argument('model',                    nargs='?',             metavar='AIモデル名', help='AIモデル名')
    parser.add_argument('-m', '--mute',             action='store_true',   help='ミュートの状態で起動します')
    parser.add_argument('-i', '--no-idle',          action='store_true',   help='アイドル時にアニメーションを再生しないようにします')
    parser.add_argument('-a', '--idle-all-anims',   action='store_true',   help='アイドル時に通常のアニメーションを再生するようにします')
    parser.add_argument('-s', '--no-speech-bubble', action='store_true',   help='吹き出しを常時非表示にします')
    parser.add_argument('-base-url',                required=False,        metavar='URL',  help='LLMのAPIのURLを指定します')
    parser.add_argument('-backend-kwargs',          required=False,        metavar='JSON', help='バックエンドのパラメーターをJSON辞書形式で指定します。コマンドラインで使うには、 \'{\\\"temperature\\\":0.5}\' のようにエスケープする必要があります。')
    parser.add_argument('-startup-animation',       required=False,        metavar='アニメーション名')
    parser.add_argument('-log-level',               required=False,        help='ログレベルを設定します', metavar='ログレベル')
    parser.add_argument('--animation-test',         action='store_true')
    parser.add_argument('--stdout',                 action='store_true',   help='ログの出力先を標準出力に強制します')

    ns = parser.parse_args()
    args = ns._get_args()
    kwargs = { key.replace('-', '_') : value for key, value in ns._get_kwargs() if value }

    backend_type = BACKEND_TYPES[kwargs.pop('backend_type', 'none')]
    if backend_type is not None and not ns.model:
        raise ValueError('none以外のbackend-typeが指定されましたがmodelが指定されていません')

    start(*args, backend_type=backend_type, **kwargs)


__all__ = ('agent_main', 'start')


if __name__ == '__main__':
    main()
