from math import ceil
import json
import os
import os.path
import logging

from PIL import Image
import numpy as np
import numpy.typing as npt

from .structs import CharacterInfo
from .buffer import Buffer
from ._image_decompression import read_paletted_images


_LOG = logging.getLogger(__name__)

_CACHE_ROWS = 16

SubimageBox = tuple[int, int, int, int]
"(左端, 上端, 幅, 高さ)"


def save_cache(paletted_images:list[npt.NDArray[np.uint8]], palette:memoryview, padding_index:int, cache_dir:str):
    path = os.path.join(cache_dir, 'sprites.png')
    os.makedirs(os.path.dirname(path), exist_ok=True)

    max_height = max(img.shape[0] for img in paletted_images)
    max_width  = max(img.shape[1] for img in paletted_images)
    cache_height = int(ceil(len(paletted_images) / _CACHE_ROWS)) * max_height
    cache_width  = _CACHE_ROWS * max_width

    cache_data = np.full(shape=(cache_height, cache_width), fill_value=padding_index, dtype=np.uint8)
    subimage_boxes:list[SubimageBox] = []
    for idx, image in enumerate(paletted_images):
        i = idx // _CACHE_ROWS * max_height
        j = idx %  _CACHE_ROWS * max_width
        spritesheet = image
        cache_data[i:i+spritesheet.shape[0], j:j+spritesheet.shape[1]] = spritesheet
        subimage_boxes.append( (j, i, image.shape[1], image.shape[0]) )

    spritesheet = Image.fromarray(cache_data, mode='P')
    spritesheet.putpalette(palette, rawmode='RGBA')
    spritesheet.save(path)

    metadata = {"max_size":[max_width, max_height], "subimages": subimage_boxes}
    with open(path + '.json', 'w') as f:
        json.dump(metadata, f)
    _LOG.info('スプライトキャッシュを保存しました: %s', cache_dir)


def make_sure_image_cache_exists(cache_dir:str, character_info:CharacterInfo, compressed_image_data:Buffer, is_saeko:bool, decompression_progress_gui:bool) -> tuple[str, list[SubimageBox]]:
    path = os.path.join(cache_dir, 'sprites.png')

    for attempt in range(2):
        try:
            if not os.path.exists(path):
                raise FileNotFoundError(path)

            with open(path + '.json') as f:
                metadata = json.load(f)

            return path, metadata["subimages"]

        except Exception as e:
            if attempt < 1:
                _LOG.error('キャッシュが存在しないか破損しているので作成します', exc_info=True)
                paletted_images = read_paletted_images(compressed_image_data, gui=decompression_progress_gui, extra_width=0 if not is_saeko else 2)
                save_cache(paletted_images, character_info.palette.data, character_info.transparency_index, cache_dir)
            else:
                # キャッシュを生成したけどダメだった場合
                raise

    raise AssertionError('ここには到達しないはずです')
