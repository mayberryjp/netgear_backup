import re

import requests
import urllib3

from netgear_backup.config import Settings

_GAMBIT_RE = re.compile(r"Gambit=([A-Za-z0-9]+)")


class NetgearError(Exception):
    pass


def _login(session: requests.Session, settings: Settings, base: str) -> str:
    """Log in to the switch web UI and return the Gambit session token."""
    resp = session.post(
        f"{base}{settings.login_path}",
        data={
            settings.login_username_field: settings.username,
            settings.login_password_field: settings.password,
        },
        timeout=settings.request_timeout_seconds,
    )
    resp.raise_for_status()

    token = session.cookies.get("gambitCookie")
    if not token:
        match = _GAMBIT_RE.search(resp.text)
        token = match.group(1) if match else None
    if not token:
        raise NetgearError("login failed: no gambit token returned")
    return str(token)


def download_config(settings: Settings) -> bytes:
    """Return the switch startup-config bytes."""
    if not settings.verify_tls:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    base = settings.base_url.rstrip("/")

    with requests.Session() as session:
        session.verify = settings.verify_tls

        token = settings.gambit or _login(session, settings, base)
        session.cookies.set("gambitCookie", token)

        resp = session.get(
            f"{base}/iss/file/get/startup-config",
            params={"Gambit": token},
            headers={"Referer": f"{base}/homepage.html"},
            timeout=settings.request_timeout_seconds,
        )
        resp.raise_for_status()

        head = resp.content[:512].lstrip().lower()
        if not resp.content or head.startswith((b"<!doctype", b"<html")):
            raise NetgearError("response is not a startup-config (session invalid?)")
        return resp.content
