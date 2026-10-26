"""Ende-zu-Ende-Test über den Flask-Testclient: Einrichtung bis PDF-Export."""
import io
import os
import re
import sys
import tempfile

TMP = tempfile.mkdtemp()
os.environ["NK_DATA"] = os.path.join(TMP, "data")
os.environ["NK_DOKUMENTE"] = os.path.join(TMP, "dokumente")
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
    assert "geändert" not in ok(c.get("/immobilien/1?reiter=ruecklage")).get_data(as_text=True)
    # Reiter: jeder Bereich hat eine eigene Adresse, der Jahr-Umschalter behält den Reiter
    assert "/immobilien/1?jahr=2025&amp;reiter=ruecklage" in html
    for reiter, text in (("buchungen", "Belege und Buchungen"), ("zaehler", "Hauptzähler"), ("dokumente", "Ablage"),
                         ("stammdaten", "Dokumentenordner"), ("unbekannt", "Gebäudekosten")):
        assert text in ok(c.get(f"/immobilien/1?reiter={reiter}")).get_data(as_text=True), reiter
    for reiter, text in (("mieter", "Neues Mietverhältnis"), ("zaehler", "Zähler &amp; Ablesungen"),
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
    assert "Wohnungsuhren zusammen 50,0 m³, Differenz 10,0 m³" in html  # 60 Haupt − (30 EG + 20 OG)

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
                                                          "vorname": "Anna", "name": "Eigner"})
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
                                                          "eigentuemer_id": "neu", "neu_name": "Ohnezugang"})
    liste = ok(c.get("/einstellungen/vermieter")).get_data(as_text=True)
    assert "Ohnezugang" in liste and "ohne Zugang" in liste
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
    seite = ok(a.get("/immobilien/1?reiter=dokumente")).get_data(as_text=True)
    assert "Protokoll Versammlung" in seite and "Angebot Dach" not in seite
    ok(a.get("/ablage/1"))
    ok(a.get("/ablage/2"), 403)
    html = ok(a.get("/dokumente")).get_data(as_text=True)
    assert "Protokoll Versammlung" in html and "Angebot Dach" not in html
    ok(a.post("/immobilien/1/ablage", data={"kategorie": "sonstiges", "dateien": pdf_datei()},
              content_type="multipart/form-data"), 403)
