import hashlib
import re
import time

import requests
import urllib3

from netgear_backup.config import Settings

_GAMBIT_RE = re.compile(r"""name=['"]Gambit['"]\s+value=['"]([A-Za-z0-9]+)['"]""")
_RAND_RE = re.compile(r"""id=['"]rand['"]\s+value=['"](\d+)['"]""")
_PAGE_TRIES = 5


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


def _digest(password: str, rand: str) -> str:
    # The switch expects md5(interleave(password, rand)); not used for security.
    return hashlib.md5(_merge(password, rand).encode()).hexdigest()  # nosec B324


def _get_rand(session: requests.Session, url: str, timeout: int) -> str:
    """Fetch a login page until it contains the rand field; some switches truncate pages."""
    last = "no response"
    for _ in range(_PAGE_TRIES):
        try:
            page = session.get(url, timeout=timeout)
            page.raise_for_status()
        except requests.RequestException as exc:
            last = type(exc).__name__
            time.sleep(1)
            continue
        match = _RAND_RE.search(page.text)
        if match:
            return match.group(1)
        title = re.search(r"<title>(.*?)</title>", page.text, re.DOTALL | re.IGNORECASE)
        last = (
            f"status={page.status_code} title={title.group(1).strip() if title else None!r} "
            f"bytes={len(page.content)}"
        )
        time.sleep(1)
    raise NetgearError(f"login failed: rand not found at {url} ({last})")


def _download_redirect_flavor(session: requests.Session, settings: Settings, base: str) -> bytes:
    """GS316EPP / MS108EUP style: POST /redirect.html, Gambit token in a hidden form field."""
    timeout = settings.request_timeout_seconds
    token = settings.gambit
    if not token:
        rand = _get_rand(session, f"{base}/", timeout)
        resp = session.post(
            f"{base}/redirect.html",
            data={"LoginPassword": _digest(settings.password, rand)},
            timeout=timeout,
        )
        resp.raise_for_status()
        match = _GAMBIT_RE.search(resp.text)
        token = match.group(1) if match else session.cookies.get("gambitCookie", "")
        if not token:
            raise NetgearError("login failed: no gambit token returned")
    session.cookies.set("gambitCookie", token)

    resp = session.get(
        f"{base}/iss/file/get/startup-config",
        params={"Gambit": token},
        headers={"Referer": f"{base}/homepage.html"},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.content


def _download_cgi_flavor(session: requests.Session, settings: Settings, base: str) -> bytes:
    """GS308EPP style: POST /login.cgi sets a SID cookie; config at /confFile.cgi."""
    timeout = settings.request_timeout_seconds
    rand = _get_rand(session, f"{base}/login.cgi", timeout)
    resp = session.post(
        f"{base}/login.cgi",
        data={"password": _digest(settings.password, rand)},
        timeout=timeout,
    )
    resp.raise_for_status()
    if "SID" not in session.cookies:
        raise NetgearError("login failed: no SID cookie returned (wrong password?)")

    resp = session.get(f"{base}/confFile.cgi", params={"cmd": "backup_conf"}, timeout=timeout)
    resp.raise_for_status()
    return resp.content


def _detect_cgi_flavor(session: requests.Session, base: str, timeout: int) -> bool:
    resp = session.get(f"{base}/", timeout=timeout)
    resp.raise_for_status()
    return "login.cgi" in resp.text


def download_config(settings: Settings) -> bytes:
    """Return the switch config backup bytes."""
    if not settings.verify_tls:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    base = settings.base_url.rstrip("/")

    with requests.Session() as session:
        session.verify = settings.verify_tls

        if _detect_cgi_flavor(session, base, settings.request_timeout_seconds):
            data = _download_cgi_flavor(session, settings, base)
        else:
            data = _download_redirect_flavor(session, settings, base)

        head = data[:512].lstrip().lower()
        if not data or head.startswith((b"<!doctype", b"<html")):
            raise NetgearError("response is not a config backup (session invalid?)")
        return data
