"""Optional x402 payments for Flashpoint: the program pays per call in USDC on Base.

Off unless X402_ENABLED=true in .env. When it's off (the default), or the x402
library isn't installed, Flashpoint calls work exactly as before with the
FLASHPOINT_TOKEN login, and any payment request stops the run instead of paying.

    X402_ENABLED=true
    WALLET_PRIVATE_KEY=0x...      # the program's own small wallet; never commit .env
    WALLET_ADDRESS=0x...          # optional; checked against the key
    X402_NETWORK=eip155:8453      # Base mainnet (eip155:84532 = Base Sepolia test net)
    X402_MAX_PER_CALL_USD=0.50    # refuse any single payment above this
    X402_MAX_PER_RUN_USD=2.00     # refuse payments once a run has spent this much

Install the extra libraries with `pip install -r requirements-wallet.txt`.
Every payment this program signs is appended to outputs/x402_payments.jsonl.
"""
from __future__ import annotations

import json
import os
import time
from decimal import Decimal
from typing import Any

from . import config

# USDC contract per network (6 decimals). Payments in any other asset are refused.
USDC = {
    "eip155:8453": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",   # Base
    "eip155:84532": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",  # Base Sepolia
}
LEGACY_NETWORK = {"base": "eip155:8453", "base-sepolia": "eip155:84532"}  # x402 v1 names


class PaymentNeeded(RuntimeError):
    """Flashpoint asked for payment and this program won't (or can't) pay."""


def enabled() -> bool:
    return os.getenv("X402_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


def _usd(name: str, default: str) -> Decimal:
    try:
        return Decimal(os.getenv(name, "").strip() or default)
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"{name} must be a dollar amount like 0.50") from e


def payment_required_in(obj: Any) -> Any:
    """Return the x402 PaymentRequired inside an MCP tool result or JSON-RPC error, else None."""
    if not isinstance(obj, dict):
        return None
    try:
        from x402.mcp.types import MCPToolResult
        from x402.mcp.utils import extract_payment_required_from_error, extract_payment_required_from_result
    except ImportError:
        # No library: still recognize the request so we can stop with a clear message.
        if obj.get("code") == 402 or (obj.get("isError") and "x402Version" in json.dumps(obj)):
            return obj
        return None
    if "code" in obj and "message" in obj:  # JSON-RPC error object
        return extract_payment_required_from_error(obj)
    if not obj.get("isError"):
        return None
    return extract_payment_required_from_result(
        MCPToolResult(
            content=obj.get("content") or [],
            is_error=True,
            meta=obj.get("_meta") or {},
            structured_content=obj.get("structuredContent"),
        )
    )


class Wallet:
    def __init__(self, max_per_call: Decimal | None = None, max_per_run: Decimal | None = None):
        try:
            from eth_account import Account
            from x402 import x402ClientSync
            from x402.mechanisms.evm import EthAccountSigner
            from x402.mechanisms.evm.exact import register_exact_evm_client
        except ImportError as e:
            raise RuntimeError(
                "X402_ENABLED=true but the wallet libraries aren't installed. "
                "Run: pip install -r requirements-wallet.txt"
            ) from e

        key = os.getenv("WALLET_PRIVATE_KEY", "").strip()
        if not key:
            raise RuntimeError("X402_ENABLED=true but WALLET_PRIVATE_KEY is missing from .env")
        self.account = Account.from_key(key)
        self.address = self.account.address
        want = os.getenv("WALLET_ADDRESS", "").strip()
        if want and want.lower() != self.address.lower():
            raise RuntimeError(
                f"WALLET_ADDRESS in .env ({want}) doesn't match the address of WALLET_PRIVATE_KEY ({self.address})"
            )
        self.network = os.getenv("X402_NETWORK", "eip155:8453").strip()
        if self.network not in USDC:
            raise RuntimeError(f"X402_NETWORK must be one of {sorted(USDC)}")
        self.max_per_call = max_per_call if max_per_call is not None else _usd("X402_MAX_PER_CALL_USD", "0.50")
        self.max_per_run = max_per_run if max_per_run is not None else _usd("X402_MAX_PER_RUN_USD", "2.00")
        self.spent = Decimal(0)  # signed this run, settled or not
        self.payments: list[dict] = []

        client = x402ClientSync()
        register_exact_evm_client(client, EthAccountSigner(self.account), networks=self.network)
        client.set_spend_controls({"max_amount_per_payment": f"${self.max_per_call}"})
        client.on_before_payment_creation(self._check)
        client.on_after_payment_creation(self._record)
        self.client = client

    # --- spend caps -------------------------------------------------------
    def _amount(self, req: Any) -> tuple[Decimal, str, str]:
        network = getattr(req, "network", "")
        network = LEGACY_NETWORK.get(network, network)
        asset = str(getattr(req, "asset", "") or "")
        atomic = getattr(req, "amount", None) or getattr(req, "max_amount_required", None) or "0"
        return Decimal(int(str(atomic))) / Decimal(10**6), network, asset

    def _check(self, ctx: Any):
        from x402.schemas.hooks import AbortResult

        usd, network, asset = self._amount(ctx.selected_requirements)
        if network != self.network or asset.lower() != USDC[self.network].lower():
            return AbortResult(reason=f"refused: asks for {asset} on {network}, only USDC on {self.network} is allowed")
        if usd > self.max_per_call:
            return AbortResult(reason=f"refused: ${usd} is over the per-call cap ${self.max_per_call}")
        if self.spent + usd > self.max_per_run:
            return AbortResult(
                reason=f"refused: ${usd} would bring this run to ${self.spent + usd}, over the cap ${self.max_per_run}"
            )
        self.spent += usd  # count it now, so a failed settlement can't be retried past the cap
        return None

    def _record(self, ctx: Any) -> None:
        usd, network, _ = self._amount(ctx.selected_requirements)
        row = {
            "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "usd": str(usd),
            "network": network,
            "pay_to": getattr(ctx.selected_requirements, "pay_to", None),
            "from": self.address,
            "run_total_usd": str(self.spent),
        }
        self.payments.append(row)
        ledger = config.OUT_DIR / "x402_payments.jsonl"
        ledger.parent.mkdir(parents=True, exist_ok=True)
        with ledger.open("a") as f:
            f.write(json.dumps(row) + "\n")
        print(f"  [x402] signed a ${usd} USDC payment (run total ${self.spent} of ${self.max_per_run})")

    # --- wallet sign-in (docs.flashpoint.ai/authentication, "MCP wallet JWT") ---
    def sign_in(self, mcp_url: str) -> str:
        """challenge -> personal_sign (EIP-191) -> 1-hour wallet JWT for Authorization: Bearer."""
        import httpx
        from eth_account.messages import encode_defunct

        base = os.getenv("FLASHPOINT_AUTH_URL") or mcp_url.rsplit("/mcp", 1)[0]
        r = httpx.post(f"{base}/auth/wallet/challenge", json={"address": self.address}, timeout=30)
        r.raise_for_status()
        ch = r.json()
        sig = self.account.sign_message(encode_defunct(text=ch["message_to_sign"])).signature.hex()
        sig = sig if sig.startswith("0x") else "0x" + sig
        r = httpx.post(f"{base}/auth/wallet/token",
                       json={"address": self.address, "nonce": ch["nonce"], "signature": sig}, timeout=30)
        r.raise_for_status()
        out = r.json()
        token = out.get("token") or out.get("access_token") or out.get("jwt") or (out.get("data") or {}).get("token")
        if not token:
            raise RuntimeError(f"Flashpoint wallet sign-in returned no token: {str(out)[:200]}")
        print(f"  [x402] signed in to Flashpoint as wallet {self.address}")
        return token

    def payment_header(self, response) -> tuple[str, str]:
        """Answer an HTTP 402 (header or JSON body) with a signed payment header, within the caps."""
        import base64

        from x402.http.utils import encode_payment_signature_header
        from x402.schemas import parse_payment_required

        raw = response.headers.get("PAYMENT-REQUIRED")
        body = None
        if raw:
            try:
                body = json.loads(base64.b64decode(raw))
            except Exception:  # noqa: BLE001
                body = None
        if body is None:
            try:
                body = response.json()
            except Exception:  # noqa: BLE001
                body = None
        data = _normalize(body)
        if not data:
            raise PaymentNeeded(f"Flashpoint sent 402 without readable payment terms: {response.text[:300]}")
        try:
            payload = self.client.create_payment_payload(parse_payment_required(data))
        except Exception as e:  # noqa: BLE001  (cap refusals land here)
            raise PaymentNeeded(f"x402 payment not made: {e}") from e
        name = "X-PAYMENT" if data["x402Version"] == 1 else "PAYMENT-SIGNATURE"
        return name, encode_payment_signature_header(payload)

    # --- the two ways Flashpoint can ask for money -------------------------
    def session(self):
        """requests.Session that pays HTTP 402 responses automatically (within the caps)."""
        import requests
        from x402.http.clients import wrapRequestsWithPayment

        return wrapRequestsWithPayment(requests.Session(), self.client)

    def pay_params(self, params: dict, payment_required: Any) -> dict:
        """Sign a payment for an MCP in-band 402 and attach it to the tool call's _meta."""
        from x402.mcp.utils import attach_payment_to_meta

        try:
            payload = self.client.create_payment_payload(payment_required)
        except Exception as e:  # noqa: BLE001  (cap refusals land here)
            raise PaymentNeeded(f"x402 payment not made: {e}") from e
        return attach_payment_to_meta(params, payload)


def _normalize(body: Any) -> dict | None:
    """Flashpoint's 402 body: {"accepts": [...]} (x402 v1 style, network "base"). Fill optional fields."""
    if isinstance(body, dict) and "accepts" not in body:
        for k in ("error", "data"):
            if isinstance(body.get(k), dict):
                found = _normalize(body[k])
                if found:
                    return found
        return None
    if not isinstance(body, dict) or not isinstance(body.get("accepts"), list) or not body["accepts"]:
        return None
    out = dict(body)
    v1 = any("maxAmountRequired" in a for a in body["accepts"])
    out.setdefault("x402Version", 1 if v1 else 2)
    accepts = []
    for a in body["accepts"]:
        a = dict(a)
        a.setdefault("maxTimeoutSeconds", 300)
        if v1:
            a.setdefault("mimeType", "application/json")
            a.setdefault("resource", "https://api.flashpoint.ai/mcp")
            a.setdefault("description", "Flashpoint MCP tool")
        if str(a.get("asset", "")).lower() in {u.lower() for u in USDC.values()}:
            a.setdefault("extra", {"name": "USD Coin" if a.get("network") in ("base", "eip155:8453") else "USDC", "version": "2"})
        accepts.append(a)
    out["accepts"] = accepts
    return out


_wallet: Wallet | None = None


def from_env() -> Wallet | None:
    """The run's wallet, or None when payments are off (token login only)."""
    global _wallet
    if not enabled():
        return None
    _wallet = _wallet or Wallet()
    return _wallet
