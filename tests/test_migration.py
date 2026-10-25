"""Migration 12: bisherige Gebäudekosten werden je eine Buchung, Rücklage-Kostenarten werden erkannt."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

import db  # noqa: E402


def test_kosten_werden_buchungen(monkeypatch):
    tmp = tempfile.mkdtemp()
    pfad = os.path.join(tmp, "alt.sqlite")
    monkeypatch.setattr(db, "DATA_DIR", tmp)
    monkeypatch.setattr(db, "DB_PATH", pfad)
    con = db.verbinden(pfad)
    for sql in db.MIGRATIONEN[:11]:
        con.executescript(sql)
    con.execute("PRAGMA user_version = 11")
    con.execute("INSERT INTO kostenart (name) VALUES ('Reparaturrücklage'), ('Versicherung')")
    con.execute("INSERT INTO immobilie (name, ordner) VALUES ('Lindenhof 7', 'Lindenhof 7')")
    con.execute("INSERT INTO wohnung (immobilie_id, bezeichnung) VALUES (1, 'EG')")
    con.executemany("INSERT INTO kosten (immobilie_id, jahr, wohnung_id, kostenart_id, betrag) VALUES (?, ?, ?, ?, ?)",
                    [(1, 2025, None, 2, 3000.0), (1, 2025, None, 1, 1900.0),
                     (1, 2025, 1, 2, 50.0),     # Kosten der Wohnung bleiben ohne Buchung
                     (1, 2026, None, 2, 0.0)])  # aus dem Vorjahr übernommen, noch ohne Betrag
    con.commit()
    con.close()

    db.init_db()
    con = db.verbinden(pfad)
    buchungen = [tuple(r) for r in con.execute("SELECT kosten_id, text, art, betrag, datum FROM buchung ORDER BY id")]
    assert buchungen == [(1, "Versicherung", "ausgabe", 3000.0, None), (2, "Reparaturrücklage", "ausgabe", 1900.0, None)]
    assert con.execute("SELECT ruecklage FROM kostenart WHERE name = 'Reparaturrücklage'").fetchone()[0] == 1
    # eine vorhandene Rücklage-Kostenart wird genutzt, keine zweite angelegt
    assert not con.execute("SELECT 1 FROM kostenart WHERE name = 'Zuführung Erhaltungsrücklage'").fetchone()
    con.close()
