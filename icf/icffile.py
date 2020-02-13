import struct

# import binascii
# from .utils import get_si_prefix
from datetime import datetime
import os
from collections import namedtuple
import numpy as np

class ICFFile:
    _file_header = struct.Struct("<4s4s2HQ2H")
    _bunch_trailer_header = struct.Struct("<2H4Q3I")
    _BunchTrailer = namedtuple(
        "BunchTrailer", "bunchoff dataoff fileoff bunchsize ndata index objsize"
    )

    def __init__(
        self,
        filename: str,
        mode="append",
        header_ext: bytes = None,
        file_identifier_ext: str = "",
        compressor=None,
        bunchsize: int = 1000000,
    ):
        self.bunchsize = bunchsize
        self.header_ext = header_ext
        self.file_identifier_ext = file_identifier_ext
        self._write_buffer = []
        self.version = 0
        self._index = []
        self._bunch_index = {}
        self._rawindex = {}
        self.n_entries = 0
        self._cbunchoffset = 0
        self._last_bunch_fp = 0
        self._bunch_number = 0
        self._bunch_buffer = BunchBuffer(10)
        self._file_index = [0]
        omode = "b"
        if mode == "append":
            omode += "a+"
        elif mode == "trunc":
            omode += "w+"
        else:
            omode += "r"

        self._file = open(filename, omode)
        self.compression = 0

        self._file.seek(0, os.SEEK_END)
        self.filesize = self._file.tell()
        if self.filesize > 0 and ("a" in omode or "r" in omode):
            self._file.seek(0)
            (
                fd,
                fd_ext,
                self.version,
                self.compression,
                self.timestamp,
                _,
                ext_len,
            ) = self._file_header.unpack(self._file.read(self._file_header.size))
            self.file_identifier_ext = fd_ext
            self.header_ext = self._file.read(ext_len)
            print(self.filesize)
            raw_index = self._scan_file(self._file.tell(), self.filesize)
            self._construct_file_index(raw_index)

        else:
            self.timestamp = int(datetime.now().timestamp())
            header_ext = b"" if header_ext is None else header_ext
            self._file.write(
                self._file_header.pack(
                    "ICF".encode(),
                    self.file_identifier_ext.encode(),
                    0,
                    self.compression,
                    self.timestamp,
                    0,
                    len(header_ext),
                )
            )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._writer.close()

    def get_timestamp(self):
        return datetime.fromtimestamp(self.timestamp)

    def write(self, data: bytes):
        """ Writes a stream of bytes to file

            args:
                data (bytes): bytes to be writen to file
        """

        self._write_buffer.append(data)
        self._cbunchoffset += len(data)
        # self._cbunchindex.append(len(data))
        self.n_entries += 1
        if self._cbunchoffset > self.bunchsize:
            self.flush()

    def _write(self, data: bytes):
        self._file.write(data)

    def flush(self):
        """Flushes any data in buffer to file.

        """
        if len(self._write_buffer) < 1:
            return
        self._file.seek(0, os.SEEK_END)

        bunch_start_fp = self._file.tell()  # self._fp
        # writing the data bunch
        cbunchindex = []
        bytes_buff = bytearray()
        for data in self._write_buffer:
            bytes_buff.extend(data)
            cbunchindex.append(len(data))
        self._write(bytes_buff)
        curr_bt_fp = self._file.tell()
        # Constructing and writing bunch trailer header
        bunch_index_trailer = self._bunch_trailer_header.pack(
            self.version,
            0,
            int(datetime.now().timestamp()),
            curr_bt_fp,
            curr_bt_fp - self._last_bunch_fp,
            curr_bt_fp - bunch_start_fp,
            len(self._write_buffer),
            self._bunch_number,
            0,
        )
        self._write(bunch_index_trailer)

        # constructing the index and writing it in the bunch trailer
        n = len(self._write_buffer)
        bunch_index = struct.pack("<{}I".format(n), *cbunchindex)
        self._write(bunch_index)

        # Write offset to begining of bunch trailer
        self._write(struct.pack("I", self._file.tell() - curr_bt_fp))

        # Keep the file pointer for the current bunch
        self._last_bunch_fp = curr_bt_fp

        self._file.flush()
        # reseting/updating the last bunch descriptors
        self._write_buffer.clear()
        self._cbunchoffset = 0
        self._bunch_number += 1

    def close(self):
        self.flush()
        self._file.close()

    def _scan_file(self, pos_start, pos_end):
        # We find the last bunch trailer by reading the last 4 bytes which
        # encodes the offset to said bunch trailer
        self._file.seek(pos_end - 4)
        bt_start_offset = struct.unpack("<I", self._file.read(4))[0]
        self._file.seek(pos_end - 4 - bt_start_offset)
        rawindex = {}
        curr_bunch = 1
        while self._file.tell() >= pos_start and curr_bunch > 0:
            print(self._file.tell(), pos_start)
            # read bunch trailer
            last_bunch_trailer = self._file.read(self._bunch_trailer_header.size)
            (
                version,
                _,
                timestamp,
                fileoff,
                bunchoff,
                dataoff,
                ndata,
                bunch_n,
                flags
            ) = self._bunch_trailer_header.unpack(last_bunch_trailer)
            curr_bunch = bunch_n
            index = struct.unpack("{}I".format(ndata), self._file.read(ndata * 4))
            objsizes = np.array(index, dtype=np.uint32)
            rawindex[(0, bunch_n)] = self._BunchTrailer(
                bunchoff,  # Offset to earlier bunch or file header if first bunch
                dataoff,  # Offset to beginning of data in bunch
                fileoff,  # Offset to beginning of file
                dataoff,  # Size of data bunch
                ndata,  # number of objects in bunch
                [0] + list(np.cumsum(objsizes[:-1])),  # Object offsets in bunch
                objsizes,  # object sizes
            )
            self._file.seek(self._file.tell() - bunchoff)
            print('Ndata',ndata,self._file.tell(),pos_start,curr_bunch)
        return rawindex

    def _construct_file_index(self, rawindex):

        for k, bunch in sorted(rawindex.items()):
            self._rawindex[k] = bunch
            self._bunch_index[k] = (bunch.fileoff - bunch.dataoff, bunch.bunchsize)
            for i, obj in enumerate(bunch.index):
                self._index.append((k, int(obj), int(bunch.objsize[i])))
        self.n_entries = len(self._index)


    def _get_bunch(self, bunch_id):

        if bunch_id in self._bunch_buffer:
            return self._bunch_buffer[bunch_id]
        else:
            self._file.seek(self._bunch_index[bunch_id][0])
            # bunch = self._compressor.decompress(
            bunch = self._file.read(
                        self._file_index[bunch_id[0]] + self._bunch_index[bunch_id][1]
                        )
            # )
            self._bunch_buffer[bunch_id] = bunch
            return bunch

    def read_at(self, ind: int) -> bytes:
        """Reads one object at the index indicated by `ind`

        Args:
            ind (int): the index of the object to be read

        Returns:
            bytes: that represent the object

        Raises:
            IndexError: if index out of range
        """

        if ind > self.n_entries - 1:
            raise IndexError(
                "The requested file object ({}) is out of range".format(ind)
            )
        obji = self._index[ind]
        if True:  # self._compressed:
            bunch = self._get_bunch(obji[0])
            return bunch[obji[1]: obji[1] + obji[2]]
        # else:
        #     fpos = self.file_index[obji[0][0]] + self._bunch_index[obji[0]][0] + obji[1]
        #     self.file.seek(fpos)

        #     return self.file.read(obji[2])


from collections import deque


class BunchBuffer(dict):
    def __init__(self, size):
        self.size = size
        self.queue = deque()

    def __setitem__(self, key, obj):
        self.queue.append((key, obj))
        super().__setitem__(key, obj)
        if len(self.queue) > self.size:
            bunch = self.queue.popleft()
            super().pop(bunch[0])