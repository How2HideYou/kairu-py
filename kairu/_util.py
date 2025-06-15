import logging
from typing import TypeVar
import asyncio
from collections.abc import Callable, Coroutine
from functools import wraps
import os


_LOG = logging.getLogger(__name__)
IS_WINDOWS = os.name == 'nt'

class ImageDecompressionInterrupt(RuntimeError):
    """
    画像の解凍画面で[Cancel]ボタンが押されたときに`raise`される。
    """
    pass


BITMAP_DRAW_OFFSET = (-1, -1) if IS_WINDOWS else (0, 0)
"""
Windowsの場合、なぜか`(-1, -1)`ずらして描画しないとマスクと一致しないが、macOSでは不要な模様
"""


_X = TypeVar('_X')

def done_future(result:_X) -> asyncio.Future[_X]:
    future = asyncio.Future()
    future.set_result(result)
    return future


C = TypeVar('C', bound=Callable[..., Coroutine])
def report_errors(error_logger:logging.Logger) -> Callable[[C], C]:
    def _decorator(async_func):
        @wraps(async_func)
        async def _wrapper(*args, **kwargs):
            try:
                return await async_func(*args, **kwargs)
            except BaseException as e:
                error_logger.exception(str(async_func))
                raise
        return _wrapper
    return _decorator # type: ignore
