"""
discover_side.py
================
CLI helper that prints spot prices for:

    • Swapr YES pool  – env **SWAPR_POOL_YES_ADDRESS**
    • Swapr NO  pool  – env **SWAPR_POOL_NO_ADDRESS**
    • Balancer pool   – env **BALANCER_POOL_ADDRESS**

The script now re-runs the price-check/arbitrage block every 10 minutes.

Usage
-----
    RPC_URL=<json-rpc> \
    SWAPR_POOL_YES_ADDRESS=0x… \
    SWAPR_POOL_PRED_YES_ADDRESS=0x… \
    SWAPR_POOL_NO_ADDRESS=0x…  \
    BALANCER_POOL_ADDRESS=0x…  \
    python -m src.arbitrage_commands.discover_side <amount> [--send]
"""

from __future__ import annotations

import os
import sys
import time
from typing import Tuple

from web3 import Web3

from helpers.swapr_price import get_pool_price as swapr_price
from helpers.balancer_price import get_pool_price as bal_price
from arbitrage_commands.buy_cond import buy_gno_yes_and_no_amounts_with_sdai
from arbitrage_commands.sell_cond import sell_gno_yes_and_no_amounts_to_sdai
from config.network import DEFAULT_RPC_URLS

# --------------------------------------------------------------------------- #
# helpers                                                                     #
# --------------------------------------------------------------------------- #


def make_web3() -> Web3:
    """Return a Web3 connected to the RPC in $RPC_URL or the primary fallback."""
    rpc_url = os.getenv("RPC_URL", DEFAULT_RPC_URLS[0])
    return Web3(Web3.HTTPProvider(rpc_url))


def fetch_swapr(pool: str, w3: Web3, *, base_token_index: int = 0) -> Tuple[str, str, str]:
    """Return 'base', 'quote', price string for an Algebra pool."""
    price, base, quote = swapr_price(w3, pool, base_token_index=base_token_index)
    return base, quote, str(price)


def fetch_balancer(pool: str, w3: Web3) -> Tuple[str, str, str]:
    """Return 'base', 'quote', price string for a Balancer V3 pool."""
    price, base, quote = bal_price(w3, pool)
    return base, quote, str(price)


# --------------------------------------------------------------------------- #
# core logic – one shot                                                       #
# --------------------------------------------------------------------------- #


def run_once(amount: float, broadcast: bool) -> None:
    """Execute a single price check + optional trade."""
    addr_yes = os.getenv("SWAPR_POOL_YES_ADDRESS")
    addr_pred_yes = os.getenv("SWAPR_POOL_PRED_YES_ADDRESS")
    addr_no = os.getenv("SWAPR_POOL_NO_ADDRESS")
    addr_bal = os.getenv("BALANCER_POOL_ADDRESS")

    if not all((addr_yes, addr_pred_yes, addr_no, addr_bal)):
        print(
            "Error: one or more pool address environment variables are unset.",
            file=sys.stderr,
        )
        sys.exit(1)

    w3 = make_web3()

    yes_base, yes_quote, yes_price = fetch_swapr(addr_yes, w3, base_token_index=0)
    _, _, pred_yes_price = fetch_swapr(addr_pred_yes, w3, base_token_index=0)
    no_base, no_quote, no_price = fetch_swapr(addr_no, w3, base_token_index=1)
    bal_base, bal_quote, bal_price_str = fetch_balancer(addr_bal, w3)

    print(f"YES  pool: 1 {yes_base} = {yes_price} {yes_quote}")
    print(f"PRED pool: 1 {yes_base} = {pred_yes_price} {yes_quote}")
    print(f"NO   pool: 1 {no_base}  = {no_price}  {no_quote}")
    print(f"BAL  pool: 1 {bal_base} = {bal_price_str} {bal_quote}")

    ideal_bal_price = float(pred_yes_price) * float(yes_price) + (
        1.0 - float(pred_yes_price)
    ) * float(no_price)
    print(f"Ideal BAL price: 1 {bal_base} = {ideal_bal_price} {bal_quote}")

    bal_price_val = float(bal_price_str)

    if amount > 0:
        if bal_price_val > ideal_bal_price:
            print("→ Buying conditional GNO")
            if broadcast:
                result = buy_gno_yes_and_no_amounts_with_sdai(amount, broadcast=False)
                print(f"Simulated Result: {result}")
                print(f"sDAI net: {result['sdai_net']}")
                if result['sdai_net'] > -0.04:
                    print("→ Broadcasting transaction")
                    result = buy_gno_yes_and_no_amounts_with_sdai(amount, broadcast=True)
                    print(f"Result: {result}")
                else:
                    print("→ No profit from buying conditional GNO")
            else:
                print("→ Not broadcasting transaction")
                result = buy_gno_yes_and_no_amounts_with_sdai(amount, broadcast=False)
                print(f"Simulated Result: {result}")
        else:
            print("→ Selling conditional GNO")
            if broadcast:
                result = sell_gno_yes_and_no_amounts_to_sdai(amount, broadcast=False)
                print(f"Simulated Result: {result}")
                print(f"sDAI net: {result['sdai_net']}")
                if result['sdai_net'] > -0.04:
                    print("→ Broadcasting transaction")
                    result = sell_gno_yes_and_no_amounts_to_sdai(amount, broadcast=True)
                    print(f"Result: {result}")
                else:
                    print("→ No profit from buying conditional GNO")
            else:
                print("→ Not broadcasting transaction")
                result = sell_gno_yes_and_no_amounts_to_sdai(amount, broadcast=False)
                print(f"Simulated Result: {result}")
        print(f"Result: {result}")

    # Re-fetch to display post-trade prices
    yes_base, yes_quote, yes_price = fetch_swapr(addr_yes, w3, base_token_index=1)
    _, _, pred_yes_price = fetch_swapr(addr_pred_yes, w3, base_token_index=0)
    no_base, no_quote, no_price = fetch_swapr(addr_no, w3, base_token_index=1)
    bal_base, bal_quote, bal_price_str = fetch_balancer(addr_bal, w3)

    print("--- after tx ---")
    print(f"YES  pool: 1 {yes_base} = {yes_price} {yes_quote}")
    print(f"PRED pool: 1 {yes_base} = {pred_yes_price} {yes_quote}")
    print(f"NO   pool: 1 {no_base}  = {no_price}  {no_quote}")
    print(f"BAL  pool: 1 {bal_base} = {bal_price_str} {bal_quote}")
    print()


# --------------------------------------------------------------------------- #
# entry-point                                                                 #
# --------------------------------------------------------------------------- #


def main() -> None:
    # ---- parse CLI once ---------------------------------------------------- #
    SEND_FLAG = {"--send", "-s"}
    broadcast = any(flag in sys.argv for flag in SEND_FLAG)
    args = [arg for arg in sys.argv[1:] if arg not in SEND_FLAG]

    if not args:
        print("Usage: discover_side.py <amount> [--send]", file=sys.stderr)
        sys.exit(2)

    try:
        amount = float(args[0])
        interval = int(args[1])
    except ValueError:
        print("Error: <amount> must be a number.", file=sys.stderr)
        sys.exit(2)

    # ---- main loop --------------------------------------------------------- #
    print(f"Starting discover_side monitor – interval: {interval} seconds\n")
    while True:
        try:
            run_once(amount, broadcast)
        except KeyboardInterrupt:
            print("\nInterrupted – exiting.")
            break
        except Exception as exc:  # noqa: BLE001
            print(f"⚠️  {type(exc).__name__}: {exc}", file=sys.stderr)

        time.sleep(interval)  # 10 minutes


if __name__ == "__main__":
    main()
