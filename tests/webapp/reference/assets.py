"""The asset register: service rounds (PLAN.md step 7.3), survival (7.4),
reports from the plate and by SMS (7.1), the QR symbol a placard carries and
the registry itself - the "rounds", "survival", "fault_reports", "qr",
"qr_capacity" and "asset_ids" to "asset_months" entries of
``reference.json``.
"""

from __future__ import annotations

import json

from groundwater.models import SiteMetadata

from .common import clean


def rounds_reference() -> dict:
    """Service rounds (PLAN.md step 7.3): what is due at each borehole of a
    register on a day, by area mechanic and in the order of the walk, with
    the words and the round sheet's parts; and each record's state as the
    registry reads it, the routine inspection among its visits. Named cases
    for each rule, then registers drawn from seeds. The cases carry their
    own inputs, so parity.mjs gives the browser exactly these."""
    import random as _random
    from dataclasses import asdict as _asdict
    from datetime import date as _date

    from groundwater import rounds as RD
    from groundwater.registry import Schedule, asset_from_dict, asset_state, mint_asset_id

    def ident(easting, northing=938150.0, zone=28, district="Western Area Rural"):
        return mint_asset_id(SiteMetadata(district=district, easting=easting,
                                          northing=northing, utm_zone=zone))

    def record(easting, *events, northing=938150.0, **fields):
        return {"asset_id": ident(easting, northing), "community": "Case",
                "district": "Western Area Rural", "easting": easting, "northing": northing,
                "utm_zone": 28, "events": list(events), **fields}

    def ev(when, kind, **more):
        return {"when": when, "kind": kind, **more}

    old, late = ev("2019-01-10", "commissioned"), ev("2022-01-10", "commissioned")
    aggressive = {"material": "stainless steel", "inspection_months": 6, "chemistry": "aggressive"}
    plain = {"material": "galvanised iron", "inspection_months": 12, "chemistry": "not_aggressive"}
    named = {
        # four on a line at 0, 1, 3 and 6 km: the walk starts at the one due
        # longest and goes to the nearest each time
        "walk": [record(694000.0, late), record(695000.0, late), record(697000.0, old),
                 record(700000.0, late)],
        # equidistant either side of the start: the lower identifier first
        "tie": [record(696000.0, late), record(694000.0, late), record(695000.0, old)],
        "silent": [record(694000.0)],
        "not_due_and_gone": [record(694000.0, ev("2024-05-20", "commissioned")),
                             record(695000.0, late, ev("2022-08-01", "decommissioned")),
                             record(696000.0, late)],
        "routine_by_design": [record(694000.0, late, ev("2023-11-20", "routine_inspection"),
                                     rising_main=aggressive),
                              record(695000.0, late, ev("2023-11-20", "routine_inspection"),
                                     rising_main=plain),
                              record(696000.0, late, ev("2023-11-20", "repair"))],
        "mechanics": [record(694000.0, late, chiefdom="Koya"),
                      record(695000.0, late, chiefdom="KORI"),
                      record(696000.0, late, chiefdom="Bo Town"),
                      record(697000.0, late, chiefdom="koya", area_mechanic=" Zainab ")],
        "merged": [record(694000.0, late), {**record(694000.0, ev("2024-05-30", "routine_inspection")),
                                            "community": "", "area_mechanic": "A. Bangura",
                                            "rising_main": aggressive},
                   {"asset_id": "not one"}],
        "unplaced": [record(694000.0, late), {**record(700000.0, late), "easting": None},
                     {**record(690000.0, late), "easting": "690000"},
                     {**record(698000.0, late), "utm_zone": "28"}],
        "beyond": [record(694000.0, ev("9999-08-01", "commissioned"))],
        "zones": [record(694000.0, late), {**record(280400.0, late, northing=925600.0),
                                            "asset_id": ident(280400.0, 925600.0, 29, "Kailahun"),
                                            "utm_zone": 29}],
    }
    table = "Koya: M. Kolleh\nkori: A. Bangura\nno colon\nKOYA: Someone Else\n: blank\n"
    cases = []

    def case(name, assets, as_of="2024-06-01", mechanics=table, schedule=None, sheets=True,
             report_url=None):
        plan = Schedule(**{**_asdict(Schedule()), **(schedule or {})})
        parsed = RD.parse_area_mechanics(mechanics)
        result = RD.service_rounds(assets, as_of, plan, parsed["entries"], report_url or "")
        states = []
        for raw in assets:
            asset = asset_from_dict(raw)
            states.append(None if asset is None
                          else asset_state(asset, _date.fromisoformat(as_of), plan).as_dict())
        rounds = []
        for one in result["rounds"]:
            told = {"text": RD.round_text(one), "rows": RD.round_rows(one)}
            if sheets:
                told["sheets"] = [RD.stop_sheet(stop) for stop in one["stops"]]
            rounds.append(told)
        cases.append({
            "name": name, "assets": assets, "as_of": as_of, "mechanics": mechanics,
            "schedule": schedule or {}, "sheets": sheets,
            **({"report_url": report_url} if report_url is not None else {}),
            "expect": {"parsed": parsed, "result": result, "words": RD.rounds_text(result),
                       "rounds": rounds, "states": states},
        })

    # the round sheet's parts are held where they differ most: the three
    # visits' boxes and bases, and merged records with a mechanic named
    with_sheets = {"routine_by_design", "merged"}
    for name, assets in named.items():
        case(name, assets, as_of="9999-12-31" if name == "beyond" else "2024-06-01",
             sheets=name in with_sheets)
    case("empty", [])
    case("schedule", named["routine_by_design"], sheets=False,
         schedule={"water_sample_months": 3, "grace_days": 0, "routine_inspection_months": 24})
    # registers drawn from seeds: a patch of zone 28 where legs tie and stops
    # coincide, second records of one borehole, and positions, mechanics and
    # rising mains that are not what they should be. The round sheet's parts
    # are held on two named cases only, to keep this section small
    # (tests/test_rounds.py holds them on its own seeded registers)
    days = ["2019-03-01", "2020-01-10", "2022-08-01", "2023-05-20", "2023-11-20", "2023-12-01",
            "2024-01-31", "2024-05-01", "2024-06-01", "2024-07-15", "2099-01-01", "not written"]
    kinds = ["commissioned", "inspection", "routine_inspection", "water_sample", "repair",
             "failure", "restored", "decommissioned", "note"]
    for seed in range(6):
        rng = _random.Random(f"rounds {seed}")
        assets, ids = [], []
        for _ in range(rng.randint(1, 9)):
            easting = rng.choice([694000.0, 694500.0, 695000.0, 696000.0,
                                  round(rng.uniform(690000.0, 700000.0), 1)])
            northing = rng.choice([938150.0, round(rng.uniform(930000.0, 940000.0), 1)])
            if ids and rng.random() < 0.2:
                asset_id = rng.choice(ids)
            else:
                asset_id = ident(easting, northing)
                ids.append(asset_id)
            raw = {"asset_id": asset_id, "community": rng.choice(["Rokel", "", None]),
                   "district": "Western Area Rural",
                   "chiefdom": rng.choice(["Koya", "KORI", "", None, "Bumpe Ngao"]),
                   "easting": rng.choice([easting] * 9 + [None]), "northing": northing,
                   "utm_zone": rng.choice([28] * 9 + [None]),
                   "events": [ev(rng.choice(days), rng.choice(kinds))
                              for _ in range(rng.choice([0, 1, 2, 3, 5]))]}
            if rng.random() < 0.4:
                raw["area_mechanic"] = rng.choice(["A. Bangura", " M. Kolleh ", "", 7])
            if rng.random() < 0.5:
                raw["rising_main"] = rng.choice([aggressive, plain, {"inspection_months": 9},
                                                 {"inspection_months": 6.5}])
            assets.append(raw)
        case(f"seed {seed}", assets, as_of=rng.choice(["2024-06-01", "2024-02-29"]), sheets=False)
    # plates printed with a report address (PLAN.md step 7.1): a scan of
    # each begins with the link to its report page
    case("linked", named["walk"], report_url=" https://water.example.org/toolkit/ ")
    return clean({"cases": cases})


def survival_reference() -> dict:
    """How long boreholes keep working (PLAN.md step 7.4): the time to the
    first failure across a register as of a day, by pump type, contractor
    and water chemistry, with the comparison, the words and the tables. Named
    cases for each rule, then registers drawn from seeds. The cases carry
    their own inputs, so parity.mjs gives the browser exactly these."""
    import random as _random
    from dataclasses import replace as _replace

    from groundwater import survival as SV
    from groundwater.config import Config, SurvivalConfig
    from groundwater.registry import mint_asset_id

    def ident(easting):
        return mint_asset_id(SiteMetadata(district="Western Area Rural", easting=easting,
                                          northing=938150.0, utm_zone=28))

    def record(i, *events, **fields):
        return {"asset_id": ident(690000.0 + 1000.0 * i), "community": "Case",
                "district": "Western Area Rural", "easting": 690000.0 + 1000.0 * i,
                "northing": 938150.0, "utm_zone": 28,
                "events": [{"when": when, "kind": kind} for when, kind in events], **fields}

    aggressive = {"material": "stainless steel", "inspection_months": 6, "chemistry": "aggressive"}
    plain = {"material": "galvanised iron", "inspection_months": 12, "chemistry": "not_aggressive"}

    def register(n_a, n_b, n_c=0, late=1500):
        """two pump types (and a third), one failing early and one late"""
        out = []
        for i in range(n_a + n_b + n_c):
            kind = "Afridev" if i < n_a else ("India Mark II" if i < n_a + n_b else "Kardia")
            offset = 200 + 40 * i if i < n_a else late + 50 * i
            year, rest = 2018 + offset // 365, offset % 365
            when = f"{year}-{1 + rest // 31:02d}-{1 + rest % 28:02d}"
            out.append(record(i, ("2018-01-10", "commissioned"),
                              (when, "failure" if i % 3 else "routine_inspection"),
                              pump_type=kind if i != 1 else kind.upper(),
                              installed_by="Contractor A" if i % 2 else "",
                              rising_main=aggressive if i % 2 else plain))
        return out

    named = {
        "two_pumps": register(6, 7, 2),
        "one_pump": register(6, 2),
        # all fail where the other group has left the risk set
        "one_at_risk": [record(i, ("2018-01-10", "commissioned"),
                               ("2018-03-01", "routine_inspection"), pump_type="A")
                        for i in range(5)]
        + [record(10 + i, ("2018-01-10", "commissioned"), (f"2023-0{i + 1}-01", "failure"),
                  pump_type="B") for i in range(5)],
        # at risk together only on the day every borehole at risk failed
        "singular": [record(i, ("2018-01-10", "commissioned"), ("2019-01-10", "failure"),
                            pump_type="AB"[i % 2]) for i in range(10)],
        # a pump type new this year, never at risk when an older one failed:
        # left out of the test, which compares the other two without it
        "new_pump": register(6, 7) + [
            record(30 + i, ("2024-01-10", "commissioned"), ("2024-03-01", "routine_inspection"),
                   pump_type="Kardia") for i in range(5)],
        "no_failures": [record(i, ("2018-01-10", "commissioned"),
                               (f"2022-01-1{i}", "water_sample"), pump_type="AB"[i % 2])
                        for i in range(10)],
        "rules": [record(0, ("2019-05-01", "failure"), ("2020-01-10", "commissioned"),
                         ("x", "failure"), ("2021-01-10", "inspection")),
                  record(1, ("2020-01-10", "commissioned"), ("2021-01-10", "repair")),
                  record(2, ("2020-01-10", "commissioned"), ("2021-01-10", "restored")),
                  record(3, ("2020-01-10", "commissioned"), ("2021-01-10", "decommissioned"),
                         ("2021-01-10", "failure")),
                  record(4, ("2020-01-10", "commissioned"), ("2021-06-01", "decommissioned")),
                  record(5, ("2020-01-10", "commissioned")),
                  record(6, ("2020-01-10", "commissioned"), ("2020-01-10", "failure")),
                  record(7, ("2021-01-10", "routine_inspection")),
                  record(8, ("2020-01-10", "commissioned"), ("2024-07-01", "failure")),
                  {"asset_id": "not one"}],
        # every one at risk fails: the estimate and its band close on nought
        "all_fail": [record(i, ("2018-01-10", "commissioned"), (f"2019-0{1 + i % 3}-15", "failure"))
                     for i in range(6)],
        "empty": [],
    }
    cases = []

    def case(name, assets, as_of="2024-06-01", settings=None):
        section = {**SurvivalConfig().__dict__, **(settings or {})}
        config = _replace(Config(), survival=SurvivalConfig(**section))
        result = SV.survival_analysis(assets, as_of, config)
        groups = [result["overall"]] + [g for grouping in result["groupings"] for g in grouping["groups"]]
        cases.append({
            "name": name, "assets": assets, "as_of": as_of, "settings": settings or {},
            "expect": {"result": result, "words": SV.survival_text(result),
                       "header": SV.survival_header(),
                       "rows": [SV.survival_rows([result["overall"]])]
                       + [SV.survival_rows(g["groups"]) for g in result["groupings"]],
                       "at_risk": [SV.at_risk_header(result), SV.at_risk_rows(groups)]},
        })

    for name, assets in named.items():
        case(name, assets)
    case("settings", named["one_pump"], settings={"min_at_risk": 2, "at_risk_years": [0, 0.5, 4]})
    case("earlier", named["two_pumps"], as_of="2020-06-30")
    # registers drawn from seeds: pump types and contractors spelt in either
    # case or not at all, rising mains that say nothing of the water, records
    # of one borehole twice, and histories in any order
    days = ["2015-03-01", "2016-06-15", "2017-01-10", "2018-02-28", "2018-11-30", "2019-07-04",
            "2020-01-10", "2020-12-31", "2021-05-20", "2022-08-01", "2023-03-15", "2023-11-20",
            "2024-05-31", "2024-06-01", "2024-09-01", "not written down"]
    kinds = ["commissioned", "commissioned", "inspection", "routine_inspection", "water_sample",
             "repair", "failure", "failure", "restored", "decommissioned", "note"]
    for seed in range(6):
        rng = _random.Random(f"survival reference {seed}")
        assets, ids = [], []
        for _ in range(rng.randint(10, 40)):
            if ids and rng.random() < 0.1:
                asset_id = rng.choice(ids)
            else:
                asset_id = ident(690000.0 + rng.randint(0, 4000) * 10.0)
                ids.append(asset_id)
            raw = {"asset_id": asset_id, "community": "Case", "district": "Western Area Rural",
                   "pump_type": rng.choice(["India Mark II", "india mark ii", "Afridev", "", None]),
                   "installed_by": rng.choice(["Contractor A", "Contractor B", ""]),
                   "events": ([{"when": rng.choice(days[:10]), "kind": "commissioned"}]
                              if rng.random() < 0.9 else [])
                   + [{"when": rng.choice(days), "kind": rng.choice(kinds)}
                      for _ in range(rng.choice([0, 1, 2, 3]))]}
            rising = rng.choice([aggressive, plain, None, {"inspection_months": 9}])
            if rising is not None:
                raw["rising_main"] = rising
            assets.append(raw)
        case(f"seed {seed}", assets, as_of=rng.choice(["2024-06-01", "2022-02-28"]))
    # reports from the plate and by SMS (PLAN.md step 7.1): one that it is
    # working is a report of working; slow and a complaint are not
    case("reported", [record(i, ("2018-01-10", "commissioned"),
                             (f"2020-0{1 + i % 3}-15", "reported_working"),
                             (f"2021-0{1 + i % 3}-15", "reported_slow"),
                             (f"2022-0{1 + i % 3}-15", "quality_complaint"),
                             *([(f"2023-0{1 + i % 3}-15", "failure")] if i % 2 else []),
                             pump_type="AB"[i % 2])
                      for i in range(10)])
    return clean({"cases": cases})


def fault_reports_reference() -> dict:
    """Reports from the plate and by SMS (PLAN.md step 7.1): files of SMS
    lines and a gateway's messages read, page reports made, and the lot
    merged into a register, written to a file of reports and read back, with
    the import's table and summary; and report addresses checked. Named
    cases for each rule, then cases drawn from seeds. The cases carry their
    own inputs, so parity.mjs gives the browser exactly these. (The held
    outcome needs an identifier the registry reads with a note, which this
    registry has none of; tests/test_fault_reports.py holds both engines to
    it with a check that stands in for one.)"""
    import random as _random

    from groundwater import fault_reports as FR
    from groundwater import registry as RG

    ids = [RG.mint_asset_id(SiteMetadata(district=d, easting=e, northing=n, utm_zone=z))
           for d, e, n, z in (("Western Area Rural", 694912.0, 938150.0, 28),
                              ("Bo", 790500.0, 875300.0, 28),
                              ("Kailahun", 280400.0, 925600.0, 29))]
    # neither the identifier's check character nor, where the registry still
    # reads one, the character it was minted with before ISO 7064 was followed
    _body, _given = ids[0].rsplit("-", 1)
    _older = getattr(RG, "legacy_check_character", None)
    _taken = {_given, _older(_body) if _older else _given}
    mistyped = f"{_body}-" + next(c for c in "ZYXW" if c not in _taken)

    def register(*which):
        return [{"asset_id": ids[i], "community": "Case", "district": "Western Area Rural",
                 "easting": 694912.0, "northing": 938150.0, "utm_zone": 28,
                 "events": [{"when": "2020-01-10", "kind": "commissioned"},
                            {"when": "2026-05-01", "kind": "failure", "note": "handle snapped",
                             "by": "SMS from +23276123456"}]} for i in which]

    photo = "data:image/jpeg;base64,AAAA"
    provenance = {"format": 1, "sha256": "ab" * 32, "stored": "original"}
    named = {
        "lines": {
            "text": "\r\n".join([
                f"2026-05-01 08:14 +23276123456 BH {ids[0]} BROKEN handle snapped",
                "",
                f"2026-05-02T09:00:00Z,Fatmata Kamara,BH {ids[0]} taste brown water",
                f"2026-05-02;+232;bh {ids[1].lower()} working",
                f"08:30 BH {ids[0]} SLOW",
                f"BH {ids[2]} colour",
                f"01/05/2026 BH {ids[0]} SLOW",
                f"2026-05-01 2026-05-02 BH {ids[0]} SLOW",
                f"2026-13-01 BH {ids[0]} SLOW",
                "hello there",
                f"BH {mistyped} BROKEN",
                f"BH {ids[0]} FIXED",
                "BH",
                f"BH {ids[0]}",
                f"2026-05-01 +23276123456 BH {ids[0]} broken handle snapped",
            ]),
            "received_on": "2026-05-03",
            "messages": [
                {"text": f"BH {ids[0]} BROKEN", "received": "2026-05-01T07:00:00+00:00",
                 "sender": "+232"},
                f"BH {ids[1]} WORKING",
                {"text": f"BH {ids[0]} SLOW", "received": "yesterday"},
                {"text": f"BH {ids[0]} SLOW", "received": "2026-02-30"}, 7, None],
            "page": [[ids[0], "slow", " 2026-05-01 ", " slow since Monday ", " Aminata "],
                     [ids[0], "broken", "2026-05-01", "", "", photo, provenance],
                     [ids[0], "broken", "2026-05-01", "", "", "", provenance],
                     [mistyped, "slow", "2026-05-01"], [ids[0], "fixed", "2026-05-01"],
                     [ids[0], "slow", "2026-02-30"], [ids[0], "slow", " "],
                     ["", "slow", "2026-05-01"]],
            "assets": register(0, 1),
        },
        "no_day": {"text": f"BH {ids[0]} BROKEN\n08:00 BH {ids[1]} WORKING", "received_on": "",
                   "messages": [f"BH {ids[0]} BROKEN"], "page": [], "assets": register(0)},
        "nothing": {"text": "", "received_on": "", "messages": [], "page": [], "assets": []},
    }
    urls = ["", "https://example.org/", " https://water.example.org/toolkit/ ",
            "HTTPS://example.org/a?b=c", "http://example.org/", "water.example.org", "https://",
            "https:///x", "https://example.org/#/report", "https://example .org/",
            "https://example.org/a\u00a0b", "ftp://example.org", 7, None,
            # printable ASCII only, the scheme read A to Z: a long s is not an s
            "http\u017f://example.org/", "https://w\u00e1ter.example.org/",
            "https://example.org/\x01", "https://xn--wter-6qa.example.org/a?b=c&d=%20"]

    def answer(c):
        lines = FR.read_sms_lines(c["text"], c["received_on"])
        messages = FR.receive_messages(c["messages"], c["received_on"])
        page = [FR.report_record(*a) for a in c["page"]]
        every = lines + messages + page
        merged = FR.merge_reports(c["assets"], every)
        payload = FR.reports_file(every)
        return {
            "lines": lines, "messages": messages, "page": page,
            "merged": {"assets": [a.as_dict() for a in merged["assets"]],
                       "added": merged["added"], "already": merged["already"],
                       "unmatched": merged["unmatched"]},
            "file": payload, "back": FR.read_reports_file(json.loads(json.dumps(payload))),
            "rows": FR.report_rows(every), "summary": FR.import_summary(every),
        }

    cases = [{"name": name, **c, "expect": answer(c)} for name, c in named.items()]
    # cases drawn from seeds: the words in any case, prefixes of every kind,
    # identifiers mistyped, lower-cased and shortened, and a stored report
    # sent again
    words = ["WORKING", "broken", "Slow", "taste", "COLOUR", "color", "BAD", "FIXED", "", "bh"]
    prefixes = ["", "2026-05-01 ", "2026-05-01 08:14 ", "2026-05-01T08:14:00Z,",
                "+23276123456 ", "2026-05-01;Fatmata Kamara;", "01/05/2026 ", "2026-13-01 ",
                "08:14 ", "2026-05-01 2026-05-02 ", "\u00a0", "2026-05-01\t+232 ",
                "2026-05-01 +23276123456 "]
    notes = ["", " handle snapped", "  brown  water ", " \u3000noted", " \U0001f600"]
    for seed in range(4):
        rng = _random.Random(f"fault reports reference {seed}")

        def ident():
            chosen, pick = rng.choice(ids), rng.random()
            if pick < 0.15:
                return chosen[:-1] + rng.choice("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ")
            if pick < 0.25:
                return chosen.lower()
            if pick < 0.3:
                return chosen[3:]
            return chosen

        lines = [rng.choice(prefixes) + rng.choice(["BH", "bh", "BH:"]) + " " + ident()
                 + (" " + w if (w := rng.choice(words)) else "") + rng.choice(notes)
                 for _ in range(rng.randint(8, 30))]
        lines.insert(rng.randint(0, len(lines)),
                     f"2026-05-01 +23276123456 BH {ids[0]} BROKEN handle snapped")
        c = {"text": "\n".join(lines), "received_on": rng.choice(["", "2026-05-03"]),
             "messages": [{"text": rng.choice(lines),
                           "received": rng.choice(["", "2026-05-02T10:00:00Z", "08:00"]),
                           "sender": rng.choice(["", "+23276"])} for _ in range(4)],
             "page": [[rng.choice(ids), rng.choice(["working", "broken", "slow", "taste", "x"]),
                       rng.choice(["2026-05-01", ""]), "", "",
                       rng.choice(["", photo]), rng.choice([None, provenance])]
                      for _ in range(4)],
             "assets": register(*range(rng.randint(0, 3)))}
        cases.append({"name": f"seed {seed}", **c, "expect": answer(c)})
    return clean({"cases": cases, "header": FR.report_header(), "sms_format": FR.sms_format(),
                  "urls": [{"url": u, "reason": RG.check_report_url(u)} for u in urls],
                  "links": [RG.report_link(ids[0], u) for u in urls[:4]]})


def fill_qr(out: dict) -> None:
    """Fill "qr" and "qr_capacity": every module of the symbols a placard carries.

    It fills ``out`` in place, where build() calls it: build.py says why."""
    # The QR encoder. Every module of every symbol, because a symbol that is
    # wrong in the data region still looks exactly like a QR symbol - and the
    # browser draws the one that gets printed and fixed to the headworks.
    from groundwater import qr

    _qr_payloads = [
        "SL-WAR-8FEEVKQ-T",
        ("BOREHOLE SL-WAR-8FEEVKQ-T\nDr. Timbo's (Western Area Rural)\n"
        "8.48310 N, 13.22940 W\n62.0 m deep, 1.85 m3/h"),
        "Kailahun - 10\u00b0 12' 03\" N",     # non-ASCII, so UTF-8 is exercised
    ]
    out["qr"] = [
        {
            "text": text, "ecc": ecc, "mask": mask,
            "version": _code.version, "size": _code.size,
            "chosen_mask": _code.mask,
            "penalty": qr._penalty(_code.modules),
            # one string per row keeps the reference file readable and diffable
            "rows": ["".join("1" if cell else "0" for cell in row)
                     for row in _code.modules],
        }
        for text in _qr_payloads
        for ecc in ("L", "M", "Q", "H")
        for mask in (None, 0, 5)
        for _code in [qr.encode(text, ecc=ecc, mask=mask)]
    ]
    out["qr_capacity"] = [
        {"version": v, "ecc": e, "bytes": qr._capacity_bytes(v, e)}
        for v in range(1, qr.MAX_VERSION + 1) for e in ("L", "M", "Q", "H")
    ]


def fill_registry(out: dict) -> None:
    """Fill the asset registry's keys, "asset_ids" to "asset_months", with
    "degree_boxes" among them.

    It fills ``out`` in place, where build() calls it: build.py says why."""
    # the gate the degree boxes below are put through: in build() these lines
    # read the import its certification gate makes, just before the call here
    from groundwater.readiness import assess_readiness

    # The asset registry: identifiers, the merge, and what the event stream
    # says is true on a fixed day.
    from datetime import date as _date

    from groundwater import registry as _registry

    _sites = [
        SiteMetadata(district="Western Area Rural", easting=694912.0,
                     northing=938150.0, utm_zone=28),
        SiteMetadata(district="Western Area Rural", easting=694914.0,
                     northing=938147.0, utm_zone=28),
        SiteMetadata(district="Bo", easting=790500.0, northing=875300.0,
                     utm_zone=28),
        SiteMetadata(district="Kailahun", easting=280400.0, northing=925600.0,
                     utm_zone=29),
        SiteMetadata(district="Nowhere At All", easting=694912.0,
                     northing=938150.0, utm_zone=28),
    ]
    out["asset_ids"] = [
        {"district": s.district, "easting": s.easting, "northing": s.northing,
         "zone": s.utm_zone, "id": _registry.mint_asset_id(s)}
        for s in _sites
    ]
    _timbo_id = _registry.mint_asset_id(_sites[0])
    out["asset_id_parsing"] = [
        {"typed": t, "parsed": _registry.parse_asset_id(t),
         "ok": _registry.validate_asset_id(t)[0],
         "reason": _registry.validate_asset_id(t)[1]}
        for t in (_timbo_id, _timbo_id.lower(), _timbo_id.replace("0", "O"),
                  _timbo_id.replace("1", "L"), " " + _timbo_id + " ",
                  _timbo_id[:-1] + "Z", _timbo_id.replace("-", ""),
                  "SL-WAR-XXXXXXX-9", "not an identifier", "",
                  # minted before the check character followed ISO 7064, and
                  # a mistyping of one that the legacy character lets through
                  "SL-WAR-8FEEVKQ-T", "sl-war-8feevkq-t", "SL-BO-C4817SW-1",
                  "SL-BO-P4817SW-1", "SL-PL-8HE2QWG-3", "SL-PL-8HE2QWG-G")
    ]
    # the check character itself, on the standard's examples and on bodies
    # the legacy calculation gives another character for
    out["check_characters"] = [
        {"body": b, "iso": _registry.check_character(b),
         "legacy": _registry.legacy_check_character(b),
         "is_legacy": _registry.is_legacy_asset_id(
             f"{b}-{_registry.legacy_check_character(b)}")}
        for b in ("00000000D07A0090", "00000000D07A009000000000",
                  "188166C7342065419F3A0245", "A12425GABC1234002",
                  "SL-WAR-8FEEVKQ", "SL-BO-C4817SW", "SL-PL-8HE2QWG",
                  "SL-KAI-KDH2TCG", "SL-XX-00000ZZ")
    ]
    # Degrees typed into the UTM boxes: the same refusal from the identifier
    # and the gate, and no position, in both engines.
    from groundwater.geo import degrees_in_utm_boxes as _degrees

    _degree_sites = [(-13.2294, 8.4831), (13.2294, 8.4831), (20.5, 5.25),
                     (-180.0, 90.0), (0.0, 0.0), (694912.0, 938150.0), (181.0, 8.0)]
    out["degree_boxes"] = []
    for _e, _n in _degree_sites:
        _site = SiteMetadata(district="Western Area Rural", easting=_e, northing=_n)
        try:
            _minted = _registry.mint_asset_id(_site)
        except ValueError as _refused:
            _minted = "refused: " + str(_refused)
        _gate = assess_readiness({"site": _site, "sources": {}}, "placard")
        out["degree_boxes"].append({
            "easting": _e, "northing": _n, "note": _degrees(_e, _n), "minted": _minted,
            "site_located": [[r.state, r.detail] for r in _gate.requirements
                             if r.key == "site_located"][0]})
    _streams = [
        [{"when": "2020-01-10", "kind": "commissioned", "by": "M. Kolleh"},
         {"when": "2023-04-02", "kind": "failure", "note": "rising main parted"}],
        [{"when": "2023-04-02", "kind": "failure", "note": "rising main parted"},
         {"when": "2023-05-11", "kind": "repair", "note": "new seals",
          "by": "A. Bangura", "photo": "data:image/jpeg;base64,AAAA"},
         {"when": "not written down", "kind": "inspection"},
         {"when": "2099-01-01", "kind": "restored"}],
    ]
    out["asset_events"] = [
        e.as_dict() for e in _registry.merge_events(_timbo_id, *_streams)
    ]
    _registry_cases = {
        "silent": [],
        "commissioned": _streams[0][:1],
        "broken": _streams[0],
        "repaired": _streams[0] + [{"when": "2023-05-11", "kind": "restored"}],
        "sampled": _streams[0][:1] + [{"when": "2023-03-01", "kind": "water_sample"},
                                      {"when": "2024-05-20", "kind": "inspection"}],
        "decommissioned": _streams[0][:1] + [{"when": "2022-08-01",
                                              "kind": "decommissioned"}],
        "merged": _streams[0] + _streams[1],
        # broken in January and reported again in May: out since January
        "rebroken": _streams[0][:1] + [
            {"when": "2024-01-10", "kind": "failure", "by": "M. Kolleh"},
            {"when": "2024-05-20", "kind": "failure", "note": "still broken"}],
        # the same visit records the failure and the decommissioning, or a
        # pump pulled for reuse on the decommissioning day
        "collapsed": _streams[0][:1] + [
            {"when": "2023-03-01", "kind": "decommissioned", "note": "backfilled"},
            {"when": "2023-03-01", "kind": "failure", "note": "hole collapsed"}],
        "pulled": _streams[0][:1] + [
            {"when": "2023-03-01", "kind": "repair", "note": "pump pulled for reuse"},
            {"when": "2023-03-01", "kind": "decommissioned", "note": "dry"}],
        # records after a decommissioning, and a new commissioning
        "after_decommissioning": _streams[0][:1] + [
            {"when": "2022-08-01", "kind": "decommissioned"},
            {"when": "2023-01-05", "kind": "repair", "note": "new seals"},
            {"when": "2023-02-01", "kind": "restored"}],
        "recommissioned": _streams[0][:1] + [
            {"when": "2022-08-01", "kind": "decommissioned"},
            {"when": "2023-01-05", "kind": "repair"},
            {"when": "2023-06-01", "kind": "commissioned", "by": "A. Bangura"}],
        # a second decommissioning record, which explains nothing away
        "decommissioned_twice": _streams[0][:1] + [
            {"when": "2022-08-01", "kind": "decommissioned", "note": "collapsed"},
            {"when": "2023-01-05", "kind": "decommissioned", "note": "backfilled"}],
        # reports from the plate and by SMS (PLAN.md step 7.1): working says
        # so; slow and a water quality complaint leave the failure standing
        "reported": _streams[0] + [{"when": "2023-05-01", "kind": "reported_working",
                                    "by": "SMS from +232"},
                                   {"when": "2023-06-01", "kind": "failure"},
                                   {"when": "2023-07-01", "kind": "reported_slow"},
                                   {"when": "2023-08-01", "kind": "quality_complaint",
                                    "photo": "data:image/jpeg;base64,AAAA",
                                    "photo_provenance": {"format": 1, "sha256": "ab" * 32}}],
    }
    _today = _date(2024, 6, 1)
    _assets = {}
    for _name, _events in _registry_cases.items():
        _assets[_name] = _registry.Asset(
            asset_id=_timbo_id, community="Dr. Timbo's",
            district="Western Area Rural", easting=694912.0, northing=938150.0,
            utm_zone=28, total_depth_m=62.0, safe_yield_m3_per_h=1.85,
            pump_type="India Mark II", installed_by="WiNGiN",
            events=[_registry.AssetEvent(**e) for e in _events],
        )
    out["asset_state"] = {
        name: _registry.asset_state(asset, _today).as_dict()
        for name, asset in _assets.items()
    }
    out["asset_placard"] = clean(_registry.placard_lines(
        _assets["commissioned"],
        _registry.asset_state(_assets["commissioned"], _today)))
    out["asset_qr_payload"] = _registry.qr_payload(_assets["commissioned"])
    # with a report address set, the symbol is a link to the report page
    out["asset_qr_link"] = _registry.qr_payload(_assets["commissioned"],
                                                "https://water.example.org/toolkit/")
    out["registry_rows"] = _registry.registry_rows(list(_assets.values()), _today)
    out["registry_stats"] = clean(
        _registry.registry_stats(list(_assets.values()), _today))
    out["asset_months"] = [
        {"from": d, "months": m, "due": _registry._add_months(
            _date.fromisoformat(d), m).isoformat()}
        for d, m in (("2023-08-31", 6), ("2023-12-31", 2), ("2020-02-29", 12),
                     ("2023-01-31", 1), ("2023-03-30", 11), ("2024-02-29", 12),
                     # a mistyped year before 1000 is written in four digits
                     ("0024-08-31", 6))
    ]
