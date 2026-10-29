# Verträge und Erinnerungen

## Verträge

Reiter **Verträge** bei der Immobilie (pflegt der Administrator) und beim Mietobjekt (wer das Mietobjekt bearbeiten darf).
Beispiele: Strom für den Flur, Gebäudeversicherung, Wartung der Heizung, Hausmeister.

| Feld | Hinweis |
|---|---|
| Vertrag, Anbieter, Kontakt, Vertragsnummer, Kundennummer | |
| Kostenart | ordnet den Vertrag einer Kostenart zu |
| Betrag, Zahlweise | für die Kosten im Jahr |
| Beginn, Vertragsende (erste Laufzeit), Verlängerung, Kündigungsfrist, Gekündigt zum | daraus berechnet die App den **nächsten Kündigungstermin** |
| Preisgarantie bis | |
| Tarif | optional: Arbeitspreis, Grundpreis, Verbrauch |
| Zähler | Haken bei den Zählern, die zu diesem Vertrag gehören (auch mehrere) |
| Unterlagen | Dateien anhängen oder vorhandene Dokumente aus der Ablage verbinden |

Die Liste zeigt je Vertrag den Status, die Kosten im Jahr, die verbundenen Zähler mit **„Verbrauch <Jahr> laut Zähler“**
und die Unterlagen. Angehängte Dateien landen in der Ablage unter „Verträge & Versicherungen“ und bleiben dort,
auch wenn der Vertrag gelöscht wird.

**Vertrag und Buchungen:** Der Betrag im Vertrag ist der vereinbarte Preis, er bucht noch nichts.
Gebucht wird im Reiter Buchungen nach Rechnung bzw. Kontoauszug, denn die tatsächlichen Beträge weichen oft ab
(Beitragsanpassung, Nachzahlung). Hat ein Vertrag der Immobilie eine **Kostenart**, zeigt die Liste unter den Kosten:

- „gebucht 2026: …“, wenn es Buchungen dieser Kostenart im Jahr gibt
- „Dauerauftrag 2026 vorhanden, noch nicht gebucht“
- „2026 noch nicht gebucht“ mit dem Knopf **„Dauerauftrag anlegen“**: legt einen passenden Dauerauftrag
  fürs angezeigte Jahr an, den du im Reiter Buchungen prüfst und buchst

Ohne Kostenart steht dort „ohne Kostenart“, dann ist der Vertrag nicht mit den Buchungen verbunden.

## Mietverträge

Mietverträge sind keine eigenen Verträge. Kaltmiete, Mietart (Staffel-/Indexmiete), nächste Mietanpassung und
Befristung stehen direkt am Mietverhältnis (Reiter **Mieter**). Der Reiter Verträge des Mietobjekts zeigt sie als Übersicht.

## Erinnerungen per E-Mail

**Einstellungen → Erinnerungen** (nur Administrator):

- an/aus und **Vorlauf** (Standard 30 Tage)
- **Empfänger** per Haken je Benutzer; optional bekommen Eigentümer die Termine ihrer Mietobjekte
- Liste „Anstehend“
- **„Jetzt prüfen und senden“** verschickt fällige Erinnerungen sofort, **„Beispiel an mich senden“** zeigt eine Muster-Mail, ohne etwas als erledigt zu markieren.

Erinnert wird an Kündigungsfristen, das Ende von Preisgarantien und Befristungen sowie an Mietanpassungen.
Jeder Termin wird nur einmal gemeldet. Die App prüft alle sechs Stunden und schickt je Empfänger eine Sammel-Mail.
Voraussetzung: E-Mail-Versand ist eingerichtet (Einstellungen → SMTP / E-Mail) und der Empfänger hat eine E-Mail-Adresse.
