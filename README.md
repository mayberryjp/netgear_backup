# netgear-backup

Long-running worker that fetches the Netgear switch `startup-config` (`/iss/file/get/startup-config`)
and saves it to a volume every `NETGEAR_INTERVAL_SECONDS` (default 24h), keeping the newest
`NETGEAR_RETENTION_COUNT` files.

The switch authenticates with a `Gambit` session token. By default the worker logs in with
`NETGEAR_USERNAME` / `NETGEAR_PASSWORD` to obtain one. If your firmware's login form differs, set
`NETGEAR_LOGIN_PATH`, `NETGEAR_LOGIN_PASSWORD_FIELD`. The defaults match the GS316EPP (password only,
sent as `md5(interleave(password, rand))` to `/redirect.html`). Alternatively set
`NETGEAR_GAMBIT` to a token copied from the browser (it expires with the web session).

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
