"""Pure-Python MP3 duration measurement (no external binaries).

Uses the Xing/Info header frame count when present (exact for LAME VBR),
cross-checked by walking every frame header. Falls back to frame walking
when no Xing header exists. Returns None when the stream cannot be parsed
— duration is never guessed.
"""

import struct
from typing import Optional, Tuple

_MPEG1_LAYER3_BITRATE = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320]
_MPEG2_LAYER3_BITRATE = [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160]
_MPEG1_SAMPLERATE = [44100, 48000, 32000]
_MPEG2_SAMPLERATE = [22050, 24000, 16000]
_MPEG25_SAMPLERATE = [11025, 12000, 8000]


class MP3ParseError(Exception):
    pass


def _skip_id3v2(data: bytes) -> int:
    if data[:3] != b"ID3":
        return 0
    if len(data) < 10:
        raise MP3ParseError("truncated ID3v2 header")
    size = (data[6] << 21) | (data[7] << 14) | (data[8] << 7) | data[9]
    return 10 + size


def _find_frame_sync(data: bytes, start: int) -> int:
    for off in range(start, len(data) - 4):
        if data[off] == 0xFF and (data[off + 1] & 0xE0) == 0xE0:
            return off
    raise MP3ParseError("no MPEG frame sync found")


def _parse_frame_header(data: bytes, off: int) -> Tuple[int, int, int, int, int]:
    """Return (version, layer, bitrate_idx, samplerate_idx, padding)."""
    b1, b2 = data[off + 1], data[off + 2]
    version = (b1 >> 3) & 0x3
    layer = (b1 >> 1) & 0x3
    bitrate_idx = (b2 >> 4) & 0xF
    sr_idx = (b2 >> 2) & 0x3
    padding = (b2 >> 1) & 0x1
    if version == 1 or layer == 0 or bitrate_idx == 0 or bitrate_idx == 15 or sr_idx == 3:
        raise MP3ParseError(f"invalid frame header at {off}")
    return version, layer, bitrate_idx, sr_idx, padding


def _samples_per_frame(version: int, layer: int) -> int:
    if layer != 1:
        raise MP3ParseError("only Layer III supported")
    if version == 3:  # MPEG1
        return 1152
    return 576  # MPEG2 / MPEG2.5


def _sample_rate(version: int, sr_idx: int) -> int:
    table = {3: _MPEG1_SAMPLERATE, 2: _MPEG2_SAMPLERATE, 0: _MPEG25_SAMPLERATE}.get(version)
    if table is None:
        raise MP3ParseError(f"unknown MPEG version {version}")
    return table[sr_idx]


def _bitrate(version: int, bitrate_idx: int) -> int:
    table = {3: _MPEG1_LAYER3_BITRATE, 2: _MPEG2_LAYER3_BITRATE, 0: _MPEG2_LAYER3_BITRATE}[version]
    return table[bitrate_idx] * 1000


def _xing_frame_count(data: bytes, frame_off: int, version: int) -> Optional[int]:
    # Xing/Info sits in the first frame's data area; its offset after the
    # 4-byte header varies with side-info size (and some encoders deviate),
    # so scan a bounded window instead of computing the offset.
    search_from = frame_off + 4
    search_to = min(frame_off + 4 + 256, len(data))
    idx = data.find(b"Xing", search_from, search_to)
    if idx < 0:
        idx = data.find(b"Info", search_from, search_to)
    if idx < 0:
        return None
    pos = idx + 4
    if pos + 4 > len(data):
        return None
    flags = struct.unpack(">I", data[pos : pos + 4])[0]
    pos += 4
    if flags & 0x1:
        if pos + 4 > len(data):
            return None
        return struct.unpack(">I", data[pos : pos + 4])[0]
    return None


def _walk_frames(data: bytes, first_off: int, version: int, bitrate_idx: int, sr_idx: int) -> int:
    """Count frames by walking headers. Returns total samples."""
    bitrate = _bitrate(version, bitrate_idx)
    sr = _sample_rate(version, sr_idx)
    spf = _samples_per_frame(version, 1)
    frame_len = (144 * bitrate) // sr if version == 3 else (72 * bitrate) // sr
    if frame_len <= 0:
        raise MP3ParseError("zero frame length")
    samples = 0
    off = first_off
    n = 0
    while off + 4 <= len(data):
        try:
            _, layer, bi, si, pad = _parse_frame_header(data, off)
        except MP3ParseError:
            break
        if layer != 1:
            break
        fl = ((144 * _bitrate(version, bi)) // _sample_rate(version, si) + pad) if version == 3 \
            else ((72 * _bitrate(version, bi)) // _sample_rate(version, si) + pad)
        if fl <= 0 or off + fl > len(data):
            break
        samples += spf
        n += 1
        off += fl
    if n == 0:
        raise MP3ParseError("no frames walked")
    return samples


def mp3_duration_ms(data: bytes) -> Optional[int]:
    """Measure MP3 duration in milliseconds. Returns None if unparseable."""
    try:
        start = _skip_id3v2(data)
        first = _find_frame_sync(data, start)
        version, layer, bitrate_idx, sr_idx, _ = _parse_frame_header(data, first)
        if layer != 1:
            return None
        sr = _sample_rate(version, sr_idx)
        spf = _samples_per_frame(version, layer)

        xing_frames = _xing_frame_count(data, first, version)
        if xing_frames:
            return round(xing_frames * spf / sr * 1000)

        samples = _walk_frames(data, first, version, bitrate_idx, sr_idx)
        return round(samples / sr * 1000)
    except MP3ParseError:
        return None
