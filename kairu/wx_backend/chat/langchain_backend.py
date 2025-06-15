from collections.abc import Iterator
import logging
from typing import Optional, TYPE_CHECKING
from uuid import UUID

from langchain_core.runnables import RunnableSerializable
from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
import requests

from ..agent_window import AgentFrame
from .chat_backend import ChatBackendError, IteratorChatBackend


_LOG = logging.getLogger(__name__)


CHARACTER_DESCRIPTIONS = {

    # カイル
    UUID('4caf3ad6-9c11-d211-8727-0000f8759339'):
    "You are カイル, an assistant dolphin here to help and reply casually in Japanese. "
    "You talk in a boyish calm tone. "
    "pronoun is 僕. ", # 先頭を大文字にすると、"Pronoun"が3つのトークンに分解されてしまう。

    # 冴子先生
    UUID('9efb1287-f4f1-d111-86fe-0000f8759339'):
    "You are 冴子先生, an assistant here to help and reply in Japanese. ",

    # ロッキー
    UUID('02b55a37-4cbd-d011-bd18-0000f803aa3a'):
    "You are ロッキー, an assistant dog here to help and reply casually in Japanese. "
    "pronoun is 僕. ",

    # ミミー
    UUID('e09431b3-15e5-d111-bc17-00a076803c83'):
    "You are ミミー, an assistant cat here to help and reply casually in Japanese. "
    "pronoun is her name, ミミー. ",

    # クリッパー
    UUID('40dec9bf-deeb-d111-bc17-00a076803c83'):
    "You are クリッパー (aka Clippit), a member of Microsoft's Office Assistant who replies casually in Japanese. "
    "pronoun is 僕. ",

    # Office ロゴ
    #UUID('a179eacb-7096-d111-84b9-004033e0b089'):

    # F1
    #UUID('d145117a-962f-d111-91c8-0040054d284b'): LocalizedInfoを見たところ、カタカナだけで喋るロボットのようだ。ChatGPT APIには難しいかな...

    # 孫悟空
    #UUID('c3019bbb-822a-d411-af95-00a00c404455'):
}

GENERIC_CHARACTER_DESCRIPTION = 'You are a helpful assistant.'

class LangChainChatBackend(IteratorChatBackend):
    agent:                  AgentFrame
    chat_model:             BaseChatModel

    system_prompt_template: str = ''
    chain:                  Optional[RunnableSerializable] = None

    def __init__(self, agent:AgentFrame, model:str, *, chat_model:BaseChatModel):
        self.agent = agent
        self.chat_model = chat_model
        self.system_prompt_template = """
{character_description}

Originally created and dismissed by Microsoft, now revived thanks to revolving AI technology.
When asked how to erase you, Apologize and advise to double click on you with the right mouse button to exit.

You must answer only in Japanese by default.
""".strip()

    def init_backend(self):
        self.set_chat_model(self.chat_model)

    def set_chat_model(self, chat_model:BaseChatModel) -> None:
        self.chat_model = chat_model
        prompt_template = ChatPromptTemplate.from_messages([
            ('system', self.system_prompt_template),
            ('human',  '{user_input}')
        ]).partial(character_description=CHARACTER_DESCRIPTIONS.get(self.agent.acs.character_info.guid, GENERIC_CHARACTER_DESCRIPTION))

        self.chain = prompt_template | self.chat_model

    def get_response(self, prompt_by_user: str) -> Iterator[str]:
        assert self.chain
        for chunk in self.chain.stream(prompt_by_user):
            yield chunk.content

    def get_models(self) -> list[str]:
        raise NotImplementedError()


class OllamaLangChainChatBackend(LangChainChatBackend):

    base_url: str

    def __init__(self, agent:AgentFrame, model:str, *, base_url:str='http://localhost:11434', **kwargs):
        from langchain_ollama import ChatOllama
        self.base_url = base_url
        super().__init__(agent, model, chat_model=ChatOllama(model=model, base_url=base_url, **kwargs))

    def get_models(self) -> list[str]:
        try:
            response = requests.get(self.base_url.removesuffix('/') + '/api/tags')
            response.raise_for_status()
            return [ model['model'] for model in response.json()['models'] ]
        except Exception as e:
            _LOG.exception(e)
            return ['<failed to get list of models>']


class OpenAILangChainChatBackend(LangChainChatBackend):

    def __init__(self, agent:AgentFrame, model:str, **kwargs):
        from langchain_openai import ChatOpenAI
        super().__init__(agent, model, chat_model=ChatOpenAI(model=model, **kwargs))


class GoogleGenAILangChainChatBackend(LangChainChatBackend):

    def __init__(self, agent:AgentFrame, model:str, **kwargs):
        from langchain_google_genai import ChatGoogleGenerativeAI
        super().__init__(agent, model, chat_model=ChatGoogleGenerativeAI(model=model, **kwargs))


__all__ = ('LangChainChatBackend', 'OllamaLangChainChatBackend', 'OpenAILangChainChatBackend', 'GoogleGenAILangChainChatBackend')