"""Shared fixtures: sample data paths and the transcribed Rokel readings,
and the writers of the compressed blocks the codec tests read."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import numpy as np
import pytest

from groundwater.models import SiteMetadata, VESSounding

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "examples" / "data"


@pytest.fixture(scope="session", autouse=True)
def sample_data():
    """Build the example datasets once for the whole test session."""
    import subprocess
    import sys

    if not (DATA / "rokel" / "rokel_ves.xlsx").exists():
        subprocess.run(
            [sys.executable, str(REPO / "examples" / "build_sample_data.py")],
            check=True,
        )
    return DATA


@pytest.fixture()
def rokel_ves_a() -> VESSounding:
    ab2 = [1, 2, 3, 3, 4, 5, 7, 10, 10, 15, 20, 30, 40, 40, 50, 70, 70, 80]
    mn = [0.4, 0.4, 0.4, 0.8, 0.8, 0.8, 0.8, 0.8, 1.5, 1.5, 1.5, 1.5, 1.5, 7.6, 7.6, 7.6, 14, 14]
    rho = [1165, 1193, 1303, 1317, 1502, 1500, 1432, 1392, 961.0, 715.5,
           732.0, 162.0, 156.1, 78.7, 52.1, 55.8, 53.2, 47.9]
    return VESSounding(
        site=SiteMetadata(community="Rokel", district="Western Area",
                          easting=708958, northing=926355, utm_zone=28),
        sounding_id="A (1)",
        ab2=np.array(ab2, float),
        mn=np.array(mn, float),
        rho_app=np.array(rho, float),
    )


# ---------------------------------------------------------------------------
# A pumping test the analysis can establish a yield from
# ---------------------------------------------------------------------------

def theis_series(T=120.0, S=1e-3, Q=5.0, r=0.1, t_min=None):
    """Drawdown in the pumped well of an ideal Theis aquifer."""
    from scipy.special import exp1

    if t_min is None:
        t_min = np.array([1, 2, 3, 5, 7, 10, 15, 20, 30, 45, 60, 90, 120, 180,
                          240, 300, 360], float)
    u = r * r * S / (4 * T * (t_min / 1440.0))
    return t_min, (Q * 24.0) / (4 * np.pi * T) * exp1(u)


def synthetic_constant_test(t_min=None, drawdown=None, swl=10.0, q=5.0,
                            pump=40.0, depth=60.0, recovery=None,
                            T=120.0):
    """A six-hour constant test in an ideal aquifer, with recovery if asked.

    ``recovery`` is ``(t_prime_min, residual_drawdown_m)``, or ``True`` for
    the theoretical Theis recovery of the same aquifer. Long enough, and
    productive enough, that the analysis establishes its yield: the point
    of the fixture is a project with nothing to hold a certificate back.
    """
    from groundwater.models import PumpingStep, PumpingTest

    if t_min is None or drawdown is None:
        t_min, drawdown = theis_series(T=T, Q=q)
    step = PumpingStep(step_number=1, discharge_m3_per_h=q, time_min=t_min,
                       water_level_m=swl + drawdown)
    test = PumpingTest(
        site=SiteMetadata(community="synthetic"), test_type="constant",
        static_water_level_m=swl, borehole_depth_m=depth, pump_setting_m=pump,
        steps=[step], pumping_duration_min=float(t_min[-1]),
    )
    if recovery is True:
        t_rec = np.array([1, 2, 3, 5, 7, 10, 15, 20, 30, 45, 60, 90, 120], float)
        slope = 2.303 * (q * 24.0) / (4 * np.pi * T)
        recovery = (t_rec, slope * np.log10((float(t_min[-1]) + t_rec) / t_rec))
    if recovery is not None:
        t_rec, residual = recovery
        test.recovery_time_min = np.asarray(t_rec, float)
        test.recovery_level_m = swl + np.asarray(residual, float)
        test.test_type = "constant+recovery"
    return test


@pytest.fixture()
def established_analysis():
    """An analysis whose yield is established, not indicative."""
    from groundwater.hydraulics import analyse_pumping_test

    return analyse_pumping_test(synthetic_constant_test(recovery=True))


# ---------------------------------------------------------------------------
# The Streamlit app
# ---------------------------------------------------------------------------

def goto(at, page: str):
    """Open one of the Streamlit app's pages, as its sidebar navigation does.

    Only the page on screen runs (PLAN.md step 1.1), so a test reaches a
    page's widgets by opening the page first. ``page`` is the title the
    sidebar lists.
    """
    at.session_state["nav"] = page
    at.run()
    assert not at.exception, at.exception
    return at


# ---------------------------------------------------------------------------
# Compressed blocks for the codec tests (geotiff.py and gwt-core.js)
# ---------------------------------------------------------------------------

def lzw_pack(codes) -> bytes:
    """``(code, width)`` pairs packed most significant bit first, as TIFF
    LZW packs them, so a test can write a stream no encoder would."""
    out = bytearray()
    acc = count = 0
    for code, width in codes:
        acc = (acc << width) | code
        count += width
        while count >= 8:
            count -= 8
            out.append((acc >> count) & 255)
        acc &= (1 << count) - 1
    if count:
        out.append((acc << (8 - count)) & 255)
    return bytes(out)


def lzw_encode(data: bytes, *, limit: int = 4094, defer: int = 0, end: bool = True) -> bytes:
    """TIFF LZW as libtiff writes it: a Clear first, codes widening one code
    early, and a Clear once the table holds ``limit`` entries (4,094 in
    libtiff). With ``limit=4096`` and ``defer=N`` the table fills and the
    Clear waits until N more codes have been sent: the "deferred clear"
    some writers use, which libtiff reads while its table, 1,023 entries
    longer than any code can name, has room. ``end=False`` leaves off the
    end code, as some writers do."""
    codes = [(256, 9)]
    width, nxt, sent, fresh = 9, 258, 0, True
    table = {bytes([i]): i for i in range(256)}
    word = b""
    for value in data:
        byte = bytes([value])
        if not word or word + byte in table:
            word += byte
            continue
        codes.append((table[word], width))
        fresh = False
        if nxt < limit:
            table[word + byte] = nxt
            nxt += 1
            if nxt >= (1 << width) and width < 12:
                width += 1
        else:
            sent += 1
        if nxt >= limit and sent >= defer:
            codes.append((256, width))
            table = {bytes([i]): i for i in range(256)}
            width, nxt, sent, fresh = 9, 258, 0, True
        word = byte
    if word:
        codes.append((table[word], width))
        if not fresh:
            # the entry a decoder adds on reading that code, which can widen
            # the end code after it, as libtiff's LZWPostEncode allows for
            nxt += 1
            if nxt >= (1 << width) and width < 12:
                width += 1
    if end:
        codes.append((257, width))
    return lzw_pack(codes)


def packbits_encode(data: bytes) -> bytes:
    """PackBits: a run of three or more equal bytes as a repeat, anything
    else as literals, at most 128 bytes to a header."""
    out = bytearray()
    i, n = 0, len(data)
    while i < n:
        run = 1
        while i + run < n and run < 128 and data[i + run] == data[i]:
            run += 1
        if run >= 3:
            out += bytes([257 - run, data[i]])
            i += run
            continue
        start = i
        while i < n and i - start < 128:
            if i + 2 < n and data[i] == data[i + 1] == data[i + 2]:
                break
            i += 1
        out.append(i - start - 1)
        out += data[start:i]
    return bytes(out)


_LBASE = [3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31,
          35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258]
_LEXT = [0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2,
         3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0]
_DBASE = [1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193,
          257, 385, 513, 769, 1025, 1537, 2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577]
_DEXT = [0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6,
         7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13]
_CL_ORDER = [16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15]
_FIXED_LIT = [8] * 144 + [9] * 112 + [7] * 24 + [8] * 8
_FIXED_DIST = [5] * 32


def _canonical(lengths) -> dict:
    """symbol -> (code, length) of the canonical Huffman code, RFC 1951 3.2.2."""
    count = [0] * 16
    for length in lengths:
        count[length] += 1
    count[0] = 0
    nxt, code = [0] * 16, 0
    for bits in range(1, 16):
        code = (code + count[bits - 1]) << 1
        nxt[bits] = code
    codes = {}
    for symbol, length in enumerate(lengths):
        if length:
            codes[symbol] = (nxt[length], length)
            nxt[length] += 1
    return codes


class DeflateWriter:
    """DEFLATE written block by block, for the streams no encoder writes: a
    copy from exactly 32,768 bytes back, the codes zlib's tables hold but
    refuse, a stored block straight after a Huffman one that ends mid-byte,
    and dynamic headers broken in each way zlib refuses. It keeps the bytes
    the stream stands for, so a valid stream carries its own Adler-32."""

    def __init__(self) -> None:
        self.body = bytearray()
        self.data = bytearray()
        self._acc = self._count = 0

    def bits(self, value: int, count: int) -> None:
        """``count`` bits of ``value``, least significant first."""
        self._acc |= (value & ((1 << count) - 1)) << self._count
        self._count += count
        while self._count >= 8:
            self.body.append(self._acc & 255)
            self._acc >>= 8
            self._count -= 8

    def _code(self, code: int, length: int) -> None:
        # a Huffman code goes most significant bit first
        self.bits(int(format(code, f"0{length}b")[::-1], 2), length)

    def _align(self) -> None:
        if self._count:
            self.bits(0, 8 - self._count)

    def stored(self, data: bytes, last: bool = False, nlen: int | None = None) -> None:
        self.bits(int(last), 1)
        self.bits(0, 2)
        self._align()
        self.body += struct.pack("<HH", len(data), len(data) ^ 0xFFFF if nlen is None else nlen)
        self.body += data
        self.data += data

    def fixed(self, items, last: bool = False) -> None:
        self.bits(int(last), 1)
        self.bits(1, 2)
        self._items(items, _canonical(_FIXED_LIT), _canonical(_FIXED_DIST))

    def dynamic(self, lit, dist, items=(), last: bool = False, *, cl=None, sequence=None) -> None:
        """A dynamic block with these literal/length and distance code
        lengths. ``cl`` gives the 19 code-length code lengths (by default
        four bits for each of 0 to 15), and ``sequence`` the code-length
        symbols sent as ``(symbol, extra)`` (by default each length as
        itself), so a header can be broken in any one way."""
        cl = list(cl) if cl is not None else [4] * 16 + [0] * 3
        self.bits(int(last), 1)
        self.bits(2, 2)
        self.bits(len(lit) - 257, 5)
        self.bits(len(dist) - 1, 5)
        sent = max([i for i, s in enumerate(_CL_ORDER) if cl[s]] + [3]) + 1
        self.bits(sent - 4, 4)
        for symbol in _CL_ORDER[:sent]:
            self.bits(cl[symbol], 3)
        cl_codes = _canonical(cl)
        if sequence is None:
            sequence = [(length, 0) for length in list(lit) + list(dist)]
        for symbol, extra in sequence:
            self._code(*cl_codes[symbol])
            if symbol >= 16:
                self.bits(extra, {16: 2, 17: 3, 18: 7}[symbol])
        self._items(items, _canonical(lit), _canonical(dist))

    def _items(self, items, lit, dist) -> None:
        """Literals as ints, ``("copy", length, distance)``, and ``("raw",
        symbol, extra bits, extra, distance symbol, extra bits, extra)`` for
        a code no encoder would send; then the end of the block."""
        for item in items:
            if isinstance(item, int):
                self._code(*lit[item])
                self.data.append(item)
                continue
            if item[0] == "copy":
                _, length, distance = item
                i = max(k for k in range(29) if _LBASE[k] <= length)
                j = max(k for k in range(30) if _DBASE[k] <= distance)
                item = ("raw", 257 + i, _LEXT[i], length - _LBASE[i], j, _DEXT[j], distance - _DBASE[j])
            _, symbol, nbits, extra, dsymbol, dbits, dextra = item
            self._code(*lit[symbol])
            self.bits(extra, nbits)
            if dsymbol is None:
                continue
            if dsymbol in dist:
                self._code(*dist[dsymbol])
            else:
                self.bits(0, 5)  # a set with no codes: zlib refuses whatever follows
            self.bits(dextra, dbits)
            if symbol <= 285 and dsymbol < 30:
                length = _LBASE[symbol - 257] + extra
                distance = _DBASE[dsymbol] + dextra
                for _ in range(length if distance <= len(self.data) else 0):
                    self.data.append(self.data[-distance])
        if 256 in lit:
            self._code(*lit[256])

    def zlib(self, junk: bytes = b"") -> bytes:
        """The stream: zlib's header, the blocks, the Adler-32 of what they
        hold, and ``junk`` after it."""
        self._align()
        return b"\x78\x9c" + bytes(self.body) + struct.pack(">I", zlib.adler32(self.data)) + junk
