import os
import re
import sqlite3

from flask import g

DATA_DIR = os.path.abspath(os.environ.get("NK_DATA", os.path.join(os.path.dirname(__file__), "..", "data")))
DB_PATH = os.path.join(DATA_DIR, "nebenkosten.sqlite")

# Jede Migration wird genau einmal ausgeführt (PRAGMA user_version).
MIGRATIONEN = [
    """
    CREATE TABLE benutzer (
        id INTEGER PRIMARY KEY,
        benutzername TEXT NOT NULL UNIQUE COLLATE NOCASE,
        passwort_hash TEXT NOT NULL,
        rolle TEXT NOT NULL DEFAULT 'vermieter',
        vorname TEXT NOT NULL DEFAULT '',
        name TEXT NOT NULL DEFAULT '',
        strasse TEXT NOT NULL DEFAULT '',
        hausnummer TEXT NOT NULL DEFAULT '',
        plz TEXT NOT NULL DEFAULT '',
        ort TEXT NOT NULL DEFAULT '',
        email TEXT NOT NULL DEFAULT '',
        notizen TEXT NOT NULL DEFAULT '',
        foto INTEGER NOT NULL DEFAULT 0,
        erstellt TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE einstellung (schluessel TEXT PRIMARY KEY, wert TEXT);
    CREATE TABLE kostenart (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        betrkv_nr TEXT NOT NULL DEFAULT '',
        umlagefaehig INTEGER NOT NULL DEFAULT 1,
        schluessel TEXT NOT NULL DEFAULT 'mea',
        sortierung INTEGER NOT NULL DEFAULT 0,
        aktiv INTEGER NOT NULL DEFAULT 1
    );
    CREATE TABLE immobilie (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        strasse TEXT NOT NULL DEFAULT '',
        hausnummer TEXT NOT NULL DEFAULT '',
        plz TEXT NOT NULL DEFAULT '',
        ort TEXT NOT NULL DEFAULT '',
        ordner TEXT NOT NULL UNIQUE,
        absender TEXT NOT NULL DEFAULT '',
        kontoinhaber TEXT NOT NULL DEFAULT '',
        iban TEXT NOT NULL DEFAULT '',
        bank TEXT NOT NULL DEFAULT '',
        gesamtflaeche REAL,
        einheiten_gesamt INTEGER,
        notiz TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE wohnung (
        id INTEGER PRIMARY KEY,
        immobilie_id INTEGER REFERENCES immobilie(id) ON DELETE SET NULL,
        eigentuemer_id INTEGER REFERENCES benutzer(id) ON DELETE SET NULL,
        bezeichnung TEXT NOT NULL,
        wohnflaeche REAL NOT NULL DEFAULT 0,
        mea REAL NOT NULL DEFAULT 0,
        mea_basis REAL NOT NULL DEFAULT 1000,
        umlageschluessel TEXT NOT NULL DEFAULT '',
        iban TEXT NOT NULL DEFAULT '',
        notiz TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE zaehler (
        id INTEGER PRIMARY KEY,
        wohnung_id INTEGER REFERENCES wohnung(id) ON DELETE CASCADE,
        immobilie_id INTEGER REFERENCES immobilie(id) ON DELETE CASCADE,
        art TEXT NOT NULL,
        nummer TEXT NOT NULL DEFAULT '',
        eingebaut TEXT,
        ausgebaut TEXT
    );
    CREATE TABLE zaehlerstand (
        id INTEGER PRIMARY KEY,
        zaehler_id INTEGER NOT NULL REFERENCES zaehler(id) ON DELETE CASCADE,
        datum TEXT NOT NULL,
        stand REAL NOT NULL,
        notiz TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE mietverhaeltnis (
        id INTEGER PRIMARY KEY,
        wohnung_id INTEGER NOT NULL REFERENCES wohnung(id) ON DELETE CASCADE,
        nummer INTEGER NOT NULL,
        ordner TEXT NOT NULL,
        von TEXT NOT NULL,
        bis TEXT,
        vorauszahlung_monat REAL NOT NULL DEFAULT 0,
        neue_anschrift TEXT NOT NULL DEFAULT '',
        notiz TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE mieter_person (
        id INTEGER PRIMARY KEY,
        mv_id INTEGER NOT NULL REFERENCES mietverhaeltnis(id) ON DELETE CASCADE,
        vorname TEXT NOT NULL DEFAULT '',
        name TEXT NOT NULL
    );
    CREATE TABLE kosten (
        id INTEGER PRIMARY KEY,
        immobilie_id INTEGER NOT NULL REFERENCES immobilie(id) ON DELETE CASCADE,
        jahr INTEGER NOT NULL,
        wohnung_id INTEGER REFERENCES wohnung(id) ON DELETE CASCADE,
        mv_id INTEGER REFERENCES mietverhaeltnis(id) ON DELETE SET NULL,
        kostenart_id INTEGER NOT NULL REFERENCES kostenart(id),
        betrag REAL NOT NULL DEFAULT 0,
        schluessel TEXT NOT NULL DEFAULT 'mea',
        notiz TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE vorauszahlung (
        id INTEGER PRIMARY KEY,
        jahr INTEGER NOT NULL,
        wohnung_id INTEGER NOT NULL REFERENCES wohnung(id) ON DELETE CASCADE,
        mv_id INTEGER REFERENCES mietverhaeltnis(id) ON DELETE CASCADE,
        betrag REAL NOT NULL
    );
    CREATE TABLE dokument (
        id INTEGER PRIMARY KEY,
        immobilie_id INTEGER NOT NULL REFERENCES immobilie(id) ON DELETE CASCADE,
        jahr INTEGER NOT NULL,
        bereich TEXT NOT NULL,
        mv_id INTEGER REFERENCES mietverhaeltnis(id) ON DELETE SET NULL,
        wohnung_id INTEGER REFERENCES wohnung(id) ON DELETE SET NULL,
        kostenart_id INTEGER REFERENCES kostenart(id) ON DELETE SET NULL,
        titel TEXT NOT NULL,
        pfad TEXT NOT NULL,
        mime TEXT NOT NULL,
        groesse INTEGER NOT NULL DEFAULT 0,
        hochgeladen_von INTEGER REFERENCES benutzer(id) ON DELETE SET NULL,
        hochgeladen_am TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """,
    # 2: Standard-Umlageschlüssel je Immobilie ('' = automatisch)
    """
    ALTER TABLE immobilie ADD COLUMN schluessel TEXT NOT NULL DEFAULT '';
    """,
    # 3: Eigentümer-Abrechnung nur bei WEG; Bestand: WEG, wenn mehr als ein Mietobjekt
    """
    ALTER TABLE immobilie ADD COLUMN weg INTEGER NOT NULL DEFAULT 0;
    UPDATE immobilie SET weg = 1 WHERE (SELECT COUNT(*) FROM wohnung w WHERE w.immobilie_id = immobilie.id) > 1;
    """,
    # 4: Immobilien archivieren (ausgeblendet, Daten bleiben erhalten)
    """
    ALTER TABLE immobilie ADD COLUMN archiviert INTEGER NOT NULL DEFAULT 0;
    """,
    # 5: Mieter rechnet der Eigentümer selbst ab (WEG: hier nur Eigentümer-Abrechnung)
    """
    ALTER TABLE wohnung ADD COLUMN mieter_extern INTEGER NOT NULL DEFAULT 0;
    """,
    # 6: Bezeichnung bzw. Standort eines Zählers (z. B. „Flurstrom Haus 1“)
    """
    ALTER TABLE zaehler ADD COLUMN bezeichnung TEXT NOT NULL DEFAULT '';
    """,
    # 7: Ablage für Dokumente außerhalb der Abrechnung (Protokolle, Pläne, Angebote …), Jahr optional
    """
    CREATE TABLE ablage (
        id INTEGER PRIMARY KEY,
        immobilie_id INTEGER NOT NULL REFERENCES immobilie(id) ON DELETE CASCADE,
        wohnung_id INTEGER REFERENCES wohnung(id) ON DELETE CASCADE,
        kategorie TEXT NOT NULL,
        titel TEXT NOT NULL,
        jahr INTEGER,
        notiz TEXT NOT NULL DEFAULT '',
        intern INTEGER NOT NULL DEFAULT 0,
        pfad TEXT NOT NULL,
        mime TEXT NOT NULL,
        groesse INTEGER NOT NULL DEFAULT 0,
        hochgeladen_von INTEGER REFERENCES benutzer(id) ON DELETE SET NULL,
        hochgeladen_am TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """,
    # 8: Kommentar auch für Abrechnungsbelege
    """
    ALTER TABLE dokument ADD COLUMN notiz TEXT NOT NULL DEFAULT '';
    """,
    # 9: Ablage-Kategorien pflegbar (vorher fest im Code; die Schlüssel bleiben gleich)
    """
    CREATE TABLE ablage_kategorie (
        schluessel TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        sortierung INTEGER NOT NULL DEFAULT 0
    );
    INSERT INTO ablage_kategorie (schluessel, name, sortierung) VALUES
        ('protokolle', 'Protokolle', 10), ('plaene', 'Pläne & Grundrisse', 20),
        ('angebote', 'Angebote & Aufträge', 30), ('vertraege', 'Verträge & Versicherungen', 40),
        ('sonstiges', 'Sonstiges', 90);
    """,
    # 10: Zwei-Faktor-Anmeldung (TOTP) mit Notfall-Codes (Hashes, zeilenweise)
    """
    ALTER TABLE benutzer ADD COLUMN totp_geheimnis TEXT NOT NULL DEFAULT '';
    ALTER TABLE benutzer ADD COLUMN totp_aktiv INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE benutzer ADD COLUMN totp_schritt INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE benutzer ADD COLUMN totp_notfall TEXT NOT NULL DEFAULT '';
    """,
    # 11: eigene Bankverbindung für die Mieter-Abrechnung eines Mietobjekts (z. B. eigene Wohnung in einer WEG)
    """
    ALTER TABLE wohnung ADD COLUMN kontoinhaber TEXT NOT NULL DEFAULT '';
    ALTER TABLE wohnung ADD COLUMN bank TEXT NOT NULL DEFAULT '';
    """,
    # 12: Buchungen (Belege) statt Einzelbetrag je Gebäudekosten-Position; Erhaltungsrücklage.
    #     kostenart_id gesetzt -> fließt in die Kostenposition (kosten_id), Einnahmen mindern sie;
    #     kostenart_id NULL     -> Rücklage (Einnahme = Zufluss, Ausgabe = Entnahme), wird nicht umgelegt.
    #     Bisherige Gebäudekosten werden je eine Buchung (ohne Datum).
    """
    ALTER TABLE kostenart ADD COLUMN ruecklage INTEGER NOT NULL DEFAULT 0;
    UPDATE kostenart SET ruecklage = 1 WHERE name LIKE '%cklage%';
    CREATE TABLE buchung (
        id INTEGER PRIMARY KEY,
        immobilie_id INTEGER NOT NULL REFERENCES immobilie(id) ON DELETE CASCADE,
        jahr INTEGER NOT NULL,
        datum TEXT,
        text TEXT NOT NULL DEFAULT '',
        art TEXT NOT NULL DEFAULT 'ausgabe',
        betrag REAL NOT NULL DEFAULT 0,
        kostenart_id INTEGER REFERENCES kostenart(id),
        kosten_id INTEGER REFERENCES kosten(id) ON DELETE CASCADE,
        bezahlt TEXT NOT NULL DEFAULT 'konto',
        erstattet TEXT,
        dokument_id INTEGER REFERENCES dokument(id) ON DELETE SET NULL
    );
    CREATE TABLE ruecklage_bestand (
        immobilie_id INTEGER NOT NULL REFERENCES immobilie(id) ON DELETE CASCADE,
        jahr INTEGER NOT NULL,
        betrag REAL NOT NULL,
        PRIMARY KEY (immobilie_id, jahr)
    );
    INSERT INTO buchung (immobilie_id, jahr, text, art, betrag, kostenart_id, kosten_id)
        SELECT k.immobilie_id, k.jahr, ka.name, 'ausgabe', k.betrag, k.kostenart_id, k.id
        FROM kosten k JOIN kostenart ka ON ka.id = k.kostenart_id
        WHERE k.wohnung_id IS NULL AND k.betrag <> 0;
    """,
    # 13: Kommentar zu Buchungen und zum Anfangsbestand der Rücklage
    """
    ALTER TABLE buchung ADD COLUMN notiz TEXT NOT NULL DEFAULT '';
    ALTER TABLE ruecklage_bestand ADD COLUMN notiz TEXT NOT NULL DEFAULT '';
    """,
    # 14: Konten einer Immobilie (Girokonto, Tagesgeld …) mit Kontoständen zum Stichtag laut Kontoauszug
    """
    CREATE TABLE konto (
        id INTEGER PRIMARY KEY,
        immobilie_id INTEGER NOT NULL REFERENCES immobilie(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        ruecklage INTEGER NOT NULL DEFAULT 1,
        iban TEXT NOT NULL DEFAULT '',
        bank TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE kontostand (
        id INTEGER PRIMARY KEY,
        konto_id INTEGER NOT NULL REFERENCES konto(id) ON DELETE CASCADE,
        datum TEXT NOT NULL,
        betrag REAL NOT NULL,
        notiz TEXT NOT NULL DEFAULT ''
    );
    """,
]

# Vorbelegte Kostenarten (Name, Nr. § 2 BetrKV, umlagefähig, Standardschlüssel)
STANDARD_KOSTENARTEN = [
    ("Heizkosten", "4", 1, "mea"),
    ("Warmwasser", "5", 1, "mea"),
    ("Allgemeinstrom", "11", 1, "mea"),
    ("Gebäudeversicherung", "13", 1, "mea"),
    ("Haftpflichtversicherung", "13", 1, "mea"),
    ("Hausmeister", "14", 1, "mea"),
    ("Grundsteuer", "1", 1, "mea"),
    ("Schneeräumung / Straßenreinigung", "8", 1, "mea"),
    ("Kanalgebühren / Niederschlagswasser", "3", 1, "mea"),
    ("Wasser / Abwasser", "2", 1, "wasser"),
    ("Müllentsorgung", "8", 1, "mea"),
    ("Gebäudereinigung", "9", 1, "mea"),
    ("Gartenpflege", "10", 1, "mea"),
    ("Schornsteinfeger", "12", 1, "mea"),
    ("Aufzug", "7", 1, "mea"),
    ("Antenne / Breitband", "15", 1, "einheiten"),
    ("Wartung / Betriebskosten", "17", 1, "mea"),
    ("Verwaltung", "", 0, "mea"),
    ("Instandhaltung / Reparaturen", "", 0, "mea"),
]


def _natuerlich_schluessel(s):
    """„Wohnung 10“ nach „Wohnung 9“: Ziffernfolgen als Zahlen vergleichen, sonst ohne Groß/klein."""
    return [(0, int(t), "") if t.isdigit() else (1, 0, t.casefold()) for t in re.split(r"(\d+)", s or "") if t]


def _natuerlich(a, b):
    x, y = _natuerlich_schluessel(a), _natuerlich_schluessel(b)
    return (x > y) - (x < y)


def verbinden(pfad=None):
    con = sqlite3.connect(pfad or DB_PATH)
    con.create_collation("NATUERLICH", _natuerlich)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def get_db():
    if "db" not in g:
        g.db = verbinden()
    return g.db


def close_db(_exc=None):
    con = g.pop("db", None)
    if con is not None:
        con.close()


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    con = verbinden()
    version = con.execute("PRAGMA user_version").fetchone()[0]
    for i, sql in enumerate(MIGRATIONEN[version:], start=version + 1):
        con.executescript(sql)
        if i == 1:
            con.executemany("INSERT INTO kostenart (name, betrkv_nr, umlagefaehig, schluessel, sortierung) "
                            "VALUES (?, ?, ?, ?, ?)",
                            [(*k, n * 10) for n, k in enumerate(STANDARD_KOSTENARTEN)])
        if i == 12 and not con.execute("SELECT 1 FROM kostenart WHERE ruecklage = 1").fetchone():
            con.execute("INSERT INTO kostenart (name, umlagefaehig, schluessel, sortierung, ruecklage) "
                        "VALUES ('Zuführung Erhaltungsrücklage', 0, 'mea', "
                        "(SELECT COALESCE(MAX(sortierung), 0) + 10 FROM kostenart), 1)")
        con.execute(f"PRAGMA user_version = {i}")
        con.commit()
    con.close()
