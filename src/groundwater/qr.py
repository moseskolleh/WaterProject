"""A QR encoder, because the code has to be there when the network is not.

A borehole's identifier is only useful if a technician standing at the
wellhead can read it off the headworks with the phone in their pocket. That
rules out anything that fetches an image from a server: the places this
toolkit is used are exactly the places with no signal. So the symbol is
generated here, offline, in both engines, from no dependency at all.

Byte mode, versions 1 to 10, all four error-correction levels. Ten versions
carry 271 bytes at level M, which is more than a placard should ever say -
a symbol that needs a steady hand and a clean lens to resolve is not an
improvement on a painted number. Level H is the default for anything that
will live outdoors: it tolerates about 30% of the symbol being lost to mud,
scratches or a torn label, which is the normal condition of a headworks
plate after one rainy season.

The implementation follows ISO/IEC 18004. It is verified against an
independent encoder in the test suite rather than by inspection, because a
QR code that is wrong in the data region still looks exactly like a QR code.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

__all__ = [
    "ECC_LEVELS",
    "MAX_VERSION",
    "QRCode",
    "encode",
    "to_png",
    "to_svg",
]

#: Error-correction levels, with the share of the symbol each can lose.
ECC_LEVELS = {"L": 0.07, "M": 0.15, "Q": 0.25, "H": 0.30}

MAX_VERSION = 10

# Two-bit level indicator used in the format information. Note that these are
# not in strength order: L is 01 and M is 00.
_ECC_BITS = {"L": 0b01, "M": 0b00, "Q": 0b11, "H": 0b10}

#: Total codewords (data + error correction) per version, 1 to 10.
_TOTAL_CODEWORDS = [26, 44, 70, 100, 134, 172, 196, 242, 292, 346]

# Block structure per (version, level):
#   (ec codewords per block, group 1 blocks, group 1 data codewords,
#    group 2 blocks, group 2 data codewords)
# Group 2 blocks carry exactly one more data codeword than group 1 blocks;
# splitting a version's data across two sizes is how the standard uses up a
# codeword count that does not divide evenly.
_BLOCKS: dict[int, dict[str, tuple[int, int, int, int, int]]] = {
    1: {"L": (7, 1, 19, 0, 0), "M": (10, 1, 16, 0, 0),
        "Q": (13, 1, 13, 0, 0), "H": (17, 1, 9, 0, 0)},
    2: {"L": (10, 1, 34, 0, 0), "M": (16, 1, 28, 0, 0),
        "Q": (22, 1, 22, 0, 0), "H": (28, 1, 16, 0, 0)},
    3: {"L": (15, 1, 55, 0, 0), "M": (26, 1, 44, 0, 0),
        "Q": (18, 2, 17, 0, 0), "H": (22, 2, 13, 0, 0)},
    4: {"L": (20, 1, 80, 0, 0), "M": (18, 2, 32, 0, 0),
        "Q": (26, 2, 24, 0, 0), "H": (16, 4, 9, 0, 0)},
    5: {"L": (26, 1, 108, 0, 0), "M": (24, 2, 43, 0, 0),
        "Q": (18, 2, 15, 2, 16), "H": (22, 2, 11, 2, 12)},
    6: {"L": (18, 2, 68, 0, 0), "M": (16, 4, 27, 0, 0),
        "Q": (24, 4, 19, 0, 0), "H": (28, 4, 15, 0, 0)},
    7: {"L": (20, 2, 78, 0, 0), "M": (18, 4, 31, 0, 0),
        "Q": (18, 2, 14, 4, 15), "H": (26, 4, 13, 1, 14)},
    8: {"L": (24, 2, 97, 0, 0), "M": (22, 2, 38, 2, 39),
        "Q": (22, 4, 18, 2, 19), "H": (26, 4, 14, 2, 15)},
    9: {"L": (30, 2, 116, 0, 0), "M": (22, 3, 36, 2, 37),
        "Q": (20, 4, 16, 4, 17), "H": (24, 4, 12, 4, 13)},
    10: {"L": (18, 2, 68, 2, 69), "M": (26, 4, 43, 1, 44),
         "Q": (24, 6, 19, 2, 20), "H": (28, 6, 15, 2, 16)},
}

#: Row/column centres of the alignment patterns, per version.
_ALIGNMENT = {
    1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34],
    7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50],
}

#: Pre-computed 18-bit version information, versions 7 upward.
_VERSION_INFO = {7: 0x07C94, 8: 0x085BC, 9: 0x09A99, 10: 0x0A4D3}

#: Remainder bits appended after the interleaved codewords.
_REMAINDER_BITS = {1: 0, 2: 7, 3: 7, 4: 7, 5: 7, 6: 7,
                   7: 0, 8: 0, 9: 0, 10: 0}


@dataclass(frozen=True)
class QRCode:
    """A finished symbol. ``modules[row][col]`` is True where the module is dark."""

    version: int
    ecc: str
    mask: int
    modules: list[list[bool]]

    @property
    def size(self) -> int:
        return len(self.modules)


# ---------------------------------------------------------------------------
# GF(256), the field the Reed-Solomon codewords live in
# ---------------------------------------------------------------------------

_EXP = [0] * 512
_LOG = [0] * 256


def _build_tables() -> None:
    x = 1
    for i in range(255):
        _EXP[i] = x
        _LOG[x] = i
        x <<= 1
        if x & 0x100:  # reduce by the primitive polynomial x^8+x^4+x^3+x^2+1
            x ^= 0x11D
    for i in range(255, 512):
        _EXP[i] = _EXP[i - 255]


_build_tables()


def _gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _generator_poly(degree: int) -> list[int]:
    """The RS generator (x-a^0)(x-a^1)...(x-a^(degree-1)), as coefficients."""
    poly = [1]
    for i in range(degree):
        nxt = [0] * (len(poly) + 1)
        for j, coeff in enumerate(poly):
            nxt[j] ^= _gf_mul(coeff, 1)
            nxt[j + 1] ^= _gf_mul(coeff, _EXP[i])
        poly = nxt
    return poly


def _ec_codewords(data: list[int], count: int) -> list[int]:
    """The ``count`` error-correction codewords for one block of data."""
    gen = _generator_poly(count)
    remainder = list(data) + [0] * count
    for i in range(len(data)):
        lead = remainder[i]
        if lead == 0:
            continue
        for j, coeff in enumerate(gen):
            remainder[i + j] ^= _gf_mul(coeff, lead)
    return remainder[len(data):]


# ---------------------------------------------------------------------------
# Data encoding
# ---------------------------------------------------------------------------

def _capacity_bytes(version: int, ecc: str) -> int:
    ec_per_block, g1, d1, g2, d2 = _BLOCKS[version][ecc]
    data_codewords = g1 * d1 + g2 * d2
    count_bits = 8 if version < 10 else 16
    return (data_codewords * 8 - 4 - count_bits) // 8


def _choose_version(length: int, ecc: str, min_version: int) -> int:
    for version in range(max(1, min_version), MAX_VERSION + 1):
        if length <= _capacity_bytes(version, ecc):
            return version
    raise ValueError(
        f"{length} bytes will not fit in a version-{MAX_VERSION} symbol at "
        f"error-correction level {ecc}; shorten the payload"
    )


def _bitstream(payload: bytes, version: int, ecc: str) -> list[int]:
    ec_per_block, g1, d1, g2, d2 = _BLOCKS[version][ecc]
    data_codewords = g1 * d1 + g2 * d2
    capacity_bits = data_codewords * 8

    bits: list[int] = [0, 1, 0, 0]  # byte mode
    count_bits = 8 if version < 10 else 16
    for shift in range(count_bits - 1, -1, -1):
        bits.append((len(payload) >> shift) & 1)
    for byte in payload:
        for shift in range(7, -1, -1):
            bits.append((byte >> shift) & 1)

    bits.extend([0] * min(4, capacity_bits - len(bits)))  # terminator
    if len(bits) % 8:
        bits.extend([0] * (8 - len(bits) % 8))
    pad = (0xEC, 0x11)
    i = 0
    while len(bits) < capacity_bits:
        for shift in range(7, -1, -1):
            bits.append((pad[i % 2] >> shift) & 1)
        i += 1
    return bits


def _interleave(bits: list[int], version: int, ecc: str) -> list[int]:
    """Split into blocks, add error correction, and interleave both halves."""
    ec_per_block, g1, d1, g2, d2 = _BLOCKS[version][ecc]
    codewords = [int("".join(str(b) for b in bits[i:i + 8]), 2)
                 for i in range(0, len(bits), 8)]

    blocks: list[list[int]] = []
    at = 0
    for count, size in ((g1, d1), (g2, d2)):
        for _ in range(count):
            blocks.append(codewords[at:at + size])
            at += size
    ec_blocks = [_ec_codewords(block, ec_per_block) for block in blocks]

    out: list[int] = []
    for i in range(max(len(b) for b in blocks)):
        for block in blocks:
            if i < len(block):
                out.append(block[i])
    for i in range(ec_per_block):
        for block in ec_blocks:
            out.append(block[i])

    final: list[int] = []
    for codeword in out:
        for shift in range(7, -1, -1):
            final.append((codeword >> shift) & 1)
    final.extend([0] * _REMAINDER_BITS[version])
    return final


# ---------------------------------------------------------------------------
# Module placement
# ---------------------------------------------------------------------------

def _blank(size: int):
    return ([[False] * size for _ in range(size)],
            [[False] * size for _ in range(size)])


def _place_function_patterns(modules, reserved, version: int) -> None:
    size = len(modules)

    def finder(row: int, col: int) -> None:
        for r in range(-1, 8):
            for c in range(-1, 8):
                rr, cc = row + r, col + c
                if not (0 <= rr < size and 0 <= cc < size):
                    continue
                edge = max(abs(r - 3), abs(c - 3))
                modules[rr][cc] = edge != 2 and edge <= 3
                reserved[rr][cc] = True

    finder(0, 0)
    finder(0, size - 7)
    finder(size - 7, 0)

    for i in range(size):  # timing patterns
        if not reserved[6][i]:
            modules[6][i] = i % 2 == 0
            reserved[6][i] = True
        if not reserved[i][6]:
            modules[i][6] = i % 2 == 0
            reserved[i][6] = True

    # Alignment patterns at every combination of the centres except the three
    # corners already occupied by finders. The test is on the index, not on
    # whether the cell is taken: from version 7 the first centre is 6, so the
    # patterns at (6, n) and (n, 6) lie across the timing lines and are drawn
    # over them - skipping those shifts every data module after them.
    centres = _ALIGNMENT[version]
    last = len(centres) - 1
    for a, row in enumerate(centres):
        for b, col in enumerate(centres):
            if (a, b) in ((0, 0), (0, last), (last, 0)):
                continue
            for r in range(-2, 3):
                for c in range(-2, 3):
                    modules[row + r][col + c] = max(abs(r), abs(c)) != 1
                    reserved[row + r][col + c] = True

    modules[4 * version + 9][8] = True  # the dark module
    reserved[4 * version + 9][8] = True

    for i in range(9):  # format information, reserved for now
        if not reserved[8][i]:
            reserved[8][i] = True
        if not reserved[i][8]:
            reserved[i][8] = True
    for i in range(8):
        reserved[8][size - 1 - i] = True
        reserved[size - 1 - i][8] = True

    if version >= 7:
        info = _VERSION_INFO[version]
        for i in range(18):
            bit = (info >> i) & 1
            row, col = i // 3, size - 11 + i % 3
            modules[row][col] = bool(bit)
            reserved[row][col] = True
            modules[col][row] = bool(bit)
            reserved[col][row] = True


def _place_data(modules, reserved, bits: list[int]) -> None:
    size = len(modules)
    at = 0
    upward = True
    col = size - 1
    while col > 0:
        if col == 6:  # the vertical timing pattern is not a data column
            col -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        for row in rows:
            for c in (col, col - 1):
                if reserved[row][c]:
                    continue
                modules[row][c] = at < len(bits) and bits[at] == 1
                at += 1
        upward = not upward
        col -= 2


_MASKS = (
    lambda i, j: (i + j) % 2 == 0,
    lambda i, j: i % 2 == 0,
    lambda i, j: j % 3 == 0,
    lambda i, j: (i + j) % 3 == 0,
    lambda i, j: (i // 2 + j // 3) % 2 == 0,
    lambda i, j: (i * j) % 2 + (i * j) % 3 == 0,
    lambda i, j: ((i * j) % 2 + (i * j) % 3) % 2 == 0,
    lambda i, j: ((i + j) % 2 + (i * j) % 3) % 2 == 0,
)


def _apply_mask(modules, reserved, mask: int):
    size = len(modules)
    rule = _MASKS[mask]
    out = [row[:] for row in modules]
    for i in range(size):
        for j in range(size):
            if not reserved[i][j] and rule(i, j):
                out[i][j] = not out[i][j]
    return out


def _format_bits(ecc: str, mask: int) -> int:
    """The 15-bit format information: 5 data bits, BCH(15,5), then masked."""
    value = (_ECC_BITS[ecc] << 3) | mask
    remainder = value
    for _ in range(10):
        remainder = (remainder << 1) ^ ((remainder >> 9) * 0x537)
    return ((value << 10) | remainder) ^ 0x5412


def _place_format(modules, ecc: str, mask: int) -> None:
    size = len(modules)
    bits = _format_bits(ecc, mask)

    def bit(i: int) -> bool:
        return bool((bits >> i) & 1)

    # First copy, wrapped around the top-left finder: down column 8, then
    # left along row 8. The two halves are not symmetric, which is why this
    # is written out rather than looped.
    for i in range(6):
        modules[i][8] = bit(i)
    modules[7][8] = bit(6)
    modules[8][8] = bit(7)
    modules[8][7] = bit(8)
    for i in range(9, 15):
        modules[8][14 - i] = bit(i)

    # Second copy, split between the other two finders, so a symbol with one
    # damaged corner still declares its own mask and level.
    for i in range(8):
        modules[8][size - 1 - i] = bit(i)
    for i in range(8, 15):
        modules[size - 15 + i][8] = bit(i)
    modules[size - 8][8] = True  # the dark module, always


#: Penalty weights from the standard: long runs, solid blocks, false finder
#: patterns, and an overall bias away from 50% dark.
_PENALTY_RUN, _PENALTY_BLOCK, _PENALTY_FINDER, _PENALTY_BALANCE = 3, 3, 40, 10


def _finder_like(history: list[int]) -> int:
    """How many false finder patterns end at this point in a line.

    The standard describes the shape as a *ratio*, 1:1:3:1:1 with a light
    margin four units wide, so a run of 2:2:6:2:2 counts too - which is why
    this reads run lengths rather than matching a fixed seven-module window.
    """
    unit = history[1]
    core = (unit > 0 and history[2] == unit and history[3] == unit * 3
            and history[4] == unit and history[5] == unit)
    return ((1 if core and history[0] >= unit * 4 and history[6] >= unit else 0)
            + (1 if core and history[6] >= unit * 4 and history[0] >= unit else 0))


def _penalty(modules) -> int:
    """How badly a masked symbol scans. Lower is better.

    The standard's four rules exist because a symbol full of long runs,
    solid blocks or things that look like finder patterns is one a phone
    gives up on. Which mask wins is not a correctness question - every mask
    produces a symbol that decodes, and two conforming encoders often pick
    differently - so this is chosen for scannability, not for agreement with
    anyone else's encoder.
    """
    size = len(modules)
    score = 0

    columns = [[modules[r][c] for r in range(size)] for c in range(size)]
    for line in [row[:] for row in modules] + columns:
        colour, run, history = False, 0, [0] * 7

        def remember(length: int) -> None:
            # The quiet zone outside the symbol is light, so a false finder
            # hard against the edge still has its margin and still counts.
            if history[0] == 0:
                length += size
            history[1:] = history[:-1]
            history[0] = length

        for cell in line:
            if cell == colour:
                run += 1
                if run == 5:
                    score += _PENALTY_RUN
                elif run > 5:
                    score += 1
            else:
                remember(run)
                if not colour:
                    score += _finder_like(history) * _PENALTY_FINDER
                colour, run = cell, 1
        if colour:
            remember(run)
            run = 0
        remember(run + size)
        score += _finder_like(history) * _PENALTY_FINDER

    for i in range(size - 1):
        for j in range(size - 1):
            block = (modules[i][j], modules[i][j + 1],
                     modules[i + 1][j], modules[i + 1][j + 1])
            if all(block) or not any(block):
                score += _PENALTY_BLOCK

    dark = sum(1 for row in modules for cell in row if cell)
    total = size * size
    # the smallest k with the dark share inside (50 +/- 5(k+1))%, in integers
    k = -(-abs(dark * 20 - total * 10) // total) - 1
    return score + max(k, 0) * _PENALTY_BALANCE


def encode(data: str | bytes, *, ecc: str = "H", min_version: int = 1,
           mask: int | None = None) -> QRCode:
    """Encode ``data`` as a QR symbol.

    ``ecc`` is one of ``L``, ``M``, ``Q``, ``H``; ``H`` by default because
    the symbols this toolkit produces are printed and hung outdoors.
    ``min_version`` forces a larger, coarser symbol than the payload needs -
    useful when a batch of placards should all look alike. ``mask`` forces
    one of the eight mask patterns instead of scoring all eight; it exists
    for the tests, which compare against an independent encoder mask by mask.
    """
    if ecc not in ECC_LEVELS:
        raise ValueError(f"unknown error-correction level {ecc!r}")
    if mask is not None and not 0 <= mask <= 7:
        raise ValueError(f"mask must be 0 to 7, not {mask!r}")
    payload = data.encode("utf-8") if isinstance(data, str) else bytes(data)
    version = _choose_version(len(payload), ecc, min_version)

    bits = _interleave(_bitstream(payload, version, ecc), version, ecc)
    size = 17 + 4 * version
    modules, reserved = _blank(size)
    _place_function_patterns(modules, reserved, version)
    _place_data(modules, reserved, bits)

    best, best_mask, best_score = None, 0, None
    for candidate_mask in range(8) if mask is None else (mask,):
        candidate = _apply_mask(modules, reserved, candidate_mask)
        _place_format(candidate, ecc, candidate_mask)
        score = _penalty(candidate)
        if best_score is None or score < best_score:
            best, best_mask, best_score = candidate, candidate_mask, score
    return QRCode(version=version, ecc=ecc, mask=best_mask, modules=best)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def to_svg(code: QRCode, *, scale: int = 4, border: int = 4) -> str:
    """The symbol as an SVG document, drawn as one path.

    The quiet zone is not decoration: a symbol printed hard against a frame
    or a photograph is much harder for a phone to find.
    """
    size = code.size + 2 * border
    parts = []
    for row in range(code.size):
        for col in range(code.size):
            if code.modules[row][col]:
                parts.append(f"M{col + border} {row + border}h1v1h-1z")
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size * scale}" '
        f'height="{size * scale}" viewBox="0 0 {size} {size}" '
        'shape-rendering="crispEdges">'
        f'<rect width="{size}" height="{size}" fill="#ffffff"/>'
        f'<path fill="#000000" d="{"".join(parts)}"/></svg>'
    )


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    body = kind + payload
    return (struct.pack(">I", len(payload)) + body
            + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))


def to_png(code: QRCode, *, scale: int = 8, border: int = 4) -> bytes:
    """The symbol as a greyscale PNG.

    Written here rather than through matplotlib so the bytes are identical
    on every machine: a report that changes because a plotting backend
    changed is a report nobody can diff.
    """
    size = (code.size + 2 * border) * scale
    raw = bytearray()
    for y in range(size):
        raw.append(0)  # no per-row filtering
        row = y // scale - border
        for x in range(size):
            col = x // scale - border
            dark = (0 <= row < code.size and 0 <= col < code.size
                    and code.modules[row][col])
            raw.append(0 if dark else 255)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 0, 0, 0, 0))
        + _png_chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + _png_chunk(b"IEND", b"")
    )
