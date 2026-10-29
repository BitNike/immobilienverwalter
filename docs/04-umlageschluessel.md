# Umlageschlüssel und Kostenarten

## Kostenarten (für alle Immobilien)

Unter **Einstellungen → Kostenarten** pflegt der Administrator den Katalog: Name, Nummer nach § 2 BetrKV,
**umlagefähig** (darf an Mieter weitergegeben werden) und ein Standard-Schlüssel.
Eine Kostenart mit Haken **„Rücklage“** gilt als Zuführung zur Erhaltungsrücklage.

Nicht umlagefähige Kosten (z. B. Verwaltung, Instandhaltung, Rücklage) erscheinen nur in der Eigentümer-Abrechnung.

## Schlüssel

| Schlüssel | Verteilung |
|---|---|
| MEA | nach Miteigentumsanteilen |
| Wohnfläche | nach m² |
| Wohneinheiten | gleich je Mietobjekt |
| Wasserverbrauch | nach den Wasserzählern der Wohnungen |

Die Verteilung ist cent-genau: Die Anteile ergeben immer genau den Gesamtbetrag.

## Reiter „Umlageschlüssel“ einer Immobilie

Jede Immobilie hat eigene Regeln, weil jede Teilungserklärung und jeder Mietvertrag anders ist.
Im Reiter **Umlageschlüssel** (nur Administrator):

- **Standard-Umlageschlüssel** der Immobilie (z. B. MEA)
- je Kostenart ein eigener **Schlüssel** und die **Grundlage** als Text, z. B. „§ 13 Abs. 1 b Teilungserklärung“
  oder „Beschluss ETV 2026“. Die Grundlage erscheint bei den Gebäudekosten unter dem Schlüssel.
- **nicht genutzt:** Die Kostenart verschwindet aus den Auswahllisten der Immobilie.
  Beim Mietobjekt bleibt sie wählbar. Beispiel: Die Müllgebühr zahlt in einer WEG jeder Eigentümer selbst,
  also bei der WEG „nicht genutzt“, beim Mietobjekt als Kosten der Wohnung.
- Haken **„auf <Jahr> anwenden“**: setzt bereits vorhandene Gebäudekosten des Jahres auf die neue Regel.

Weicht eine Kostenposition von der Regel ab, meldet das die Liste „Bitte prüfen“.

## Welcher Schlüssel gilt gegenüber dem Mieter?

Bei einer vermieteten Eigentumswohnung gilt grundsätzlich der Schlüssel der Gemeinschaft auch gegenüber dem Mieter
(§ 556a Abs. 3 BGB), außer der Mietvertrag regelt etwas anderes. So rechnet die App:
Der Mieter bekommt den Anteil der Wohnung, zeitanteilig nach Monaten und nur die umlagefähigen Kosten.
