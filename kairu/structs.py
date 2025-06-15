"""
ACSファイル内の構造体
"""

from dataclasses import dataclass
from typing import Optional
from uuid import UUID
import logging

import numpy as np
import numpy.typing as npt

from .buffer import Buffer


_LOG = logging.getLogger(__name__)


class AcsStruct:
    __slots__ = ()


_LOCALES = {0x401: 'ar_SA', 0x404: 'zh_TW', 0x405: 'cs_CZ', 0x406: 'da_DK', 0x407: 'de_DE', 0x408: 'el_GR', 0x009: 'en_US', 0x40b: 'fi_FI', 0x40c: 'fr_FR', 0x40d: 'he_IL', 0x40e: 'hu_HU', 0x410: 'it_IT', 0x411: 'ja_JP', 0x412: 'ko_KR', 0x413: 'nl_NL', 0x414: 'nb_NO', 0x415: 'pl_PL', 0x416: 'pt_BR', 0x418: 'ro_RO', 0x419: 'ru_RU', 0x41a: 'hr_HR', 0x41b: 'sk_SK', 0x41d: 'sv_SE', 0x41e: 'th_TH', 0x41f: 'tr_TR', 0x424: 'sl_SI', 0x42d: 'eu_ES', 0x804: 'zh_CN', 0x816: 'pt_PT', 0xc0a: 'es_ES', }

@dataclass(slots=True, frozen=True)
class LocalizedInfo(AcsStruct):
    numeric_lang_id: int
    name:            str
    description:     str
    extra_data:      str

    def __bool__(self):
        return bool(self.numeric_lang_id)

def localized_info(buf:Buffer):
    return LocalizedInfo(buf.read_ushort(), buf.read_string(), buf.read_string(), buf.read_string())


@dataclass(slots=True)
class CharacterInfo(AcsStruct):
    localized_infos:    dict[str, LocalizedInfo]
    guid:               UUID
    character_size:     tuple[int, int]
    transparency_index: int
    palette:            npt.NDArray[np.uint8] #RGBA
    state_infos:        dict[str, list[str]]

    def __init__(self, buf:Buffer):
        buf.read_ushort()
        buf.read_ushort()

        loc_info_list = buf.locator().read_list(localized_info, 'ushort')
        self.localized_infos = {}
        for loc_info in loc_info_list:
            locale_string = _LOCALES.get(loc_info.numeric_lang_id)
            if locale_string:
                self.localized_infos[locale_string] = loc_info
            else:
                _LOG.warning('不明なロケールIDです: %s', hex(loc_info.numeric_lang_id))

        self.guid = UUID(bytes=bytes(buf.read_bytes(16)))
        _LOG.info('GUID: %s', self.guid)
        self.character_size = (buf.read_ushort(), buf.read_ushort())
        self.transparency_index = buf.read()
        buf.read_ulong()
        buf.read_ushort()
        buf.read_ushort()
        CharacterInfo._skip_balloon_info(buf)

        palette_size = buf.read_ulong()
        palette = np.frombuffer(buf.read_bytes(palette_size * 4), dtype=np.uint8).reshape((palette_size, 4))
        self.palette = np.full_like(palette, fill_value=255)
        self.palette[:, 0] = palette[:, 2]
        self.palette[:, 1] = palette[:, 1]
        self.palette[:, 2] = palette[:, 0]
        self.palette[self.transparency_index, :] = 0

        tray_icon_present = buf.read() == 1
        if tray_icon_present:
            raise NotImplementedError("TRAYICONを含むACSファイルの読み込みには対応していません")
        
        state_infos = buf.read_list(lambda b: (b.read_string(), b.read_list(Buffer.read_string, count_type='ushort')), count_type='ushort')
        self.state_infos = dict(state_infos)

    @staticmethod
    def _skip_balloon_info(buf:Buffer):
        buf.skip(1 + 1 + 4 + 4 + 4)
        buf.read_string()
        buf.skip(4 + 4 + 1 + 1)

def character_info(buf:Buffer):
    return CharacterInfo(buf)


@dataclass(slots=True, frozen=True)
class FrameImage(AcsStruct):
    image_idx: int
    offset:    tuple[int, int]

def frame_image(buf:Buffer):
    return FrameImage(buf.read_ulong(), (buf.read_integer(2, True), buf.read_integer(2, True)))


USE_RETURN_ANIMATION = 0
USE_EXIT_BRANCHES = 1
NO_TRANSITION = 2

@dataclass(slots=True, frozen=True)
class BranchInfo(AcsStruct):
    jump_target_idx: int
    prob_percent:    int

def branch_info(buf:Buffer):
    return BranchInfo(buf.read_ushort(), buf.read_ushort())


@dataclass(slots=True)
class FrameInfo(AcsStruct):
    frame_images: list[FrameImage]
    audio_idx:    int
    duration_centiseconds:int
    exit_index:   int # アニメーションの終了がリクエストされたときにジャンプするフレーム
    branch_infos: list[BranchInfo]

    def __init__(self, buf:Buffer):
        self.frame_images = buf.read_list(frame_image, 'ushort')
        self.audio_idx = buf.read_ushort()
        self.duration_centiseconds = buf.read_ushort()
        self.exit_index = buf.read_integer(2, True)
        self.branch_infos = buf.read_list(branch_info, 'byte')

        if buf.read() > 0:
            raise NotImplementedError('口のオーバーレイには対応していません')

    def pick_jump_destination(self, rand_value:int) -> Optional[int]:
        prob_sum = 0
        for branch in self.branch_infos:
            prob_sum += branch.prob_percent
            if rand_value < prob_sum:
                return branch.jump_target_idx
        return None


def frame_info(buf:Buffer):
    return FrameInfo(buf)


@dataclass(slots=True)
class AnimInfo(AcsStruct):
    name:             str
    transition_type:  int
    return_anim_name: str
    frames:           list[FrameInfo]

    def __init__(self, buf:Buffer):
        self.name = buf.read_string()
        self.transition_type = buf.read()
        self.return_anim_name = buf.read_string()
        self.frames = buf.read_list(FrameInfo, 'ushort')

    def frames_string(self) -> str:
        """
        このアニメーションに含まれるフレームの情報一覧を人間が読める形式の文字列にする
        """
        from itertools import pairwise
        text = []

        junctions = set([0, len(self.frames)])
        for i, frame in enumerate(self.frames):
            if frame.branch_infos:
                junctions.add(i + 1)
                for branch in frame.branch_infos:
                    junctions.add(branch.jump_target_idx)

        junctions = sorted(junctions)
        for start, end_plus_one in pairwise(junctions):
            end = end_plus_one - 1
            if start == end:
                text.append('Frame %3s    : ' % start)
            else:
                text.append('Frame %3s-%3s: ' % (start, end))
            branch_infos = self.frames[end].branch_infos
            text.extend(', '.join(f'[->{branch.jump_target_idx} {branch.prob_percent}%]' for branch in branch_infos))
            if sum(branch.prob_percent for branch in branch_infos) >= 100:
                text.append('\n')
            text.append('\n')

        return ''.join(text)

def anim_info(buf:Buffer) -> AnimInfo:
    name = buf.read_string()
    info = AnimInfo(buf.locator())
    upper_name = name.upper()
    if upper_name != info.name:
        _LOG.warning(f'{name} <> {upper_name}')
    return info