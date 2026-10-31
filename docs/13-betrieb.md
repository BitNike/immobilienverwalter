# Betrieb: Sicherung, Update, Rückweg

## Wo die Daten liegen

| Volume | Inhalt |
|---|---|
| `immobilienverwalter_daten` → `/data` | SQLite-Datenbank, Profilfotos, Logo |
| `immobilienverwalter_dokumente` → `/dokumente` | Belege und Ablage |

## Sicherung

```bash
docker run --rm -v immobilienverwalter_daten:/data -v immobilienverwalter_dokumente:/dokumente \
  -v "$PWD":/backup debian:bookworm-slim tar czf /backup/backup-$(date +%F).tgz /data /dokumente
```

Am besten vor jedem Update und regelmäßig, z. B. per Cronjob.

## Update

```bash
docker compose pull && docker compose up -d
```

Neue Versionen ändern die Datenbank nur, indem sie Spalten oder Tabellen ergänzen. Die Änderungen stehen in den
[Release-Notizen](https://github.com/BitNike/immobilienverwalter/releases).

## Rückweg auf eine ältere Version

1. In der `docker-compose.yml` statt `latest` eine feste Version eintragen, z. B.
   `image: ghcr.io/bitnike/immobilienverwalter:0.24.2`
2. `docker compose up -d`
3. Steht in den Release-Notizen, dass der Rückweg nicht ohne Weiteres geht, vorher die Sicherung einspielen.

## Gesundheitscheck

`/health` antwortet ohne Anmeldung mit der Version und prüft die Datenbank. Docker nutzt das für den Status „healthy“.

## E-Mail

E-Mail-Versand ist optional und wird in der `.env` eingerichtet (`SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY`, `SMTP_USER`,
`SMTP_PASSWORD`, `SMTP_FROM`, siehe [`.env.example`](../.env.example)). Unter **Einstellungen → SMTP / E-Mail** kannst du eine Testmail schicken.

## Sicherheit

Eingebaut:

- **Schutz vor untergeschobenen Formularen (CSRF):** Jedes Formular enthält ein geheimes Feld der Sitzung.
  Fehlt es oder passt es nicht, wird nichts gespeichert und es erscheint „Bitte noch einmal absenden“.
  Das passiert auch, wenn eine Seite sehr lange offen war. Dann die Seite neu laden und noch einmal speichern.
- Sitzungs-Cookie nur für die eigene Seite (`SameSite=Lax`, nicht per JavaScript lesbar).
- Sicherheits-Header gegen Einbetten in fremde Seiten und falsch erkannte Dateitypen.
- Passwörter nur als Hash, optional Zwei-Faktor-Anmeldung.

Die App ist für das Heimnetz gedacht. Bevor sie aus dem Internet erreichbar ist:

1. **HTTPS** über einen Reverse Proxy (z. B. Nginx Proxy Manager, Traefik, Caddy) und `APP_URL` auf die https-Adresse setzen.
2. **Starke Passwörter** und **Zwei-Faktor-Anmeldung** für Administratoren.
3. Regelmäßige **Sicherungen** und Updates.

Für Entwickler: `NK_CSRF=aus` schaltet den CSRF-Schutz ab (nur für Tests gedacht).
