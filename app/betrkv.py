"""Übersicht der umlagefähigen Betriebskosten nach § 556 BGB i. V. m. § 2 BetrKV (Hilfe bei den Kostenarten)."""

# (Schlüssel, Nr. nach § 2 BetrKV, Titel, Beschreibung, üblicher Umlageschlüssel)
_KOSTENARTEN = [
    ("grundsteuer", "1", "Laufende öffentliche Lasten des Grundstücks",
     "Insbesondere die Grundsteuer.", "flaeche"),
    ("wasser", "2", "Wasserversorgung",
     "Wasserverbrauch, Grundgebühren, Miete und Eichung der Wasserzähler, Ablesung und Abrechnung, "
     "Wartung von Wassermengenreglern, Wasseraufbereitung.", "verbrauch"),
    ("entwaesserung", "3", "Entwässerung",
     "Gebühren für Haus- und Grundstücksentwässerung (Schmutz- und Niederschlagswasser), "
     "Betrieb einer Entwässerungspumpe.", "verbrauch"),
    ("heizung", "4", "Heizung",
     "Brennstoff und Lieferung, Betriebsstrom, Bedienung, Wartung und Reinigung der Anlage, Messungen, "
     "Miete und Ablesung der Heizkostenverteiler, Wärmelieferung. Abrechnung nach HeizkostenV: "
     "50–70 % nach Verbrauch.", "verbrauch"),
    ("warmwasser", "5", "Warmwasserversorgung",
     "Wassererwärmung, Wartung der Anlage, Ablesung der Warmwasserzähler. Abrechnung nach HeizkostenV: "
     "50–70 % nach Verbrauch.", "verbrauch"),
    ("heizung_warmwasser", "6", "Verbundene Heizungs- und Warmwasseranlagen",
     "Kosten einer gemeinsamen Anlage für Heizung und Warmwasser (Nr. 4 und 5 zusammen).", "verbrauch"),
    ("aufzug", "7", "Personen- oder Lastenaufzug",
     "Betriebsstrom, Beaufsichtigung, Bedienung, Überwachung, Pflege, regelmäßige Prüfung, Reinigung, "
     "Notrufanlage.", "flaeche"),
    ("strassenreinigung_muell", "8", "Straßenreinigung und Müllbeseitigung",
     "Öffentliche Gebühren oder private Dienste, Müllabfuhr, Müllkompressoren und -schlucker, "
     "Sperrmüll.", "personen"),
    ("gebaeudereinigung", "9", "Gebäudereinigung und Ungezieferbekämpfung",
     "Reinigung gemeinsam genutzter Flächen (Flure, Treppen, Keller, Waschküche, Aufzug), "
     "regelmäßige Ungezieferbekämpfung.", "flaeche"),
    ("garten", "10", "Gartenpflege",
     "Pflege gärtnerisch angelegter Flächen einschließlich Erneuerung von Pflanzen, Spielplätze, "
     "Plätze, Zugänge und Zufahrten.", "flaeche"),
    ("beleuchtung", "11", "Beleuchtung",
     "Strom für Außenbeleuchtung und gemeinsam genutzte Gebäudeteile (Treppenhaus, Keller, Flure).", "flaeche"),
    ("schornstein", "12", "Schornsteinreinigung",
     "Kehrgebühren nach Gebührenordnung, soweit nicht bereits unter Heizung erfasst.", "flaeche"),
    ("versicherung", "13", "Sach- und Haftpflichtversicherung",
     "Gebäudeversicherung gegen Feuer, Sturm, Wasser und Elementarschäden, Glasversicherung, "
     "Haftpflicht für Gebäude, Öltank und Aufzug.", "flaeche"),
    ("hauswart", "14", "Hauswart",
     "Vergütung und Sozialbeiträge des Hauswarts, soweit keine Instandhaltung, Instandsetzung, "
     "Erneuerung, Schönheitsreparaturen oder Hausverwaltung.", "flaeche"),
    ("antenne_breitband", "15", "Gemeinschafts-Antennenanlage / Breitbandnetz",
     "Betriebsstrom und Prüfung der Gemeinschafts-Antennenanlage, Glasfaser-Bereitstellungsentgelt "
     "nach § 72 TKG. Kabel-TV-Grundgebühren sind seit 01.07.2024 nicht mehr umlagefähig.", "einheiten"),
    ("waeschepflege", "16", "Einrichtungen für die Wäschepflege",
     "Betriebsstrom, Überwachung, Pflege und Reinigung, Prüfung der Betriebsbereitschaft, "
     "Wasser (soweit nicht unter Nr. 2).", "einheiten"),
    ("sonstige", "17", "Sonstige Betriebskosten",
     "Nur umlagefähig, wenn im Mietvertrag konkret benannt, z. B. Dachrinnenreinigung, "
     "Wartung von Rauchwarnmeldern oder Feuerlöschern.", "flaeche"),
]

KOSTENARTEN = [
    {"key": k, "nr": nr, "titel": titel, "beschreibung": beschr, "schluessel": schl}
    for k, nr, titel, beschr, schl in _KOSTENARTEN
]
