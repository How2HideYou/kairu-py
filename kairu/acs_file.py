import os.path
from typing import Optional
import locale
import logging
from uuid import UUID
from importlib.resources import files

from .buffer import Buffer
from .structs import AnimInfo, anim_info, CharacterInfo, character_info, FrameInfo, LocalizedInfo
from ._image_cache import make_sure_image_cache_exists, SubimageBox
from ._sound import make_sure_sound_cache_exists


_LOG = logging.getLogger(__name__)
KAIRU_ROOT = str(files(__package__)) # type: ignore

class AcsFile:
    filename:  str
    _cache_dir: str

    character_info:   CharacterInfo
    anim_infos:       dict[str, AnimInfo]
    spritesheet_path: str
    sprite_boxes:     list[SubimageBox]
    sound_paths:      list[Optional[str]]

    def __init__(self, name:str, buf, *, decompression_progress_gui:bool=False):
        mv = memoryview(buf)
        buf = Buffer(mv, mv, 0)
        self.filename = os.path.basename(name)
        self._cache_dir = os.path.join(KAIRU_ROOT, 'acs_cache', self.filename) # TODO: userprofileの.cacheフォルダにする?

        if bytes(buf[:4]) != b'\xc3\xab\xcd\xab':
            raise ValueError('ファイルのマジックナンバーが間違っています')

        self.character_info = character_info(buf[4:].locator())
        anim_info_list = buf[12:].locator().read_list(anim_info, 'ulong')
        self.anim_infos = { info.name:info for info in anim_info_list }
        self.sound_paths = make_sure_sound_cache_exists(self._cache_dir, buf[28:].locator())

        is_saeko = self.character_info.guid == UUID('{9efb1287-f4f1-d111-86fe-0000f8759339}')
        self.spritesheet_path, self.sprite_boxes = make_sure_image_cache_exists(
            self._cache_dir, self.character_info, buf[20:].locator(), is_saeko, decompression_progress_gui
        )


    @classmethod
    def from_file(cls, path:str, *, decompression_progress_gui:bool=False):
        with open(os.path.join(KAIRU_ROOT, 'resources', path), 'rb') as f: data = f.read()
        acs = cls(os.path.basename(path), data, decompression_progress_gui=decompression_progress_gui)
        return acs


    def localized_info(self, locale_:Optional[str]=None) -> LocalizedInfo:
        """
        `locale_`が`None`もしくは空の場合、システムのロケールが選択される。
        """
        loc = locale_ or locale.getdefaultlocale()[0] or 'en_US'

        return self.character_info.localized_infos.get(loc) \
        or self.character_info.localized_infos.get('en_US') \
        or LocalizedInfo(-1,
            os.path.basename(self.filename).rsplit('.', maxsplit=1)[0],
            f"<Couldn't find LocalizedInfo for {loc or '(None)'} and en_US>", ''
        )


    def dump_animations(self, path:Optional[str]=None):
        l = [f'{self.localized_info()} [{self.character_info.guid}]\n\n']

        for state_name, anim_names in self.character_info.state_infos.items():
            l.append(f'{state_name}: {", ".join(anim_names)}\n')
        l.append('\n')

        transition_type_names = {0: 'Uses Return Animation', 1: 'Uses Exit Branches'}
        for anim_info in self.anim_infos.values():
            l.append(f'==============={anim_info.name}===============\n')

            transition_type = transition_type_names.get(anim_info.transition_type)
            if transition_type:
                l.append(f'Transition Type: {transition_type}\n')

            if anim_info.return_anim_name:
                l.append(f'Return Animation Name: {anim_info.return_anim_name}\n')

            l.append(anim_info.frames_string())
            l.append('\n\n')

        path = path or os.path.join(self._cache_dir, 'animations.txt')
        with open(path, 'w', encoding='UTF-8') as f:
            f.write(''.join(l))
        _LOG.info(f'{path} にアニメーション情報を出力しました')


__all__ = ('AcsFile', )