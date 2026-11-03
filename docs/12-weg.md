# Wohnungseigentümergemeinschaft (WEG)

Bei einer WEG verteilst du die Kosten der Gemeinschaft auf die Eigentümer. Jeder Eigentümer rechnet danach selbst mit
seinem Mieter ab. Gehört dir eine der Wohnungen, erstellst du beides: die Eigentümer-Abrechnung für alle und die
Mieter-Abrechnung für deinen Mieter, ohne etwas doppelt zu erfassen.

## Einrichten

1. Immobilie → Stammdaten → Haken **Wohnungseigentümergemeinschaft (WEG)**.
2. Bei jedem Mietobjekt **MEA** laut Teilungserklärung und den **Eigentümer** eintragen (meist „ohne Zugang“).
3. Wohnungen, deren Mieter du nicht kennst: Haken **„Mieter rechnet der Eigentümer selbst ab“**.
4. Reiter **Umlageschlüssel:** Schlüssel je Kostenart laut Teilungserklärung bzw. Beschluss, mit Grundlage.
5. **Hausgeld** als Buchungen bzw. Daueraufträge erfassen (siehe [Buchungen](05-buchungen.md#hausgeld-nur-weg)).
6. **Rücklage:** Anfangsbestand, jährliche Zuführung, Konten (siehe [Rücklage](07-ruecklage.md)).

Die Übersicht zeigt die Tabelle **„Hausgeld der Eigentümer <Jahr>“**: je Wohnung Kosten, Hausgeld, Ergebnis und Export.

## Durchgerechnetes Beispiel

Musterhaus „Lindenhof 7“ mit vier Wohnungen und 1.000 MEA:

| Wohnung | MEA | Wasser (m³) |
|---|---|---|
| Wohnung 1 | 300 | 40 |
| Wohnung 2 | 250 | 30 |
| Wohnung 3 | 250 | 20 |
| Wohnung 4 | 200 | 10 |

Kosten des Jahres:

| Kostenart | Betrag | Schlüssel | Anteil Wohnung 2 |
|---|---|---|---|
| Gebäudeversicherung | 2.000,00 € | MEA | 500,00 € |
| Hausmeister | 1.200,00 € | Wohneinheiten | 300,00 € |
| Wasser / Abwasser | 1.000,00 € | Wasserverbrauch | 300,00 € |
| Zuführung Erhaltungsrücklage | 1.500,00 € | MEA | 375,00 € |
| **Summe** | | | **1.475,00 €** |

**Eigentümer-Abrechnung Wohnung 2:** Der Eigentümer hat 12 × 120,00 € = 1.440,00 € Hausgeld gezahlt.
Ergebnis: **35,00 € Nachzahlung** an die Gemeinschaft.

**Mieter-Abrechnung Wohnung 2:** Der Mieter ist am 01.04. eingezogen (9 von 12 Monaten), sein Wasserzähler zeigt 24 m³.

| Kostenart | Rechnung | Mieter |
|---|---|---|
| Gebäudeversicherung | 500,00 € × 9/12 | 375,00 € |
| Hausmeister | 300,00 € × 9/12 | 225,00 € |
| Wasser / Abwasser | 300,00 € × 24/30 m³ | 240,00 € |
| Rücklage | nicht umlagefähig | – |
| **Summe** | | **840,00 €** |

Vorauszahlungen 9 × 90,00 € = 810,00 €, also **30,00 € Nachzahlung** des Mieters an den Eigentümer.

Den Rest von 635,00 € trägt der Eigentümer: Leerstand Januar bis März (125,00 € + 75,00 € + 60,00 €) und die Rücklage (375,00 €).

## Eigene Wohnung mit Mieter: Schritt für Schritt

Am Beispiel oben: Dir gehört Wohnung 2 im Lindenhof 7, dein Mieter wohnt dort seit dem 01.04.

1. **Gebäudekosten der Gemeinschaft** erfasst du einmal bei der Immobilie (Reiter **Buchungen**), nicht bei der Wohnung.
   Die App verteilt sie nach MEA, Wohneinheiten oder Verbrauch auf alle Wohnungen und davon zeitanteilig auf deinen Mieter.
2. **Mieter** anlegen (Wohnung 2 → Reiter **Mieter**): Einzug 01.04., NK-Vorauszahlung je Monat.
3. **Kosten nur dieser Wohnung** (Reiter **Abrechnung** → „Kosten nur für diese Wohnung erfassen“). Zwei Fragen entscheiden:

   | Frage | Antwort | Auswahl |
   |---|---|---|
   | Gilt der Betrag für das ganze Jahr der Wohnung? | ja, z. B. Grundsteuerbescheid | **Wohnung – zeitanteilig auf die Mieter** |
   | | nein, nur für die Mietzeit, z. B. Einzelabrechnung des Messdienstes für den Mieter | **Für Mieter … (100 %)** |
   | Wer bezahlt die Rechnung? | die Gemeinschaft (Heizung, Wasser, Strom, Versicherung, Hausmeister) | **Bezahlt: über die WEG** |
   | | du selbst, der Bescheid geht an dich (Grundsteuer, Müll, Straßenreinigung) | **Bezahlt: Eigentümer direkt** |

4. **Vorauszahlungen** des Mieters prüfen und speichern: was er im Jahr tatsächlich gezahlt hat, nicht die Kosten.
5. **Hausgeld** deiner Wohnung als Buchung oder von Hand eintragen.
6. **Prüfen:** Mieteranteil + „Leerstand / nicht umlagefähig – trägt der Eigentümer“ = Summe Wohnung. Die Liste
   „Bitte prüfen“ meldet typische Verwechslungen, z. B. „direkt für Mieter“, obwohl er nicht das ganze Jahr da war, oder
   „Eigentümer direkt“ bei Kosten, die meist die Gemeinschaft zahlt.
7. Zwei Briefe exportieren: **Mieter** (an deinen Mieter) und **Eigentümer** (deine Abrechnung gegenüber der Gemeinschaft).

**Typische Fehler:**

- Jahreskosten der Wohnung aus einer alten WEG-Abrechnung von Hand übernommen und „Für Mieter (100 %)“ gewählt:
  Der Mieter zahlt dann auch die Monate vor seinem Einzug.
- Alle Posten auf „Eigentümer direkt“: Die Eigentümer-Abrechnung zeigt dann 0,00 € Kosten.
- Kostensumme als Vorauszahlung eingetragen: Das Ergebnis ist dann immer 0,00 €.
- Leerstand ist kein Fehler: Kosten für Monate ohne Mieter trägt der Eigentümer, sie stehen nicht im Mieterbrief.

## Gut zu wissen

- Die Mieter-Vorauszahlungen gehören **nicht** in die Eigentümer-Abrechnung, sie stehen dem Eigentümer zu.
- Kosten, die ein Eigentümer selbst bezahlt (Müllgebühr, Grundsteuer), trägst du beim Mietobjekt mit
  **„Bezahlt: Eigentümer direkt“** ein. Sie gehen an den Mieter, aber nicht in die Abrechnung gegenüber der Gemeinschaft.
- Gegenüber dem Mieter gilt grundsätzlich der Schlüssel der Gemeinschaft (§ 556a Abs. 3 BGB).
- Die Rücklage ist nicht umlagefähig und erscheint nur in der Eigentümer-Abrechnung, dort mit Entwicklung und Kontoständen auf Seite 2.
- Kosten nur eines Hauses (z. B. Treppenhaus) lassen sich mit **„nur Haus …“** buchen (siehe [Mehrere Häuser](03-immobilien-mietobjekte.md#mehrere-häuser-in-einer-immobilie)).
- Hausgeld für mehrere Wohnungen eines Eigentümers wird nie zwischen Immobilien vermischt.
