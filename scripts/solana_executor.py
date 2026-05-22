"""Solana Executor — Jupiter DEX aggregator + Solana RPC.

Executes swaps on ALL Solana DEXes simultaneously through Jupiter.
Supports any SPL token including pump.fun memecoins.

Setup:
  Add to .env:
    SOLANA_PRIVATE_KEY=<base58 private key from Phantom>
    SOLANA_RPC=https://api.mainnet-beta.solana.com  (or paid RPC)

  Export private key from Phantom:
    Settings → Security & Privacy → Export Private Key

Usage:
    python scripts/solana_executor.py balance
    python scripts/solana_executor.py quote SOL USDC 0.1
    python scripts/solana_executor.py swap SOL USDC 0.1
    python scripts/solana_executor.py swap SOL <TOKEN_MINT> 0.05
    python scripts/solana_executor.py tokens
    python scripts/solana_executor.py price <TOKEN_MINT>
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import ssl
import sys
from pathlib import Path

import httpx
import truststore
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# ── Config ────────────────────────────────────────────────────────────────────
PRIVATE_KEY_B58 = os.getenv("SOLANA_PRIVATE_KEY", "")
JUPITER_QUOTE   = "https://api.jup.ag/swap/v1/quote"
JUPITER_SWAP    = "https://api.jup.ag/swap/v1/swap"
JUPITER_PRICE   = "https://api.jup.ag/price/v2"

# RPC with automatic fallback chain
_RPC_ENDPOINTS = [
    os.getenv("SOLANA_RPC", ""),                          # primary from .env
    "https://rpc.ankr.com/solana",                        # free backup, no key
    "https://api.mainnet-beta.solana.com",                # public last resort
]
_RPC_ENDPOINTS = [r for r in _RPC_ENDPOINTS if r]        # remove empty

def _rpc_call(method: str, params: list) -> dict:
    """Try each RPC endpoint in order, return first success."""
    last_err = None
    for url in _RPC_ENDPOINTS:
        try:
            with httpx.Client(verify=_SSL, timeout=15) as c:
                r = c.post(url, json={"jsonrpc": "2.0", "id": 1,
                                      "method": method, "params": params})
                if r.status_code == 429:
                    continue  # rate limited, try next
                r.raise_for_status()
                result = r.json()
                if "error" in result and result["error"]:
                    last_err = result["error"]
                    continue
                return result.get("result", {})
        except Exception as e:
            last_err = e
            continue
    raise Exception(f"All RPC endpoints failed. Last error: {last_err}")

_SSL = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

# ── Well-known mint addresses ─────────────────────────────────────────────────
KNOWN_MINTS = {
    "SOL":   "So11111111111111111111111111111111111111112",
    "USDC":  "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "USDT":  "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
    "BONK":  "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
    "WIF":   "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
    "JUP":   "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
    "RAY":   "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R",
    "PYTH":  "HZ1JovNiVvGrGs7cTsBcEbqhKADYN2cVLYU5HpnNbvzU",
}

# ── Keypair ───────────────────────────────────────────────────────────────────

def _load_keypair():
    """Load Solana keypair from SOLANA_PRIVATE_KEY in .env."""
    if not PRIVATE_KEY_B58:
        print("[ERROR] SOLANA_PRIVATE_KEY not set in .env")
        print("  Export from Phantom: Settings → Security & Privacy → Export Private Key")
        sys.exit(1)
    try:
        from solders.keypair import Keypair
        import base58 as b58
        secret = b58.b58decode(PRIVATE_KEY_B58)
        return Keypair.from_bytes(secret)
    except Exception as e:
        print(f"[ERROR] Failed to load keypair: {e}")
        sys.exit(1)


def _pubkey() -> str:
    return str(_load_keypair().pubkey())


# ── Solana RPC ────────────────────────────────────────────────────────────────

def rpc(method: str, params: list) -> dict:
    return _rpc_call(method, params)


def get_sol_balance(pubkey: str) -> float:
    result = rpc("getBalance", [pubkey, {"commitment": "confirmed"}])
    lamports = result.get("value", 0) if isinstance(result, dict) else result
    return lamports / 1e9


def get_token_accounts(pubkey: str) -> list[dict]:
    result = rpc("getTokenAccountsByOwner", [
        pubkey,
        {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
        {"encoding": "jsonParsed", "commitment": "confirmed"},
    ])
    return result.get("value", [])


# ── Jupiter API ───────────────────────────────────────────────────────────────

def resolve_mint(token: str) -> str:
    """Resolve ticker or mint address."""
    upper = token.upper()
    if upper in KNOWN_MINTS:
        return KNOWN_MINTS[upper]
    if len(token) >= 32:  # looks like a mint address
        return token
    print(f"[WARN] Unknown token '{token}' — treating as mint address")
    return token


def get_quote(input_mint: str, output_mint: str,
              amount_ui: float, slippage_bps: int = 100) -> dict | None:
    """Get Jupiter quote. Returns quoteResponse dict."""
    # For SOL: 1 SOL = 1e9 lamports; for most tokens: 1e6 decimals
    decimals = 9 if input_mint == KNOWN_MINTS["SOL"] else 6
    amount_raw = int(amount_ui * (10 ** decimals))

    params = {
        "inputMint":   input_mint,
        "outputMint":  output_mint,
        "amount":      str(amount_raw),
        "slippageBps": str(slippage_bps),
        "onlyDirectRoutes": "false",
    }
    try:
        with httpx.Client(verify=_SSL, timeout=15) as c:
            r = c.get(JUPITER_QUOTE, params=params)
            r.raise_for_status()
            return r.json()
    except Exception as e:
        print(f"[Jupiter Quote] Error: {e}")
        return None


def execute_swap(quote_response: dict, keypair) -> str | None:
    """Build, sign and send swap transaction. Returns tx signature."""
    try:
        pubkey_str = str(keypair.pubkey())

        # 1. Get swap transaction from Jupiter
        with httpx.Client(verify=_SSL, timeout=20) as c:
            r = c.post(JUPITER_SWAP, json={
                "quoteResponse":        quote_response,
                "userPublicKey":        pubkey_str,
                "wrapAndUnwrapSol":     True,
                "dynamicComputeUnitLimit": True,
                "prioritizationFeeLamports": 100_000,  # ~0.0001 SOL priority fee
            })
            r.raise_for_status()
            swap_data = r.json()

        tx_b64 = swap_data.get("swapTransaction")
        if not tx_b64:
            print(f"[ERROR] No swapTransaction in response: {swap_data}")
            return None

        # 2. Sign transaction
        from solders.transaction import VersionedTransaction
        tx_bytes = base64.b64decode(tx_b64)
        tx = VersionedTransaction.from_bytes(tx_bytes)
        signed_tx = keypair.sign_message(bytes(tx.message))

        # Re-assemble signed transaction
        from solders.transaction import VersionedTransaction
        signed_bytes = bytes(tx_bytes)  # Jupiter transactions are pre-built

        # 3. Send via RPC (sendTransaction)
        signed_b64 = base64.b64encode(tx_bytes).decode()

        # Actually sign properly
        from solders.keypair import Keypair as KP
        signed_tx = VersionedTransaction(tx.message, [keypair])
        signed_b64 = base64.b64encode(bytes(signed_tx)).decode()

        rpc_url = _RPC_ENDPOINTS[0]
        with httpx.Client(verify=_SSL, timeout=30) as c:
            r = c.post(rpc_url, json={
                "jsonrpc": "2.0", "id": 1,
                "method": "sendTransaction",
                "params": [signed_b64, {
                    "encoding": "base64",
                    "skipPreflight": False,
                    "preflightCommitment": "confirmed",
                }]
            })
            result = r.json()

        if "error" in result:
            print(f"[ERROR] RPC: {result['error']}")
            return None
        return result.get("result")  # transaction signature

    except Exception as e:
        print(f"[ERROR] Swap execution: {e}")
        import traceback; traceback.print_exc()
        return None


def get_token_price(mint: str) -> dict | None:
    """Get token price in USD from Jupiter Price API."""
    try:
        with httpx.Client(verify=_SSL, timeout=10) as c:
            r = c.get(JUPITER_PRICE, params={"ids": mint})
            r.raise_for_status()
            data = r.json().get("data", {})
            return data.get(mint)
    except Exception:
        return None


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_balance(args) -> None:
    pubkey = _pubkey()
    print(f"\nWallet: {pubkey}")
    sol = get_sol_balance(pubkey)
    print(f"SOL balance: {sol:.6f} SOL")

    # Estimate USD value
    sol_price_data = get_token_price(KNOWN_MINTS["SOL"])
    if sol_price_data:
        sol_usd = float(sol_price_data.get("price", 0))
        print(f"          ≈ ${sol * sol_usd:,.2f} USD")


def cmd_tokens(args) -> None:
    pubkey = _pubkey()
    print(f"\nTokens for {pubkey[:16]}...\n")
    accounts = get_token_accounts(pubkey)

    if not accounts:
        print("No SPL tokens found.")
        return

    for acc in accounts:
        info = acc.get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
        mint      = info.get("mint", "?")
        amount_raw = int(info.get("tokenAmount", {}).get("amount", "0"))
        decimals  = info.get("tokenAmount", {}).get("decimals", 0)
        ui_amount = amount_raw / (10 ** decimals) if decimals else amount_raw

        if ui_amount == 0:
            continue

        # Get ticker from known mints (reverse lookup)
        ticker = next((k for k, v in KNOWN_MINTS.items() if v == mint), mint[:8] + "...")
        price_data = get_token_price(mint)
        usd_str = ""
        if price_data:
            price = float(price_data.get("price", 0))
            if price > 0:
                usd_str = f" ≈ ${ui_amount * price:,.2f}"

        print(f"  {ticker:<12} {ui_amount:>16.4f}{usd_str}")


def cmd_quote(args) -> None:
    in_mint  = resolve_mint(args.input)
    out_mint = resolve_mint(args.output)
    amount   = float(args.amount)

    print(f"\nGetting quote: {amount} {args.input} → {args.output}...")
    quote = get_quote(in_mint, out_mint, amount, slippage_bps=args.slippage)
    if not quote:
        print("No quote available.")
        return

    out_amount = int(quote.get("outAmount", 0))
    out_dec = 9 if out_mint == KNOWN_MINTS.get("SOL") else 6
    out_ui  = out_amount / (10 ** out_dec)

    price_impact = float(quote.get("priceImpactPct", 0)) * 100

    print(f"\n  Input:        {amount} {args.input}")
    print(f"  Output:       {out_ui:.6f} {args.output}")
    print(f"  Price impact: {price_impact:.4f}%")
    print(f"  Slippage:     {args.slippage / 100:.1f}%")
    print(f"  Route:        {' → '.join(r.get('label','?') for r in quote.get('routePlan',[])[:3])}")

    if price_impact > 2:
        print(f"\n  ⚠️  High price impact ({price_impact:.2f}%) — consider smaller size")


def cmd_swap(args) -> None:
    in_mint  = resolve_mint(args.input)
    out_mint = resolve_mint(args.output)
    amount   = float(args.amount)

    print(f"\nSwap: {amount} {args.input} → {args.output}")
    print(f"Slippage: {args.slippage / 100:.1f}%")

    # Get quote first
    quote = get_quote(in_mint, out_mint, amount, slippage_bps=args.slippage)
    if not quote:
        print("Failed to get quote.")
        return

    out_amount = int(quote.get("outAmount", 0))
    out_dec    = 9 if out_mint == KNOWN_MINTS.get("SOL") else 6
    out_ui     = out_amount / (10 ** out_dec)
    price_impact = float(quote.get("priceImpactPct", 0)) * 100

    print(f"\n  You will receive: ~{out_ui:.6f} {args.output}")
    print(f"  Price impact:     {price_impact:.4f}%")

    if price_impact > 5:
        print(f"\n  ⚠️  VERY HIGH price impact ({price_impact:.2f}%)! Low liquidity.")

    # Confirm
    if not args.yes:
        confirm = input("\nProceed with swap? [y/N]: ").strip().lower()
        if confirm != "y":
            print("Cancelled.")
            return

    print("\nExecuting swap...")
    keypair = _load_keypair()
    sig = execute_swap(quote, keypair)

    if sig:
        print(f"\n✅ Swap executed!")
        print(f"   Signature: {sig}")
        print(f"   Explorer:  https://solscan.io/tx/{sig}")
    else:
        print("\n❌ Swap failed. Check error above.")


def cmd_price(args) -> None:
    mint = resolve_mint(args.token)
    print(f"\nPrice for {args.token} ({mint[:12]}...):")
    data = get_token_price(mint)
    if data:
        price = float(data.get("price", 0))
        print(f"  ${price:.8f}" if price < 0.01 else f"  ${price:,.4f}")
        print(f"  (Source: Jupiter Price API)")
    else:
        print("  Price not available.")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(description="Solana Executor — Jupiter DEX")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("balance", help="SOL balance").set_defaults(func=cmd_balance)
    sub.add_parser("tokens",  help="All SPL token balances").set_defaults(func=cmd_tokens)

    q = sub.add_parser("quote", help="Get swap quote (no execution)")
    q.add_argument("input",  help="Input token: SOL, USDC, or mint address")
    q.add_argument("output", help="Output token: SOL, USDC, or mint address")
    q.add_argument("amount", help="Amount to swap")
    q.add_argument("--slippage", type=int, default=100, help="Slippage in bps (default 100 = 1%)")
    q.set_defaults(func=cmd_quote)

    s = sub.add_parser("swap", help="Execute swap via Jupiter")
    s.add_argument("input",  help="Input token: SOL, USDC, or mint address")
    s.add_argument("output", help="Output token: SOL, USDC, or mint address")
    s.add_argument("amount", help="Amount to swap")
    s.add_argument("--slippage", type=int, default=100, help="Slippage in bps (default 100 = 1%)")
    s.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")
    s.set_defaults(func=cmd_swap)

    pr = sub.add_parser("price", help="Get token price in USD")
    pr.add_argument("token", help="Token ticker or mint address")
    pr.set_defaults(func=cmd_price)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
