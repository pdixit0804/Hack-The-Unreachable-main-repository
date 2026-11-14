"""Check the program's wallet, then (only if asked) make ONE capped x402 payment to Flashpoint.

    python3 scripts/flashpoint_wallet.py                      # dry run: no payment, ever
    python3 scripts/flashpoint_wallet.py --test-one-paid-call # pays at most once, at most --max-usd

Dry run: shows the wallet address and its USDC / ETH balance on Base, then connects
to Flashpoint with payments switched OFF and reports whether a call asks for money.

--test-one-paid-call: makes the same call with payments ON, capped at one payment
of at most --max-usd (default $0.10) for the whole script, then prints what was paid.
Pick the call with --tool and --args (JSON). The default is a read-only panel list.
Reads WALLET_PRIVATE_KEY / WALLET_ADDRESS from .env and never prints the key.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from stress_tester import config, wallet  # noqa: E402,F401  (config loads .env)
from stress_tester.panel import flashpoint as fp  # noqa: E402

RPC = {"eip155:8453": "https://mainnet.base.org", "eip155:84532": "https://sepolia.base.org"}


def balances(address: str, network: str) -> tuple[str, str]:
    import httpx

    url = os.getenv("BASE_RPC_URL") or RPC[network]
    data = "0x70a08231" + address[2:].lower().rjust(64, "0")  # balanceOf(address)

    def rpc(method, params):
        r = httpx.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=20)
        return int(r.json()["result"], 16)

    try:
        usdc = rpc("eth_call", [{"to": wallet.USDC[network], "data": data}, "latest"]) / 1e6
        eth = rpc("eth_getBalance", [address, "latest"]) / 1e18
        return f"{usdc:.2f} USDC", f"{eth:.6f} ETH"
    except Exception as e:  # noqa: BLE001
        return f"(couldn't read: {type(e).__name__})", "-"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--test-one-paid-call", action="store_true", help="allow ONE payment (otherwise nothing is paid)")
    ap.add_argument("--max-usd", default="0.10", help="most this script may pay, in USD (default 0.10)")
    ap.add_argument("--tool", default="panel", help="Flashpoint tool to call (default: panel)")
    ap.add_argument("--args", default='{"action": "list"}', help="tool arguments as JSON")
    a = ap.parse_args()

    os.environ["X402_ENABLED"] = "false"  # build the wallet by hand below; the client stays unpaid unless asked
    cap = Decimal(a.max_usd)
    try:
        w = wallet.Wallet(max_per_call=cap, max_per_run=cap)
    except Exception as e:  # noqa: BLE001
        print(f"Wallet not ready: {e}")
        return 1
    usdc, eth = balances(w.address, w.network)
    print(f"Wallet  {w.address}")
    print(f"Network {w.network}   balance {usdc}, {eth}")
    print(f"Cap     at most ${cap} in total for this script")
    print(f"Token login: {'set' if os.getenv('FLASHPOINT_TOKEN') else 'not set'}")

    client = fp.MCPClient()  # payments OFF: a payment request stops with PaymentNeeded
    if a.test_one_paid_call:
        client.wallet = w
        client.http = w.session()
        client._post_kw = {"timeout": 600}
        print("\nPAID TEST: one payment allowed.")
    else:
        print("\nDRY RUN: no payment will be made.")

    try:
        client.initialize()
        print(f"Connected. {len(client.list_tools())} tools available.")
        res = client.call_tool(a.tool, json.loads(a.args))
        print(f"\n{a.tool} answered (isError={res.get('isError')}):")
        print(json.dumps(fp.result_payload(res), indent=2, default=str)[:1500])
    except wallet.PaymentNeeded as e:
        print(f"\nPayment requested: {e}")
        if not a.test_one_paid_call:
            print("Run again with --test-one-paid-call to pay for this one call.")
    except Exception as e:  # noqa: BLE001
        print(f"\nCall failed: {type(e).__name__}: {str(e)[:600]}")

    if w.payments:
        print(f"\nPaid: {json.dumps(w.payments, indent=2)}")
        scan = "sepolia.basescan.org" if w.network == "eip155:84532" else "basescan.org"
        print(f"Check it at https://{scan}/address/{w.address}#tokentxns")
    else:
        print("\nNo payment was made." + ("" if a.test_one_paid_call else " (dry run)"))
        if a.test_one_paid_call:
            print("This call didn't ask for money, so your login covers it. Ask a mentor which call is paid, "
                  "then pass it with --tool and --args.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
