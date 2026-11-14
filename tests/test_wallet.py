"""x402 wallet payments against a fake Flashpoint server. Uses a throwaway key; no network, no real money."""
import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

pytest.importorskip("x402")
eth_account = pytest.importorskip("eth_account")

from stress_tester import wallet  # noqa: E402
from stress_tester.panel import flashpoint as fp  # noqa: E402

USDC = wallet.USDC["eip155:84532"]


def requirement(usd: str) -> dict:
    return {
        "x402Version": 2,
        "resource": {"url": "mcp://tool/panel", "description": "panel call"},
        "accepts": [{
            "scheme": "exact", "network": "eip155:84532", "asset": USDC,
            "amount": str(int(float(usd) * 1_000_000)), "payTo": "0x" + "ab" * 20,
            "maxTimeoutSeconds": 300, "extra": {"name": "USDC", "version": "2"},
        }],
    }


def fake_server(mode: str, usd: str):
    """mode 'http': HTTP 402 until a PAYMENT-SIGNATURE header arrives; 'inband': MCP isError until _meta payment."""
    seen = {"paid": 0}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if "id" not in body:
                self.send_response(202); self.end_headers(); return
            if body["method"] == "tools/call":
                params = body["params"]
                paid_http = bool(self.headers.get("PAYMENT-SIGNATURE"))
                paid_meta = "x402/payment" in (params.get("_meta") or {})
                if mode == "http" and not paid_http:
                    req = base64.b64encode(json.dumps(requirement(usd)).encode()).decode()
                    self.send_response(402); self.send_header("PAYMENT-REQUIRED", req)
                    self.send_header("Content-Type", "application/json"); self.end_headers()
                    self.wfile.write(b"{}"); return
                if mode == "inband" and not paid_meta:
                    result = {"isError": True, "structuredContent": requirement(usd),
                              "content": [{"type": "text", "text": json.dumps(requirement(usd))}]}
                else:
                    seen["paid"] += 1
                    result = {"content": [{"type": "text", "text": '{"ok": true}'}]}
            else:
                result = {"tools": []} if body["method"] == "tools/list" else {}
            out = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": result}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
            self.wfile.write(out)

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}/mcp", seen


@pytest.fixture
def env(monkeypatch, offline_workspace):
    monkeypatch.setenv("WALLET_PRIVATE_KEY", eth_account.Account.create().key.hex())
    monkeypatch.delenv("WALLET_ADDRESS", raising=False)
    monkeypatch.setenv("X402_NETWORK", "eip155:84532")
    monkeypatch.setenv("X402_MAX_PER_CALL_USD", "0.50")
    monkeypatch.setenv("X402_MAX_PER_RUN_USD", "0.08")
    monkeypatch.setattr(wallet, "_wallet", None)
    monkeypatch.setenv("FLASHPOINT_TOKEN", "")
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    return offline_workspace


@pytest.mark.parametrize("mode", ["http", "inband"])
def test_pays_once_and_logs(env, monkeypatch, mode):
    monkeypatch.setenv("X402_ENABLED", "true")
    srv, url, seen = fake_server(mode, "0.05")
    c = fp.MCPClient(url=url)
    res = c.call_tool("panel", {"action": "list"})
    srv.shutdown()
    assert not res.get("isError") and seen["paid"] == 1
    assert [p["usd"] for p in c.wallet.payments] == ["0.05"]
    ledger = (env / "outputs" / "x402_payments.jsonl").read_text().splitlines()
    assert len(ledger) == 1 and "PRIVATE" not in ledger[0]


@pytest.mark.parametrize("mode", ["http", "inband"])
def test_payments_off_never_pays(env, monkeypatch, mode):
    monkeypatch.setenv("X402_ENABLED", "false")
    srv, url, seen = fake_server(mode, "0.05")
    c = fp.MCPClient(url=url)
    with pytest.raises(wallet.PaymentNeeded):
        c.call_tool("panel", {})
    srv.shutdown()
    assert seen["paid"] == 0 and c.wallet is None


@pytest.mark.parametrize("mode", ["http", "inband"])
def test_per_call_cap_refuses(env, monkeypatch, mode):
    monkeypatch.setenv("X402_ENABLED", "true")
    srv, url, seen = fake_server(mode, "0.60")
    c = fp.MCPClient(url=url)
    with pytest.raises(Exception):
        c.call_tool("panel", {})
    srv.shutdown()
    assert seen["paid"] == 0 and c.wallet.payments == []


def test_per_run_cap_stops_second_payment(env, monkeypatch):
    monkeypatch.setenv("X402_ENABLED", "true")
    srv, url, seen = fake_server("inband", "0.05")
    c = fp.MCPClient(url=url)
    c.call_tool("panel", {})
    with pytest.raises(wallet.PaymentNeeded):
        c.call_tool("panel", {})  # 0.05 + 0.05 > 0.08 run cap
    srv.shutdown()
    assert seen["paid"] == 1 and len(c.wallet.payments) == 1


def test_mismatched_address_is_refused(env, monkeypatch):
    monkeypatch.setenv("WALLET_ADDRESS", "0x" + "11" * 20)
    with pytest.raises(RuntimeError, match="doesn't match"):
        wallet.Wallet()
