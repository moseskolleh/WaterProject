"""Photo evidence (PLAN.md step 2.4): the "photo_evidence" entry of
``reference.json``.
"""

from __future__ import annotations

from .common import OUT


# ----------------------------------------------- photo evidence (step 2.4)

def photo_evidence_reference() -> dict:
    """The provenance both engines record for the same files, and the gate.

    The files are the committed fixture, whose EXIF was written by hand, and
    variants of it from the same builder: big-endian, no metadata at all
    (so the device clock and a device fix are used), and a blank clock.
    The bytes travel in this file, so the browser reads exactly these.
    """
    import base64
    import importlib.util

    from groundwater.photos import describe_provenance, photo_provenance
    from groundwater.readiness import assess_readiness

    spec = importlib.util.spec_from_file_location(
        "make_photo_fixture", OUT.parent / "fixtures" / "make_photo_fixture.py")
    make = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(make)
    attached = "2026-10-03T09:00:00Z"
    files = {
        "fixture": ((OUT.parent / "fixtures" / "photo_exif.jpg").read_bytes(), {}),
        "big_endian": (make.jpeg_with_exif(make.build_tiff(">", **make.FIXTURE_EXIF)), {}),
        "no_exif_device_fix": (make.BASE_JPEG, {
            "device_fix": {"lat": 8.4801, "lon": -13.2302, "accuracy_m": 12.5}}),
        "no_exif_refused": (make.BASE_JPEG, {"position_note": "refused",
                                             "stored": "downscaled"}),
        "blank_clock": (make.jpeg_with_exif(make.build_tiff(
            "<", taken="0000:00:00 00:00:00", lat=make.FIXTURE_EXIF["lat"],
            lon=make.FIXTURE_EXIF["lon"])), {}),
        # padded with a control byte that str.strip() takes and trim() does
        # not, and with a space both take: the two once read this differently
        "control_padding": (make.jpeg_with_exif(make.build_tiff(
            ">", taken=" 2024:03:05 14:22:10", offset="+01:00\x1c",
            lat=("N ", ((8, 1), (1, 1), (1, 1))),
            lon=("W\x1f", ((13, 1), (0, 1), (0, 1))))), {}),
    }
    cases = {}
    for name, (data, options) in files.items():
        record = photo_provenance(data, attached, **options)
        cases[name] = {
            "b64": base64.b64encode(data).decode("ascii"),
            "options": options,
            "record": record,
            "shown": describe_provenance(record),
        }
    photo = {"b64": cases["fixture"]["b64"]}
    gate = {
        "none": {},
        "one": {"supervision": {"evidence": {"des-backfill-placed-6": photo}}},
        "all": {"supervision": {"evidence": {
            key: photo for key in ("des-casing-screen-assemblage",
                                   "des-backfill-placed-6",
                                   "dev-borehole-disinfected-chlorine")}}},
        "na": {"supervision": {"responses": {
            "des-casing-screen-assemblage": {"status": "na"},
            "des-backfill-placed-6": {"status": "na"},
            "dev-borehole-disinfected-chlorine": {"status": "na"}}}},
    }
    # Every critical item needs an answer: answered in both apps' shapes
    # (the browser's {status}, the Streamlit app's bare code), a No is an
    # answer, and a code that is none of the four is pending.
    from groundwater.supervision import load_checklists as _load_checklists

    _critical = [i.item_id for i in _load_checklists() if i.critical]
    _photographed = {key: photo for key in ("des-casing-screen-assemblage",
                                            "des-backfill-placed-6",
                                            "dev-borehole-disinfected-chlorine")}
    gate["answered"] = {"supervision": {"evidence": _photographed, "responses": {
        key: ({"status": "yes"} if n % 2 else "Yes ") for n, key in enumerate(_critical)}}}
    gate["failed"] = {"supervision": {"evidence": _photographed, "responses": {
        key: {"status": "no", "remark": "not done"} for key in _critical}}}
    gate["garbled"] = {"supervision": {"evidence": _photographed, "responses": {
        key: ("maybe" if n < 3 else "na") for n, key in enumerate(_critical)}}}
    gate["three_of_38"] = {"supervision": {"evidence": _photographed, "responses": {
        key: {"status": "yes"} for key in _photographed}}}
    # records as a hand-edited project file can hold them: a position that
    # is text, half a position, one out of range, not a number, an accuracy
    # that is text or below zero, and codes that are not text
    base = {"sha256": "ab" * 32, "taken_at": "2026-10-03T09:00:00Z", "time_source": "exif",
            "position_source": "exif", "position_note": "refused"}
    positions = [{"lat": "8.5N", "lon": -12.1, "accuracy_m": None}, {"lat": "8.5", "lon": "-12.1"},
                 {"lat": 8.5, "lon": None}, {"lat": None, "lon": -12.1}, {"lat": 95.0, "lon": -12.1},
                 {"lat": 8.5, "lon": -181.0}, {"lat": True, "lon": -12.1}, "8.5N, 12.1W", [8.5, -12.1], 0,
                 {"lat": 8.5, "lon": -12.1, "accuracy_m": "5 m"}, {"lat": 8.5, "lon": -12.1, "accuracy_m": -3},
                 {"lat": -90, "lon": 180, "accuracy_m": 4}, {"lat": None, "lon": None}, None, {}]
    edited = [dict(base, position=position) for position in positions]
    edited += [dict(base, position=None, position_note=["refused"], time_source=["exif"]),
               dict(base, position={"lat": 8.5, "lon": -12.1}, position_source=["exif"]),
               dict(base, position={"lat": 8.5, "lon": -12.1, "accuracy_m": True}),
               dict(base, position={"lat": 8.5, "lon": -12.1, "accuracy_m": 0}),
               dict(base, taken_at=20261003.5, position=None),
               dict(base, taken_at=["2026-10-03"], position=None),
               dict(base, sha256=12345), dict(base, sha256=["ab" * 32]), dict(base, sha256="")]
    return {
        "attached_at": attached,
        "cases": cases,
        "hand_edited": [{"record": r, "shown": describe_provenance(r)} for r in edited],
        "no_record": describe_provenance(None),
        "gate": {
            name: [[r.key, r.state, r.detail]
                   for r in assess_readiness(state, "supervision").requirements]
            for name, state in gate.items()
        },
        "gate_states": gate,
    }
