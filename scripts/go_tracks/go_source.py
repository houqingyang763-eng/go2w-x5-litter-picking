"""Read the official GO archives by verified HTTP byte range."""

import bz2
from collections import Counter
from dataclasses import dataclass
import io
import json
import struct
import time
import zlib

from lz4.frame import decompress as decompress_lz4
import requests


@dataclass(frozen=True)
class Source:
    file_id: str
    size: int
    name: str
    split_key: str = ""


SOURCES = {
    "spring": Source(
        "1CXmHX61njEUhmRBZ1nQ_798o6kviDRta",
        45_242_711_455,
        "tamu_full_stack_morning_run_1_2024-04-24-08-30-42_filtered.bag",
        "tamu_full_stack_morning_run_1_2024-04-24-08-30-42",
    ),
    "winter": Source(
        "1qlGjFenEoXRKXIm6-0w9XRefIRavMWUg",
        61_499_289_407,
        "2025-01-24-10-42-36_newcal.bag",
        "2025-01-24-10-42-36",
    ),
    "labels": Source("1S5kNhSlOlikyaN6_ooWUGdD0YK7sVE9l", 1_589_952_606, "go_rgb_segmentation.zip"),
}

ADDRESS = "https://drive.usercontent.google.com/download"
NS = 1_000_000_000
MAX_RANGE = 64 * 1024 * 1024
MAGIC = b"#ROSBAG V2.0\n"
U32 = struct.Struct("<I")
FORWARD_LEFT = "/lester/stereo_left/image_rect_color/compressed"


class RangeFile(io.RawIOBase):
    def __init__(self, source, proxy=None):
        self.source = source
        self.position = 0
        self.transferred = 0
        self.session = requests.Session()
        if proxy:
            self.session.trust_env = False
            self.session.proxies.update(http=proxy, https=proxy)

    def fetch(self, start, length):
        size = self.source.size
        if length < 1 or start < 0 or start + length > size or length > MAX_RANGE:
            raise ValueError(f"Invalid file range at {start} with {length} bytes")
        stop = start + length - 1
        headers = {"Range": f"bytes={start}-{stop}", "Accept-Encoding": "identity"}
        params = {"id": self.source.file_id, "export": "download", "confirm": "t"}
        for attempt in range(5):
            try:
                with self.session.get(ADDRESS, params=params, headers=headers, timeout=(12, 30)) as response:
                    received = response.headers.get("Content-Range")
                    if response.status_code != 206 or received != f"bytes {start}-{stop}/{size}":
                        raise OSError(f"HTTP {response.status_code}, Content-Range {received!r}")
                    data = response.content
                if len(data) != length:
                    raise OSError(f"Short HTTP range at {start}")
                self.transferred += len(data)
                return data
            except (requests.RequestException, OSError):
                if attempt == 4:
                    raise
                time.sleep(0.8 * (attempt + 1))
        raise AssertionError("Unreachable retry state")

    def read(self, n=-1):
        available = max(0, self.source.size - self.position)
        length = available if n < 0 else min(n, available)
        if not length:
            return b""
        data = self.fetch(self.position, length)
        self.position += length
        return data

    def tell(self):
        return self.position

    def seek(self, offset, whence=io.SEEK_SET):
        bases = {io.SEEK_SET: 0, io.SEEK_CUR: self.position, io.SEEK_END: self.source.size}
        position = bases[whence] + offset
        if position < 0:
            raise OSError("Negative file offset")
        self.position = position
        return self.position

    def readable(self):
        return True

    def seekable(self):
        return True

    def close(self):
        self.session.close()
        super().close()


def record_data(stream):
    length = U32.unpack(stream.read(4))[0]
    data = stream.read(length)
    if len(data) != length:
        raise ValueError("Incomplete ROS bag record")
    return data


def fields(data):
    result = {}
    stream = io.BytesIO(data)
    while stream.tell() < len(data):
        key, value = record_data(stream).split(b"=", 1)
        result[key.decode("ascii")] = value
    return result


def ros_stamp(data):
    sec, nsec = struct.unpack("<II", data)
    return sec * NS + nsec


def bag_index(source, proxy):
    with RangeFile(source, proxy) as remote:
        prefix = io.BytesIO(remote.fetch(0, 8192))
        if prefix.read(len(MAGIC)) != MAGIC:
            raise ValueError("Expected a ROS bag 2.0 archive")
        header = fields(record_data(prefix))
        prefix.seek(U32.unpack(prefix.read(4))[0], io.SEEK_CUR)
        first = fields(record_data(prefix))
        index_pos = struct.unpack("<Q", header["index_pos"])[0]
        tail = io.BytesIO(remote.fetch(index_pos, source.size - index_pos))

    connections = {}
    for _ in range(U32.unpack(header["conn_count"])[0]):
        header_part = fields(record_data(tail))
        metadata = fields(record_data(tail))
        if header_part["op"] != b"\x07":
            raise ValueError("Expected a ROS bag connection record")
        connections[str(U32.unpack(header_part["conn"])[0])] = {
            "topic": header_part["topic"].decode(),
            "type": metadata["type"].decode(),
        }
    chunks = []
    counts = Counter()
    for _ in range(U32.unpack(header["chunk_count"])[0]):
        header_part = fields(record_data(tail))
        if header_part["op"] != b"\x06":
            raise ValueError("Expected a ROS bag chunk information record")
        chunk_counts = {str(conn): count for conn, count in struct.iter_unpack("<II", record_data(tail))}
        counts.update(chunk_counts)
        chunks.append([
            struct.unpack("<Q", header_part["chunk_pos"])[0],
            ros_stamp(header_part["start_time"]),
            ros_stamp(header_part["end_time"]),
            chunk_counts,
        ])
    for conn, metadata in connections.items():
        metadata["count"] = counts[conn]
    return {
        "name": source.name,
        "bytes": source.size,
        "index_pos": index_pos,
        "first_compression": first["compression"].decode("ascii"),
        "start_ns": min(chunk[1] for chunk in chunks),
        "end_ns": max(chunk[2] for chunk in chunks),
        "connections": connections,
    }, chunks


def rgb_frames(chunk, conn_id):
    record = io.BytesIO(chunk)
    header = fields(record_data(record))
    if header["op"] != b"\x05":
        raise ValueError("Expected a ROS bag chunk")
    compressed = record_data(record)
    compression = header["compression"]
    if compression == b"bz2":
        data = bz2.decompress(compressed)
    elif compression == b"lz4":
        data = decompress_lz4(compressed)
    elif compression == b"none":
        data = compressed
    else:
        raise ValueError(f"Unsupported ROS bag chunk compression {compression!r}")
    if len(data) != U32.unpack(header["size"])[0]:
        raise ValueError("ROS bag chunk decompressed size mismatch")
    stream = io.BytesIO(data)
    while stream.tell() < len(data):
        metadata = fields(record_data(stream))
        size = U32.unpack(stream.read(4))[0]
        if metadata["op"] != b"\x02" or U32.unpack(metadata["conn"])[0] != conn_id:
            stream.seek(size, io.SEEK_CUR)
            continue
        message = io.BytesIO(stream.read(size))
        seq, sec, ns = struct.unpack("<III", message.read(12))
        frame_id = record_data(message).decode()
        encoding = record_data(message).decode()
        image = record_data(message)
        if not image.startswith(b"\xff\xd8"):
            raise ValueError(f"Expected a JPEG from {FORWARD_LEFT}, encoding {encoding}")
        yield {
            "stamp_ns": sec * NS + ns,
            "bag_ns": ros_stamp(metadata["time"]),
            "seq": seq,
            "frame_id": frame_id,
            "encoding": encoding,
        }, image


def zip_member(remote, info, next_offset):
    """Read one ZIP member as a range and validate it against the central directory."""
    directory_cursor = info.header_offset
    data = remote.fetch(directory_cursor, next_offset - directory_cursor)
    if data[:4] != b"PK\x03\x04":
        raise ValueError(f"Invalid ZIP member header for {info.filename}")
    name_size, extra_size = struct.unpack_from("<HH", data, 26)
    if data[30:30 + name_size].decode("utf-8") != info.filename:
        raise ValueError(f"ZIP member name mismatch for {info.filename}")
    start = 30 + name_size + extra_size
    body = data[start:start + info.compress_size]
    if info.compress_type == 8:
        body = zlib.decompress(body, -15)
    elif info.compress_type != 0:
        raise ValueError(f"Unsupported ZIP method for {info.filename}")
    if len(body) != info.file_size or zlib.crc32(body) != info.CRC:
        raise ValueError(f"ZIP member size or CRC mismatch for {info.filename}")
    return body


def write_text_manifest(path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    temporary.replace(path)
