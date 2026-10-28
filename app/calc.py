"""Verteilung der Kosten: Immobilie -> Mietobjekt (Wohnung) -> Mietverhältnis / Leerstand.

Reine Python-Logik ohne Flask, damit sie einzeln testbar ist.
"""
import calendar
import re
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

SCHLUESSEL = {
    "mea": "Miteigentumsanteile (MEA)",
    "flaeche": "Wohnfläche",
    "einheiten": "Wohneinheiten",
    "wasser": "Wasserverbrauch",
}


# ---------- Hilfsfunktionen ----------

def parse_date(s):
    if not s:
        return None
    return s if isinstance(s, date) else date.fromisoformat(s)


def parse_num(s, default=0.0):
    """Akzeptiert deutsche (1.234,56) und englische (1234.56) Schreibweise."""
    if s is None:
        return default
    s = str(s).strip().replace(" ", "").replace("€", "").replace("m²", "")
    if not s:
        return default
    if "," in s or re.fullmatch(r"\d{1,3}(\.\d{3})+", s):  # 1.000 = Tausend
        s = s.replace(".", "").replace(",", ".")
    return float(s)


def parse_mea(s):
    """'86,13/1.000' -> (86.13, 1000.0); '86,13' -> (86.13, None)"""
    s = (s or "").replace("MEA", "").strip()
    if "/" in s:
        a, b = s.split("/", 1)
        return parse_num(a), parse_num(b, None)
    return parse_num(s), None


def rund(x):
    """Kaufmännisch auf Cent runden (77,655 -> 77,66)."""
    return float(Decimal(f"{x:.6f}").quantize(Decimal("0.01"), ROUND_HALF_UP))


def cent_genau(betraege):
    """{schluessel: ungerundet} auf Cent runden, sodass die Summe der gerundeten Werte der gerundeten Gesamtsumme
    entspricht (z. B. 136,85 € auf 3 Wohnungen: 45,62 + 45,62 + 45,61). Der Ausgleich geht an die größten Rundungsreste."""
    gerundet = {k: rund(v) for k, v in betraege.items()}
    diff = round((rund(sum(betraege.values())) - sum(gerundet.values())) * 100)
    reihenfolge = sorted(betraege, key=lambda k: betraege[k] - gerundet[k], reverse=diff > 0)
    for k in reihenfolge[:abs(diff)]:
        gerundet[k] = rund(gerundet[k] + (0.01 if diff > 0 else -0.01))
    return gerundet


def de_num(v, stellen=2):
    s = f"{v:,.{stellen}f}"
    return s.replace(",", "\0").replace(".", ",").replace("\0", ".")


def de_monate(m):
    return str(int(round(m))) if abs(m - round(m)) < 0.005 else de_num(m, 2)


def plus_jahr(d):
    try:
        return d.replace(year=d.year + 1)
    except ValueError:  # 29. Februar
        return d.replace(year=d.year + 1, day=28)


def ueberlappung(von, bis, p_von, p_bis):
    a = max(von, p_von)
    b = min(bis or p_bis, p_bis)
    return (a, b) if a <= b else None


def monate(von, bis):
    """Monate im Zeitraum. Volle Monate zählen 1, angebrochene anteilig nach Tagen."""
    m, d = 0.0, von
    while d <= bis:
        dim = calendar.monthrange(d.year, d.month)[1]
        ende = min(date(d.year, d.month, dim), bis)
        m += ((ende - d).days + 1) / dim
        d = ende + timedelta(days=1)
    return m


def verbrauch_zeitraum(zaehler, von, bis):
    """
    Verbrauch aller übergebenen Zähler (z. B. alte + neue Wasseruhr) im Zeitraum.
    Anfang = letzte Ablesung am/vor `von`; fehlt sie (Einbau oder erste Ablesung erst im Zeitraum),
    zählt der Verbrauch ab der ersten Ablesung im Zeitraum (siehe `messbeginn`).
    Ende = letzte Ablesung am/vor `bis` (bzw. Ausbaustand). None, wenn das Ende fehlt.
    """
    summe, gezaehlt = 0.0, False
    for z in zaehler:
        ein, aus = parse_date(z.get("eingebaut")), parse_date(z.get("ausgebaut"))
        if (aus and aus < von) or (ein and ein > bis):
            continue
        st = sorted((parse_date(d), s) for d, s in z["staende"])
        vorher = [s for s in st if s[0] <= von]
        if vorher:
            start = vorher[-1]
        elif st and st[0][0] <= bis:
            start = st[0]
        else:
            return None
        bis_eff = min(bis, aus) if aus else bis
        ende = [s for s in st if s[0] <= bis_eff]
        if not ende or ende[-1][0] < bis_eff:
            return None
        summe += ende[-1][1] - start[1]
        gezaehlt = True
    return summe if gezaehlt else None


def messbeginn(zaehler, von, bis):
    """Datum der ersten Ablesung, wenn für den Zeitraum kein Stand am/vor `von` vorliegt und der Zähler
    nicht erst im Zeitraum eingebaut wurde – der Verbrauch davor ist dann unbekannt. Sonst None."""
    for z in zaehler:
        ein, aus = parse_date(z.get("eingebaut")), parse_date(z.get("ausgebaut"))
        if (aus and aus < von) or (ein and ein > von):
            continue
        st = sorted(parse_date(d) for d, _ in z["staende"])
        if st and st[0] > von and st[0] <= bis:
            return st[0]
    return None


# ---------- Berechnung ----------

def berechne(von, bis, immobilie, wohnungen, kosten, kostenarten, mvs, zaehler, vorauszahlungen):
    """
    von, bis           Abrechnungszeitraum (date)
    immobilie          dict mit gesamtflaeche, einheiten_gesamt (optional)
    wohnungen          [{id, bezeichnung, wohnflaeche, mea, mea_basis, haus}]
    kosten             [{id, wohnung_id, mv_id, kostenart_id, betrag, schluessel, haus}]
                         wohnung_id None  -> Gebäudekosten, Verteilung nach `schluessel`
                                             (mit `haus` nur auf die Wohnungen dieses Hauses)
                         wohnung_id gesetzt -> Kosten der Wohnung, zeitanteilig auf die Mieter
                         mv_id gesetzt    -> 100 % für dieses Mietverhältnis (z. B. Heizkostenabrechnung)
    kostenarten        {id: {name, umlagefaehig}}
    mvs                [{id, wohnung_id, von, bis, vorauszahlung_monat, ...}]
    zaehler            [{wohnung_id, art, eingebaut, ausgebaut, staende: [(datum, stand)]}]
    vorauszahlungen    {(wohnung_id, mv_id | None): betrag}   None = Eigentümer
    """
    M = monate(von, bis)
    F = immobilie.get("gesamtflaeche") or sum(w["wohnflaeche"] for w in wohnungen)
    N = immobilie.get("einheiten_gesamt") or len(wohnungen)
    wasserzaehler = {w["id"]: [z for z in zaehler if z["wohnung_id"] == w["id"] and z["art"] == "wasser"]
                     for w in wohnungen}
    erg = {}
    for w in wohnungen:
        wz = wasserzaehler[w["id"]]
        erg[w["id"]] = {"wohnung": w, "posten": [], "summe": 0.0,
                        "wasser": verbrauch_zeitraum(wz, von, bis) if wz else None,
                        "wasser_ab": messbeginn(wz, von, bis) if wz else None}

    def verteile(k):
        b, s = k["betrag"], k["schluessel"]
        haus = k.get("haus") or ""
        if haus:  # nur die Wohnungen dieses Hauses; MEA, Fläche und Einheiten beziehen sich dann auf das Haus
            ws = [w for w in wohnungen if (w.get("haus") or "") == haus]
            if not ws:
                return {}, f"Kein Mietobjekt ist dem Haus „{haus}“ zugeordnet."
            fl, n = sum(w["wohnflaeche"] for w in ws), len(ws)
        else:
            ws, fl, n = wohnungen, F, N
        if s == "mea":
            if not any(w["mea"] for w in ws):
                return {}, "Keine MEA hinterlegt."
            if haus:
                summe = sum(w["mea"] / w["mea_basis"] for w in ws if w["mea_basis"])
                return {w["id"]: (b * w["mea"] / w["mea_basis"] / summe,
                                  f"{de_num(w['mea'])} von {de_num(sum(x['mea'] for x in ws if x['mea_basis']))} MEA ({haus})")
                        for w in ws if w["mea_basis"]}, None
            return {w["id"]: (b * w["mea"] / w["mea_basis"],
                              f"{de_num(w['mea'])}/{de_num(w['mea_basis'], 0)} MEA")
                    for w in ws if w["mea_basis"]}, None
        zusatz = f" ({haus})" if haus else ""
        if s == "flaeche":
            if fl <= 0:
                return {}, "Keine Wohnfläche hinterlegt."
            return {w["id"]: (b * w["wohnflaeche"] / fl, f"{de_num(w['wohnflaeche'])} von {de_num(fl)} m²{zusatz}")
                    for w in ws}, None
        if s == "einheiten":
            if n <= 0:
                return {}, "Keine Einheiten vorhanden."
            return {w["id"]: (b / n, f"1 von {n} Einheiten{zusatz}") for w in ws}, None
        if s == "wasser":
            fehlt = [w["bezeichnung"] for w in ws if erg[w["id"]]["wasser"] is None]
            if fehlt:
                return {}, "Zählerstände Wasser fehlen: " + ", ".join(fehlt)
            S = sum(erg[w["id"]]["wasser"] for w in ws)
            if S <= 0:
                return {}, "Kein Wasserverbrauch erfasst."
            return {w["id"]: (b * erg[w["id"]]["wasser"] / S,
                              f"{de_num(erg[w['id']]['wasser'], 1)} von {de_num(S, 1)} m³{zusatz}")
                    for w in ws}, None
        return {}, f"Unbekannter Schlüssel {s}."

    gebaeude = []
    for k in kosten:
        ka = kostenarten[k["kostenart_id"]]
        name = ka["name"] + (f" – {k['haus']}" if k.get("haus") and not k["wohnung_id"] else "")
        basis = {"kostenart": name, "umlagefaehig": ka["umlagefaehig"], "kosten_id": k["id"]}
        if k["wohnung_id"]:
            if k["wohnung_id"] in erg:
                erg[k["wohnung_id"]]["posten"].append({
                    **basis, "gesamt": k["betrag"], "betrag": k["betrag"], "basis": "Kosten der Wohnung",
                    "art": "mieter" if k["mv_id"] else "zeit", "mv_id": k["mv_id"]})
            continue
        anteile, warnung = verteile(k)
        verteilt = 0.0
        betraege = cent_genau({wid: x for wid, (x, _) in anteile.items()})
        for wid, (_, text) in anteile.items():
            x = betraege[wid]
            verteilt += x
            erg[wid]["posten"].append({**basis, "gesamt": k["betrag"], "betrag": x, "basis": text,
                                       "art": "wasser" if k["schluessel"] == "wasser" else "zeit", "mv_id": None})
        gebaeude.append({"kosten": k, "kostenart": name, "verteilt": rund(verteilt),
                         "rest": rund(k["betrag"] - verteilt), "warnung": warnung})

    for wid, r in erg.items():
        r["summe"] = rund(sum(p["betrag"] for p in r["posten"]))
        r["vorauszahlung"] = vorauszahlungen.get((wid, None), 0.0)
        r["saldo"] = rund(r["summe"] - r["vorauszahlung"])
        r["parteien"], r["leerstand"] = _aufteilen(r, [m for m in mvs if m["wohnung_id"] == wid],
                                                   wasserzaehler[wid], von, bis, M, vorauszahlungen)

    return {"monate": M, "flaeche": F, "einheiten": N, "wohnungen": erg, "gebaeude": gebaeude,
            "summe_gebaeude": rund(sum(g["kosten"]["betrag"] for g in gebaeude))}


def _aufteilen(r, mvs, wasserzaehler, von, bis, M, vorauszahlungen):
    """Kosten einer Wohnung auf ihre Mietverhältnisse verteilen; Rest = Eigentümer (Leerstand)."""
    parteien = []
    for mv in mvs:
        ov = ueberlappung(parse_date(mv["von"]), parse_date(mv["bis"]), von, bis)
        if not ov:
            continue
        m = monate(*ov)
        soll = rund(mv["vorauszahlung_monat"] * m)
        parteien.append({
            "mv": mv, "von": ov[0], "bis": ov[1], "monate": m, "prozent": m / M * 100,
            "wasser": verbrauch_zeitraum(wasserzaehler, *ov) if wasserzaehler else None,
            "posten": [], "summe": 0.0, "vorauszahlung_soll": soll,
            "vorauszahlung": vorauszahlungen.get((r["wohnung"]["id"], mv["id"]), soll),
        })
    wasser_ok = bool(r["wasser"]) and all(p["wasser"] is not None for p in parteien)
    belegt = sum(p["monate"] for p in parteien)
    leer = {"monate": max(M - belegt, 0.0), "posten": [], "summe": 0.0}

    for po in r["posten"]:
        verteilt = 0.0
        if po["umlagefaehig"]:
            for p in parteien:
                if po["art"] == "mieter":
                    if po["mv_id"] != p["mv"]["id"]:
                        continue
                    x, text = po["betrag"], "Ihnen direkt zugeordnet"
                elif po["art"] == "wasser" and wasser_ok:
                    x = po["betrag"] * p["wasser"] / r["wasser"]
                    text = f"Verbrauch {de_num(p['wasser'], 1)} von {de_num(r['wasser'], 1)} m³"
                else:
                    x = po["betrag"] * p["monate"] / M
                    text = f"{de_monate(p['monate'])} von {de_monate(M)} Monaten"
                x = rund(x)
                p["posten"].append({"kostenart": po["kostenart"], "gesamt": po["betrag"], "betrag": x, "basis": text})
                p["summe"] += x
                verteilt += x
        rest = rund(po["betrag"] - verteilt)
        if rest:
            grund = "nicht umlagefähig" if not po["umlagefaehig"] else "Leerstand / nicht zugeordnet"
            leer["posten"].append({"kostenart": po["kostenart"], "gesamt": po["betrag"], "betrag": rest,
                                   "basis": grund})
            leer["summe"] += rest

    for p in parteien:
        p["summe"] = rund(p["summe"])
        p["saldo"] = rund(p["summe"] - p["vorauszahlung"])
    leer["summe"] = rund(leer["summe"])
    return parteien, leer
