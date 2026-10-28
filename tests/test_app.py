"""Ende-zu-Ende-Test über den Flask-Testclient: Einrichtung bis PDF-Export."""
import io
import os
import re
import sys
import tempfile

TMP = tempfile.mkdtemp()
os.environ["NK_DATA"] = os.path.join(TMP, "data")
os.environ["NK_DOKUMENTE"] = os.path.join(TMP, "dokumente")
os.environ["NK_ERINNERUNG"] = "aus"  # keine Hintergrund-Prüfung im Test
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from PIL import Image  # noqa: E402
from pypdf import PdfReader, PdfWriter  # noqa: E402

from main import app  # noqa: E402

app.config["TESTING"] = True


def pdf_datei(name="beleg.pdf"):
    w = PdfWriter()
    w.add_blank_page(width=595, height=842)
    buf = io.BytesIO()
    w.write(buf)
    buf.seek(0)
    return buf, name


def bild_datei(name="foto.jpg", fmt="JPEG", mode="RGB", size=(800, 600)):
    buf = io.BytesIO()
    Image.new(mode, size, (200, 100, 50, 128) if mode == "RGBA" else (200, 100, 50)).save(buf, fmt)
    buf.seek(0)
    return buf, name


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.request.path, r.get_data(as_text=True)[:2000])
    return r


def post(c, url, code=302, **kw):
    """POST und prüfen, dass keine Fehlermeldung (Flash „fehler“) entstanden ist."""
    r = ok(c.post(url, **kw), code)
    with c.session_transaction() as s:
        fehler = [m for kat, m in s.get("_flashes", []) if kat == "fehler"]
    assert not fehler, (url, fehler)
    return r


def test_gesamter_ablauf():
    c = app.test_client()
    assert c.get("/").headers["Location"].endswith("/einrichtung")
    assert ok(c.get("/health")).get_json()["status"] == "ok"  # Healthcheck ohne Anmeldung, auch vor der Einrichtung
    post(c, "/einrichtung", data={"benutzername": "admin", "vorname": "Max", "name": "Vermieter",
                                    "passwort": "geheim123", "passwort2": "geheim123"})
    post(c, "/profil", data={"vorname": "Max", "name": "Vermieter", "strasse": "Musterweg", "hausnummer": "1",
                               "plz": "12345", "ort": "Musterstadt", "email": "", "notizen": "Notiz",
                               "foto": bild_datei()}, content_type="multipart/form-data")

    # Immobilie mit Dokument anlegen
    r = c.post("/immobilien/neu", data={"name": "Lindenhof 7", "strasse": "Lindenhof", "hausnummer": "7",
                                        "plz": "12345", "ort": "Musterstadt", "iban": "de00 1234", "weg": "on",
                                        "dateien": pdf_datei("Grundsteuerbescheid.pdf"), "dok_jahr": "2025",
                                        "bereich": "mieter"}, content_type="multipart/form-data")
    ok(r, 302)
    assert os.path.exists(os.path.join(TMP, "dokumente", "Lindenhof 7", "2025", "Mieter", "Grundsteuerbescheid.pdf"))

    # Zwei Mietobjekte
    post(c, "/immobilien/1/wohnungen/neu", data={"bezeichnung": "EG", "wohnflaeche": "65", "mea": "86,13/1.000",
                                                   "eigentuemer_id": "1", "wasser_nummer": "W-1",
                                                   "umlageschluessel": "Heizung nach Verbrauch"})
    post(c, "/einstellungen/admin/wohnungen/neu", data={"bezeichnung": "OG", "wohnflaeche": "50", "mea": "60",
                                                          "mea_basis": "1.000", "immobilie_id": "",
                                                          "wasser_nummer": "W-2"})
    post(c, "/immobilien/1/wohnungen/neu", data={"vorhandene": "2"})

    # Mieter mit zweiter Person, Einzug 01.04.2025
    post(c, "/wohnungen/1/mieter", data={"vorname": "Noah", "name": "Gerber", "von": "2025-04-01",
                                           "vorauszahlung_monat": "150"})
    post(c, "/mieter/1/personen", data={"vorname": "Mia", "name": "Muster"})

    # Zählerstände Wasser (Zähler 1 = EG, Zähler 2 = OG)
    for zid, staende in ((1, [("2024-12-31", "100"), ("2025-03-31", "105"), ("2025-12-31", "130")]),
                         (2, [("2024-12-31", "0"), ("2025-12-31", "20")])):
        for d, s in staende:
            post(c, f"/zaehler/{zid}/staende", data={"datum": d, "stand": s})

    # Kosten 2025
    c.get("/immobilien/1?jahr=2025")
    ka = {k: i + 1 for i, k in enumerate(["Heizkosten", "Warmwasser", "Allgemeinstrom", "Gebäudeversicherung",
                                          "Haftpflichtversicherung", "Hausmeister", "Grundsteuer"])}
    post(c, "/immobilien/1/buchungen", data={"datum": "2025-03-01", "text": "Versicherung", "art": "ausgabe",
                                               "ziel": ka["Gebäudeversicherung"], "betrag": "1.000,00", "bezahlt": "konto"})
    post(c, "/immobilien/1/buchungen", data={"datum": "2025-12-01", "text": "Stadtwerke", "art": "ausgabe",
                                               "ziel": "10", "betrag": "500", "bezahlt": "konto"})
    post(c, "/wohnungen/1/kosten", data={"kostenart_id": ka["Heizkosten"], "betrag": "712,37", "mv_id": "1"})
    post(c, "/wohnungen/1/kosten", data={"kostenart_id": ka["Grundsteuer"], "betrag": "103,54"})

    # Kosten bearbeiten: erst nach Klick auf den Stift sind die Felder offen
    assert 'form="k1"' not in ok(c.get("/immobilien/1")).get_data(as_text=True)
    assert 'name="notiz" form="k1"' in ok(c.get("/immobilien/1?bearbeiten=1")).get_data(as_text=True)
    html = ok(c.get("/wohnungen/1?bearbeiten=3")).get_data(as_text=True)
    assert 'name="mv_id" form="k3"' in html
    assert "/immobilien/1?bearbeiten=1#kosten" in html  # Gebäudekosten: Stift führt zur Immobilie
    post(c, "/kosten/1", data={"kostenart_id": ka["Gebäudeversicherung"], "betrag": "9", "schluessel": "mea",
                               "notiz": "Police 2025\nZweite Zeile"})  # Betrag der Gebäudekosten kommt nur aus den Buchungen
    post(c, "/kosten/4", data={"kostenart_id": ka["Grundsteuer"], "betrag": "103,54", "mv_id": "", "notiz": "Bescheid"})
    assert "Police 2025" in ok(c.get("/immobilien/1")).get_data(as_text=True)

    html = ok(c.get("/wohnungen/1")).get_data(as_text=True)
    assert "Gerber" in html and "Noah Gerber, Mia Muster" in html
    assert "1.350,00" in html  # Soll-Vorauszahlung 9 × 150 als Platzhalter
    # Prüfliste: Vorauszahlung nur vorgeschlagen; Gebäudekosten nicht vollständig verteilt (OG noch nicht zugeordnet)
    assert "Bitte prüfen" in html and "noch nicht gespeichert" in html
    immo_html = ok(c.get("/immobilien/1")).get_data(as_text=True)
    assert "keinem Mietobjekt zugeordnet" in immo_html and "Summe MEA" in immo_html
    assert "Trotzdem speichern" in ok(c.get("/wohnungen/1/export?partei=1")).get_data(as_text=True)

    # Brief prüfen: Grundsteuer 75 %, Heizkosten 100 %
    brief = ok(c.get("/wohnungen/1/export/brief?partei=1")).get_data(as_text=True)
    assert "77,66 €" in brief and "712,37 €" in brief and "75 %" in brief
    assert "Erstellt mit Immobilienverwalter" in brief  # Fußzeile standardmäßig an
    # eigenes Konto beim Mietobjekt gilt nur für die Mieter-Abrechnung, die Eigentümer-Abrechnung zahlt aufs Konto der Immobilie
    post(c, "/einstellungen/admin/wohnungen/1", data={"bezeichnung": "EG", "wohnflaeche": "65", "mea": "86,13/1.000",
                                                        "immobilie_id": "1", "eigentuemer_id": "1",
                                                        "umlageschluessel": "Heizung nach Verbrauch",
                                                        "iban": "DE89 3704 0044 0532 0130 00", "bank": "Meine Bank"})
    post(c, "/wohnungen/1/vorauszahlungen", data={"vz_1": "0"})  # Nachzahlung, damit die Bankverbindung im Brief steht
    assert "DE89 3704 0044 0532 0130 00" in ok(c.get("/wohnungen/1/export/brief?partei=1")).get_data(as_text=True)
    eig_brief = ok(c.get("/wohnungen/1/export/brief?partei=eigentuemer")).get_data(as_text=True)
    assert "DE89" not in eig_brief and "DE00 1234" in eig_brief
    from export import girocode, sepa_text
    assert sepa_text("Gartenstraße 5, Klara Krämer & Söhne") == "Gartenstrasse 5, Klara Kraemer Soehne"
    assert girocode("Max", "DE89 3704 0044 0532 0130 00", 162.43, "Nebenkosten").startswith("<svg")
    assert girocode("Max", "", 162.43, "x") is None and girocode("Max", "DE89", 0, "x") is None
    assert "Max Vermieter, Musterweg 1, 12345 Musterstadt" in brief
    assert "Nachzahlung" in brief or "Gutschrift" in brief

    post(c, "/wohnungen/1/vorauszahlungen", data={"vz_1": "1.350", "vz_eigentuemer": "500"})
    html = ok(c.get("/wohnungen/1")).get_data(as_text=True)
    assert "noch nicht gespeichert" not in html and "Eigentümer-Abrechnung (WEG)" in html
    # ohne WEG keine Eigentümer-Abrechnung, nur die Übersicht
    post(c, "/immobilien/1/stammdaten", data={"name": "Lindenhof 7", "strasse": "Lindenhof", "hausnummer": "7",
                                              "plz": "12345", "ort": "Musterstadt", "iban": "DE00 1234"})
    html = ok(c.get("/wohnungen/1")).get_data(as_text=True)
    assert "Eigentümer-Abrechnung (WEG)" not in html and "Der Eigentümer trägt selbst" in html
    post(c, "/immobilien/1/stammdaten", data={"name": "Lindenhof 7", "strasse": "Lindenhof", "hausnummer": "7",
                                              "plz": "12345", "ort": "Musterstadt", "iban": "DE00 1234", "weg": "on"})

    # Standard-Umlageschlüssel einer Immobilie gilt für Gebäudekosten, die aus einer Buchung neu entstehen
    post(c, "/immobilien/neu", data={"name": "Haus Test", "schluessel": "einheiten"})
    post(c, "/immobilien/2/buchungen", data={"datum": "2025-05-01", "text": "Versicherung", "art": "ausgabe",
                                               "ziel": ka["Gebäudeversicherung"], "betrag": "10", "bezahlt": "konto"})
    assert "<td>Wohneinheiten</td>" in ok(c.get("/immobilien/2")).get_data(as_text=True)
    # Archivieren blendet aus, Wiederherstellen holt zurück
    post(c, "/immobilien/2/wohnungen/neu", data={"bezeichnung": "Versehen", "wohnflaeche": "40"})
    post(c, "/immobilien/2/archiv", data={"archiviert": "1"})
    assert "Haus Test" not in ok(c.get("/")).get_data(as_text=True)
    assert "Haus Test" in ok(c.get("/archiv")).get_data(as_text=True)
    post(c, "/immobilien/2/archiv", data={"archiviert": "0"})
    assert "Archiv (" not in ok(c.get("/")).get_data(as_text=True)
    # Löschen entfernt die Immobilie samt Mietobjekten
    assert "Mietobjekt löschen" in ok(c.get("/wohnungen/3?reiter=stammdaten")).get_data(as_text=True)
    post(c, "/immobilien/2/loeschen")
    ok(c.get("/immobilien/2"), 404)
    ok(c.get("/einstellungen/admin/wohnungen/3"), 404)

    # Dokument in den Mieterordner
    post(c, "/immobilien/1/dokumente", data={"wohnung_id": "1", "dok_wohnung_id": "1", "dok_jahr": "2025",
                                               "bereich": "mieterordner", "mv_id": "1", "kostenart_id": "1",
                                               "dateien": bild_datei("Heizkosten.jpg")},
              content_type="multipart/form-data")
    assert os.path.exists(os.path.join(TMP, "dokumente", "Lindenhof 7", "2025", "Mieter", "001 - Gerber",
                                       "Heizkosten.jpg"))

    # Alle Seiten rendern
    for url in ["/", "/immobilien/1", "/wohnungen/1", "/wohnungen/2", "/immobilien/1/wohnungen/neu",
                "/wohnungen/1/export?partei=1", "/wohnungen/1/export?partei=eigentuemer",
                "/wohnungen/1/export/brief?partei=eigentuemer", "/einstellungen/vermieter",
                "/einstellungen/admin/vermieter/neu", "/einstellungen/admin/vermieter/1",
                "/einstellungen/admin/wohnungen", "/einstellungen/admin/wohnungen/1", "/einstellungen/admin/wohnungen/neu",
                "/einstellungen/admin/kostenarten", "/einstellungen/admin/ablage", "/einstellungen/info", "/einstellungen/admin/logo", "/einstellungen/admin/smtp",
                "/profil", "/profil/immobilien", "/profil/passwort", "/immobilien/neu", "/benutzer/1/foto",
                "/dokumente/1", "/dokumente/2"]:
        ok(c.get(url))

    # PDF mit beiden Anlagen
    r = post(c, "/wohnungen/1/export/pdf", 200, data={"partei": "1", "dokumente": ["1", "2"], "aktion": "speichern"})
    assert r.mimetype == "application/pdf" and "attachment" in r.headers["Content-Disposition"]
    assert len(PdfReader(io.BytesIO(r.data)).pages) == 4  # Brief (2 Seiten) + PDF-Beleg + JPG-Beleg
    r = post(c, "/wohnungen/1/export/pdf", 200, data={"partei": "eigentuemer", "aktion": "vorschau"})
    assert "inline" in r.headers.get("Content-Disposition", "inline")

    # Belege und Buchungen: mehrere Belege je Kostenart, Einnahmen mindern, Rücklage wird nicht umgelegt
    import sqlite3
    dbcon = sqlite3.connect(os.path.join(TMP, "data", "nebenkosten.sqlite"))

    def kosten(kostenart_id):
        r = dbcon.execute("SELECT betrag FROM kosten WHERE immobilie_id = 1 AND jahr = 2025 AND wohnung_id IS NULL "
                          "AND kostenart_id = ?", (kostenart_id,)).fetchall()
        return [x[0] for x in r]

    garten, hausmeister, zufuehrung = 13, 6, 20  # Zuführung: von Migration 12 angelegt
    c.get("/immobilien/1?jahr=2025")
    post(c, "/immobilien/1/buchungen", data={"datum": "2025-09-19", "text": "Esso, Rasenmäher", "art": "ausgabe",
                                               "ziel": garten, "betrag": "18,01", "bezahlt": "bar"})
    r = post(c, "/immobilien/1/buchungen", data={"datum": "2025-11-24", "text": "Obi", "art": "ausgabe", "ziel": garten,
                                                   "betrag": "17,97", "bezahlt": "bar", "beleg": pdf_datei("Obi.pdf")},
             content_type="multipart/form-data")
    assert r.headers["Location"].endswith("reiter=buchungen&neu=1")
    assert os.path.exists(os.path.join(TMP, "dokumente", "Lindenhof 7", "2025", "Vermieter", "Obi.pdf"))
    assert kosten(garten) == [35.98]
    html = ok(c.get("/immobilien/1?reiter=buchungen&neu=1")).get_data(as_text=True)
    assert "offen</small>" in html and "zusammen 35,98 €" in html
    assert "aus 2 Buchungen" in ok(c.get("/immobilien/1")).get_data(as_text=True)  # Übersicht: Gebäudekosten
    assert 'value="2025-11-24" required autofocus' in html and f'<option value="{garten}" selected>' in html
    post(c, "/immobilien/1/buchungen", data={"datum": "2025-12-10", "text": "Gutschrift", "art": "einnahme",
                                               "ziel": garten, "betrag": "5,98", "bezahlt": "konto"})
    assert kosten(garten) == [30.0]
    post(c, "/buchungen/3/erstattet")
    post(c, "/buchungen/4", data={"datum": "2025-11-24", "text": "Obi", "art": "ausgabe", "ziel": hausmeister,
                                  "betrag": "17,97", "bezahlt": "bar", "erstattet": "2025-12-01"})
    assert kosten(garten) == [12.03] and kosten(hausmeister) == [17.97]
    assert "offen</small>" not in ok(c.get("/immobilien/1?reiter=buchungen")).get_data(as_text=True)
    post(c, "/buchungen/3/loeschen")
    post(c, "/buchungen/5/loeschen")
    assert kosten(garten) == []  # ohne Buchungen fällt die Kostenposition weg
    # Belegdatum aus einem anderen Jahr: nach Rückfrage (Feld buchungsjahr) landet die Buchung dort, die Ansicht wechselt mit
    r = post(c, "/immobilien/1/buchungen", data={"datum": "2026-07-06", "text": "Tanken", "art": "ausgabe", "ziel": garten,
                                                 "betrag": "23,75", "bezahlt": "konto", "buchungsjahr": "2026"})
    assert "jahr=2026" in r.headers["Location"]
    tanken = dbcon.execute("SELECT id, jahr FROM buchung WHERE text = 'Tanken'").fetchone()
    assert tanken[1] == 2026 and kosten(garten) == []
    c.get("/immobilien/1?jahr=2025")
    post(c, f"/buchungen/{tanken[0]}", data={"datum": "2026-07-06", "text": "Tanken", "art": "ausgabe", "ziel": garten,
                                             "betrag": "23,75", "bezahlt": "konto", "buchungsjahr": "2025"})
    assert kosten(garten) == [23.75]  # bewusst im Jahr 2025 gelassen (z. B. Rechnung fürs Vorjahr)
    html = ok(c.get("/immobilien/1?reiter=buchungen")).get_data(as_text=True)
    assert "nicht 2025" in html and "Summe Ausgaben" in html
    # im Jahr 2026 erscheint ein Hinweis mit „nach 2026 holen“; ein Klick verschiebt die Buchung samt Gebäudekosten
    assert "→ 2026</button>" in html
    html = ok(c.get("/immobilien/1?jahr=2026&reiter=buchungen")).get_data(as_text=True)
    assert "1 Buchung mit Datum in 2026 steht in einem anderen Jahr" in html and "nach 2026 holen" in html
    post(c, f"/buchungen/{tanken[0]}/jahr")
    assert kosten(garten) == [] and dbcon.execute("SELECT jahr FROM buchung WHERE id = ?", (tanken[0],)).fetchone()[0] == 2026
    assert "nach 2026 holen" not in ok(c.get("/immobilien/1?reiter=buchungen")).get_data(as_text=True)
    c.get("/immobilien/1?jahr=2025")
    post(c, f"/buchungen/{tanken[0]}/loeschen")
    assert kosten(garten) == []
    # Erhaltungsrücklage: Zuführung über die Kostenart, PV-Einnahme hinein, Energieausweise heraus
    post(c, "/immobilien/1/buchungen", data={"datum": "2025-12-31", "text": "Zuführung", "art": "ausgabe",
                                               "ziel": zufuehrung, "betrag": "1.900,00", "bezahlt": "konto"})
    post(c, "/immobilien/1/buchungen", data={"datum": "2025-06-30", "text": "PV-Anlage", "art": "einnahme",
                                               "ziel": "ruecklage", "betrag": "700", "bezahlt": "konto"})
    post(c, "/immobilien/1/buchungen", data={"datum": "2025-05-09", "text": "Energieausweise", "art": "ausgabe",
                                               "ziel": "ruecklage", "betrag": "800,00", "bezahlt": "konto"})
    html = ok(c.get("/immobilien/1")).get_data(as_text=True)
    assert "Der Anfangsbestand fehlt" in html
    r = post(c, "/immobilien/1/ruecklage", data={"anfang": "10.000,00"})
    assert r.headers["Location"].endswith("reiter=ruecklage")
    assert "Der Anfangsbestand fehlt" not in ok(c.get("/immobilien/1")).get_data(as_text=True)
    html = ok(c.get("/immobilien/1?reiter=ruecklage")).get_data(as_text=True)
    assert "11.800,00 €" in html  # 10.000 + 1.900 + 700 − 800
    eig_brief = ok(c.get("/wohnungen/1/export/brief?partei=eigentuemer")).get_data(as_text=True)
    assert "Erhaltungsrücklage 2025" in eig_brief and "11.800,00 €" in eig_brief
    assert "1.016,33 €" in eig_brief  # Anteil 86,13/1.000 MEA
    assert "Energieausweise" in eig_brief and "Zuführung Erhaltungsrücklage" in eig_brief
    mieter_brief = ok(c.get("/wohnungen/1/export/brief?partei=1")).get_data(as_text=True)
    assert "Erhaltungsrücklage" not in mieter_brief and "Energieausweise" not in mieter_brief
    # Export-Auswahl: Belegliste als Zusatzseite, Rücklage abwählbar; Mieter sehen nur umlagefähige Belege
    seite = ok(c.get("/wohnungen/1/export?partei=eigentuemer")).get_data(as_text=True)
    assert "Belegliste 2025" in seite
    # Beleg der Buchung „Obi“ (jetzt Hausmeister, umlagefähig): Eigentümer vorausgewählt, Mieter nur zur Auswahl
    assert re.search(r'value="3" checked>\s*<span>Obi<br><small class="leise">Beleg zur Buchung', seite)
    assert re.search(r'value="3" >\s*<span>Obi<br>', ok(c.get("/wohnungen/1/export?partei=1")).get_data(as_text=True))
    html = ok(c.get("/immobilien/1?reiter=buchungen")).get_data(as_text=True)
    assert "5 von 6 Buchungen ohne Beleg" in html and html.count(">fehlt<") == 5

    def pdf_text(daten):
        r = post(c, "/wohnungen/1/export/pdf", 200, data={**daten, "aktion": "speichern"})
        seiten = PdfReader(io.BytesIO(r.data)).pages
        return len(seiten), " ".join(x.extract_text() for x in seiten)

    n, text = pdf_text({"partei": "eigentuemer", "teile": ["ruecklage", "belegliste"]})
    assert n == 3 and "Belegliste 2025" in text and "Energieausweise" in text and "Summe Gebäudeversicherung" in text
    n, text = pdf_text({"partei": "eigentuemer"})
    assert n == 2 and "Erhaltungsrücklage 2025" not in text
    n, text = pdf_text({"partei": "1", "teile": ["belegliste"]})
    assert n == 3 and "Versicherung" in text and "Energieausweise" not in text and "Zuführung" not in text

    # Vorjahr übernehmen in 2026, Rücklage wird fortgeschrieben
    c.get("/immobilien/1?jahr=2026")
    post(c, "/immobilien/1/vorjahr")
    html = ok(c.get("/immobilien/1")).get_data(as_text=True)
    assert "Gebäudeversicherung" in html
    html = ok(c.get("/immobilien/1?reiter=ruecklage")).get_data(as_text=True)
    assert "11.800,00 €" in html and "aus 2025 fortgeschrieben" in html
    # Rücklage als Kontoblatt: Einträge direkt im Reiter, mit Kommentar, bearbeitbar und löschbar
    r = post(c, "/immobilien/1/buchungen", data={"reiter": "ruecklage", "rl_art": "zufuehrung", "datum": "2026-01-31",
                                                 "text": "Bausparrate Januar", "notiz": "Vertrag 4711", "betrag": "100",
                                                 "bezahlt": "konto"})
    assert r.headers["Location"].endswith("reiter=ruecklage&neu=1")
    post(c, "/immobilien/1/buchungen", data={"reiter": "ruecklage", "rl_art": "einnahme", "datum": "2026-03-01",
                                               "text": "Zinsen", "betrag": "5", "bezahlt": "konto"})
    post(c, "/immobilien/1/buchungen", data={"reiter": "ruecklage", "rl_art": "entnahme", "datum": "2026-04-01",
                                               "text": "Dachrinne", "betrag": "50", "bezahlt": "bar"})
    html = ok(c.get("/immobilien/1?reiter=ruecklage")).get_data(as_text=True)
    assert "Vertrag 4711" in html and "11.855,00 €" in html  # 11.800 + 100 + 5 − 50
    assert "11.900,00 €" in html and "11.905,00 €" in html  # laufender Stand
    zufuehrung_2026 = dbcon.execute("SELECT id, kostenart_id, kosten_id FROM buchung WHERE text = 'Bausparrate Januar'").fetchone()
    assert zufuehrung_2026[1] == zufuehrung and zufuehrung_2026[2]  # läuft über die Rücklage-Kostenart, wird umgelegt
    bid = zufuehrung_2026[0]
    assert 'name="rl_art"' in ok(c.get(f"/immobilien/1?reiter=ruecklage&buchung={bid}")).get_data(as_text=True)
    r = post(c, f"/buchungen/{bid}", data={"reiter": "ruecklage", "rl_art": "zufuehrung", "ziel": str(zufuehrung),
                                           "datum": "2026-01-31", "text": "Bausparrate Januar", "notiz": "geändert",
                                           "betrag": "120", "bezahlt": "konto"})
    assert r.headers["Location"].endswith("reiter=ruecklage")
    html = ok(c.get("/immobilien/1?reiter=ruecklage")).get_data(as_text=True)
    assert "geändert" in html and "11.875,00 €" in html
    post(c, "/immobilien/1/ruecklage", data={"anfang": "100", "notiz": "Testeintrag"})
    html = ok(c.get("/immobilien/1?reiter=ruecklage")).get_data(as_text=True)
    assert "Testeintrag" in html and "175,00 €" in html  # 100 + 120 + 5 − 50
    post(c, "/immobilien/1/ruecklage", data={"anfang": ""})  # eingetragenen Anfangsbestand wieder entfernen
    assert "11.875,00 €" in ok(c.get("/immobilien/1?reiter=ruecklage")).get_data(as_text=True)
    post(c, f"/buchungen/{bid}/loeschen", data={"reiter": "ruecklage"})
    # Konten: Stände zum Stichtag, Jahr aus dem Datum, Abgleich mit der Rücklage, bearbeiten und löschen
    post(c, "/immobilien/1/konten", data={"name": "Tagesgeld", "ruecklage": "on"})
    post(c, "/immobilien/1/konten", data={"name": "Girokonto", "iban": "de00 9999"})
    tg, giro = [x[0] for x in dbcon.execute("SELECT id FROM konto ORDER BY id")]
    post(c, "/immobilien/1/kontostaende", data={"konto_id": tg, "datum": "2025-12-31", "betrag": "11.000"})
    r = post(c, "/immobilien/1/kontostaende", data={"konto_id": tg, "datum": "2026-12-31", "betrag": "11.755",
                                                    "notiz": "Auszug 12"})
    assert "jahr=2026" not in r.headers["Location"]  # Ansicht steht schon auf 2026
    post(c, "/immobilien/1/kontostaende", data={"konto_id": giro, "datum": "2026-12-31", "betrag": "2.000"})
    html = ok(c.get("/immobilien/1?reiter=ruecklage")).get_data(as_text=True)
    assert "Auszug 12" in html and "13.755,00 €" in html and "+ 755,00 €" in html and "stimmt überein" in html  # Rücklage 11.755
    sid = dbcon.execute("SELECT id FROM kontostand WHERE notiz = 'Auszug 12'").fetchone()[0]
    post(c, f"/kontostaende/{sid}", data={"datum": "2026-12-31", "betrag": "11.780", "notiz": "korrigiert"})
    assert "Differenz 25,00 €" in ok(c.get("/immobilien/1?reiter=ruecklage")).get_data(as_text=True)
    r = post(c, f"/kontostaende/{sid}", data={"datum": "2025-06-30", "betrag": "11.780", "notiz": "korrigiert"})
    assert "jahr=2025" in r.headers["Location"]  # falsches Jahr erkannt, Ansicht springt mit
    c.get("/immobilien/1?jahr=2026")
    post(c, f"/kontostaende/{sid}/loeschen")
    post(c, f"/konten/{giro}", data={"name": "Girokonto WEG"})
    post(c, f"/konten/{giro}/loeschen")
    assert dbcon.execute("SELECT name FROM konto").fetchall() == [("Tagesgeld",)]
    # Ohne Anfangsbestand: kein Alarm, sondern Übernahme der Kontostände vom 31.12. des Vorjahres als Anfangsbestand
    c.get("/immobilien/1?jahr=2027")
    seite = ok(c.get("/immobilien/1?reiter=ruecklage")).get_data(as_text=True)
    assert "noch kein Anfangsbestand" not in seite  # 2027 wird aus 2026 fortgeschrieben
    dbcon.execute("DELETE FROM ruecklage_bestand")
    dbcon.commit()
    seite = ok(c.get("/immobilien/1?reiter=ruecklage")).get_data(as_text=True)
    assert "noch kein Anfangsbestand" in seite and "bitte Buchungen und Kontostände prüfen" not in seite
    assert "aus den Kontoständen übernehmen (11.000,00 €)" in seite
    post(c, "/immobilien/1/ruecklage", data={"anfang": "11.000,00", "notiz": "Summe der Rücklage-Konten am 31.12.2026"})
    seite = ok(c.get("/immobilien/1?reiter=ruecklage")).get_data(as_text=True)
    assert "Summe der Rücklage-Konten am 31.12.2026" in seite and "noch kein Anfangsbestand" not in seite
    c.get("/immobilien/1?jahr=2026")
    assert not dbcon.execute("SELECT 1 FROM kontostand WHERE konto_id = ?", (giro,)).fetchone()
    assert "geändert" not in ok(c.get("/immobilien/1?reiter=ruecklage")).get_data(as_text=True)
    # Daueraufträge: gelten nur für ein Jahr; je Jahr eine Buchung mit Rechenweg; Betragswechsel über zwei Aufträge
    c.get("/immobilien/1?jahr=2026")

    def fehlermeldung(url, daten):
        ok(c.post(url, data=daten), 302)
        with c.session_transaction() as sitzung:
            return " ".join(m for kat, m in sitzung.pop("_flashes", []) if kat == "fehler")

    assert "nur für ein Jahr" in fehlermeldung("/immobilien/1/dauerauftraege", {
        "text": "Hausmeister", "art": "ausgabe", "ziel": hausmeister, "betrag": "170", "rhythmus": "monat",
        "von": "2025-01-01", "bis": "2026-06-30"})
    post(c, "/immobilien/1/dauerauftraege", data={"text": "Hausmeister", "art": "ausgabe", "ziel": hausmeister,
                                                  "betrag": "170", "rhythmus": "monat", "von": "2026-01-01", "bis": "2026-06-30"})
    post(c, "/immobilien/1/dauerauftraege", data={"text": "Hausmeister", "art": "ausgabe", "ziel": hausmeister,
                                                  "betrag": "180", "rhythmus": "monat", "von": "2026-07-01"})  # bis = 31.12.
    post(c, "/immobilien/1/dauerauftraege", data={"text": "Rücklage-Anteil", "art": "ausgabe", "ziel": zufuehrung,
                                                  "betrag": "480", "rhythmus": "quartal", "von": "2026-02-15"})
    seite = ok(c.get("/immobilien/1?reiter=buchungen")).get_data(as_text=True)
    assert "6 × 170,00 €<br><strong>= 1.020,00 €" in seite and "6 × 180,00 €<br><strong>= 1.080,00 €" in seite
    assert "4 × 480,00 €<br><strong>= 1.920,00 €" in seite and "für 2026 buchen" in seite
    post(c, "/immobilien/1/dauerauftraege/buchen")

    def kosten26(ka):
        return [x[0] for x in dbcon.execute("SELECT betrag FROM kosten WHERE immobilie_id = 1 AND jahr = 2026 "
                                           "AND wohnung_id IS NULL AND kostenart_id = ?", (ka,))]
    assert kosten26(hausmeister) == [2100.0] and kosten26(zufuehrung) == [1920.0]  # 6×170 + 6×180; 4×480
    seite = ok(c.get("/immobilien/1?reiter=buchungen")).get_data(as_text=True)
    assert seite.count("gebucht ✓") == 3 and "für 2026 buchen" not in seite
    assert "Hausmeister 2026" in seite and "Dauerauftrag)" in seite
    # Jahresbuchung von Hand geändert → Hinweis und „angleichen“
    b_id, da_id = dbcon.execute("SELECT id, dauerauftrag_id FROM buchung WHERE text = 'Rücklage-Anteil 2026'").fetchone()
    post(c, f"/buchungen/{b_id}", data={"datum": "2026-11-15", "text": "Rücklage-Anteil 2026", "art": "ausgabe",
                                        "ziel": zufuehrung, "betrag": "1.440", "bezahlt": "konto", "notiz": "ein Quartal fehlt"})
    seite = ok(c.get("/immobilien/1?reiter=buchungen")).get_data(as_text=True)
    assert "gebucht 1.440,00 €" in seite and "angleichen" in seite
    assert "1.440,00 €" in ok(c.get("/immobilien/1?reiter=ruecklage")).get_data(as_text=True)  # Zuführung im Kontoblatt
    post(c, f"/dauerauftraege/{da_id}/angleichen")
    assert kosten26(zufuehrung) == [1920.0]
    # 2027: nichts läuft weiter; Übernahme aus dem Vorjahr kopiert mit verschobenen Daten, aber nur einmal
    seite = ok(c.get("/immobilien/1?jahr=2027&reiter=buchungen")).get_data(as_text=True)
    assert "180,00 €" not in seite and "3 Dauerauftrag/-aufträge aus 2026 übernehmen" in seite
    post(c, "/immobilien/1/dauerauftraege/vorjahr")
    assert dbcon.execute("SELECT von, bis FROM dauerauftrag WHERE jahr = 2027 AND betrag = 180").fetchone() == \
        ("2027-07-01", "2027-12-31")
    assert "schon Daueraufträge" in fehlermeldung("/immobilien/1/dauerauftraege/vorjahr", {})
    dbcon.execute("DELETE FROM dauerauftrag WHERE jahr = 2027")
    dbcon.commit()
    c.get("/immobilien/1?jahr=2026")
    post(c, f"/dauerauftraege/{da_id}/loeschen")
    assert kosten26(zufuehrung) == [1920.0]  # Buchung bleibt
    assert 'class="info"' in ok(c.get("/immobilien/1?reiter=buchungen")).get_data(as_text=True)

    # Hausgeld als Buchung: eigene WEG mit drei Wohnungen eines Eigentümers und einer Wohnung eines zweiten
    post(c, "/immobilien/neu", data={"name": "Hausgeld-Test", "weg": "on"})
    hid = dbcon.execute("SELECT id FROM immobilie WHERE name = 'Hausgeld-Test'").fetchone()[0]
    for bez in ("W1", "W2", "W3"):
        post(c, f"/immobilien/{hid}/wohnungen/neu", data={"bezeichnung": bez, "wohnflaeche": "50", "mea": "250/1000",
                                                         "eigentuemer_id": "1"})
    post(c, f"/immobilien/{hid}/wohnungen/neu", data={"bezeichnung": "W4", "wohnflaeche": "50", "mea": "250/1000",
                                                     "eigentuemer_id": "neu", "neu_name": "Zweit"})
    w1, w2, w3, w4 = [x[0] for x in dbcon.execute("SELECT id FROM wohnung WHERE immobilie_id = ? ORDER BY bezeichnung",
                                                  (hid,))]
    zweit = dbcon.execute("SELECT eigentuemer_id FROM wohnung WHERE id = ?", (w4,)).fetchone()[0]
    c.get(f"/immobilien/{hid}?jahr=2026")
    seite = ok(c.get(f"/immobilien/{hid}?reiter=buchungen")).get_data(as_text=True)
    assert 'value="e1"' in seite and f'value="w{w4}"' in seite and f'value="e{zweit}"' not in seite  # „alle“ nur bei mehreren
    assert "Hausgeld der Eigentümer: in der Spalte" in seite and "Bei keinem Mietobjekt ist ein Eigentümer" not in seite
    # 100 € für alle drei Wohnungen: cent-genau 33,34 + 33,33 + 33,33; Art wird immer „Einnahme“
    post(c, f"/immobilien/{hid}/buchungen", data={"datum": "2026-01-05", "text": "Hausgeld Januar", "art": "ausgabe",
                                                  "ziel": "e1", "betrag": "100", "bezahlt": "konto"})
    # monatliches Hausgeld per Dauerauftrag, einzeln gebucht: 12 × 450 € für alle drei, 12 × 200 € für W4
    post(c, f"/immobilien/{hid}/dauerauftraege", data={"text": "Hausgeld Eigentümer 1", "art": "einnahme", "ziel": "e1",
                                                       "betrag": "450", "rhythmus": "monat", "einzeln": "on",
                                                       "von": "2026-01-05"})
    post(c, f"/immobilien/{hid}/dauerauftraege", data={"text": "Hausgeld Zweit", "art": "einnahme", "ziel": f"w{w4}",
                                                       "betrag": "200", "rhythmus": "monat", "einzeln": "on",
                                                       "von": "2026-01-01"})
    post(c, f"/immobilien/{hid}/dauerauftraege/buchen")
    assert dbcon.execute("SELECT COUNT(*), SUM(betrag) FROM buchung WHERE immobilie_id = ? AND dauerauftrag_id IS NOT NULL",
                         (hid,)).fetchone() == (24, 7800.0)  # 12 × 450 + 12 × 200
    assert dbcon.execute("SELECT DISTINCT art FROM buchung WHERE immobilie_id = ?", (hid,)).fetchall() == [("einnahme",)]
    seite = ok(c.get(f"/immobilien/{hid}?reiter=buchungen")).get_data(as_text=True)
    assert seite.count("gebucht ✓") == 2 and "Hausgeld Eigentümer 1 03/2026" in seite
    from immobilien import hausgeld_aus_buchungen
    with app.test_request_context():
        hg = hausgeld_aus_buchungen(hid, 2026)[0]
    assert sorted(hg[w]["betrag"] for w in (w1, w2, w3)) == [1833.33, 1833.33, 1833.34]  # 12 × 150 + 100/3
    assert round(sum(hg[w]["betrag"] for w in (w1, w2, w3)), 2) == 5500.0 and hg[w4]["betrag"] == 2400.0
    assert hg[w1]["anzahl"] == 13 and hg[w4]["anzahl"] == 12
    # Hausgeld-Tabelle übernimmt die Summen, von Hand nicht mehr änderbar; Eigentümer-Brief zeigt die Jahressumme
    seite = ok(c.get(f"/immobilien/{hid}")).get_data(as_text=True)
    assert "aus 13 Buchungen" in seite and f'name="hg_{w1}"' not in seite and "2.400,00 €" in seite
    assert ">fehlt<" not in ok(c.get(f"/immobilien/{hid}?reiter=buchungen")).get_data(as_text=True)
    post(c, f"/immobilien/{hid}/hausgeld", data={f"hg_{w4}": "1"})  # wird ignoriert
    assert "2.400,00 €" in ok(c.get(f"/wohnungen/{w4}/export/brief?partei=eigentuemer")).get_data(as_text=True)
    assert "aus 12 Buchungen" in ok(c.get(f"/wohnungen/{w4}")).get_data(as_text=True)
    # Hausgeld gehört weder in die Rücklage noch in Belegliste oder Anlagen
    assert "Hausgeld" not in ok(c.get(f"/immobilien/{hid}?reiter=ruecklage")).get_data(as_text=True).split("<h3")[0] \
        .split("</thead>")[-1]
    assert "Belegliste" not in ok(c.get(f"/wohnungen/{w1}/export?partei=eigentuemer")).get_data(as_text=True)
    # Filter und Suche
    def zeilen(params):
        html_ = ok(c.get(f"/immobilien/{hid}?reiter=buchungen&{params}")).get_data(as_text=True)
        tbody = html_.split("<tbody>")[1].split("</tbody>")[0]
        return tbody.count("<tr>") - tbody.count("Keine Buchung passt zum Filter")
    assert zeilen("") == 25
    assert zeilen("eigentuemer=1") == 13 and zeilen(f"wohnung={w2}") == 13 and zeilen(f"wohnung={w4}") == 12
    assert zeilen("q=450") == 12 and zeilen("q=Januar") == 1 and zeilen("monat=1") == 3 and zeilen("ziel=hausgeld") == 25
    assert zeilen("ziel=ruecklage") == 0 and zeilen("ohne=1") == 0  # Hausgeld braucht keinen Beleg
    assert "Keine Buchung passt zum Filter" in ok(c.get(f"/immobilien/{hid}?reiter=buchungen&ziel=ruecklage")).get_data(as_text=True)
    assert "Gefiltert: 12 von 25 Buchungen" in ok(c.get(f"/immobilien/{hid}?reiter=buchungen&q=450")).get_data(as_text=True)
    # Eigentümer ohne Wohnung mehr: Hausgeld „für alle“ kann nicht zugeordnet werden → Prüfliste
    dbcon.execute("UPDATE wohnung SET eigentuemer_id = NULL WHERE immobilie_id = ? AND eigentuemer_id = 1", (hid,))
    dbcon.commit()
    assert "keine Wohnung mehr" in ok(c.get(f"/immobilien/{hid}")).get_data(as_text=True)
    post(c, f"/immobilien/{hid}/loeschen")
    dbcon.execute("DELETE FROM benutzer WHERE id = ?", (zweit,))  # spätere Tests erwarten die bisherigen Nummern
    dbcon.commit()
    c.get("/immobilien/1?jahr=2026")

    # Kosten nur eines Hauses (Teilungserklärung: Treppenhaus nach MEA der Wohnungen dieses Hauses)
    post(c, "/immobilien/neu", data={"name": "Haus-Test", "weg": "on"})
    tid = dbcon.execute("SELECT id FROM immobilie WHERE name = 'Haus-Test'").fetchone()[0]
    for bez, haus, mea in (("H1", "Haus A", "250"), ("H2", "Haus A", "250"), ("H3", "Haus B", "300"), ("H4", "Haus B", "200")):
        post(c, f"/immobilien/{tid}/wohnungen/neu", data={"bezeichnung": bez, "haus": haus, "wohnflaeche": "50",
                                                         "mea": f"{mea}/1000", "eigentuemer_id": "1"})
    h1, h2, h3, h4 = [x[0] for x in dbcon.execute("SELECT id FROM wohnung WHERE immobilie_id = ? ORDER BY bezeichnung",
                                                  (tid,))]
    instand = str(dbcon.execute("SELECT id FROM kostenart WHERE name = 'Instandhaltung / Reparaturen'").fetchone()[0])
    seite = ok(c.get(f"/immobilien/{tid}?reiter=buchungen")).get_data(as_text=True)
    assert '<option value="Haus A"' in seite and ">nur Haus B<" in seite
    post(c, f"/immobilien/{tid}/buchungen", data={"datum": "2026-04-01", "text": "Treppenhaus streichen", "art": "ausgabe",
                                                  "ziel": instand, "haus": "Haus B", "betrag": "100", "bezahlt": "konto"})
    post(c, f"/immobilien/{tid}/buchungen", data={"datum": "2026-05-01", "text": "Dachrinne", "art": "ausgabe",
                                                  "ziel": instand, "haus": "", "betrag": "40", "bezahlt": "konto"})
    assert "Kein Mietobjekt gehört" in fehlermeldung(f"/immobilien/{tid}/buchungen", {
        "datum": "2026-05-01", "text": "x", "art": "ausgabe", "ziel": instand, "haus": "Haus C", "betrag": "1"})
    assert sorted(dbcon.execute("SELECT haus, betrag FROM kosten WHERE immobilie_id = ?", (tid,)).fetchall()) == \
        [("", 40.0), ("Haus B", 100.0)]  # je Haus eine eigene Kostenposition
    from core import row
    from immobilien import berechnung
    with app.test_request_context():
        erg = berechnung(row("SELECT * FROM immobilie WHERE id = ?", (tid,)), 2026)
    summe = {w: erg["wohnungen"][w]["summe"] for w in (h1, h2, h3, h4)}
    assert summe == {h1: 10.0, h2: 10.0, h3: 72.0, h4: 48.0}  # 100 € nur auf Haus B (300:200), 40 € auf alle nach MEA
    texte = [p["basis"] for p in erg["wohnungen"][h3]["posten"]]
    assert "300,00 von 500,00 MEA (Haus B)" in texte and "300,00/1.000 MEA" in texte
    seite = ok(c.get(f"/immobilien/{tid}?reiter=buchungen")).get_data(as_text=True)
    assert "nur Haus B" in seite
    assert "Instandhaltung / Reparaturen – Haus B" in ok(c.get(f"/immobilien/{tid}")).get_data(as_text=True)
    # Belegliste: Kosten des anderen Hauses tauchen bei Haus A nicht auf
    from export import belegliste
    with app.test_request_context():
        def namen(haus):
            return [gr["name"] for gr in belegliste({"partei": "eigentuemer", "immo": {"id": tid}, "jahr": 2026,
                                                      "w": {"haus": haus}})]
        assert namen("Haus A") == ["Instandhaltung / Reparaturen"]
        assert namen("Haus B") == ["Instandhaltung / Reparaturen", "Instandhaltung / Reparaturen – Haus B"]
    # Umlageschlüssel je Immobilie: eigene Regel mit Grundlage, ungenutzte Kostenarten ausblenden, aufs Jahr anwenden
    hm = str(dbcon.execute("SELECT id FROM kostenart WHERE name = 'Hausmeister'").fetchone()[0])
    aufzug = str(dbcon.execute("SELECT id FROM kostenart WHERE name = 'Aufzug'").fetchone()[0])
    assert "Umlageschlüssel dieser Immobilie" in ok(c.get(f"/immobilien/{tid}?reiter=schluessel")).get_data(as_text=True)
    post(c, f"/immobilien/{tid}/umlageschluessel", data={f"s_{hm}": "einheiten", f"g_{hm}": "Beschluss ETV 2027",
                                                         f"u_{aufzug}": "on"})
    post(c, f"/immobilien/{tid}/buchungen", data={"datum": "2026-06-01", "text": "Hausmeister", "art": "ausgabe",
                                                  "ziel": hm, "betrag": "120", "bezahlt": "konto"})
    assert dbcon.execute("SELECT schluessel FROM kosten WHERE immobilie_id = ? AND kostenart_id = ?",
                         (tid, hm)).fetchone() == ("einheiten",)
    seite = ok(c.get(f"/immobilien/{tid}")).get_data(as_text=True)
    assert "Beschluss ETV 2027" in seite and "Regel der Immobilie" not in seite
    seite = ok(c.get(f"/immobilien/{tid}?reiter=buchungen")).get_data(as_text=True)
    assert f'<option value="{hm}"' in seite and f'<option value="{aufzug}"' not in seite  # Aufzug ausgeblendet
    # Regel nachträglich geändert: Prüfliste weist auf die Abweichung hin, „anwenden“ zieht die Position nach
    post(c, f"/immobilien/{tid}/umlageschluessel", data={f"s_{instand}": "flaeche"})
    assert "die Regel der Immobilie sagt Wohnfläche" in ok(c.get(f"/immobilien/{tid}")).get_data(as_text=True)
    post(c, f"/immobilien/{tid}/umlageschluessel", data={f"s_{instand}": "flaeche", f"s_{hm}": "einheiten",
                                                         "anwenden": "on"})
    assert {r[0] for r in dbcon.execute("SELECT schluessel FROM kosten WHERE immobilie_id = ? AND kostenart_id = ?",
                                        (tid, instand))} == {"flaeche"}
    assert "Regel der Immobilie" not in ok(c.get(f"/immobilien/{tid}")).get_data(as_text=True)
    assert dbcon.execute("SELECT COUNT(*) FROM immobilie_kostenart WHERE immobilie_id = ?", (tid,)).fetchone()[0] == 2
    post(c, f"/immobilien/{tid}/loeschen")
    assert dbcon.execute("SELECT COUNT(*) FROM immobilie_kostenart").fetchone()[0] == 0
    c.get("/immobilien/1?jahr=2026")
    # Spalten einklappen: Zustand kommt aus dem Cookie, Mietobjekte zeigen dann ihre Kurzform
    seite = ok(c.get("/immobilien/1")).get_data(as_text=True)
    assert 'class="spalte sidebar "' in seite and 'onclick="spalteUmschalten(this)"' in seite
    c.set_cookie("spalte_immobilien", "zu")
    c.set_cookie("spalte_mietobjekte", "zu")
    seite = ok(c.get("/immobilien/1")).get_data(as_text=True)
    assert 'class="spalte sidebar zu"' in seite and 'class="spalte zu" data-name="mietobjekte"' in seite
    c.delete_cookie("spalte_immobilien")
    c.delete_cookie("spalte_mietobjekte")
    from immobilien import kurzname
    assert [kurzname(x) for x in ("Wohnung 12", "Wohnung 3a", "EG", "10a Dachgeschoss")] == ["12", "3a", "EG", "10a"]
    # Verträge: Kündigungstermin wie in der Vertragsübersicht
    from datetime import date as datum_, timedelta
    import vertraege as vt
    t = vt.termin("2024-01-15", None, 12, 3, None, datum_(2026, 10, 27), 30)
    assert (t["status"], t["ende"], t["kuendigen_bis"]) == ("laeuft", datum_(2028, 1, 15), datum_(2027, 10, 15))
    t = vt.termin("2025-01-01", "2027-01-01", 12, 3, None, datum_(2026, 9, 15), 30)
    assert (t["status"], t["kuendigen_bis"], t["tage"]) == ("bald", datum_(2026, 10, 1), 16)
    assert vt.termin("2025-01-01", "2026-01-01", 1, 1, None, datum_(2026, 10, 27), 30)["flexibel"]
    assert vt.termin(None, "2027-03-01", 0, 3, None, datum_(2026, 10, 27), 30)["status"] == "endet"
    assert vt.termin(None, None, 12, 3, "2026-12-31", datum_(2026, 10, 27), 30)["status"] == "gekuendigt"
    assert vt.termin(None, None, 12, 3, None, datum_(2026, 10, 27), 30)["status"] == "unbekannt"
    # Anlegen: Immobilie (Strom mit naher Kündigungsfrist, Versicherung mit Kostenart) und Mietobjekt
    heute = datum_.today()
    post(c, "/immobilien/1/vertraege", data={"art": "Strom (Allgemeinstrom)", "anbieter": "Muster-Energie", "betrag": "80",
                                             "zahlweise": "monatlich", "beginn": "2024-01-01",
                                             "ablauf": (heute + timedelta(days=40)).isoformat(), "verlaengerung": "12",
                                             "frist": "1", "erinnern": "on", "arbeitspreis": "30", "grundpreis": "10",
                                             "verbrauch": "2000", "seite": "immobilie"})
    post(c, "/immobilien/1/vertraege", data={"art": "Gebäudeversicherung", "anbieter": "Muster AG", "betrag": "1.200",
                                             "zahlweise": "jaehrlich", "beginn": "2020-01-01", "verlaengerung": "12",
                                             "frist": "3", "kostenart_id": ka["Gebäudeversicherung"], "erinnern": "on"})
    r = post(c, "/immobilien/1/vertraege", data={"art": "Internet / TV", "betrag": "30", "zahlweise": "monatlich",
                                                 "wohnung_id": "1", "seite": "wohnung", "verlaengerung": "1", "frist": "1"})
    assert r.headers["Location"].endswith("/wohnungen/1?reiter=vertraege")
    seite = ok(c.get("/immobilien/1?reiter=vertraege")).get_data(as_text=True)
    assert "Muster-Energie" in seite and "bald kündigen" in seite and "<strong>Internet / TV</strong>" in seite  # auch Wohnung
    assert "<strong>3</strong>" in seite and "2.520,00 €" in seite  # 12×80 + 1.200 + 12×30
    assert "Tarif: 720,00 €/Jahr" in seite  # 2000 kWh × 30 ct + 12 × 10 €
    seite = ok(c.get("/wohnungen/1?reiter=vertraege")).get_data(as_text=True)
    assert "<strong>Internet / TV</strong>" in seite and "Muster-Energie" not in seite and "Mietverträge" in seite
    # Bearbeiten und Dauerauftrag aus dem Vertrag (nur Immobilie, mit Kostenart)
    vid = dbcon.execute("SELECT id FROM vertrag WHERE art = 'Gebäudeversicherung'").fetchone()[0]
    assert 'name="art" value="Gebäudeversicherung"' in ok(c.get(f"/immobilien/1?reiter=vertraege&vertrag={vid}")).get_data(as_text=True)
    post(c, f"/vertraege/{vid}", data={"art": "Gebäudeversicherung", "anbieter": "Muster AG", "betrag": "1.250",
                                       "zahlweise": "jaehrlich", "beginn": "2020-01-01", "verlaengerung": "12", "frist": "3",
                                       "kostenart_id": ka["Gebäudeversicherung"], "erinnern": "on"})
    r = post(c, f"/vertraege/{vid}/dauerauftrag")
    assert r.headers["Location"].endswith("reiter=buchungen#dauerauftraege")
    assert dbcon.execute("SELECT betrag, rhythmus, von, bis FROM dauerauftrag WHERE text = 'Gebäudeversicherung · Muster AG'"
                         ).fetchone() == (1250.0, "jahr", "2026-01-01", "2026-12-31")
    dbcon.execute("DELETE FROM dauerauftrag WHERE text = 'Gebäudeversicherung · Muster AG'")
    dbcon.commit()
    # Mietvertragsangaben am Mietverhältnis
    post(c, "/mieter/1", data={"von": "2025-04-01", "vorauszahlung_monat": "150", "kaltmiete": "520", "mietart": "index",
                               "anpassung_am": (heute + timedelta(days=20)).isoformat(),
                               "befristet_bis": (heute + timedelta(days=400)).isoformat()})
    seite = ok(c.get("/wohnungen/1?reiter=vertraege")).get_data(as_text=True)
    assert "520,00 €" in seite and "Indexmiete ab" in seite and "noch 20 Tage" in seite
    # Erinnerung: eine Sammel-Mail an Benutzer mit Haken, je Termin nur einmal
    post(c, "/profil", data={"vorname": "Max", "name": "Vermieter", "email": "max@example.org"})
    gesendet = []
    import mail as mailmodul
    alt = mailmodul.konfiguriert, mailmodul.senden
    mailmodul.konfiguriert = lambda: True
    mailmodul.senden = lambda an, betreff, text, html=None, bilder=None: gesendet.append((an, betreff, text, html, bilder))
    try:
        seite = ok(c.get("/einstellungen/admin/erinnerungen")).get_data(as_text=True)
        assert "Muster-Energie" in seite and "Mietanpassung ab" in seite
        assert 'name="empfaenger" value="1" checked' in seite  # der Admin aus der Einrichtung ist vorausgewählt
        post(c, "/einstellungen/admin/erinnerungen", data={"aktion": "jetzt"})
        assert len(gesendet) == 1 and gesendet[0][0] == "max@example.org"
        assert "Kündigungsfrist" in gesendet[0][2] and "Muster-Energie" in gesendet[0][2] and "Mietanpassung" in gesendet[0][2]
        _, betreff, text, mail_html, bilder = gesendet[0]
        assert betreff == "Erinnerung: 2 Termine bei Verträgen" and text.startswith("Hallo Max,")
        assert 'src="cid:logo"' in mail_html and "Kündigen bis" in mail_html and "Im Immobilienverwalter ansehen" not in mail_html
        assert bilder["logo"][1] == "png" and bilder["logo"][0][:4] == b"\x89PNG"  # eingebautes Standard-Logo
        with app.app_context():
            assert vt.pruefen() == 0  # schon gemeldet
        assert len(gesendet) == 1  # nichts Neues: keine leere Mail
        post(c, "/einstellungen/admin/erinnerungen", data={"aktion": "beispiel"})  # Vorschau, markiert nichts
        assert len(gesendet) == 2 and gesendet[1][1].startswith("[Beispiel] Erinnerung:") and "Muster-Energie" in gesendet[1][2]
        post(c, "/einstellungen/admin/erinnerungen", data={"vorlauf": "30", "empfaenger": "1"})  # ausgeschaltet
    finally:
        mailmodul.konfiguriert, mailmodul.senden = alt
    vid = dbcon.execute("SELECT id FROM vertrag WHERE art = 'Strom (Allgemeinstrom)'").fetchone()[0]
    post(c, f"/vertraege/{vid}/loeschen", data={"seite": "immobilie"})
    assert "Muster-Energie" not in ok(c.get("/immobilien/1?reiter=vertraege")).get_data(as_text=True)

    # Reiter: jeder Bereich hat eine eigene Adresse, der Jahr-Umschalter behält den Reiter
    assert "/immobilien/1?jahr=2025&amp;reiter=ruecklage" in html
    for reiter, text in (("buchungen", "Belege und Buchungen"), ("zaehler", "Hauptzähler"), ("dokumente", "Ablage"),
                         ("stammdaten", "Dokumentenordner"), ("unbekannt", "Gebäudekosten")):
        assert text in ok(c.get(f"/immobilien/1?reiter={reiter}")).get_data(as_text=True), reiter
    for reiter, text in (("mieter", "Neues Mietverhältnis"), ("zaehler", "Wasserverbrauch"),
                         ("dokumente", "Dokumente hochladen"), ("stammdaten", "Aus der Immobilie lösen")):
        assert text in ok(c.get(f"/wohnungen/1?reiter={reiter}")).get_data(as_text=True), reiter

    # Zählertausch
    post(c, "/zaehler/2/tausch", data={"datum": "2026-06-30", "endstand": "30", "nummer": "W-2b",
                                         "anfangsstand": "0"})

    # Hauptzähler: zwei Flurstromzähler werden addiert, Wasser-Hauptuhr mit Wohnungsuhren verglichen
    for nr, (start, ende) in enumerate([(1000, 1400), (500, 650)], start=1):
        post(c, "/zaehler", data={"immobilie_id": "1", "art": "strom", "bezeichnung": f"Flurstrom Haus {nr}",
                                  "eingebaut": "2024-12-31", "stand": str(start)})
    post(c, "/zaehler", data={"immobilie_id": "1", "art": "wasser", "eingebaut": "2024-12-31", "stand": "1000"})
    for zid, stand in ((4, "1400"), (5, "650"), (6, "1060")):
        post(c, f"/zaehler/{zid}/staende", data={"datum": "2025-12-31", "stand": stand, "notiz": "Jahresablesung"})
    post(c, "/zaehler/6/bearbeiten", data={"bezeichnung": "Hauptwasser Keller", "nummer": "HW-1"})
    html = ok(c.get("/immobilien/1?jahr=2025&reiter=zaehler")).get_data(as_text=True)
    assert "Flurstrom Haus 2" in html and "Hauptwasser Keller" in html and "Jahresablesung" in html
    assert "550,0 kWh" in html                                    # 400 + 150
    assert "Wohnungsuhren 50,0 m³ · Differenz 10,0 m³" in html
    # Zähler mit Vertrag verbinden, Kommentar am Zähler, Kundennummer am Vertrag
    post(c, "/immobilien/1/vertraege", data={"art": "Strom (Allgemeinstrom)", "anbieter": "Stadtwerke Muster",
                                             "kundennummer": "K-123", "betrag": "50", "zahlweise": "monatlich"})
    strom = dbcon.execute("SELECT id FROM vertrag WHERE anbieter = 'Stadtwerke Muster'").fetchone()[0]
    internet = dbcon.execute("SELECT id FROM vertrag WHERE art = 'Internet / TV'").fetchone()[0]
    seite = ok(c.get("/immobilien/1?reiter=zaehler&zaehler=4")).get_data(as_text=True)
    assert f'<option value="{strom}"' in seite and f'<option value="{internet}"' not in seite  # nur Verträge der Immobilie
    for zid in (4, 5):
        post(c, f"/zaehler/{zid}/bearbeiten", data={"bezeichnung": f"Flurstrom Haus {zid - 3}", "nummer": f"F-{zid}",
                                                     "vertrag_id": str(strom), "notiz": "Keller links"})
    with c.session_transaction() as sitzung:
        sitzung.pop("_flashes", None)
    ok(c.post("/zaehler/4/bearbeiten", data={"bezeichnung": "x", "vertrag_id": str(internet)}), 302)
    with c.session_transaction() as sitzung:
        assert "gehört nicht zu diesem Zähler" in " ".join(m for _, m in sitzung.pop("_flashes", []))
    assert dbcon.execute("SELECT vertrag_id FROM zaehler WHERE id = 4").fetchone()[0] == strom
    seite = ok(c.get("/immobilien/1?jahr=2025&reiter=zaehler")).get_data(as_text=True)
    assert "Vertrag: Strom (Allgemeinstrom) · Stadtwerke Muster" in seite and "Keller links" in seite
    seite = ok(c.get("/immobilien/1?reiter=vertraege")).get_data(as_text=True)
    assert "Kd.-Nr. K-123" in seite and "Zähler Flurstrom Haus 1 (Nr. F-4)" in seite and "Zähler Flurstrom Haus 2" in seite
    assert "Verbrauch 2025 laut Zähler: 550 kWh" in seite  # beide Flurstromzähler zusammen
    # Zähler auch direkt im Vertragsformular an- und abhaken
    seite = ok(c.get(f"/immobilien/1?reiter=vertraege&vertrag={strom}")).get_data(as_text=True)
    assert 'name="zaehler" value="4" checked' in seite and 'name="zaehler" value="6" >' in seite
    vertragsdaten = {"art": "Strom (Allgemeinstrom)", "anbieter": "Stadtwerke Muster", "betrag": "50",
                     "zahlweise": "monatlich", "zaehler_auswahl": "1"}
    post(c, f"/vertraege/{strom}", data={**vertragsdaten, "zaehler": ["4"]})
    assert [r[0] for r in dbcon.execute("SELECT id FROM zaehler WHERE vertrag_id = ?", (strom,))] == [4]
    post(c, f"/vertraege/{strom}", data={**vertragsdaten, "zaehler": ["4", "5"]})
    assert [r[0] for r in dbcon.execute("SELECT id FROM zaehler WHERE vertrag_id = ? ORDER BY id", (strom,))] == [4, 5]
    seite = ok(c.get("/wohnungen/1?reiter=vertraege")).get_data(as_text=True)
    assert 'name="zaehler" value="4"' not in seite  # Mietobjekt bietet nur seine eigenen Zähler an
    # Unterlagen am Vertrag: hochladen (landen in der Ablage) und vorhandene Ablage-Dokumente verbinden
    post(c, "/immobilien/1/ablage", data={"kategorie": "sonstiges", "titel": "Preisblatt 2025", "dateien": pdf_datei()},
         content_type="multipart/form-data")
    preisblatt = dbcon.execute("SELECT id FROM ablage WHERE titel = 'Preisblatt 2025'").fetchone()[0]
    seite = ok(c.get(f"/immobilien/1?reiter=vertraege&vertrag={strom}")).get_data(as_text=True)
    assert 'enctype="multipart/form-data"' in seite and f'name="unterlagen" value="{preisblatt}"' in seite
    post(c, f"/vertraege/{strom}", data={**vertragsdaten, "zaehler": ["4", "5"], "unterlagen_auswahl": "1",
                                         "unterlagen": [str(preisblatt)], "unterlagen_neu": pdf_datei("Stromvertrag.pdf")},
         content_type="multipart/form-data")
    assert sorted(r[0] for r in dbcon.execute("SELECT titel FROM ablage WHERE vertrag_id = ?", (strom,))) == \
        ["Preisblatt 2025", "Stromvertrag"]
    assert dbcon.execute("SELECT kategorie, notiz FROM ablage WHERE titel = 'Stromvertrag'").fetchone() == \
        ("vertraege", "Vertrag: Strom (Allgemeinstrom)")
    seite = ok(c.get("/immobilien/1?reiter=vertraege")).get_data(as_text=True)
    assert "Stromvertrag</a>" in seite and "Preisblatt 2025</a>" in seite
    post(c, f"/vertraege/{strom}", data={**vertragsdaten, "zaehler": ["4", "5"], "unterlagen_auswahl": "1",
                                         "unterlagen": []})  # Preisblatt abwählen: bleibt in der Ablage
    assert dbcon.execute("SELECT vertrag_id FROM ablage WHERE id = ?", (preisblatt,)).fetchone()[0] is None
    post(c, f"/vertraege/{strom}/loeschen", data={"seite": "immobilie"})
    assert dbcon.execute("SELECT COUNT(*) FROM zaehler WHERE vertrag_id IS NOT NULL").fetchone()[0] == 0
    assert dbcon.execute("SELECT vertrag_id FROM ablage WHERE titel = 'Stromvertrag'").fetchone() == (None,)  # bleibt
    for (aid,) in dbcon.execute("SELECT id FROM ablage WHERE titel IN ('Stromvertrag', 'Preisblatt 2025')").fetchall():
        post(c, f"/ablage/{aid}/loeschen")  # spätere Tests erwarten eine leere Ablage
    html = ok(c.get("/immobilien/1?jahr=2025&reiter=zaehler")).get_data(as_text=True)
    # Zählertabelle wie die Rücklage: Stand 01.01./31.12., Verbrauch je Zähler; Ablesung über die Auswahl eintragen
    assert "Stand 01.01.2025" in html and "1.000,00 kWh" in html and "<strong>400,0 kWh</strong>" in html
    r = post(c, "/zaehlerstaende", data={"zaehler_id": "4", "datum": "2026-06-30", "stand": "1.500",
                                         "next": "/immobilien/1?reiter=zaehler"})
    assert r.headers["Location"] == "/immobilien/1?reiter=zaehler&jahr=2026"  # Ablesung aus 2026 → Ansicht springt mit
    html = ok(c.get(r.headers["Location"])).get_data(as_text=True)
    assert "1.400,00 kWh" in html and "1.500,00 kWh" in html and "100,0 kWh<br>" in html and "bisher, bis 30.06.26" in html
    sid = dbcon.execute("SELECT id FROM zaehlerstand WHERE stand = 1500").fetchone()[0]
    post(c, f"/zaehlerstaende/{sid}", data={"datum": "2026-06-30", "stand": "1.550", "notiz": "korrigiert",
                                            "next": "/immobilien/1?reiter=zaehler"})
    html = ok(c.get("/immobilien/1?reiter=zaehler")).get_data(as_text=True)
    assert "korrigiert" in html and "150,0 kWh<br>" in html
    post(c, f"/zaehlerstaende/{sid}/loeschen")
    c.get("/immobilien/1?jahr=2025")  # 60 Haupt − (30 EG + 20 OG)

    # Logo, Kostenart
    post(c, "/einstellungen/admin/logo", data={"logo_typ": "text", "logo_text": "Vermietung",
                                                 "logo": bild_datei("logo.png", "PNG", "RGBA", (900, 300))},
              content_type="multipart/form-data")
    ok(c.get("/logo"))
    # Fußzeile im Brief ist abschaltbar (Haken fehlte beim Speichern)
    assert "Erstellt mit" not in ok(c.get("/wohnungen/1/export/brief?partei=1")).get_data(as_text=True)
    post(c, "/einstellungen/admin/logo", data={"logo_typ": "text", "logo_text": "Vermietung", "brief_anschrift_hoch": "15"})
    assert ".anschrift { position: absolute; top: 30mm;" in ok(c.get("/wohnungen/1/export/brief?partei=1")).get_data(as_text=True)
    post(c, "/einstellungen/admin/kostenarten", data={"name": "Dachrinnenreinigung", "betrkv_nr": "17",
                                                        "schluessel": "mea", "umlagefaehig": "on"})

    # Zweiter Vermieter (Vermieter +) als Eigentümer der OG-Wohnung
    post(c, "/einstellungen/admin/vermieter/neu", data={"benutzername": "anna", "rolle": "vermieter_plus",
                                                          "passwort": "passwort1", "passwort2": "passwort1",
                                                          "vorname": "Anna", "name": "Eigner",
                                                          "telefon": "01234 567 89", "mobil": "0170 1234567"})
    post(c, "/einstellungen/admin/wohnungen/2", data={"bezeichnung": "OG", "wohnflaeche": "50", "mea": "60",
                                                        "mea_basis": "1000", "immobilie_id": "1",
                                                        "eigentuemer_id": "2"})
    # Mieter rechnet der Eigentümer selbst ab: nur Eigentümer-Abrechnung, kein „Leerstand“
    post(c, "/einstellungen/admin/wohnungen/2", data={"bezeichnung": "OG", "wohnflaeche": "50", "mea": "60",
                                                        "mea_basis": "1000", "immobilie_id": "1",
                                                        "eigentuemer_id": "2", "mieter_extern": "on"})
    html = ok(c.get("/wohnungen/2")).get_data(as_text=True)
    assert "rechnet der Eigentümer" in html and "Leerstand" not in html and "Eigentümer-Abrechnung (WEG)" in html
    html = ok(c.get("/immobilien/1")).get_data(as_text=True)
    assert "rechnet Eigentümer ab" in html and "OG: Das Hausgeld des Eigentümers" in html
    # Hausgeld aller Wohnungen auf einmal: dieselben Werte wie beim einzelnen Mietobjekt
    assert "Hausgeld der Eigentümer" in html
    post(c, "/immobilien/1/hausgeld", data={"hg_1": "500", "hg_2": "300,50"})
    assert 'value="300,50"' in ok(c.get("/wohnungen/2")).get_data(as_text=True)
    assert "Das Hausgeld des Eigentümers" not in ok(c.get("/immobilien/1")).get_data(as_text=True)

    # Ablage: jahresunabhängig, nicht in den Anlagen des Briefs, „nur Admin“ für Eigentümer unsichtbar
    post(c, "/immobilien/1/ablage", data={"kategorie": "protokolle", "titel": "Protokoll Versammlung", "jahr": "2024",
                                         "dateien": pdf_datei("protokoll.pdf")}, content_type="multipart/form-data")
    post(c, "/immobilien/1/ablage", data={"kategorie": "angebote", "titel": "Angebot Dach", "intern": "on",
                                         "dateien": pdf_datei("angebot.pdf")}, content_type="multipart/form-data")
    html = ok(c.get("/immobilien/1?reiter=dokumente")).get_data(as_text=True)
    assert "Protokoll Versammlung" in html and "Angebot Dach" in html and "nur Admin" in html
    assert "Protokoll Versammlung" not in ok(c.get("/wohnungen/1/export?partei=1")).get_data(as_text=True)
    ok(c.get("/ablage/1"))

    # Dokumentenübersicht: Belege und Ablage zusammen, Filter, Suche, Kommentar bearbeiten
    html = ok(c.get("/dokumente")).get_data(as_text=True)
    assert "Protokoll Versammlung" in html and "Grundsteuerbescheid" in html
    html = ok(c.get("/dokumente?art=ablage")).get_data(as_text=True)
    assert "Protokoll Versammlung" in html and "Grundsteuerbescheid" not in html
    assert "Angebot Dach" not in ok(c.get("/dokumente?q=protokoll")).get_data(as_text=True)
    post(c, "/dokumente/beleg/1/bearbeiten", data={"titel": "Grundsteuerbescheid 2025", "notiz": "Stadt Musterstadt"})
    assert "Stadt Musterstadt" in ok(c.get("/dokumente?q=musterstadt")).get_data(as_text=True)
    ok(c.get("/dokumente?bearbeiten=ablage-1&sort=titel&richtung=auf"))
    # neue Ablage-Kategorie direkt beim Hochladen; gleichnamige wird wiederverwendet; volle Kategorie nicht löschbar
    for _ in range(2):
        post(c, "/immobilien/1/ablage", data={"kategorie": "neu", "neue_kategorie": "Energieausweis",
                                             "dateien": pdf_datei("ea.pdf")}, content_type="multipart/form-data")
    seite = ok(c.get("/einstellungen/admin/ablage")).get_data(as_text=True)
    assert seite.count('value="Energieausweis"') == 1 and "Energieausweis" in ok(c.get("/immobilien/1?reiter=dokumente")).get_data(as_text=True)
    ok(c.post("/einstellungen/admin/ablage/protokolle/loeschen"), 302)
    assert "Protokolle" in ok(c.get("/einstellungen/admin/ablage")).get_data(as_text=True)
    post(c, "/einstellungen/admin/ablage/sonstiges/loeschen")
    assert 'value="Sonstiges"' not in ok(c.get("/einstellungen/admin/ablage")).get_data(as_text=True)

    # Eigentümer ohne Zugang direkt beim Mietobjekt anlegen (nur der Name ist Pflicht)
    post(c, "/einstellungen/admin/wohnungen/neu", data={"bezeichnung": "Garage", "wohnflaeche": "15", "immobilie_id": "",
                                                          "eigentuemer_id": "neu", "neu_name": "Ohnezugang",
                                                          "neu_mobil": "0151 7654321"})
    liste = ok(c.get("/einstellungen/vermieter")).get_data(as_text=True)
    assert "Ohnezugang" in liste and "ohne Zugang" in liste
    assert 'href="tel:0123456789">01234 567 89</a>' in liste and 'href="tel:01701234567"' in liste and "0151 7654321" in liste
    anna = dbcon.execute("SELECT id FROM benutzer WHERE benutzername = 'anna'").fetchone()[0]
    assert 'value="0170 1234567"' in ok(c.get(f"/einstellungen/admin/vermieter/{anna}")).get_data(as_text=True)
    # weiteres Mietobjekt beim Eigentümer zuordnen
    post(c, "/einstellungen/admin/wohnungen/neu", data={"bezeichnung": "Keller", "wohnflaeche": "5", "immobilie_id": ""})
    post(c, "/einstellungen/admin/vermieter/3/mietobjekte", data={"wid": "4"})
    seite = ok(c.get("/einstellungen/admin/vermieter/3")).get_data(as_text=True)
    assert "Garage" in seite and "Keller" in seite.split("Weiteres Mietobjekt")[0]
    # Anmeldung ist für Eigentümer ohne Zugang unmöglich (Platzhalter-Benutzername, leeres Passwort)
    import db as datenbank
    platzhalter = datenbank.verbinden().execute("SELECT benutzername FROM benutzer WHERE id = 3").fetchone()[0]
    assert platzhalter.startswith("~")
    x = app.test_client()
    ok(x.post("/login", data={"benutzername": platzhalter, "passwort": ""}))
    assert x.get("/").status_code == 302
    # Zugang nachträglich einrichten
    post(c, "/einstellungen/admin/vermieter/3", data={"rolle": "vermieter", "benutzername": "otto", "name": "Ohnezugang",
                                                      "passwort": "passwort9", "passwort2": "passwort9"})
    post(x, "/login", data={"benutzername": "otto", "passwort": "passwort9"})
    ok(x.get("/"))

    # Zwei-Faktor-Anmeldung: einrichten, Anmeldung mit Code, Notfall-Code, Zurücksetzen durch den Admin
    import time
    import zweifaktor
    ok(x.get("/profil/passwort"))
    post(x, "/profil/zweifaktor/start")
    with x.session_transaction() as sitzung:
        geheimnis = sitzung["totp_neu"]
    assert "<svg" in ok(x.get("/profil/passwort")).get_data(as_text=True)
    jetzt = int(time.time() // 30)
    html = ok(x.post("/profil/zweifaktor/bestaetigen", data={"code": zweifaktor._hotp(geheimnis, jetzt)})).get_data(as_text=True)
    notfall = re.findall(r"<code>([0-9a-f]{4}-[0-9a-f]{4})</code>", html)
    assert len(notfall) == 8
    post(x, "/logout")
    assert x.post("/login", data={"benutzername": "otto", "passwort": "passwort9"}).headers["Location"].endswith("/login/code")
    assert x.get("/").status_code == 302                       # ohne Code nicht angemeldet
    ok(x.post("/login/code", data={"code": "000000"}))
    post(x, "/login/code", data={"code": zweifaktor._hotp(geheimnis, jetzt + 1)})
    ok(x.get("/"))
    post(x, "/logout")
    post(x, "/login", data={"benutzername": "otto", "passwort": "passwort9"})
    post(x, "/login/code", data={"code": notfall[0]})
    ok(x.get("/"))
    post(x, "/logout")
    post(x, "/login", data={"benutzername": "otto", "passwort": "passwort9"})
    ok(x.post("/login/code", data={"code": notfall[0]}))        # Notfall-Code gilt nur einmal
    post(c, "/einstellungen/admin/vermieter/3/zweifaktor-zuruecksetzen")
    x = app.test_client()
    post(x, "/login", data={"benutzername": "otto", "passwort": "passwort9"})
    ok(x.get("/"))
    post(c, "/logout")

    a = app.test_client()
    post(a, "/login", data={"benutzername": "anna", "passwort": "passwort1"})
    seite = ok(a.get("/immobilien/1")).get_data(as_text=True)
    assert ">OG<" in seite.replace("<span>", ">").replace("</span>", "<") and "/wohnungen/1\"" not in seite
    ok(a.get("/wohnungen/2"))
    ok(a.get("/wohnungen/1"), 403)
    ok(a.get("/einstellungen/admin/kostenarten"), 403)
    ok(a.get("/einstellungen/vermieter"))
    ok(a.get("/dokumente/2"), 403)  # Mieterordner einer fremden Wohnung
    ok(a.get("/dokumente/1"))       # gemeinsamer Mieterbeleg
    post(a, "/wohnungen/2/mieter", data={"name": "Neu", "von": "2026-01-01"})
    ok(a.post("/immobilien/1/buchungen", data={"datum": "2025-01-01", "text": "x", "art": "ausgabe", "ziel": "1",
                                                "betrag": "1", "bezahlt": "konto"}), 403)
    ok(a.post("/buchungen/1/loeschen"), 403)
    ok(a.post("/immobilien/1/vertraege", data={"art": "Gas"}), 403)  # Verträge der Immobilie nur Admin
    post(a, "/immobilien/1/vertraege", data={"art": "Strom Wohnung", "wohnung_id": "2", "seite": "wohnung"})
    ok(a.post("/immobilien/1/vertraege", data={"art": "Fremd", "wohnung_id": "1"}), 403)
    seite = ok(a.get("/immobilien/1?reiter=vertraege")).get_data(as_text=True)
    assert "<strong>Strom Wohnung</strong>" in seite and "<strong>Internet / TV</strong>" not in seite
    assert "<strong>Gebäudeversicherung</strong>" in seite
    # Hausgeld fremder Wohnungen bleibt für Eigentümer unsichtbar, eigenes ist sichtbar
    dbcon.execute("INSERT INTO buchung (immobilie_id, jahr, datum, text, art, betrag, hausgeld_eigentuemer_id, "
                  "hausgeld_wohnung_id) VALUES (1, 2026, '2026-03-01', 'HG fremd', 'einnahme', 99, 1, 1), "
                  "(1, 2026, '2026-03-01', 'HG eigen', 'einnahme', 77, 2, 2)")
    dbcon.commit()
    a.get("/immobilien/1?jahr=2026")
    seite = ok(a.get("/immobilien/1?reiter=buchungen")).get_data(as_text=True)
    assert "HG eigen" in seite and "HG fremd" not in seite
    dbcon.execute("DELETE FROM buchung WHERE text IN ('HG fremd', 'HG eigen')")
    dbcon.commit()
    seite = ok(a.get("/immobilien/1?reiter=dokumente")).get_data(as_text=True)
    assert "Protokoll Versammlung" in seite and "Angebot Dach" not in seite
    ok(a.get("/ablage/1"))
    ok(a.get("/ablage/2"), 403)
    html = ok(a.get("/dokumente")).get_data(as_text=True)
    assert "Protokoll Versammlung" in html and "Angebot Dach" not in html
    ok(a.post("/immobilien/1/ablage", data={"kategorie": "sonstiges", "dateien": pdf_datei()},
              content_type="multipart/form-data"), 403)
