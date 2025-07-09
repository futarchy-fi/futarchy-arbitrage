"""
light_bot.py
============
A lightweight version of complex_bot that monitors prices and executes conditional token trades on Swapr,
but skips the final Balancer swap operations. This bot will:
- Split sDAI into YES/NO conditional tokens
- Swap conditional sDAI to conditional Company tokens on Swapr
- Merge conditional Company tokens back to regular Company tokens
- Skip the final Balancer swap (Company → sDAI)

This means the bot accumulates Company tokens instead of completing the full arbitrage loop.

Usage
-----
    RPC_URL=<json-rpc> \
    SWAPR_POOL_YES_ADDRESS=0x… \
    SWAPR_POOL_PRED_YES_ADDRESS=0x… \
    SWAPR_POOL_NO_ADDRESS=0x…  \
    BALANCER_POOL_ADDRESS=0x…  \
    python -m src.arbitrage_commands.light_bot --amount <amount> --interval <interval> --tolerance <tolerance> [--send]
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
# Modified trading functions without Balancer swaps                           #
# --------------------------------------------------------------------------- #


def buy_conditional_only(amount: float, broadcast: bool = False):
    """Execute buy conditional tokens but skip Balancer swap."""
    from decimal import Decimal
    from eth_account import Account
    from helpers.swapr_swap import (
        w3,
        client,
        build_exact_in_tx,
        parse_simulated_swap_results as parse_simulated_swapr_results,
        parse_broadcasted_swap_results as parse_broadcasted_swapr_results,
    )
    from helpers.split_position import build_split_tx
    from helpers.merge_position import build_merge_tx
    from helpers.blockchain_sender import send_tenderly_tx_onchain
    from helpers.conditional_sdai_liquidation import (
        build_conditional_sdai_liquidation_steps,
    )
    
    acct = Account.from_key(os.environ["PRIVATE_KEY"])
    
    token_yes_in = w3.to_checksum_address(os.environ["SWAPR_SDAI_YES_ADDRESS"])
    token_yes_out = w3.to_checksum_address(os.environ["SWAPR_GNO_YES_ADDRESS"])
    token_no_in = w3.to_checksum_address(os.environ["SWAPR_SDAI_NO_ADDRESS"])
    token_no_out = w3.to_checksum_address(os.environ["SWAPR_GNO_NO_ADDRESS"])
    
    router_addr = w3.to_checksum_address(os.environ["FUTARCHY_ROUTER_ADDRESS"])
    proposal_addr = w3.to_checksum_address(os.environ["FUTARCHY_PROPOSAL_ADDRESS"])
    collateral_addr = w3.to_checksum_address(os.environ["SDAI_TOKEN_ADDRESS"])
    company_collateral_addr = w3.to_checksum_address(os.environ["COMPANY_TOKEN_ADDRESS"])
    
    sdai_amount = Decimal(str(amount)) * 10**18
    
    # Step 1: Split sDAI
    split_tx = build_split_tx(
        w3,
        client,
        router_addr,
        proposal_addr,
        collateral_addr,
        int(sdai_amount),
        acct.address,
    )
    
    # Step 2: Swap conditional sDAI to conditional Company on Swapr (YES)
    amount_out_min = 0  # Accept any amount for now
    swapr_yes_tx = build_exact_in_tx(
        token_yes_in,
        token_yes_out,
        int(sdai_amount),
        amount_out_min,
        acct.address,
    )
    
    # Step 3: Swap conditional sDAI to conditional Company on Swapr (NO)
    swapr_no_tx = build_exact_in_tx(
        token_no_in,
        token_no_out,
        int(sdai_amount),
        amount_out_min,
        acct.address,
    )
    
    bundle = [split_tx, swapr_yes_tx, swapr_no_tx]
    
    if broadcast:
        # Execute on-chain
        starting_nonce = w3.eth.get_transaction_count(acct.address)
        tx_hashes = []
        for i, tx in enumerate(bundle):
            tx_hash = send_tenderly_tx_onchain(tx, nonce=starting_nonce + i)
            tx_hashes.append(tx_hash)
        
        # Wait for receipts
        receipts = [w3.eth.wait_for_transaction_receipt(h) for h in tx_hashes]
        
        # Parse YES swap using tx hash (index 1 is YES swap)
        print(f"Parsing YES swap tx: {tx_hashes[1]}")
        yes_result = parse_broadcasted_swapr_results(tx_hashes[1], fixed="in")
        if yes_result is None:
            raise Exception(f"parse_broadcasted_swapr_results returned None for YES swap tx {tx_hashes[1]}")
        yes_amount_out = yes_result["output_amount"]
        
        # Parse NO swap using tx hash (index 2 is NO swap)
        print(f"Parsing NO swap tx: {tx_hashes[2]}")
        no_result = parse_broadcasted_swapr_results(tx_hashes[2], fixed="in")
        if no_result is None:
            raise Exception(f"parse_broadcasted_swapr_results returned None for NO swap tx {tx_hashes[2]}")
        no_amount_out = no_result["output_amount"]
        
        # Merge what we can
        merge_amount = min(yes_amount_out, no_amount_out)
        if merge_amount > 0:
            merge_tx = build_merge_tx(
                w3,
                client,
                router_addr,
                proposal_addr,
                company_collateral_addr,
                int(merge_amount * 10**18),
                acct.address,
            )
            merge_hash = send_tenderly_tx_onchain(merge_tx, nonce=starting_nonce + len(bundle))
            w3.eth.wait_for_transaction_receipt(merge_hash)
        
        return {
            "yes_amount": float(yes_amount_out),
            "no_amount": float(no_amount_out),
            "merged_company": float(merge_amount),
            "status": "completed without Balancer swap"
        }
    else:
        # Simulate only
        result = client.simulate(bundle)
        
        if result and result.get("simulation_results"):
            sims = result["simulation_results"]
            
            # Parse YES swap (index 1)
            yes_result = parse_simulated_swapr_results([sims[1]])
            if yes_result is None:
                raise Exception(f"parse_simulated_swapr_results returned None for YES swap simulation")
            yes_amount_out = Decimal(yes_result["output_amount"])
            
            # Parse NO swap (index 2)
            no_result = parse_simulated_swapr_results([sims[2]])
            if no_result is None:
                raise Exception(f"parse_simulated_swapr_results returned None for NO swap simulation")
            no_amount_out = Decimal(no_result["output_amount"])
            
            merge_amount = min(yes_amount_out, no_amount_out)
            
            return {
                "yes_amount": float(yes_amount_out),
                "no_amount": float(no_amount_out),
                "merged_company": float(merge_amount),
                "status": "simulated without Balancer swap"
            }
        else:
            raise Exception(f"Simulation failed: {result}")


# --------------------------------------------------------------------------- #
# core logic – one shot                                                       #
# --------------------------------------------------------------------------- #


def run_once(amount: float, tolerance: float, broadcast: bool) -> None:
    """Execute a single price check + optional trade without Balancer operations."""
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
            print("→ Buying conditional Company tokens (without Balancer swap)")
            try:
                if broadcast:
                    result = buy_conditional_only(amount, broadcast=False)
                    print(f"Simulated Result: {result}")
                    if result['merged_company'] > 0:
                        print("→ Broadcasting transaction")
                        result = buy_conditional_only(amount, broadcast=True)
                        print(f"Result: {result}")
                    else:
                        print("→ No Company tokens would be produced")
                else:
                    print("→ Not broadcasting transaction")
                    result = buy_conditional_only(amount, broadcast=False)
                    print(f"Simulated Result: {result}")
            except Exception as e:
                print(f"Error: {e}")
                import traceback
                traceback.print_exc()
        else:
            print("→ Selling conditional Company tokens not supported in light mode")
            print("  (Would require buying Company tokens first)")

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
    
    parser = argparse.ArgumentParser(description="Light bot that skips Balancer operations")
    parser.add_argument("--amount", type=float, required=True, help="Amount to trade")
    parser.add_argument("--interval", type=int, required=True, help="Interval between checks in seconds")
    parser.add_argument("--tolerance", type=float, required=True, help="Profit tolerance threshold")
    parser.add_argument("--send", "-s", action="store_true", help="Execute real transactions")
    
    args = parser.parse_args()
    
    amount = args.amount
    interval = args.interval
    tolerance = args.tolerance
    broadcast = args.send

    # ---- main loop --------------------------------------------------------- #
    print(f"Starting light_bot monitor – interval: {interval} seconds\n")
    print("This bot executes conditional token trades but skips Balancer swaps.\n")
    
    while True:
        try:
            run_once(amount, tolerance, broadcast)
        except KeyboardInterrupt:
            print("\nInterrupted – exiting.")
            break
        except Exception as exc:  # noqa: BLE001
            print(f"⚠️  {type(exc).__name__}: {exc}", file=sys.stderr)

        time.sleep(interval)


if __name__ == "__main__":
    main()