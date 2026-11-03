# Mieter, Mietkonto und Kosten der Wohnung

## Mietverhältnis anlegen

Mietobjekt → Reiter **Mieter**:

| Feld | Hinweis |
|---|---|
| Personen | eine oder mehrere (Paare, WG) über + |
| Einzug, Auszug | Die Kosten werden nach **Monaten** aufgeteilt. |
| NK-Vorauszahlung / Monat | Vorschlag für die Abrechnung |
| Kaltmiete, Mietart, Nächste Mietanpassung, Befristet bis | Angaben zum Mietvertrag, mit Erinnerung (siehe [Verträge](09-vertraege.md)) |
| Kaution | zum Im-Blick-Behalten; steht auch in der Übersicht Mietverträge (Reiter Verträge) |
| Neue Anschrift nach Auszug | für die Abschlussrechnung |

Jedes Mietverhältnis bekommt eine fortlaufende Nummer und einen Ordner, z. B. `001 - Muster`.
Die Nummer bleibt dauerhaft.

Zeiten ohne Mieter sind **Leerstand**. Die Kosten dafür trägt der Eigentümer.

## Vorauszahlungen

Im Reiter **Abrechnung** stehen je Mieter Monate, Kosten, Vorauszahlungen und Ergebnis.
Die Vorauszahlung ist zunächst nur aus dem Monatsbetrag **vorgeschlagen**. Prüfe sie und speichere mit
**„Vorauszahlungen speichern“**. Bis dahin meldet die Liste „Bitte prüfen“ einen Fehler.

## Kosten der Wohnung

Manche Kosten betreffen nur ein Mietobjekt, z. B. Grundsteuer, Müllgebühr oder die Heizkostenabrechnung des Messdienstes.
Du erfasst sie im Reiter **Abrechnung** unter der Kostenaufstellung:

| Zuordnung | Verteilung |
|---|---|
| Wohnung – zeitanteilig auf die Mieter | nach Monaten auf alle Mieter des Jahres, Rest Leerstand |
| Für Mieter … (100 %) | ganz für diesen Mieter, z. B. eine Einzelabrechnung des Messdienstes, die bereits seinen Zeitraum abdeckt |

**Bei einer WEG** gibt es zusätzlich die Auswahl **Bezahlt**:

| Bezahlt | Beispiel | Mieter-Abrechnung | Eigentümer-Abrechnung (gegen das Hausgeld) |
|---|---|---|---|
| über die WEG | Heizkostenabrechnung, wenn die Gemeinschaft den Brennstoff bezahlt | ja | ja |
| Eigentümer direkt | Müllgebühr, Grundsteuer: der Bescheid geht an den Eigentümer | ja | nein |

Direkt gezahlte Kosten stehen in der Kostenaufstellung mit dem Zusatz „zahlt der Eigentümer direkt“.
In der Zeile Eigentümer-Abrechnung steht dann „ohne … € direkt gezahlt“.

Kosten, die das ganze Haus betreffen, gehören zu den **Gebäudekosten** der Immobilie (Reiter Buchungen), nicht hierher.
Die Kostenaufstellung zeigt sie mit dem Zusatz „Gebäudekosten der Immobilie“.

## Mietkonto: Miete und Zahlungen Monat für Monat

Für die Nebenkostenabrechnung brauchst du das Mietkonto nicht. Es hilft, wenn Mieter **Miete und Nebenkosten in einer
Summe** überweisen und du den Überblick über **Rückstände** behalten oder sie belegen musst, z. B. gegenüber einem Anwalt.

Mietobjekt → Reiter **Mietkonto**, je Mieter und Jahr:

| Spalte | Inhalt |
|---|---|
| Soll | Kaltmiete + NK-Vorauszahlung aus dem Mietverhältnis. Über den Stift für einen Monat änderbar, z. B. bei Einzug zur Monatsmitte |
| gezahlt, am | was eingegangen ist; mehrere Teilbeträge eines Monats zusammenzählen und unter Bemerkung festhalten |
| offen, Saldo | Differenz des Monats und laufender Stand; Saldo > 0 = Rückstand, < 0 = Guthaben des Mieters |
| Bemerkung | z. B. „Rest angekündigt“, „Mahnung 10.06.“ |

So funktioniert es:

- Das Konto **beginnt mit dem ersten Monat, für den du eine Zahlung einträgst**. Ab dann gelten fällige Monate ohne Eintrag
  als nicht bezahlt; frühere Monate zählen nicht. Du musst also nicht rückwirkend alle Jahre nachtragen.
- **„Fällige Monate als bezahlt eintragen“** trägt bei allen fälligen Monaten ohne Zahlung das Soll ein. Danach pflegst du nur
  noch die Ausreißer. Vorhandene Einträge bleiben unverändert.
- Ändert sich die Miete im Mietverhältnis, behalten die bereits fälligen Monate ihr bisheriges Soll.
- **Weitere Forderung oder Gutschrift:** z. B. eine Mahngebühr. Das Ergebnis der Betriebskostenabrechnung des Vorjahres
  übernimmst du mit einem Klick („Ins Mietkonto übernehmen“); ein Guthaben steht mit Minus darin.
- Der Saldo wird ins nächste Jahr übertragen.
- Wird das Mietkonto geführt und steht das Ergebnis der Betriebskostenabrechnung des Vorjahres noch nicht darin, erinnert
  die Liste **„Bitte prüfen“** daran.
- Besteht ein Rückstand, meldet ihn die Liste **„Bitte prüfen“** bei Mietobjekt und Immobilie. Ab zwei Monatsmieten steht
  dort zusätzlich ein Hinweis auf § 543 BGB (fristlose Kündigung). Vorher bitte rechtlich beraten lassen.
- **Ansicht** und **PDF** erzeugen eine Aufstellung für das gewählte Jahr, **„PDF seit …“** über alle Jahre seit Beginn des
  Kontos: Monat, Soll, Zahlung mit Datum, offen, Saldo und Bemerkung, am Ende der offene Betrag.

Das Mietkonto sehen Administratoren und der Eigentümer des Mietobjekts; eintragen dürfen Administratoren und Vermieter +.
Bei „Mieter rechnet der Eigentümer selbst ab“ gibt es den Reiter nicht.

## Was trägt der Mieter, was der Eigentümer?

- Der Mieter zahlt seinen Anteil an den **umlagefähigen** Kosten für die Monate seines Mietverhältnisses.
- Der Eigentümer trägt **Leerstand** und **nicht umlagefähige** Kosten (z. B. Verwaltung, Instandhaltung, Rücklage).
- Die Zeile „Leerstand / nicht umlagefähig – trägt der Eigentümer“ zeigt diesen Betrag.
