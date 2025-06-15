from collections.abc import Callable, Sequence
from typing import Literal, Optional, TypeVar, overload
import inspect


_T = TypeVar('_T')

class Buffer(Sequence[int]):
    """
    順番にバイトを読み出せるバイト配列
    """

    mv:          memoryview
    pos:         int
    _root:       memoryview
    _abs_offset: int

    __slots__ = ('mv', '_root', 'pos', '_abs_offset')

    def __bytes__  (self): return bytes(self.mv)
    def __len__    (self): return len(self.mv)

    @overload
    def __getitem__(self, slice_or_index:slice) -> 'Buffer':
        """
        このBufferの範囲ビューを返す。
        """
        ...

    @overload
    def __getitem__(self, slice_or_index:int) -> int:
        ...

    def __getitem__(self, slice_or_index:slice|int):
        if isinstance(slice_or_index, int):
            return self.mv.__getitem__(slice_or_index)
        else:
            slice_:slice = slice_or_index
            if slice_.step in (None, 1):
                return Buffer(self.mv[slice_], self._root, self._abs_offset + (slice_.start or 0))
            else:
                raise NotImplementedError('Bufferの添え字のスライスにNoneと1以外を使うことはできません')

    def __buffer__(self) -> memoryview:
        return self.mv

    def __init__(self, mv:memoryview, root:memoryview, abs_offset:int, pos:int=0):
        self.mv = mv
        self._root = root
        self._abs_offset = abs_offset
        self.pos = pos

    def read(self) -> int:
        """
        1バイト読み込む。
        """
        data = self.mv[self.pos]
        self.pos += 1
        return data

    def read_bytes(self, length:int) -> memoryview:
        """
        lengthバイト分のビューを返す。
        """
        data = self.mv[self.pos:self.pos+length]
        self.pos += length
        return data

    def read_integer(self, length:int, signed:bool=False) -> int:
        return int.from_bytes(self.read_bytes(length), 'little', signed=signed)

    def read_ushort(self) -> int:
        return self.read_integer(2)

    def read_ulong(self) -> int:
        return self.read_integer(4)

    def read_string(self) -> str:
        length = self.read_ulong()
        string = ''.join(chr(self.read_ushort()) for _ in range(length))
        if length > 0:
            self.skip(2) # 空文字列ではない場合、終端のヌル文字をスキップ
        #print(string)
        return string

    def _read_list(self, elem_reader:Callable, length:int, has_length_arg:bool) -> list:
        if length >= 65536:
            raise ValueError(f'lengthが大きすぎます! {length}')
        if has_length_arg:
            return [elem_reader(self, length=length) for _ in range(length)]
        else:
            return [elem_reader(self) for _ in range(length)]

    def read_list(self, elem_reader:Callable[['Buffer'], _T]|Callable[['Buffer', int], _T], count_type:Literal['byte', 'ushort', 'ulong']='ushort', limit:Optional[int] = None) -> list[_T]:
        """
        長さが`count_type`の型で指定されたリストを読み込む。
        `elem_reader`に`length`という名前の引数があれば、それに全体の長さが渡される。
        """
        match count_type:
            case 'byte':   length = self.read()
            case 'ushort': length = self.read_ushort()
            case 'ulong':  length = self.read_ulong()
        if limit != None:
            length = min(limit, length)
        
        argspec = inspect.getfullargspec(elem_reader)
        has_length_arg = 'length' in argspec.args or 'length' in argspec.kwonlyargs
        return self._read_list(elem_reader, length, has_length_arg)

    def locator(self, sized=True) -> 'Buffer':
        """
        ACSLOCATORが指し示す範囲のBufferを生成する。
        """
        address = self.read_ulong()
        size    = self.read_ulong()
        if address + size > len(self._root):
            raise IndexError(f'ACSLOCATORがデータの範囲を超えています: ({hex(address)}から{hex(size)}バイト) {hex(len(self._root))}')
        return Buffer(self._root[address:address+size], self._root, address) if sized else Buffer(self._root[address:], self._root, address)

    def skip(self, count:int):
        self.pos += count