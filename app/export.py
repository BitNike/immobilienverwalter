"""Export: Abrechnung als PDF mit Deckblatt und ausgewählten Belegen."""
import io
import os
from datetime import date

from flask import abort, g, render_template, request, send_file

import dateien
from calc import de_num, parse_num, rund
from core import NAME, URL, app, einstellung, ist_admin, jahr, one, person_name, row, rows, wohnung_laden
from immobilien import adresse, berechnung, dokumente_sichtbar, konten, mv_name, pruefungen, ruecklage

HINWEIS_NACHZAHLUNG = ("Bitte überweisen Sie die Nachzahlung innerhalb von 30 Tagen nach Erhalt dieser Abrechnung "
                       "auf folgendes Konto:")


def _zeile(person, o):
    a1, a2 = adresse(o)
    return ", ".join(x for x in (person, a1, a2) if x)


SEPA_ZEICHEN = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/-?:().,'+ ")
UMLAUTE = {"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"}


def sepa_text(s):
    """Auf den SEPA-Grundzeichensatz bringen (Umlaute ausschreiben), den alle Banken sicher verarbeiten."""
    s = "".join(UMLAUTE.get(z, z) for z in s or "")
    return " ".join("".join(z if z in SEPA_ZEICHEN else " " for z in s).split())


def girocode(name, iban, betrag, zweck):
    """EPC-QR-Code („GiroCode“) als SVG: Banking-Apps übernehmen daraus Empfänger, IBAN, Betrag und Zweck."""
    import segno
    iban = "".join(iban.split()).upper()
    if not (name and iban and betrag > 0):
        return None
    daten = "\n".join(["BCD", "002", "1", "SCT", "", sepa_text(name)[:70], iban, f"EUR{betrag:.2f}", "", "",
                       sepa_text(zweck)[:140]])
    return segno.make(daten, error="m", micro=False).svg_inline(scale=1, border=0, omitsize=True)


def brief_daten(wid, partei):
    w = wohnung_laden(wid)
    immo = row("SELECT * FROM immobilie WHERE id = ?", (w["immobilie_id"],))
    j = jahr()
    erg = berechnung(immo, j)
    r = erg["wohnungen"][wid]
    eig = one("SELECT * FROM benutzer WHERE id = ?", (w["eigentuemer_id"],))
    objekt = list(adresse(immo))
    if len(erg["wohnungen"]) > 1:
        objekt.append(w["bezeichnung"])
    d = {
        "jahr": j, "erstellt": date.today(), "immo": immo, "w": w, "objekt": [x for x in objekt if x],
        "abrechnung_von": date(j, 1, 1), "abrechnung_bis": date(j, 12, 31),
        "iban": immo["iban"], "kontoinhaber": immo["kontoinhaber"], "bank": immo["bank"],
        "umlageschluessel": ", ".join(x for x in (
            f"Wohnfläche {de_num(w['wohnflaeche'])} m²"
            + (f" ({de_num(w['mea'])}/{de_num(w['mea_basis'], 0)} MEA)" if w["mea"] else ""),
            w["umlageschluessel"]) if x),
        "hinweis_nachzahlung": HINWEIS_NACHZAHLUNG,
    }
    if partei == "eigentuemer":
        d.update(
            partei="eigentuemer", partei_name="Eigentümer",
            empfaenger=[person_name(eig), *adresse(eig)] if eig else ["Eigentümer nicht hinterlegt"],
            absender=immo["absender"] or _zeile(person_name(g.user), g.user),
            nutzung_von=d["abrechnung_von"], nutzung_bis=d["abrechnung_bis"], monate=erg["monate"], prozent=100.0,
            posten=r["posten"], summe=r["summe"], vorauszahlung=r["vorauszahlung"], saldo=r["saldo"],
            spalte_gesamt="Gesamtkosten Immobilie", mv=None)
        rl = ruecklage(immo["id"], j)
        if rl["vorhanden"]:
            d["ruecklage"] = rl
            d["ruecklage_anteil"] = rund(rl["ende"] * w["mea"] / w["mea_basis"]) if w["mea"] and w["mea_basis"] else None
        kt = konten(immo["id"], j)
        if any(k["ende"] for k in kt["liste"]):
            d["konten"] = kt
    else:
        p = next((x for x in r["parteien"] if str(x["mv"]["id"]) == str(partei)), None)
        if p is None:
            abort(404)
        mv = p["mv"]
        if mv["bis"] and mv["neue_anschrift"]:
            anschrift = [z.strip() for z in mv["neue_anschrift"].splitlines() if z.strip()]
        else:
            anschrift = list(adresse(immo))
        d.update(
            partei=str(mv["id"]), partei_name=mv_name(mv), mv=mv,
            empfaenger=[person_name(x) for x in mv["personen"]] + anschrift,
            absender=_zeile(person_name(eig), eig) if eig else immo["absender"],
            **({"iban": w["iban"], "kontoinhaber": w["kontoinhaber"] or (person_name(eig) if eig else ""),
                "bank": w["bank"]} if w["iban"] else {}),
            nutzung_von=p["von"], nutzung_bis=p["bis"], monate=p["monate"], prozent=p["prozent"],
            posten=p["posten"], summe=p["summe"], vorauszahlung=p["vorauszahlung"], saldo=p["saldo"],
            spalte_gesamt="Gesamtkosten im Jahr")
    d["summe_gesamt"] = rund(sum(x["gesamt"] for x in d["posten"]))
    wohnung = w["bezeichnung"] if len(erg["wohnungen"]) > 1 else ""
    d["anschrift_hoch"] = round(parse_num(einstellung("brief_anschrift_hoch", "0")))
    d["fusszeile"] = (f"Erstellt mit {NAME}" + (f" · {URL}" if URL else "")
                      if einstellung("brief_fusszeile", "1") == "1" else "")
    d["verwendungszweck"] = sepa_text(", ".join(x for x in (f"Nebenkosten {j}", d["objekt"][0] if d["objekt"] else "",
                                                            wohnung, d["partei_name"]) if x))
    d["girocode"] = girocode(d["kontoinhaber"] or (person_name(eig) if eig else ""), d["iban"] or "", d["saldo"],
                             d["verwendungszweck"]) if d["saldo"] > 0 else None
    return d


def belegliste(d):
    """Buchungen des Jahres nach Kostenart gruppiert. Mieter sehen nur umlagefähige Kostenarten, Eigentümer zusätzlich
    die nicht umlagefähigen und die Erhaltungsrücklage. „wert“: Kosten positiv, in der Rücklage Zuflüsse positiv."""
    eigentuemer = d["partei"] == "eigentuemer"
    gruppen = []
    for b in rows("SELECT b.*, ka.name AS kostenart, ka.umlagefaehig FROM buchung b "
                  "LEFT JOIN kostenart ka ON ka.id = b.kostenart_id WHERE b.immobilie_id = ? AND b.jahr = ? "
                  "AND b.hausgeld_eigentuemer_id IS NULL "  # Hausgeld anderer Eigentümer gehört nicht in den Brief
                  "ORDER BY b.kostenart_id IS NULL, ka.sortierung, ka.name, b.datum IS NULL, b.datum, b.id",
                  (d["immo"]["id"], d["jahr"])):
        if not eigentuemer and not (b["kostenart_id"] and b["umlagefaehig"]):
            continue
        name = b["kostenart"] or "Erhaltungsrücklage"
        if not gruppen or gruppen[-1]["name"] != name:
            gruppen.append({"name": name, "buchungen": [], "summe": 0.0})
        einnahme = b["art"] == "einnahme"
        b["wert"] = (b["betrag"] if einnahme else -b["betrag"]) if not b["kostenart_id"] else \
            (-b["betrag"] if einnahme else b["betrag"])
        gruppen[-1]["buchungen"].append(b)
        gruppen[-1]["summe"] = rund(gruppen[-1]["summe"] + b["wert"])
    return gruppen


def export_dokumente(d):
    """Belege des Jahres; vorausgewählt sind die Mieterbelege dieser Wohnung bzw. dieses Mieters."""
    docs = dokumente_sichtbar(d["immo"]["id"], d["jahr"], d["w"]["id"])
    erg = []
    for doc in docs:
        if doc["bereich"] == "vermieter" and not ist_admin():
            continue
        if d["mv"] and doc["mv_id"] and doc["mv_id"] != d["mv"]["id"]:
            continue
        doc["vorauswahl"] = doc["bereich"] != "vermieter"
        erg.append(doc)
    if ist_admin():
        # Belege der Buchungen: in der Eigentümer-Abrechnung alle vorausgewählt, Mietern nur umlagefähige zur Auswahl
        eigentuemer = d["partei"] == "eigentuemer"
        vorhanden = {doc["id"] for doc in erg}
        for doc in rows("SELECT d.*, ka.name AS kostenart, b.kostenart_id AS b_kostenart, ka.umlagefaehig FROM buchung b "
                        "JOIN dokument d ON d.id = b.dokument_id LEFT JOIN kostenart ka ON ka.id = b.kostenart_id "
                        "WHERE b.immobilie_id = ? AND b.jahr = ? AND b.hausgeld_eigentuemer_id IS NULL "
                        "ORDER BY b.datum IS NULL, b.datum, b.id",
                        (d["immo"]["id"], d["jahr"])):
            if doc["id"] in vorhanden or not (eigentuemer or (doc["b_kostenart"] and doc["umlagefaehig"])):
                continue
            doc.update(vorauswahl=eigentuemer, buchung=True)
            vorhanden.add(doc["id"])
            erg.append(doc)
    return erg


@app.get("/wohnungen/<int:wid>/export")
def export(wid):
    partei = request.args.get("partei", "eigentuemer")
    d = brief_daten(wid, partei)
    pruefung = pruefungen(d["immo"], berechnung(d["immo"], d["jahr"]), {wid})
    return render_template("export/export.html", d=d, dokumente=export_dokumente(d), wid=wid, pruefung=pruefung,
                           belege=sum(len(gr["buchungen"]) for gr in belegliste(d)))


@app.get("/wohnungen/<int:wid>/export/brief")
def export_brief(wid):
    d = brief_daten(wid, request.args.get("partei", "eigentuemer"))
    return render_template("export/brief.html", d=d, vorschau=True)


@app.post("/wohnungen/<int:wid>/export/pdf")
def export_pdf(wid):
    from pypdf import PdfReader, PdfWriter
    from weasyprint import HTML

    d = brief_daten(wid, request.form.get("partei", "eigentuemer"))
    erlaubt = {doc["id"]: doc for doc in export_dokumente(d)}
    gewaehlt = [erlaubt[int(x)] for x in request.form.getlist("dokumente") if int(x) in erlaubt]
    teile = request.form.getlist("teile")
    if "ruecklage" not in teile:
        d.pop("ruecklage", None)
    liste = belegliste(d) if "belegliste" in teile else None

    html = render_template("export/brief.html", d=d, vorschau=False, anlagen=gewaehlt, belegliste=liste)
    writer = PdfWriter()
    writer.append(PdfReader(io.BytesIO(HTML(string=html, base_url=request.url_root).write_pdf())))
    for doc in gewaehlt:
        pfad = dateien.dokument_pfad(doc["pfad"])
        if not os.path.exists(pfad):
            continue
        if doc["mime"] == "application/pdf":
            writer.append(PdfReader(pfad))
        else:
            from PIL import Image, ImageOps
            buf = io.BytesIO()
            ImageOps.exif_transpose(Image.open(pfad)).convert("RGB").save(buf, "PDF", resolution=150)
            buf.seek(0)
            writer.append(PdfReader(buf))
    out = io.BytesIO()
    writer.write(out)
    out.seek(0)
    name = dateien.ordnername(f"Betriebskostenabrechnung {d['jahr']} - {d['w']['bezeichnung']} - {d['partei_name']}")
    return send_file(out, mimetype="application/pdf", download_name=f"{name}.pdf",
                     as_attachment=request.form.get("aktion") == "speichern")
