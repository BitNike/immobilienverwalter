# Immobilien und Mietobjekte

## Begriffe

**Immobilie** (das Gebäude) → **Mietobjekt** (Wohnung, Gewerbeeinheit, Garage) → **Mietverhältnis** (ein oder mehrere Mieter).

## Immobilie

Reiter **Stammdaten** (nur Administrator):

- Name, Anschrift, Absender für die Briefe
- **Bankverbindung** (IBAN, Bank, Kontoinhaber). Sie steht in der Zahlungsaufforderung und im GiroCode.
- Haken **Wohnungseigentümergemeinschaft (WEG)**: schaltet die Eigentümer-Abrechnung, das Hausgeld und den Vermögensbericht frei.
  Siehe [WEG](12-weg.md).

Unten in den Stammdaten kannst du die Immobilie **archivieren** (ausgeblendet, über „Archiv“ links unten wiederherstellbar)
oder **löschen** (mit allen Mietobjekten; hochgeladene Dateien bleiben im Dokumentenordner).

## Mietobjekt

Reiter **Stammdaten**:

| Feld | Wofür |
|---|---|
| Bezeichnung | z. B. „Wohnung 3“. Die Sortierung ist natürlich: Wohnung 2 vor Wohnung 10. |
| Haus / Eingang | nur bei mehreren Häusern in einer Immobilie, z. B. „Haus 13“. Gleiche Angabe = gleiches Haus. |
| Wohnfläche | für Kosten nach Wohnfläche |
| MEA | Miteigentumsanteile laut Teilungserklärung, z. B. 86,13 (bei 1.000 MEA insgesamt) |
| Eigentümer | Empfänger der Eigentümer-Abrechnung |
| Umlageschlüssel (Text für die Abrechnung) | freier Text, der im Brief steht, z. B. „Heizung nach Verbrauch laut Messdienst“ |
| Konto für die Mieter-Abrechnung | falls der Eigentümer ein eigenes Konto hat; sonst gilt das Konto der Immobilie |
| Mieter rechnet der Eigentümer selbst ab | für WEG-Wohnungen, deren Mieter du nicht kennst; dann gibt es nur die Eigentümer-Abrechnung |

Wohnfläche und MEA werden von Hand eingetragen (aus Kaufvertrag oder Teilungserklärung) und nicht berechnet.
Die Übersicht der Immobilie zeigt die Summe der MEA und warnt, wenn sie nicht 1.000/1.000 bzw. 100 % ergibt.

Vorgefertigte Mietobjekte, die du keiner Immobilie zuordnest, verwaltest du unter **Einstellungen → Mietobjekte (Wohnungen)**.

## Mehrere Häuser in einer Immobilie

Manche Gemeinschaften bestehen aus mehreren Häusern, und die Teilungserklärung verteilt einzelne Kosten nur auf ein Haus
(z. B. Instandhaltung des Treppenhauses). Dafür:

1. Bei jedem Mietobjekt **Haus / Eingang** eintragen.
2. Bei einer Buchung mit Kostenart erscheint dann die Auswahl **„alle Häuser / nur Haus …“**.

Kosten „nur Haus 13“ werden nur auf die Wohnungen dieses Hauses verteilt. Bei MEA zählt das Verhältnis innerhalb des Hauses,
z. B. „86,13 von 332,00 MEA (Haus 13)“.
