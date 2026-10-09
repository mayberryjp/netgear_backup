import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from netgear_backup.client import download_config
from netgear_backup.config import Settings, device_settings, load_settings
from netgear_backup.logging import configure_logging, get_logger

log = get_logger("worker.backup")


def _host_label(base_url: str) -> str:
    return (urlparse(base_url).hostname or "netgear").replace(":", "_")


def run_backup(settings: Settings) -> Path:
    data = download_config(settings)
    out_dir = Path(settings.backup_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    prefix = f"startup-config-{_host_label(settings.base_url)}-"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = out_dir / f"{prefix}{stamp}.cfg"
    tmp = target.with_suffix(".cfg.tmp")
    tmp.write_bytes(data)
    tmp.replace(target)

    if settings.retention_count > 0:
        old = sorted(out_dir.glob(f"{prefix}*.cfg"))[: -settings.retention_count]
        for path in old:
            path.unlink()
            log.info("removed old backup %s", path.name)
    return target


def backup_with_retries(settings: Settings) -> None:
    for attempt in range(1, settings.max_attempts + 1):
        try:
            target = run_backup(settings)
            log.info("backup saved to %s", target)
            return
        except Exception:
            log.exception(
                "backup attempt %d/%d failed for %s", attempt, settings.max_attempts, settings.base_url
            )
            if attempt < settings.max_attempts:
                time.sleep(settings.retry_delay_seconds)


def main() -> None:
    settings = load_settings()
    configure_logging(settings.log_level)
    log.info("starting; interval=%ss dir=%s", settings.interval_seconds, settings.backup_dir)
    targets = device_settings(settings)
    while True:
        for target in targets:
            backup_with_retries(target)
        time.sleep(settings.interval_seconds)


if __name__ == "__main__":
    main()
