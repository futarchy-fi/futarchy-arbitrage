"""
pectra_bot.py
=============
Arbitrage bot with support for EIP-7702 bundled transactions.

This bot monitors price discrepancies between Balancer and Swapr pools
and executes arbitrage trades using either sequential transactions or
atomic EIP-7702 bundles.

Usage
-----
    # Sequential mode (default):
    python -m src.arbitrage_commands.pectra_bot --amount <amount> --interval <interval> --tolerance <tolerance> [--send]
    
    # Bundled mode (EIP-7702):
    python -m src.arbitrage_commands.pectra_bot --amount <amount> --interval <interval> --tolerance <tolerance> --use-bundle [--send]
"""

from __future__ import annotations

import os
import sys
import time
from typing import Tuple
from decimal import Decimal

from web3 import Web3

from helpers.swapr_price import get_pool_price as swapr_price
from helpers.balancer_price import get_pool_price as bal_price
from arbitrage_commands.buy_cond import buy_gno_yes_and_no_amounts_with_sdai
from arbitrage_commands.sell_cond import sell_gno_yes_and_no_amounts_to_sdai
from config.network import DEFAULT_RPC_URLS

# Import bundled transaction functions if available
try:
    from arbitrage_commands.buy_cond_eip7702 import buy_conditional_bundled
    from arbitrage_commands.sell_cond_eip7702 import sell_conditional_bundled
    EIP7702_AVAILABLE = True
except ImportError:
    EIP7702_AVAILABLE = False
    print("Warning: EIP-7702 modules not available. Bundle mode disabled.")

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


def run_once(amount: float, tolerance: float, broadcast: bool, use_bundle: bool = False) -> None:
    """Execute a single price check + optional trade.
    
    Args:
        amount: Amount to trade
        tolerance: Profit tolerance threshold
        broadcast: Whether to execute real transactions
        use_bundle: Whether to use EIP-7702 bundled transactions
    """
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

    yes_base, yes_quote, yes_price = fetch_swapr(addr_yes, w3, base_token_index=1)
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
    print(f"Ideal BAL price:  {ideal_bal_price} = {float(pred_yes_price)} * {float(yes_price)} + (1.0 - {float(pred_yes_price)}) * {float(no_price)}")
    print(f"Ideal BAL price: 1 {bal_base} = {ideal_bal_price} {bal_quote}")

    bal_price_val = float(bal_price_str)

    if amount > 0:
        if bal_price_val > ideal_bal_price:
            print("→ Buying conditional GNO" + (" (Bundled)" if use_bundle else ""))
            
            if use_bundle and EIP7702_AVAILABLE:
                # Use bundled transaction approach
                result = buy_conditional_bundled(Decimal(str(amount)), broadcast=False)
                print(f"Simulated Result: {result}")
                
                if broadcast:
                    sdai_net = result.get('sdai_net', Decimal('0'))
                    if sdai_net > -tolerance:
                        print("→ Broadcasting bundled transaction")
                        result = buy_conditional_bundled(Decimal(str(amount)), broadcast=True)
                        print(f"Result: {result}")
                    else:
                        print("→ No profit from buying conditional GNO")
                else:
                    print("→ Not broadcasting transaction")
            else:
                # Use sequential approach
                if broadcast:
                    result = buy_gno_yes_and_no_amounts_with_sdai(amount, broadcast=False)
                    print(f"Simulated Result: {result}")
                    print(f"sDAI net: {result['sdai_net']}")
                    if result['sdai_net'] > -tolerance:
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
            print("→ Selling conditional GNO" + (" (Bundled)" if use_bundle else ""))
            
            if use_bundle and EIP7702_AVAILABLE:
                # Use bundled transaction approach
                if 'sell_conditional_bundled' in globals():
                    result = sell_conditional_bundled(Decimal(str(amount)), broadcast=False)
                    print(f"Simulated Result: {result}")
                    
                    if broadcast:
                        sdai_net = result.get('sdai_net', Decimal('0'))
                        if sdai_net > -tolerance:
                            print("→ Broadcasting bundled transaction")
                            result = sell_conditional_bundled(Decimal(str(amount)), broadcast=True)
                            print(f"Result: {result}")
                        else:
                            print("→ No profit from selling conditional GNO")
                    else:
                        print("→ Not broadcasting transaction")
                else:
                    print("→ Sell bundled not implemented yet, falling back to sequential")
                    use_bundle = False
            
            if not use_bundle:
                # Use sequential approach
                if broadcast:
                    result = sell_gno_yes_and_no_amounts_to_sdai(amount, broadcast=False)
                    print(f"Simulated Result: {result}")
                    print(f"sDAI net: {result['sdai_net']}")
                    if result['sdai_net'] > -tolerance:
                        print("→ Broadcasting transaction")
                        result = sell_gno_yes_and_no_amounts_to_sdai(amount, broadcast=True)
                        print(f"Result: {result}")
                    else:
                        print("→ No profit from selling conditional GNO")
                else:
                    print("→ Not broadcasting transaction")
                    result = sell_gno_yes_and_no_amounts_to_sdai(amount, broadcast=False)
                    print(f"Simulated Result: {result}")
        
        if 'result' in locals():
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
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Pectra arbitrage bot with EIP-7702 bundle support",
        epilog="Use --use-bundle to enable atomic EIP-7702 transactions (requires FUTARCHY_BATCH_EXECUTOR_ADDRESS)"
    )
    parser.add_argument("--amount", type=float, required=True, help="Amount to trade")
    parser.add_argument("--interval", type=int, required=True, help="Interval between checks in seconds")
    parser.add_argument("--tolerance", type=float, required=True, help="Profit tolerance threshold")
    parser.add_argument("--send", "-s", action="store_true", help="Execute real transactions")
    parser.add_argument("--use-bundle", action="store_true", help="Use EIP-7702 bundled transactions")
    
    args = parser.parse_args()
    
    amount = args.amount
    interval = args.interval
    tolerance = args.tolerance
    broadcast = args.send
    use_bundle = args.use_bundle

    # ---- verify bundle mode setup ------------------------------------------ #
    if use_bundle:
        if not EIP7702_AVAILABLE:
            print("Error: EIP-7702 modules not available. Cannot use bundle mode.")
            sys.exit(1)
        
        if not os.getenv("FUTARCHY_BATCH_EXECUTOR_ADDRESS"):
            print("Error: FUTARCHY_BATCH_EXECUTOR_ADDRESS not set.")
            print("Deploy the batch executor first: python -m src.setup.deploy_batch_executor")
            sys.exit(1)
        
        print("🚀 Bundle mode enabled - using EIP-7702 atomic transactions")
        print(f"Batch executor: {os.getenv('FUTARCHY_BATCH_EXECUTOR_ADDRESS')}")
    else:
        print("Sequential mode - using traditional multi-transaction approach")

    # ---- main loop --------------------------------------------------------- #
    print(f"\nStarting Pectra bot – interval: {interval} seconds\n")
    while True:
        try:
            run_once(amount, tolerance, broadcast, use_bundle)
        except KeyboardInterrupt:
            print("\nInterrupted – exiting.")
            break
        except Exception as exc:  # noqa: BLE001
            print(f"⚠️  {type(exc).__name__}: {exc}", file=sys.stderr)

        time.sleep(interval)


if __name__ == "__main__":
    main()
