"""Dokumentenübersicht: Abrechnungsbelege und Ablage aller Immobilien an einer Stelle, mit Suche, Filtern und Sortierung."""
import os

from flask import g, redirect, render_template, request, url_for

from core import ABLAGE_KATEGORIEN, app, exe, ist_admin, person_name, rows, wohnung_bearbeitbar
from db import _natuerlich_schluessel
from immobilien import _ablage_laden, _dokument_laden

ARTEN = {"belege": "Abrechnungsbelege", "ablage": "Ablage (alle Kategorien)",
         **{k: f"Ablage · {t}" for k, t in ABLAGE_KATEGORIEN.items()}}
SPALTEN = {"titel": "Dokument", "notiz": "Kommentar", "immobilie": "Immobilie", "wohnung": "Mietobjekt",
           "art": "Art", "jahr": "Jahr", "datum": "Hochgeladen am"}
ABLAGEORT = {"mieter": "Mieter", "vermieter": "Vermieter"}


def _alle_dokumente():
    """Belege und Ablage in einheitlicher Form, gefiltert auf das, was der Benutzer sehen darf."""
    belege = rows("""SELECT d.*, COALESCE(d.wohnung_id, m.wohnung_id) AS wid, i.name AS immobilie, i.archiviert,
                            w.bezeichnung AS wohnung, w.eigentuemer_id, m.ordner AS mv_ordner, ka.name AS kostenart,
                            b.vorname, b.name AS b_name, b.benutzername
                     FROM dokument d JOIN immobilie i ON i.id = d.immobilie_id
                     LEFT JOIN mietverhaeltnis m ON m.id = d.mv_id
                     LEFT JOIN wohnung w ON w.id = COALESCE(d.wohnung_id, m.wohnung_id)
                     LEFT JOIN kostenart ka ON ka.id = d.kostenart_id
                     LEFT JOIN benutzer b ON b.id = d.hochgeladen_von""")
    ablage = rows("""SELECT a.*, a.wohnung_id AS wid, i.name AS immobilie, i.archiviert, w.bezeichnung AS wohnung,
                            w.eigentuemer_id, b.vorname, b.name AS b_name, b.benutzername
                     FROM ablage a JOIN immobilie i ON i.id = a.immobilie_id
                     LEFT JOIN wohnung w ON w.id = a.wohnung_id
                     LEFT JOIN benutzer b ON b.id = a.hochgeladen_von""")
    admin = ist_admin()
    if not admin:
        eigene = rows("SELECT id, immobilie_id FROM wohnung WHERE eigentuemer_id = ?", (g.user["id"],))
        eigene_w = {w["id"] for w in eigene}
        eigene_i = {w["immobilie_id"] for w in eigene}

    erg = []
    for d in belege:
        if not admin and not (d["wid"] in eigene_w if d["wid"] else
                              d["bereich"] == "mieter" and d["immobilie_id"] in eigene_i):
            continue
        ort = d["mv_ordner"] if d["bereich"] == "mieterordner" else ABLAGEORT.get(d["bereich"], "")
        erg.append({**_gemeinsam(d), "typ": "beleg", "art_schluessel": "belege",
                    "art": " · ".join(x for x in (f"Beleg {d['jahr']}", ort, d["kostenart"]) if x),
                    "link": url_for("dokument_anzeigen", did=d["id"])})
    for a in ablage:
        if not admin and (a["intern"] or not (a["wid"] in eigene_w if a["wid"] else a["immobilie_id"] in eigene_i)):
            continue
        erg.append({**_gemeinsam(a), "typ": "ablage", "art_schluessel": a["kategorie"],
                    "art": f"Ablage · {ABLAGE_KATEGORIEN.get(a['kategorie'], a['kategorie'])}",
                    "kategorie": a["kategorie"], "intern": a["intern"],
                    "link": url_for("ablage_anzeigen", aid=a["id"])})
    return erg


def _gemeinsam(d):
    return {"id": d["id"], "schluessel": None, "titel": d["titel"], "notiz": d["notiz"], "jahr": d["jahr"],
            "datum": (d["hochgeladen_am"] or "")[:10], "von": person_name({"vorname": d["vorname"], "name": d["b_name"],
                                                                         "benutzername": d["benutzername"] or ""}),
            "immobilie_id": d["immobilie_id"], "immobilie": d["immobilie"], "archiviert": d["archiviert"],
            "wohnung_id": d["wid"], "wohnung": d["wohnung"] or "", "dateiname": os.path.basename(d["pfad"]),
            "groesse": d["groesse"],
            "darf": wohnung_bearbeitbar({"eigentuemer_id": d["eigentuemer_id"]}) if d["wid"] else ist_admin()}


def _sortierschluessel(spalte):
    if spalte in ("jahr",):
        return lambda d: (d["jahr"] is None, d["jahr"] or 0)
    if spalte == "datum":
        return lambda d: d["datum"]
    return lambda d: _natuerlich_schluessel(d.get(spalte) or "")


@app.get("/dokumente")
def dokumente_uebersicht():
    alle = _alle_dokumente()
    for d in alle:
        d["schluessel"] = f"{d['typ']}-{d['id']}"
    a = request.args
    q = a.get("q", "").strip().casefold()
    immobilie = a.get("immobilie", type=int)
    wohnung = a.get("wohnung", type=int)
    art = a.get("art", "")
    jahr = a.get("jahr", type=int)

    treffer = [d for d in alle
               if (not q or any(q in (d[k] or "").casefold() for k in ("titel", "notiz", "dateiname", "art")))
               and (not immobilie or d["immobilie_id"] == immobilie)
               and (not wohnung or d["wohnung_id"] == wohnung)
               and (not art or (art == "ablage" and d["typ"] == "ablage") or d["art_schluessel"] == art)
               and (not jahr or d["jahr"] == jahr)]
    sort = a.get("sort", "datum") if a.get("sort", "datum") in SPALTEN else "datum"
    absteigend = a.get("richtung", "ab" if sort == "datum" else "auf") == "ab"
    treffer.sort(key=_sortierschluessel(sort), reverse=absteigend)

    def sortier_link(spalte):
        neu = a.to_dict()
        neu.pop("bearbeiten", None)
        neu["sort"] = spalte
        neu["richtung"] = "auf" if spalte == sort and absteigend else ("ab" if spalte == sort or spalte == "datum" else "auf")
        return url_for("dokumente_uebersicht", **neu)

    immobilien = sorted({(d["immobilie_id"], d["immobilie"], d["archiviert"]) for d in alle},
                        key=lambda x: _natuerlich_schluessel(x[1]))
    wohnungen = sorted({(d["wohnung_id"], d["immobilie"], d["wohnung"]) for d in alle
                        if d["wohnung_id"] and (not immobilie or d["immobilie_id"] == immobilie)},
                       key=lambda x: (_natuerlich_schluessel(x[1]), _natuerlich_schluessel(x[2])))
    jahre = sorted({d["jahr"] for d in alle if d["jahr"]}, reverse=True)
    return render_template("dokumente.html", treffer=treffer, anzahl=len(alle), immobilien=immobilien,
                           wohnungen=wohnungen, jahre=jahre, arten=ARTEN, spalten=SPALTEN, sort=sort,
                           absteigend=absteigend, sortier_link=sortier_link, filter_aktiv=any(
                               a.get(k) for k in ("q", "immobilie", "wohnung", "art", "jahr")),
                           bearbeiten=a.get("bearbeiten", ""))


@app.post("/dokumente/<typ>/<int:did>/bearbeiten")
def dokument_bearbeiten(typ, did):
    f = request.form
    titel = f.get("titel", "").strip()
    if not titel:
        raise ValueError("Bitte einen Titel angeben.")
    if typ == "beleg":
        _dokument_laden(did, bearbeiten=True)
        exe("UPDATE dokument SET titel = ?, notiz = ? WHERE id = ?", (titel, f.get("notiz", "").strip(), did))
    elif typ == "ablage":
        _ablage_laden(did, bearbeiten=True)
        kategorie = f.get("kategorie")
        if kategorie not in ABLAGE_KATEGORIEN:
            raise ValueError("Bitte eine Kategorie wählen.")
        jahr = int(f["jahr"]) if f.get("jahr", "").strip() else None
        exe("UPDATE ablage SET titel = ?, notiz = ?, kategorie = ?, jahr = ? WHERE id = ?",
            (titel, f.get("notiz", "").strip(), kategorie, jahr, did))
    else:
        raise ValueError("Unbekannte Dokumentart.")
    ziel = f.get("next", "")
    return redirect(ziel if ziel.startswith("/") and not ziel.startswith("//") else url_for("dokumente_uebersicht"))
