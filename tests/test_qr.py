"""The QR encoder, checked by things that are not it.

A QR symbol that is wrong in the data region still looks like a QR symbol -
seven-by-seven finders, a quiet zone, a convincing scatter of modules - so
reading the output and nodding at it proves nothing. Two independent
oracles are used instead.

segno, an independent encoder, is compared module for module. The two
disagree on one thing: after the four-bit terminator a byte-mode stream is
already on a byte boundary, and segno adds a further zero byte before the
pad codewords where the standard adds none. Both symbols decode, because a
decoder stops at the terminator - but it means the two only have to agree
exactly when the payload fills the data capacity and there is no padding to
disagree about. That is where the comparison is made, and it covers every
version, every error-correction level and all eight masks.

OpenCV's detector then reads the symbols back. That is the property that
actually matters at a wellhead: not that the modules are defensible, but
that a phone resolves them into the identifier. It is also the only way to
show the error-correction codewords are real - a symbol with a corner
scribbled out still has to decode.

Both oracles are test-only, and both are named in the ``dev`` extra so CI
installs them; ``test_packaging`` fails if that stops being true.
"""

from __future__ import annotations

import zlib

import pytest

from groundwater import qr

segno = pytest.importorskip("segno", reason="the oracle encoder is not installed")


PLACARD_PAYLOADS = [
    "SL-WAR-8T4KQ2-7",
    ("BH SL-WAR-8T4KQ2-7\nDr. Timbo's Residence, Western Area Rural\n"
    "8.48310 N 13.22940 W\nDrilled 2018-05-10  62.0 m  1.85 m3/h"),
    "x",
    "0123456789" * 11,
]


def _oracle(text: str, ecc: str, mask: int | None = None, version=None):
    """segno, held to the level asked for.

    ``boost_error`` is on by default: given a payload that leaves room,
    segno silently raises the level, so a symbol requested at L comes back
    at H and every comparison below would be against the same level.
    """
    return segno.make(text, error=ecc, mask=mask, version=version,
                      micro=False, mode="byte", boost_error=False)


def _filling_payload(version: int, ecc: str) -> str:
    """A payload that exactly fills the data capacity, so nothing is padded."""
    n = qr._capacity_bytes(version, ecc)
    return "".join(chr(65 + (i * 7) % 26) for i in range(n))


@pytest.mark.parametrize("version", range(1, qr.MAX_VERSION + 1))
@pytest.mark.parametrize("ecc", ["L", "M", "Q", "H"])
def test_every_module_matches_an_independent_encoder(version, ecc):
    """All eight masks, so nothing hides behind mask selection."""
    text = _filling_payload(version, ecc)
    for mask in range(8):
        ours = qr.encode(text, ecc=ecc, mask=mask, min_version=version)
        assert ours.version == version
        theirs = [[bool(cell) for cell in row]
                  for row in _oracle(text, ecc, mask).matrix]
        assert len(theirs) == ours.size, f"v{version} {ecc}/{mask}: size differs"
        for row in range(ours.size):
            assert ours.modules[row] == theirs[row], (
                f"v{version} {ecc} mask {mask}: row {row} differs")


@pytest.mark.parametrize("version", range(1, qr.MAX_VERSION + 1))
def test_the_chosen_mask_is_the_best_scoring_one(version):
    """Mask selection is a penalty score, and the choice has to follow it.

    Not compared against segno: which mask wins is not a correctness
    question - every mask decodes, the score only picks the one that scans
    most easily - and two conforming encoders routinely differ. What must
    hold is that the encoder actually picks its own minimum, deterministically
    and with the lowest index on a tie, so the same payload always produces
    the same symbol.
    """
    for ecc in ("L", "M", "Q", "H"):
        text = _filling_payload(version, ecc)
        chosen = qr.encode(text, ecc=ecc, min_version=version)
        scores = [qr._penalty(qr.encode(text, ecc=ecc, min_version=version,
                                        mask=mask).modules) for mask in range(8)]
        assert chosen.mask == scores.index(min(scores)), (version, ecc, scores)
        assert chosen.modules == qr.encode(
            text, ecc=ecc, min_version=version).modules


# ---------------------------------------------------------------------------
# Reading the symbols back
# ---------------------------------------------------------------------------

def _decoded(code: qr.QRCode, scale: int = 8) -> str:
    cv2 = pytest.importorskip("cv2", reason="no decoder installed")
    import numpy as np

    png = qr.to_png(code, scale=scale, border=4)
    image = cv2.imdecode(np.frombuffer(png, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    text, *_ = cv2.QRCodeDetector().detectAndDecode(image)
    return text


@pytest.mark.parametrize("text", PLACARD_PAYLOADS)
@pytest.mark.parametrize("ecc", ["L", "M", "Q", "H"])
def test_a_symbol_reads_back_as_what_went_into_it(text, ecc):
    """Through the PNG writer, because that is what gets printed."""
    assert _decoded(qr.encode(text, ecc=ecc)) == text


def test_the_error_correction_is_real_error_correction():
    """A placard lives outdoors. Level H exists to survive losing a corner.

    Without this the Reed-Solomon codewords could be any 17 bytes at all and
    every other test here would still pass.
    """
    text = "SL-WAR-8T4KQ2-7 / Dr. Timbo's Residence"
    code = qr.encode(text, ecc="H")
    damaged = [row[:] for row in code.modules]
    size = code.size
    for row in range(size - 9, size):        # scribble out the far corner,
        for col in range(size - 9, size):    # about a tenth of the symbol
            damaged[row][col] = (row + col) % 2 == 0
    assert _decoded(qr.QRCode(code.version, code.ecc, code.mask, damaged)) == text


# ---------------------------------------------------------------------------
# Structure and refusals
# ---------------------------------------------------------------------------

def test_the_block_tables_are_self_consistent():
    """Data plus error correction has to be exactly the codeword count.

    A mistyped digit in the block table produces a symbol that encodes the
    right bytes into the wrong shape, which the oracle catches - but this
    says so in one line instead of eighty failures.
    """
    for version, levels in qr._BLOCKS.items():
        for level, (ec, g1, d1, g2, d2) in levels.items():
            total = g1 * d1 + g2 * d2 + ec * (g1 + g2)
            assert total == qr._TOTAL_CODEWORDS[version - 1], (version, level)
            if g2:
                assert d2 == d1 + 1, (version, level)


def test_a_stronger_level_never_carries_more_data():
    for version in range(1, qr.MAX_VERSION + 1):
        capacities = [qr._capacity_bytes(version, level) for level in "LMQH"]
        assert capacities == sorted(capacities, reverse=True), version


def test_a_payload_too_large_is_refused_not_truncated():
    """Silently dropping the tail would produce a symbol that scans and lies."""
    with pytest.raises(ValueError, match="will not fit"):
        qr.encode("x" * 300, ecc="H")


def test_an_unknown_error_correction_level_is_refused():
    with pytest.raises(ValueError, match="error-correction level"):
        qr.encode("x", ecc="Z")
    with pytest.raises(ValueError, match="mask must be"):
        qr.encode("x", mask=9)


def test_the_quiet_zone_is_part_of_the_image():
    """A symbol printed hard against a border is one a phone cannot find."""
    code = qr.encode("SL-WAR-8T4KQ2-7", ecc="M")
    svg = qr.to_svg(code, scale=4, border=4)
    assert f'viewBox="0 0 {code.size + 8} {code.size + 8}"' in svg
    assert svg.startswith("<svg") and svg.endswith("</svg>")


def test_the_png_is_a_png_and_is_the_same_bytes_every_time():
    """Reports get diffed. An image that changes on its own defeats that."""
    code = qr.encode("SL-WAR-8T4KQ2-7", ecc="M")
    first = qr.to_png(code, scale=4, border=4)
    assert first[:8] == b"\x89PNG\r\n\x1a\n"
    assert first == qr.to_png(code, scale=4, border=4)

    width = int.from_bytes(first[16:20], "big")
    height = int.from_bytes(first[20:24], "big")
    expected = (code.size + 8) * 4
    assert (width, height) == (expected, expected)

    # and the pixels really are the modules, not a plausible-looking texture
    idat, at = b"", 8
    while at < len(first):
        length = int.from_bytes(first[at:at + 4], "big")
        if first[at + 4:at + 8] == b"IDAT":
            idat += first[at + 8:at + 8 + length]
        at += 12 + length
    raw = zlib.decompress(idat)
    stride = width + 1
    for row, col in ((0, 0), (code.size // 2, code.size // 3),
                     (code.size - 1, code.size - 1)):
        pixel = raw[((row + 4) * 4) * stride + 1 + (col + 4) * 4]
        assert (pixel == 0) == code.modules[row][col], (row, col)
