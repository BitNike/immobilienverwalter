import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from calc import berechne, monate, parse_mea, parse_num, verbrauch_zeitraum  # noqa: E402

VON, BIS = date(2025, 1, 1), date(2025, 12, 31)
KA = {1: {"name": "Grundsteuer", "umlagefaehig": 1}, 2: {"name": "Heizkosten", "umlagefaehig": 1},
      3: {"name": "Wasser", "umlagefaehig": 1}, 4: {"name": "Verwaltung", "umlagefaehig": 0},
      5: {"name": "Versicherung", "umlagefaehig": 1}}


def wohnung(wid, flaeche=65.0, mea=86.13):
    return {"id": wid, "bezeichnung": f"W{wid}", "wohnflaeche": flaeche, "mea": mea, "mea_basis": 1000.0}


def kosten(kid, ka, betrag, wohnung_id=None, mv_id=None, schluessel="mea"):
    return {"id": kid, "kostenart_id": ka, "betrag": betrag, "wohnung_id": wohnung_id, "mv_id": mv_id,
            "schluessel": schluessel}


def mv(mid, wid, von, bis=None, vz=0.0):
    return {"id": mid, "wohnung_id": wid, "von": von, "bis": bis, "vorauszahlung_monat": vz}


def wasseruhr(wid, staende, **kw):
    return {"wohnung_id": wid, "art": "wasser", "staende": staende, **kw}


def test_parser():
    assert parse_num("1.234,56") == 1234.56
    assert parse_mea("86,13/1.000") == (86.13, 1000.0)
    assert monate(date(2025, 4, 1), date(2025, 12, 31)) == 9


def test_musterabrechnung():
    """Einzug 01.04.: Grundsteuer zeitanteilig (75 %), Heizkostenabrechnung 100 % für den Mieter."""
    k = [kosten(1, 1, 103.54, wohnung_id=1), kosten(2, 2, 712.37, wohnung_id=1, mv_id=10)]
    erg = berechne(VON, BIS, {}, [wohnung(1)], k, KA, [mv(10, 1, "2025-04-01", vz=150)], [], {})
    w = erg["wohnungen"][1]
    p = w["parteien"][0]
    assert p["monate"] == 9 and round(p["prozent"]) == 75
    assert [x["betrag"] for x in p["posten"]] == [77.66, 712.37]
    assert p["vorauszahlung"] == 1350.0
    assert p["saldo"] == round(77.66 + 712.37 - 1350, 2)
    assert w["leerstand"]["summe"] == round(103.54 - 77.66, 2)  # Jan–März trägt der Eigentümer


def test_gebaeudekosten_nach_mea_und_nicht_umlagefaehig():
    ws = [wohnung(1, mea=600), wohnung(2, mea=400)]
    k = [kosten(1, 5, 1000.0), kosten(2, 4, 100.0)]
    erg = berechne(VON, BIS, {}, ws, k, KA, [mv(10, 1, "2020-01-01")], [], {})
    assert erg["wohnungen"][1]["summe"] == 660.0
    p = erg["wohnungen"][1]["parteien"][0]
    assert p["summe"] == 600.0  # Verwaltung nicht auf den Mieter
    assert erg["wohnungen"][1]["leerstand"]["summe"] == 60.0
    assert erg["wohnungen"][2]["leerstand"]["summe"] == 440.0  # Wohnung 2 komplett leer


def test_wasser_mit_zaehlerwechsel_und_mieterwechsel():
    ws = [wohnung(1), wohnung(2)]
    uhren = [
        wasseruhr(1, [("2024-12-31", 100.0), ("2025-06-30", 130.0)], ausgebaut="2025-06-30"),
        wasseruhr(1, [("2025-06-30", 0.0), ("2025-12-31", 30.0)], eingebaut="2025-06-30"),
        wasseruhr(2, [("2024-12-31", 0.0), ("2025-12-31", 40.0)]),
    ]
    assert verbrauch_zeitraum(uhren[:2], VON, BIS) == 60.0
    mvs = [mv(10, 1, "2020-01-01", "2025-06-30"), mv(11, 1, "2025-07-01")]
    erg = berechne(VON, BIS, {}, ws, [kosten(1, 3, 500.0, schluessel="wasser")], KA, mvs, uhren, {})
    w1 = erg["wohnungen"][1]
    assert w1["summe"] == 300.0  # 60 von 100 m³
    assert [p["summe"] for p in w1["parteien"]] == [150.0, 150.0]


def test_wasser_fehlende_ablesung():
    ws = [wohnung(1), wohnung(2)]
    uhren = [wasseruhr(1, [("2024-12-31", 0.0)]), wasseruhr(2, [("2024-12-31", 0.0), ("2025-12-31", 5.0)])]
    erg = berechne(VON, BIS, {}, ws, [kosten(1, 3, 100.0, schluessel="wasser")], KA, [], uhren, {})
    assert "W1" in erg["gebaeude"][0]["warnung"]


def test_eigentuemer_vorauszahlung():
    erg = berechne(VON, BIS, {}, [wohnung(1)], [kosten(1, 1, 200.0, wohnung_id=1)], KA, [], [], {(1, None): 250.0})
    assert erg["wohnungen"][1]["saldo"] == -50.0


def test_natuerliche_sortierung():
    import sqlite3

    import db
    con = sqlite3.connect(":memory:")
    con.create_collation("NATUERLICH", db._natuerlich)
    con.execute("CREATE TABLE t (n TEXT)")
    con.executemany("INSERT INTO t VALUES (?)", [(x,) for x in ["Wohnung 10", "Wohnung 2", "wohnung 1", "Garage", "Wohnung 12a"]])
    assert [r[0] for r in con.execute("SELECT n FROM t ORDER BY n COLLATE NATUERLICH")] == \
        ["Garage", "wohnung 1", "Wohnung 2", "Wohnung 10", "Wohnung 12a"]


def test_wasser_erste_ablesung_im_jahr():
    from calc import messbeginn
    # Uhr ohne Stand zum 01.01., erste Ablesung beim Einzug am 17.03.
    uhr = [wasseruhr(1, [("2025-03-17", 1335.0), ("2025-12-31", 1356.0)], eingebaut="2025-01-01")]
    assert verbrauch_zeitraum(uhr, VON, BIS) == 21.0
    assert messbeginn(uhr, VON, BIS) == date(2025, 3, 17)
    # mit Stand zum Jahresanfang: kein Hinweis
    assert messbeginn([wasseruhr(1, [("2024-12-31", 1300.0), ("2025-12-31", 1356.0)])], VON, BIS) is None
