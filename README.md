# netgear-backup

Long-running worker that downloads the config backup from Netgear web-managed switches and saves it
to a volume every `NETGEAR_INTERVAL_SECONDS` (default 24h), keeping the newest
`NETGEAR_RETENTION_COUNT` files per host.

Two firmware flavours are detected automatically; both log in with the password only (no username),
sent as `md5(interleave(password, rand))`:

- GS316EPP / MS108EUP: `POST /redirect.html`, then `/iss/file/get/startup-config?Gambit=<token>`.
  `NETGEAR_GAMBIT` may supply a browser token to skip login.
- GS308EPP: `POST /login.cgi` (sets a `SID` cookie), then `/confFile.cgi?cmd=backup_conf`.

The backup is a binary file for the switch's own restore; it is not human readable.

## Multiple devices

Set `NETGEAR_DEVICES` to a JSON list. Each entry needs `base_url` and may override `username`,
`password` and `gambit`; anything omitted inherits `NETGEAR_USERNAME` / `NETGEAR_PASSWORD`. Each device is
backed up in turn, and one failing does not stop the others. Files are named by host, and retention applies
per host.

## Run

    docker build -t netgear-backup:dev .
    docker compose up -d

Set `NETGEAR_PASSWORD` in `docker-compose.yml`. Backups land in the `netgear_backups` volume as
`startup-config-<host>-<YYYYmmdd-HHMMSS>.cfg`.

## Local

    python -m pip install -e ".[dev]"
    NETGEAR_PASSWORD=... NETGEAR_BACKUP_DIR=./backups python -m netgear_backup
