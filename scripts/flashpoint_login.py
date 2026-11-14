"""Sign in to Flashpoint's MCP server (standard MCP OAuth) and save the token to .env.

    python3 scripts/flashpoint_login.py

Opens your browser, you sign in to Flashpoint, and the token is written to
FLASHPOINT_TOKEN in .env (which git ignores). Uses OAuth 2.1 authorization code
+ PKCE with dynamic client registration, as the MCP spec describes.
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import json
import re
import secrets
import sys
import threading
import urllib.parse
import webbrowser
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
RESOURCE = "https://api.flashpoint.ai/mcp"
PORT = 8765
REDIRECT = f"http://localhost:{PORT}/callback"


def discover(issuer: str) -> dict:
    base = issuer.rstrip("/")
    for path in ("/.well-known/oauth-authorization-server", "/.well-known/openid-configuration"):
        r = httpx.get(base + path, timeout=20)
        if r.status_code == 200:
            return r.json()
    sys.exit(f"Could not find OAuth metadata at {base}/.well-known/oauth-authorization-server")


def register(meta: dict) -> tuple[str, str | None]:
    if not meta.get("registration_endpoint"):
        sys.exit("Flashpoint doesn't allow self-registration. Ask the mentors for a client id or a token.\n"
                 + json.dumps(meta, indent=2))
    r = httpx.post(
        meta["registration_endpoint"],
        json={
            "client_name": "Wording Stress-Tester (hackathon)",
            "redirect_uris": [REDIRECT],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
        timeout=20,
    )
    if r.status_code >= 400:
        sys.exit(f"Client registration failed ({r.status_code}): {r.text[:500]}")
    j = r.json()
    return j["client_id"], j.get("client_secret")


class _Handler(http.server.BaseHTTPRequestHandler):
    result: dict = {}

    def do_GET(self):  # noqa: N802
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _Handler.result = {k: v[0] for k, v in q.items()}
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<h2>Signed in. You can close this tab and go back to Terminal.</h2>")

    def log_message(self, *a):
        pass


def save_token(token: str) -> None:
    env = ROOT / ".env"
    text = env.read_text() if env.exists() else ""
    if re.search(r"^FLASHPOINT_TOKEN=.*$", text, re.M):
        text = re.sub(r"^FLASHPOINT_TOKEN=.*$", f"FLASHPOINT_TOKEN={token}", text, flags=re.M)
    else:
        text += f"\nFLASHPOINT_TOKEN={token}\n"
    env.write_text(text)


def main():
    meta = discover("https://api.flashpoint.ai")
    client_id, client_secret = register(meta)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        "resource": RESOURCE,
    }
    url = meta["authorization_endpoint"] + "?" + urllib.parse.urlencode(params)

    server = http.server.HTTPServer(("localhost", PORT), _Handler)
    threading.Thread(target=server.handle_request, daemon=True).start()
    print("Opening your browser to sign in to Flashpoint...\nIf it doesn't open, paste this link:\n" + url)
    webbrowser.open(url)
    server_thread_wait = 300
    import time

    t0 = time.time()
    while not _Handler.result and time.time() - t0 < server_thread_wait:
        time.sleep(0.5)
    res = _Handler.result
    if not res:
        sys.exit("Timed out waiting for sign-in.")
    if res.get("state") != state or "code" not in res:
        sys.exit(f"Sign-in failed: {res}")

    data = {
        "grant_type": "authorization_code",
        "code": res["code"],
        "redirect_uri": REDIRECT,
        "client_id": client_id,
        "code_verifier": verifier,
        "resource": RESOURCE,
    }
    if client_secret:
        data["client_secret"] = client_secret
    r = httpx.post(meta["token_endpoint"], data=data, timeout=30)
    if r.status_code >= 400:
        sys.exit(f"Token exchange failed ({r.status_code}): {r.text[:500]}")
    token = r.json()["access_token"]
    save_token(token)
    print("Signed in. Token saved to .env (git ignores it). Now run: python3 scripts/flashpoint_probe.py")


if __name__ == "__main__":
    main()
