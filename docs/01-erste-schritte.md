# Erste Schritte

## Installation

Der Immobilienverwalter läuft als Docker-Container auf einem PC, Server, NAS oder Raspberry Pi.

1. Die Datei [`docker-compose.yml`](../docker-compose.yml) in einen eigenen Ordner legen,
   oder in Portainer, Dockge, Unraid bzw. dem Synology Container Manager einen neuen Stack anlegen und den Inhalt einfügen.
2. Starten: `docker compose up -d`
3. Im Browser öffnen: `http://<IP-des-Rechners>:8080`

Der Port lässt sich über `NK_PORT` in einer `.env`-Datei ändern (Vorlage: [`.env.example`](../.env.example)).
Dort trägst du auch die E-Mail-Zugangsdaten (SMTP) ein. Sie werden für „Passwort vergessen“, Einladungen und
Erinnerungen gebraucht und sind optional.

Wenn die App über eine eigene Adresse erreichbar ist (z. B. hinter einem Reverse Proxy), setze `APP_URL` in der `.env`.
Dann zeigen die Links in E-Mails auf diese Adresse.

## Einrichtung

Beim ersten Aufruf legst du den ersten Zugang an. Dieser Benutzer ist **Administrator**.
Danach geht es in dieser Reihenfolge weiter:

1. **Einstellungen → Logo & Brief:** Logo und Gestaltung des Briefs.
2. **Einstellungen → Kostenarten:** Die Liste ist vorbelegt (Grundsteuer, Wasser, Müll, Versicherungen …).
   Ergänze oder deaktiviere nach Bedarf.
3. **Immobilie anlegen** (+ in der linken Spalte), dann die **Mietobjekte** (+ in der mittleren Spalte).
4. Mieter, Zähler und Kosten eintragen, siehe die folgenden Kapitel.

## Aufbau der Oberfläche

| Bereich | Inhalt |
|---|---|
| Linke Spalte | Immobilien, + legt eine neue an (nur Administrator) |
| Mittlere Spalte | Mietobjekte der gewählten Immobilie |
| Kopfzeile rechts | Ordner (alle Dokumente), Zahnrad (Einstellungen), Profil |
| Jahr-Umschalter ‹ 2026 › | Jahr der Abrechnung; du arbeitest immer rückwirkend für ein Jahr |
| Reiter | Unterseiten der Immobilie bzw. des Mietobjekts |

Die beiden Spalten lassen sich mit dem Knopf «/» einklappen, praktisch auf kleinen Bildschirmen.
Der Zustand wird im Browser gemerkt.

**Reiter einer Immobilie:** Übersicht · Buchungen · Rücklage · Zähler · Verträge · Dokumente · Stammdaten · Umlageschlüssel

**Reiter eines Mietobjekts:** Abrechnung · Mieter · Zähler · Verträge · Dokumente · Stammdaten

Das Symbol ⓘ neben vielen Feldern erklärt kurz, was einzutragen ist. Fahre mit der Maus darüber oder tippe es an.

## Der Jahresablauf in Kürze

1. Jahr oben auf das Abrechnungsjahr stellen.
2. Gebäudekosten als **Buchungen** erfassen (Rechnungen, Daueraufträge).
3. **Zählerstände** zum Jahresende eintragen.
4. Beim Mietobjekt **Mieter**, **Vorauszahlungen** und die **Kosten der Wohnung** (z. B. Grundsteuer, Heizkostenabrechnung) prüfen.
5. Die Liste **„Bitte prüfen“** abarbeiten.
6. **Exportieren:** PDF mit Brief, Belegliste und Belegen.
