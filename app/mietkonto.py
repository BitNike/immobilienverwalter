"""Mietkonto je Mietverhältnis: Soll (Kaltmiete + NK-Vorauszahlung) und Zahlungen Monat für Monat, sonstige Forderungen
(z. B. Nachzahlung aus der Betriebskostenabrechnung), laufender Saldo und Druckfassung als Forderungsaufstellung."""
import io
from datetime import date

from flask import abort, flash, redirect, render_template, request, send_file, url_for

import dateien
from calc import de_num, parse_date, parse_num, rund
from core import NAME, URL, app, einstellung, exe, jahr, one, person_name, row, rows, wohnung_laden
from immobilien import adresse, berechnung, mv_name, mv_personen

MONATE = ("Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November",
          "Dezember")


def monate_im_jahr(mv, j):
    """Monate (1–12), in denen das Mietverhältnis im Jahr j läuft, auch angebrochene."""
    von, bis = parse_date(mv["von"]), parse_date(mv["bis"])
    return [m for m in range(1, 13)
            if von < date(j + m // 12, m % 12 + 1, 1) and (bis is None or bis >= date(j, m, 1))]


def monatsmiete(mv):
    return rund((mv["kaltmiete"] or 0) + (mv["vorauszahlung_monat"] or 0))


def _gleich(a, b):
    return abs((a or 0) - (b or 0)) < 0.005


def konto(mv, bis_jahr=None, heute=None):
    """Mietkonto bis einschließlich bis_jahr (mindestens bis heute). Das Konto beginnt mit dem ersten Monat, für den eine
    Zahlung eingetragen ist; ab dann zählen fällige Monate ohne Eintrag als nicht bezahlt, davor zählt nichts.
    Ergebnis: {jahre: {j: {zeilen, vortrag, soll, gezahlt, offen, ende}}, beginn: (j, m) | None, erstes, stand}.
    stand > 0 = Rückstand, < 0 = Guthaben des Mieters."""
    heute = heute or date.today()
    daten = rows("SELECT * FROM mietzahlung WHERE mv_id = ? ORDER BY jahr, monat IS NULL, monat, id", (mv["id"],))
    monate = {(z["jahr"], z["monat"]): z for z in daten if z["monat"]}
    bezahlt = [k for k, z in monate.items() if z["gezahlt"] is not None]
    beginn = min(bezahlt) if bezahlt else None
    zaehlend = [beginn[0]] if beginn else []
    zaehlend += [z["jahr"] for z in daten if not z["monat"]]
    erstes = min(zaehlend) if zaehlend else None
    letztes = max([bis_jahr or heute.year, heute.year] + [z["jahr"] for z in daten])
    jahre, saldo = {}, 0.0
    for j in range(min([erstes or letztes, bis_jahr or letztes]), letztes + 1):
        zeilen = []
        for m in monate_im_jahr(mv, j):
            z = monate.get((j, m))
            kalt = z["kaltmiete"] if z else mv["kaltmiete"] or 0
            nk = z["nebenkosten"] if z else mv["vorauszahlung_monat"] or 0
            gezahlt = z["gezahlt"] if z else None
            zeilen.append({"monat": m, "name": MONATE[m - 1], "id": z["id"] if z else None, "kaltmiete": kalt,
                           "nebenkosten": nk, "soll": rund(kalt + nk), "gezahlt": gezahlt,
                           "datum": z["datum"] if z else None, "notiz": z["notiz"] if z else "",
                           "zaehlt": gezahlt is not None or bool(beginn and (j, m) >= beginn and date(j, m, 1) <= heute)})
        for z in daten:
            if not z["monat"] and z["jahr"] == j:
                zeilen.append({"monat": None, "name": z["text"], "id": z["id"], "text": z["text"],
                               "soll": z["sonstiges"], "gezahlt": z["gezahlt"], "datum": z["datum"], "notiz": z["notiz"],
                               "zaehlt": True})
        vortrag = saldo
        for zl in zeilen:
            zl["offen"] = zl["saldo"] = None
            if zl["zaehlt"]:
                zl["offen"] = rund(zl["soll"] - (zl["gezahlt"] or 0))
                saldo = zl["saldo"] = rund(saldo + zl["offen"])
        z = [zl for zl in zeilen if zl["zaehlt"]]
        jahre[j] = {"zeilen": zeilen, "vortrag": vortrag, "soll": rund(sum(zl["soll"] for zl in z)),
                    "gezahlt": rund(sum(zl["gezahlt"] or 0 for zl in z)), "offen": rund(sum(zl["offen"] for zl in z)),
                    "ende": saldo}
    return {"jahre": jahre, "beginn": beginn, "erstes": erstes, "stand": saldo}


def nk_ergebnis(mv, w, j):
    """Ergebnis der Betriebskostenabrechnung j für dieses Mietverhältnis als Vorschlag für das Mietkonto."""
    if not w["immobilie_id"]:
        return None
    erg = berechnung(row("SELECT * FROM immobilie WHERE id = ?", (w["immobilie_id"],)), j)
    p = next((x for x in erg["wohnungen"].get(w["id"], {}).get("parteien", []) if x["mv"]["id"] == mv["id"]), None)
    if not p or _gleich(p["saldo"], 0):
        return None
    return {"text": f"Betriebskostenabrechnung {j}: {'Nachzahlung' if p['saldo'] > 0 else 'Guthaben'}",
            "betrag": p["saldo"]}


def reiter_daten(w, mvs, j):
    """Mietkonten der Mietverhältnisse, die im Jahr j laufen, für den Reiter „Mietkonto“."""
    erg = []
    for mv in mvs:
        if not mv["im_jahr"]:
            continue
        k = konto(mv, j)
        vorschlag = nk_ergebnis(mv, w, j - 1)
        if vorschlag and one("SELECT 1 FROM mietzahlung WHERE mv_id = ? AND monat IS NULL AND text = ?",
                             (mv["id"], vorschlag["text"])):
            vorschlag = None
        erg.append({"mv": mv, "jahr": k["jahre"][j], "beginn": k["beginn"], "stand": k["stand"],
                    "monatsmiete": monatsmiete(mv), "vorschlag": vorschlag})
    return erg


def rueckstaende(wohnungen):
    """Prüfpunkte für Mietrückstände (Stand heute) der Mietverhältnisse dieser Mietobjekte."""
    punkte = []
    for w in wohnungen:
        if w["mieter_extern"]:
            continue
        for mv in rows("SELECT DISTINCT m.* FROM mietverhaeltnis m JOIN mietzahlung z ON z.mv_id = m.id "
                       "WHERE m.wohnung_id = ?", (w["id"],)):
            stand = konto(mv)["stand"]
            if stand < 0.005:
                continue
            mv["personen"] = mv_personen(mv["id"])
            text = f"{w['bezeichnung']}: Mietrückstand {mv_name(mv)} {de_num(stand)} €"
            miete = monatsmiete(mv)
            if miete and stand >= 2 * miete - 0.005:
                text += " – mehr als zwei Monatsmieten. Vor einer Kündigung (§ 543 BGB) rechtlich beraten lassen."
            punkte.append({"text": text + ".", "art": "hinweis",
                           "link": url_for("wohnung", wid=w["id"], reiter="mietkonto", jahr=date.today().year)
                           + f"#mk{mv['id']}"})
    return punkte


def soll_festhalten(mv_alt, vals):
    """Ändert sich die Miete im Vertrag, behalten die bereits fälligen Monate seit Kontobeginn ihr bisheriges Soll."""
    if "kaltmiete" not in vals or (_gleich(vals["kaltmiete"], mv_alt["kaltmiete"])
                                   and _gleich(vals["vorauszahlung_monat"], mv_alt["vorauszahlung_monat"])):
        return
    k = konto(mv_alt)
    if not k["beginn"]:
        return
    heute = date.today()
    for j in range(k["beginn"][0], heute.year + 1):
        for m in monate_im_jahr(mv_alt, j):
            if (j, m) >= k["beginn"] and date(j, m, 1) <= heute:
                exe("INSERT OR IGNORE INTO mietzahlung (mv_id, jahr, monat, kaltmiete, nebenkosten) VALUES (?, ?, ?, ?, ?)",
                    (mv_alt["id"], j, m, mv_alt["kaltmiete"] or 0, mv_alt["vorauszahlung_monat"] or 0))


# ---------- Routen ----------

def _mv_laden(mid, bearbeiten=True):
    mv = row("SELECT * FROM mietverhaeltnis WHERE id = ?", (mid,))
    w = wohnung_laden(mv["wohnung_id"], bearbeiten=bearbeiten)
    if w["mieter_extern"]:
        abort(404)
    mv["personen"] = mv_personen(mid)
    return mv, w


def _zurueck(mv, j):
    return redirect(url_for("wohnung", wid=mv["wohnung_id"], reiter="mietkonto", jahr=j) + f"#mk{mv['id']}")


def _datum(s):
    if s:
        parse_date(s)  # ungültiges Datum → ValueError
    return s or None


@app.post("/mieter/<int:mid>/mietkonto")
def mietkonto_speichern(mid):
    mv, _w = _mv_laden(mid)
    f = request.form
    j = int(f["jahr"])
    for m in monate_im_jahr(mv, j):
        p = f"m{m}_"
        if p + "gezahlt" not in f:
            continue
        z = one("SELECT * FROM mietzahlung WHERE mv_id = ? AND jahr = ? AND monat = ?", (mid, j, m))
        kalt, nk = (z["kaltmiete"], z["nebenkosten"]) if z else (mv["kaltmiete"], mv["vorauszahlung_monat"])
        werte = {"kaltmiete": parse_num(f.get(p + "kalt"), kalt), "nebenkosten": parse_num(f.get(p + "nk"), nk),
                 "gezahlt": parse_num(f.get(p + "gezahlt"), None), "datum": _datum(f.get(p + "datum")),
                 "notiz": f.get(p + "notiz", "").strip()}
        if z:
            exe(f"UPDATE mietzahlung SET {', '.join(k + ' = ?' for k in werte)} WHERE id = ?", [*werte.values(), z["id"]])
        elif werte["gezahlt"] is not None or werte["datum"] or werte["notiz"] or \
                not _gleich(werte["kaltmiete"], mv["kaltmiete"]) or not _gleich(werte["nebenkosten"], mv["vorauszahlung_monat"]):
            werte.update(mv_id=mid, jahr=j, monat=m)
            exe(f"INSERT INTO mietzahlung ({', '.join(werte)}) VALUES ({', '.join('?' * len(werte))})", list(werte.values()))
    for z in rows("SELECT id FROM mietzahlung WHERE mv_id = ? AND jahr = ? AND monat IS NULL", (mid, j)):
        p = f"s{z['id']}_"
        if p + "betrag" not in f:
            continue
        text = f.get(p + "text", "").strip()
        if not text:
            raise ValueError("Bitte eine Bezeichnung für die Forderung angeben.")
        exe("UPDATE mietzahlung SET text = ?, sonstiges = ?, gezahlt = ?, datum = ?, notiz = ? WHERE id = ?",
            (text, parse_num(f.get(p + "betrag")), parse_num(f.get(p + "gezahlt"), None), _datum(f.get(p + "datum")),
             f.get(p + "notiz", "").strip(), z["id"]))
    if f.get("aktion") == "alle":
        n = alle_bezahlt(mv, j)
        flash(f"{n} fällige Monat{'e' if n != 1 else ''} mit dem Soll als bezahlt eingetragen." if n else
              "Es gibt keinen fälligen Monat ohne Zahlung.")
    else:
        flash("Mietkonto gespeichert.")
    return _zurueck(mv, j)


def alle_bezahlt(mv, j):
    """Fällige Monate des Jahres ohne eingetragene Zahlung mit dem Soll als bezahlt eintragen. Gibt die Anzahl zurück."""
    heute, n = date.today(), 0
    for m in monate_im_jahr(mv, j):
        if date(j, m, 1) > heute:
            continue
        z = one("SELECT * FROM mietzahlung WHERE mv_id = ? AND jahr = ? AND monat = ?", (mv["id"], j, m))
        if z is None:
            exe("INSERT INTO mietzahlung (mv_id, jahr, monat, kaltmiete, nebenkosten, gezahlt) VALUES (?, ?, ?, ?, ?, ?)",
                (mv["id"], j, m, mv["kaltmiete"] or 0, mv["vorauszahlung_monat"] or 0, monatsmiete(mv)))
        elif z["gezahlt"] is None:
            exe("UPDATE mietzahlung SET gezahlt = ? WHERE id = ?", (rund(z["kaltmiete"] + z["nebenkosten"]), z["id"]))
        else:
            continue
        n += 1
    return n


@app.post("/mieter/<int:mid>/mietkonto/neu")
def mietkonto_neu(mid):
    mv, w = _mv_laden(mid)
    f = request.form
    j = int(f["jahr"])
    if f.get("aktion") == "abrechnung":
        v = nk_ergebnis(mv, w, j - 1)
        if not v:
            raise ValueError(f"Für {j - 1} gibt es kein Ergebnis der Betriebskostenabrechnung.")
        text, betrag, gezahlt, datum, notiz = v["text"], v["betrag"], None, None, ""
    else:
        text = f.get("text", "").strip()
        if not text:
            raise ValueError("Bitte eine Bezeichnung angeben, z. B. „Mahngebühr“.")
        betrag, gezahlt = parse_num(f.get("betrag")), parse_num(f.get("gezahlt"), None)
        datum, notiz = _datum(f.get("datum")), f.get("notiz", "").strip()
    exe("INSERT INTO mietzahlung (mv_id, jahr, text, sonstiges, gezahlt, datum, notiz) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (mid, j, text, betrag, gezahlt, datum, notiz))
    return _zurueck(mv, j)


@app.post("/mietzahlung/<int:zid>/loeschen")
def mietzahlung_loeschen(zid):
    z = row("SELECT * FROM mietzahlung WHERE id = ?", (zid,))
    mv, _w = _mv_laden(z["mv_id"])
    exe("DELETE FROM mietzahlung WHERE id = ?", (zid,))
    return _zurueck(mv, z["jahr"])


@app.get("/mieter/<int:mid>/mietkonto/druck")
def mietkonto_druck(mid):
    mv, w = _mv_laden(mid, bearbeiten=False)
    j = jahr()
    k = konto(mv, j)
    von = k["erstes"] if request.args.get("alle") and k["erstes"] and k["erstes"] < j else j
    immo = one("SELECT * FROM immobilie WHERE id = ?", (w["immobilie_id"],)) or {}
    eig = one("SELECT * FROM benutzer WHERE id = ?", (w["eigentuemer_id"],))
    d = {"mv": mv, "w": w, "immo": immo, "heute": date.today(), "von": von, "bis": j, "stand": k["stand"],
         "jahre": [(y, k["jahre"][y]) for y in range(von, j + 1)], "monatsmiete": monatsmiete(mv),
         "objekt": [x for x in (*adresse(immo), w["bezeichnung"]) if x],
         "vermieter": [x for x in ((person_name(eig), *adresse(eig)) if eig else (immo.get("absender"),)) if x],
         "ende": k["jahre"][j]["ende"],
         "fusszeile": (f"Erstellt mit {NAME}" + (f" · {URL}" if URL else "")
                       if einstellung("brief_fusszeile", "1") == "1" else "")}
    html = render_template("export/mietkonto.html", d=d, vorschau=not request.args.get("pdf"))
    if not request.args.get("pdf"):
        return html
    from weasyprint import HTML
    zeitraum = str(j) if von == j else f"{von}-{j}"
    name = dateien.ordnername(f"Mietkonto {zeitraum} - {w['bezeichnung']} - {mv_name(mv)}")
    return send_file(io.BytesIO(HTML(string=html, base_url=request.url_root).write_pdf()), mimetype="application/pdf",
                     download_name=f"{name}.pdf", as_attachment=True)

