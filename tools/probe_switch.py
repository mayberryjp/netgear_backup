"""Standalone Netgear switch probe (stdlib only). Run from a host on the switch's LAN segment.

    set SW_PW=yourpassword            (PowerShell: $env:SW_PW='...')
    python probe_switch.py 10.3.30.2

Logs in (both known firmware flavours), crawls the web UI, saves every file under ./probe_out/<host>/
and prints candidate backup/config endpoints. Skips reset/reboot/firmware-style URLs.
Password and session ids are redacted from everything it prints or saves.
"""

import gzip
import hashlib
import os
import re
import socket
import sys
import time
import zlib

HOST = sys.argv[1]
PW = os.environ.get("SW_PW", "")
OUT = os.path.join("probe_out", HOST)
os.makedirs(OUT, exist_ok=True)
SKIP = re.compile(r"reset|reboot|restart|factory|erase|upgrade|firmware|logout|delete|clear", re.I)
KEYS = re.compile(r"backup|restore|config|download|upload|save|export|import", re.I)
cookies: dict[str, str] = {}
gambit = ""
secrets: set[str] = set()


def redact(text: str) -> str:
    for s in secrets:
        if s:
            text = text.replace(s, "<redacted>")
    return text


def dechunk(b: bytes) -> tuple[bytes, bool]:
    out, i = b"", 0
    while True:
        j = b.find(b"\r\n", i)
        if j < 0:
            return out, False
        try:
            n = int(b[i:j].split(b";")[0], 16)
        except ValueError:
            return out, False
        if n == 0:
            return out, True
        if len(b) < j + 2 + n:
            return out + b[j + 2:], False
        out += b[j + 2:j + 2 + n]
        i = j + 2 + n + 2


def once(method: str, path: str, body: bytes = b"", timeout: float = 6.0):
    hdr = [f"{method} {path} HTTP/1.1", f"Host: {HOST}", "Connection: close",
           "Accept-Encoding: gzip", "User-Agent: Mozilla/5.0"]
    if cookies:
        hdr.append("Cookie: " + "; ".join(f"{k}={v}" for k, v in cookies.items()))
    if method == "POST":
        hdr += ["Content-Type: application/x-www-form-urlencoded", f"Content-Length: {len(body)}"]
    req = ("\r\n".join(hdr) + "\r\n\r\n").encode() + body
    buf = b""
    s = socket.create_connection((HOST, 80), timeout=timeout)
    try:
        s.sendall(req)
        while chunk := s.recv(4096):
            buf += chunk
            if b"\r\n\r\n" in buf:
                head, _, rest = buf.partition(b"\r\n\r\n")
                h = head.lower()
                m = re.search(rb"content-length:\s*(\d+)", h)
                if m and len(rest) >= int(m.group(1)):
                    break
                if b"chunked" in h and dechunk(rest)[1]:
                    break
    except OSError:
        pass
    finally:
        s.close()
    head, _, rest = buf.partition(b"\r\n\r\n")
    lines = head.decode("latin1").split("\r\n")
    status = int(lines[0].split()[1]) if lines and lines[0].startswith("HTTP") else 0
    headers: dict[str, str] = {}
    for ln in lines[1:]:
        if ":" in ln:
            k, v = ln.split(":", 1)
            headers.setdefault(k.strip().lower(), v.strip())
            if k.strip().lower() == "set-cookie":
                name, _, val = v.strip().split(";")[0].partition("=")
                cookies[name] = val
                secrets.add(val)
    complete = False
    if "chunked" in headers.get("transfer-encoding", ""):
        rest, complete = dechunk(rest)
    elif "content-length" in headers:
        complete = len(rest) >= int(headers["content-length"])
    else:
        complete = rest.rstrip().endswith((b"</html>", b"}", b";"))
    if headers.get("content-encoding") == "gzip" and rest:
        try:
            rest = zlib.decompressobj(31).decompress(rest)
        except zlib.error:
            complete = False
    return status, headers, rest, complete


def fetch(method: str, path: str, body: bytes = b"", tries: int = 8):
    best = (0, {}, b"", False)
    for n in range(tries):
        try:
            r = once(method, path, body)
        except OSError as e:
            print(f"    {path} try {n + 1}: {type(e).__name__}")
            time.sleep(1)
            continue
        if len(r[2]) >= len(best[2]):
            best = r
        if r[3]:
            return r
        print(f"    {path} try {n + 1}: partial {len(r[2])} bytes")
    return best


def unpack(js: str) -> str:
    """Expand the firmware's LZ-style eval((function(x){...})("...")) wrappers."""
    out = js
    for m in re.finditer(r'return d\}\)\("((?:[^"\\]|\\.)*)"\)\)', js, re.S):
        x = m.group(1).encode("latin1", "replace").decode("unicode_escape")
        d, p = "", 0
        while p < len(x):
            if x[p] != "`":
                d += x[p]
                p += 1
                continue
            n = ord(x[p + 3]) - 28
            if n > 4:
                start = len(d) - ord(x[p + 1]) * 96 - ord(x[p + 2]) + 3104 - n
                d += d[start:start + n]
            else:
                d += "`"
            p += 4
        out += "\n/* unpacked */\n" + d
    return out


def merge(a: str, b: str) -> str:
    return "".join((a[i] if i < len(a) else "") + (b[i] if i < len(b) else "")
                   for i in range(max(len(a), len(b))))


def find_rand(path: str) -> str:
    for _ in range(10):
        _, _, body, _ = fetch("GET", path, tries=1)
        m = re.search(rb"""id=['"]rand['"]\s+value=['"](\d+)""", body)
        if m:
            return m.group(1).decode()
    sys.exit(f"rand not found on {path} after 10 tries")


def login() -> str:
    global gambit
    secrets.add(PW)
    _, _, root, _ = fetch("GET", "/", tries=4)
    flavor = "cgi" if b"login.cgi" in root else "redirect"
    print("flavor:", flavor)
    page, field = ("/login.cgi", "password") if flavor == "cgi" else ("/", "LoginPassword")
    post = "/login.cgi" if flavor == "cgi" else "/redirect.html"
    rand = find_rand(page)
    digest = hashlib.md5(merge(PW, rand).encode()).hexdigest()
    status, headers, body, complete = fetch("POST", post, f"{field}={digest}".encode(), tries=3)
    print("login status", status, "complete", complete, "cookies", sorted(cookies))
    m = re.search(rb"""name=['"]Gambit['"]\s+value=['"]([A-Za-z0-9]+)""", body)
    if m:
        gambit = m.group(1).decode()
        secrets.add(gambit)
        cookies["gambitCookie"] = gambit
        print("gambit token obtained")
    elif not cookies:
        print("LOGIN FAILED; response head:", redact(body[:300].decode("latin1")))
    return flavor


def diagnostics() -> None:
    print("== transfer reliability: 6 x GET /")
    for i in range(6):
        t0 = time.time()
        try:
            st, h, b, c = once("GET", "/")
            print(f"  {i}: status={st} bytes={len(b)} complete={c} {time.time() - t0:.1f}s")
        except OSError as e:
            print(f"  {i}: {type(e).__name__}")


def main() -> None:
    diagnostics()
    flavor = login()
    start = "/index.cgi" if flavor == "cgi" else "/homepage.html"
    queue, seen, found = [start], set(), []
    pat = re.compile(rb"""['"=(]\s*(/?[\w./-]+\.(?:js|cgi|htm|html|cfg|bin|lua)(?:\?[\w=&%.-]*)?)""")
    while queue and len(seen) < 80:
        path = queue.pop(0)
        if path in seen or SKIP.search(path):
            continue
        seen.add(path)
        url = "/" + path.lstrip("/")
        if gambit and "Gambit=" not in url and not url.endswith((".js", ".css")):
            url += ("&" if "?" in url else "?") + f"Gambit={gambit}"
        st, h, body, ok = fetch("GET", url)
        if "javascript" in h.get("content-type", ""):
            body = unpack(body.decode("latin1")).encode("latin1", "replace")
        name = re.sub(r"[^\w.-]", "_", path.strip("/")) or "root"
        with open(os.path.join(OUT, name), "wb") as f:
            f.write(redact(body.decode("latin1")).encode("latin1"))
        print(f"{'OK ' if ok else 'PART'} {st} {len(body):6d} {h.get('content-type', '')[:28]:28s} {path}")
        if st != 200:
            continue
        for m in pat.finditer(body):
            p = m.group(1).decode()
            if p not in seen and not p.endswith((".css", ".png", ".svg")):
                queue.append(p)
        text = body.decode("latin1")
        for mm in KEYS.finditer(text):
            ctx = text[max(0, mm.start() - 50):mm.end() + 70].replace("\n", " ")
            if re.search(r"\.(cgi|htm|html|cfg|bin)", ctx):
                found.append((path, redact(ctx)))
    print(f"\n== candidate endpoints ({len(found)}); files saved in {OUT}")
    for p, c in found[:60]:
        print(f"  [{p}] ...{c}...")


main()
