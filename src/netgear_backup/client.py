import hashlib
import re

import requests
import urllib3

from netgear_backup.config import Settings

_GAMBIT_RE = re.compile(r"""name=['"]Gambit['"]\s+value=['"]([A-Za-z0-9]+)['"]""")
_RAND_RE = re.compile(r"""id=['"]rand['"]\s+value=['"](\d+)['"]""")


def _merge(a: str, b: str) -> str:
    """Interleave two strings character by character, as the switch login JS does."""
    out: list[str] = []
    for i in range(max(len(a), len(b))):
        if i < len(a):
            out.append(a[i])
        if i < len(b):
            out.append(b[i])
    return "".join(out)


class NetgearError(Exception):
    pass


def _login(session: requests.Session, settings: Settings, base: str) -> str:
    """Log in to the switch web UI and return the Gambit session token."""
    timeout = settings.request_timeout_seconds
    page = session.get(f"{base}/", timeout=timeout)
    page.raise_for_status()
    rand = _RAND_RE.search(page.text)
    if not rand:
        raise NetgearError("login failed: rand not found on login page")

    # The switch expects md5(interleave(password, rand)); not used for security.
    digest = hashlib.md5(_merge(settings.password, rand.group(1)).encode()).hexdigest()  # nosec B324
    resp = session.post(
        f"{base}{settings.login_path}",
        data={settings.login_password_field: digest},
        timeout=timeout,
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
