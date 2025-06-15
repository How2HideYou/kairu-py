import logging

from bitstring import BitStream
import numpy as np
import numpy.typing as npt

from .buffer import Buffer
from ._util import ImageDecompressionInterrupt


_LOG = logging.getLogger(__name__)


class _BitStream(BitStream):
    def read_rev(self, count:int=1) -> int:
        """
        `count`個のbitを読み込み、整数に変換して返す。ただし、ビットが前後反転されている。
        """
        v = 0
        for offset in range(count):
            v |= self.read('uint:1') << offset # type: ignore
        return v

    def count_consecutive_ones(self, limit:int) -> int:
        """
        最大`limit`ビットまで、連続する`1`のビットを数える。
        """
        count = 0
        for _ in range(limit):
            if self.read('bool'):
                count += 1
            else:
                break
        return count


_VALUE_BIT_COUNT = (6, 9, 12, 20)
_OFFSET_TO_ADD = (1, 65, 577, 4673)


def _reverse_bits(b):
    b = (b >> 4 & 0b00001111) | (b << 4 & 0b11110000)
    b = (b >> 2 & 0b00110011) | (b << 2 & 0b11001100)
    b = (b >> 1 & 0b01010101) | (b << 1 & 0b10101010)
    return b


def decompress(data, buffer_size:int) -> npt.NDArray[np.uint8]:
    data = bytes(_reverse_bits(b) for b in data)
    stream = _BitStream(data)
    out = np.zeros(buffer_size, dtype=np.uint8)
    out_pos = 0

    total_decoded_count = 0
    stream.read_rev(8)

    while stream.pos < len(stream):

        if not (stream.read('bool')):
            # 圧縮されていない1バイト
            byte = stream.read_rev(8)
            #print(f'圧縮されていない1バイト: {hex(byte)} {byte}')
            out[out_pos] = byte
            out_pos += 1
            total_decoded_count += 1
        else:
            #print('コピーを開始')
            # 解凍されたデータをコピー
            bytes_to_be_decoded = 2
            seq_bits_1 = stream.count_consecutive_ones(3)
            val_bit_count = _VALUE_BIT_COUNT[seq_bits_1]
            offset = stream.read_rev(val_bit_count)
            if val_bit_count == 20:
                if offset == 0x000FFFFF:
                    break
                else:
                    bytes_to_be_decoded += 1
            
            offset += _OFFSET_TO_ADD[seq_bits_1]

            seq_bits_2 = stream.count_consecutive_ones(12)
            assert seq_bits_2 != 12

            add1 = (1 << seq_bits_2) - 1
            add2 = stream.read_rev(seq_bits_2)
            bytes_to_be_decoded += add1 + add2

            # コピーを実行
            source_idx = total_decoded_count - offset
            total_decoded_count += bytes_to_be_decoded
            #print(f'解凍されたデータをコピー: {source_idx} {total_decoded_count} {bytes_to_be_decoded}')
            for i in range(bytes_to_be_decoded):
                out[out_pos + i] = out[source_idx + i] # スライスを使ってはいけない
            out_pos += bytes_to_be_decoded

    return out[:total_decoded_count]


def decompress_paletted_image(data:bytes, size:tuple[int, int], compressed:bool=True, extra_width:int=0) -> npt.NDArray[np.uint8]:
    w = size[0] + extra_width
    h = size[1]
    decompressed = decompress(data, ((w + 3) & 0xfc) * h) if compressed else np.array(data, dtype=np.uint8)
    expected_len = w * h
    if len(decompressed) > expected_len:
        decompressed = decompressed[:expected_len]
    return np.flip(decompressed.reshape((h, w)), axis=0)


def read_image(_buf:Buffer, extra_width:int) -> npt.NDArray[np.uint8]:
    b = _buf.locator()
    _buf.skip(4)
    b.skip(1)
    size = (b.read_ushort(), b.read_ushort())
    compressed = bool(b.read())
    comp_length = b.read_ulong()
    return decompress_paletted_image(b.read_bytes(comp_length), size, compressed, extra_width)


def read_paletted_images(buf:Buffer, *, gui:bool=False, extra_width:int=0) -> list[npt.NDArray[np.uint8]]:
    _LOG.info('画像データを解凍しています')

    pd = None
    if gui:
        import wx
        app = wx.App.Get() or wx.App()
        pd = wx.ProgressDialog('画像データを解凍中...', '画像データを解凍中...', style=wx.PD_APP_MODAL|wx.PD_AUTO_HIDE|wx.PD_REMAINING_TIME|wx.PD_CAN_ABORT)

    progress = 0
    def _read_image(_buf:Buffer, length:int) -> npt.NDArray[np.uint8]:
        nonlocal progress
        msg = f'画像データを解凍しています ({progress}/{length})'
        if progress % 10 == 0:
            _LOG.info(msg)

        if pd:
            pd.Update(progress, msg)
            if pd.WasCancelled():
                raise ImageDecompressionInterrupt('画像データの解凍が中止されました')
            pd.SetRange(length)

        result = read_image(_buf, extra_width)
        progress += 1
        return result

    result = buf.read_list(_read_image, 'ulong')
    _LOG.info('%d枚の画像データの解凍が完了しました!', len(result))
    return result


if __name__ == '__main__':
    import io
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
    data = bytes.fromhex('00 40 00 04 10 D0 90 80 42 ED 98 01 B7 FF FF FF FF FF FF')
    expected = bytes.fromhex('20 00 00 00 01 00 00 00 00 00 00 00 A8 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00')

    print(decompress(data, 256).tobytes().hex(' '))
    print(expected.hex(' '))