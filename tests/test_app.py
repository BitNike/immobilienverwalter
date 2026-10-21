"""Ende-zu-Ende-Test über den Flask-Testclient: Einrichtung bis PDF-Export."""
import io
import os
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
    post(c, "/immobilien/1/kosten", data={"kostenart_id": ka["Gebäudeversicherung"], "betrag": "1.000,00",
                                            "schluessel": "mea"})
    post(c, "/immobilien/1/kosten", data={"kostenart_id": 10, "betrag": "500", "schluessel": "wasser"})
    post(c, "/wohnungen/1/kosten", data={"kostenart_id": ka["Heizkosten"], "betrag": "712,37", "mv_id": "1"})
    post(c, "/wohnungen/1/kosten", data={"kostenart_id": ka["Grundsteuer"], "betrag": "103,54"})

    # Kosten bearbeiten: erst nach Klick auf den Stift sind die Felder offen
    assert 'form="k1"' not in ok(c.get("/immobilien/1")).get_data(as_text=True)
    assert 'name="notiz" form="k1"' in ok(c.get("/immobilien/1?bearbeiten=1")).get_data(as_text=True)
    html = ok(c.get("/wohnungen/1?bearbeiten=3")).get_data(as_text=True)
    assert 'name="mv_id" form="k3"' in html
    assert "/immobilien/1?bearbeiten=1#kosten" in html  # Gebäudekosten: Stift führt zur Immobilie
    post(c, "/kosten/1", data={"kostenart_id": ka["Gebäudeversicherung"], "betrag": "1.000,00", "schluessel": "mea",
                               "notiz": "Police 2025\nZweite Zeile"})
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
    from export import girocode
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

    # Standard-Umlageschlüssel einer Immobilie wird beim Erfassen neuer Gebäudekosten vorausgewählt
    post(c, "/immobilien/neu", data={"name": "Haus Test", "schluessel": "einheiten"})
    html = ok(c.get("/immobilien/2")).get_data(as_text=True)
    assert 'Umlageschlüssel<select name="schluessel" ><option value="mea" >' in html
    assert '<option value="einheiten" selected>' in html
    post(c, "/immobilien/2/loeschen")

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
                "/einstellungen/admin/kostenarten", "/einstellungen/admin/logo", "/einstellungen/admin/smtp",
                "/profil", "/profil/immobilien", "/profil/passwort", "/immobilien/neu", "/benutzer/1/foto",
                "/dokumente/1", "/dokumente/2"]:
        ok(c.get(url))

    # PDF mit beiden Anlagen
    r = post(c, "/wohnungen/1/export/pdf", 200, data={"partei": "1", "dokumente": ["1", "2"], "aktion": "speichern"})
    assert r.mimetype == "application/pdf" and "attachment" in r.headers["Content-Disposition"]
    assert len(PdfReader(io.BytesIO(r.data)).pages) == 4  # Brief (2 Seiten) + PDF-Beleg + JPG-Beleg
    r = post(c, "/wohnungen/1/export/pdf", 200, data={"partei": "eigentuemer", "aktion": "vorschau"})
    assert "inline" in r.headers.get("Content-Disposition", "inline")

    # Vorjahr übernehmen in 2026
    c.get("/immobilien/1?jahr=2026")
    post(c, "/immobilien/1/vorjahr")
    assert "Gebäudeversicherung" in ok(c.get("/immobilien/1")).get_data(as_text=True)

    # Zählertausch
    post(c, "/zaehler/2/tausch", data={"datum": "2026-06-30", "endstand": "30", "nummer": "W-2b",
                                         "anfangsstand": "0"})

    # Logo, Kostenart
    post(c, "/einstellungen/admin/logo", data={"logo_typ": "text", "logo_text": "Vermietung",
                                                 "logo": bild_datei("logo.png", "PNG", "RGBA", (900, 300))},
              content_type="multipart/form-data")
    ok(c.get("/logo"))
    post(c, "/einstellungen/admin/kostenarten", data={"name": "Dachrinnenreinigung", "betrkv_nr": "17",
                                                        "schluessel": "mea", "umlagefaehig": "on"})

    # Zweiter Vermieter (Vermieter +) als Eigentümer der OG-Wohnung
    post(c, "/einstellungen/admin/vermieter/neu", data={"benutzername": "anna", "rolle": "vermieter_plus",
                                                          "passwort": "passwort1", "passwort2": "passwort1",
                                                          "vorname": "Anna", "name": "Eigner"})
    post(c, "/einstellungen/admin/wohnungen/2", data={"bezeichnung": "OG", "wohnflaeche": "50", "mea": "60",
                                                        "mea_basis": "1000", "immobilie_id": "1",
                                                        "eigentuemer_id": "2"})
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
    ok(a.post("/immobilien/1/kosten", data={"kostenart_id": "1", "betrag": "1"}), 403)
