import logging
import os
import os.path
import subprocess
from typing import Optional

from .buffer import Buffer
from ._util import IS_WINDOWS


_LOG = logging.getLogger(__name__)

_FFMPEG_PATH = 'ffmpeg'

_REMOVE_SOUND_CACHE = False


def make_sure_sound_cache_exists(cache_dir:str, buffer:Buffer, use_ffmpeg:bool=not IS_WINDOWS) -> list[Optional[str]]:
    """
    ACSファイルから音声データを取り出し、キャッシュファイルが存在しなければ生成する。
    キャッシュファイルのパスの一覧 (キャッシュ生成に失敗したファイルは`None`) を返す。
    `use_ffmpeg`が`True`の場合、FFmpegを経由して音声ファイルを一般的なwavのコーデック (pcm_s16le) に変換する。

    ACSファイルに含まれているwavファイルの一部には、Windowsでしか扱えないコーデックが使われている。
    そこで、Windows以外のOSで使う際には、FFmpegでPCMに再エンコードする。
    """

    if _REMOVE_SOUND_CACHE:
        import shutil
        shutil.rmtree(os.path.join(cache_dir, 'sounds'))

    os.makedirs(os.path.join(cache_dir, 'sounds'), exist_ok=True)

    def _load_sound(b:Buffer) -> memoryview:
        data = b.locator().mv[:-4]
        b.skip(4)
        return data
    sound_files = buffer.read_list(_load_sound, 'ulong')

    sound_paths = []
    for index, sound_file in enumerate(sound_files):
        path = os.path.join(cache_dir, 'sounds', f'{index}.wav')
        if not os.path.isfile(path):
            if use_ffmpeg:
                with subprocess.Popen([_FFMPEG_PATH, '-hide_banner', '-y', '-i', '-', '-c:a', 'pcm_s16le', path], stdin=subprocess.PIPE) as ffmpeg:
                    ffmpeg.communicate(sound_file)
            else:
                with open(path, 'wb') as f:
                    f.write(sound_file)

        sound_paths.append(path if os.path.isfile(path) else None)

    return sound_paths