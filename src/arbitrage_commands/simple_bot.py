"""
simple_bot.py
=============
Simple arbitrage bot that performs basic conditional token arbitrage when both 
conditional prices deviate from the spot price in the same direction.

Usage:
    python -m src.arbitrage_commands.simple_bot <amount> [--simulate]

Environment Variables Required:
    PRIVATE_KEY
    RPC_URL
    FUTARCHY_ROUTER_ADDRESS
    FUTARCHY_PROPOSAL_ADDRESS
    SDAI_TOKEN_ADDRESS
    GNO_TOKEN_ADDRESS
    BALANCER_POOL_ADDRESS
    SWAPR_POOL_YES_ADDRESS
    SWAPR_POOL_NO_ADDRESS
    SWAPR_GNO_YES_ADDRESS
    SWAPR_GNO_NO_ADDRESS
    SWAPR_SDAI_YES_ADDRESS
    SWAPR_SDAI_NO_ADDRESS
"""

import os
import sys
import time
from decimal import Decimal
from web3 import Web3
from eth_account import Account

from helpers.swapr_price import get_pool_price as swapr_price
from helpers.balancer_price import get_pool_price as bal_price
from helpers.swapr_swap import build_exact_in_tx, client
from helpers.split_position import build_split_tx
from helpers.merge_position import build_merge_tx
from helpers.balancer_swap import build_sell_gno_to_sdai_swap_tx, build_buy_gno_to_sdai_swap_tx
from helpers.blockchain_sender import send_tenderly_tx_onchain
from config.network import DEFAULT_RPC_URLS


def initialize():
    """Initialize Web3 connection and account"""
    rpc_url = os.getenv("RPC_URL", DEFAULT_RPC_URLS[0])
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    acct = Account.from_key(os.environ["PRIVATE_KEY"])
    
    # Contract addresses
    router_addr = w3.to_checksum_address(os.environ["FUTARCHY_ROUTER_ADDRESS"])
    proposal_addr = w3.to_checksum_address(os.environ["FUTARCHY_PROPOSAL_ADDRESS"])
    sdai_addr = w3.to_checksum_address(os.environ["SDAI_TOKEN_ADDRESS"])
    gno_addr = w3.to_checksum_address(os.environ["GNO_TOKEN_ADDRESS"])
    
    return w3, acct, router_addr, proposal_addr, sdai_addr, gno_addr


def fetch_prices(w3):
    """Fetch spot and conditional prices"""
    # Balancer spot price (GNO per sDAI)
    bal_price_val, _, _ = bal_price(w3, os.environ["BALANCER_POOL_ADDRESS"])
    
    # Swapr conditional prices (GNO per sDAI)
    yes_price_val, _, _ = swapr_price(w3, os.environ["SWAPR_POOL_YES_ADDRESS"], base_token_index=0)
    no_price_val, _, _ = swapr_price(w3, os.environ["SWAPR_POOL_NO_ADDRESS"], base_token_index=1)
    
    return float(bal_price_val), float(yes_price_val), float(no_price_val)


def execute_conditionals_high(w3, acct, router_addr, proposal_addr, sdai_addr, gno_addr, amount_sdai):
    """Execute when both conditionals > spot price"""
    amount_wei = w3.to_wei(Decimal(amount_sdai), "ether")
    
    # Step 1: Buy GNO with sDAI on Balancer
    buy_gno_tx = build_buy_gno_to_sdai_swap_tx(w3, client, amount_wei, 1, acct.address)
    
    # Step 2: Split GNO into conditional tokens
    # Estimate GNO output from step 1 (rough calculation with slippage buffer)
    spot_price, _, _ = fetch_prices(w3)
    estimated_gno = amount_sdai / spot_price * 0.99  # 1% slippage buffer
    estimated_gno_wei = w3.to_wei(Decimal(estimated_gno), "ether")
    
    split_tx = build_split_tx(
        w3, client, router_addr, proposal_addr, gno_addr,
        estimated_gno_wei, acct.address
    )
    
    # Step 3: Sell both conditional GNO for conditional sDAI
    yes_swap_tx = build_exact_in_tx(
        os.environ["SWAPR_GNO_YES_ADDRESS"],
        os.environ["SWAPR_SDAI_YES_ADDRESS"],
        estimated_gno_wei,
        0, acct.address
    )
    
    no_swap_tx = build_exact_in_tx(
        os.environ["SWAPR_GNO_NO_ADDRESS"],
        os.environ["SWAPR_SDAI_NO_ADDRESS"],
        estimated_gno_wei,
        0, acct.address
    )
    
    # Step 4: Merge conditional sDAI
    # Estimate minimum output based on current prices
    _, yes_price, no_price = fetch_prices(w3)
    min_sdai_out = estimated_gno * min(yes_price, no_price) * 0.99
    min_sdai_out_wei = w3.to_wei(Decimal(min_sdai_out), "ether")
    
    merge_tx = build_merge_tx(
        w3, client, router_addr, proposal_addr, sdai_addr,
        min_sdai_out_wei, acct.address
    )
    
    return [buy_gno_tx, split_tx, yes_swap_tx, no_swap_tx, merge_tx]


def execute_conditionals_low(w3, acct, router_addr, proposal_addr, sdai_addr, gno_addr, amount_sdai):
    """Execute when both conditionals < spot price"""
    amount_wei = w3.to_wei(Decimal(amount_sdai), "ether")
    
    # Step 1: Split sDAI into conditional sDAI
    split_tx = build_split_tx(
        w3, client, router_addr, proposal_addr, sdai_addr,
        amount_wei, acct.address
    )
    
    # Step 2: Buy conditional GNO with conditional sDAI
    yes_swap_tx = build_exact_in_tx(
        os.environ["SWAPR_SDAI_YES_ADDRESS"],
        os.environ["SWAPR_GNO_YES_ADDRESS"],
        amount_wei, 0, acct.address
    )
    
    no_swap_tx = build_exact_in_tx(
        os.environ["SWAPR_SDAI_NO_ADDRESS"],
        os.environ["SWAPR_GNO_NO_ADDRESS"],
        amount_wei, 0, acct.address
    )
    
    # Step 3: Merge conditional GNO
    # Estimate minimum output based on current prices
    _, yes_price, no_price = fetch_prices(w3)
    min_gno_out = amount_sdai / max(yes_price, no_price) * 0.99
    min_gno_out_wei = w3.to_wei(Decimal(min_gno_out), "ether")
    
    merge_tx = build_merge_tx(
        w3, client, router_addr, proposal_addr, gno_addr,
        min_gno_out_wei, acct.address
    )
    
    # Step 4: Sell GNO for sDAI on Balancer
    sell_gno_tx = build_sell_gno_to_sdai_swap_tx(
        w3, client, min_gno_out_wei, 1, acct.address
    )
    
    return [split_tx, yes_swap_tx, no_swap_tx, merge_tx, sell_gno_tx]


def run_once(amount: float, execute_trades: bool) -> None:
    """Execute a single price check + optional trade."""
    # Initialize
    w3, acct, router_addr, proposal_addr, sdai_addr, gno_addr = initialize()
    
    # Fetch current prices
    spot_price, yes_price, no_price = fetch_prices(w3)
    
    print(f"Spot price (Balancer): {spot_price:.6f} GNO/sDAI")
    print(f"YES price (Swapr): {yes_price:.6f} GNO/sDAI")
    print(f"NO price (Swapr): {no_price:.6f} GNO/sDAI")
    
    # Only proceed if amount > 0
    if amount <= 0:
        print("Amount is 0, skipping trade execution.")
        return
    
    # Determine arbitrage strategy
    if yes_price > spot_price and no_price > spot_price:
        print("Both conditionals > spot. Executing high strategy...")
        print("Strategy: Buy GNO → Split → Sell conditionals → Merge")
        txs = execute_conditionals_high(w3, acct, router_addr, proposal_addr, sdai_addr, gno_addr, amount)
        
    elif yes_price < spot_price and no_price < spot_price:
        print("Both conditionals < spot. Executing low strategy...")
        print("Strategy: Split sDAI → Buy conditionals → Merge → Sell GNO")
        txs = execute_conditionals_low(w3, acct, router_addr, proposal_addr, sdai_addr, gno_addr, amount)
        
    else:
        print("Conditionals diverge around spot price. No arbitrage opportunity.")
        print(f"YES vs Spot: {yes_price - spot_price:+.6f}")
        print(f"NO vs Spot: {no_price - spot_price:+.6f}")
        return
    
    print(f"Number of transactions: {len(txs)}")
    
    if not execute_trades:
        print("Simulating transactions...")
        try:
            result = client.simulate(txs)
            print("Simulation successful!")
            print("Result:", result)
        except Exception as e:
            print(f"Simulation failed: {e}")
    else:
        print("Executing transactions...")
        try:
            nonce = w3.eth.get_transaction_count(acct.address)
            for i, tx in enumerate(txs):
                print(f"Sending transaction {i+1}/{len(txs)}...")
                tx_hash = send_tenderly_tx_onchain(tx, nonce=nonce + i)
                print(f"Transaction {i+1}: {tx_hash}")
            print("All transactions sent successfully!")
        except Exception as e:
            print(f"Execution failed: {e}")
    
    # Re-fetch prices after transaction
    spot_price, yes_price, no_price = fetch_prices(w3)
    print("--- after tx ---")
    print(f"Spot price (Balancer): {spot_price:.6f} GNO/sDAI")
    print(f"YES price (Swapr): {yes_price:.6f} GNO/sDAI") 
    print(f"NO price (Swapr): {no_price:.6f} GNO/sDAI")
    print()


def main():
    """Main entry point"""
    # ---- parse CLI once ---------------------------------------------------- #
    SEND_FLAG = {"--send", "-s"}
    execute_trades = any(flag in sys.argv for flag in SEND_FLAG)
    args = [arg for arg in sys.argv[1:] if arg not in SEND_FLAG]

    if len(args) < 2:
        print("Usage: python -m src.arbitrage_commands.simple_bot <amount> <interval> [--send]", file=sys.stderr)
        print("  <amount>   - Amount in sDAI to trade", file=sys.stderr)
        print("  <interval> - Interval in seconds between runs", file=sys.stderr)
        print("  --send     - Execute transactions (default: simulate only)", file=sys.stderr)
        sys.exit(2)

    try:
        amount = float(args[0])
        interval = int(args[1])
    except ValueError:
        print("Error: <amount> must be a number and <interval> must be an integer.", file=sys.stderr)
        sys.exit(2)

    # ---- main loop --------------------------------------------------------- #
    print(f"Starting simple arbitrage bot – interval: {interval} seconds")
    print(f"Amount per trade: {amount} sDAI")
    print(f"Mode: {'EXECUTE' if execute_trades else 'SIMULATE'}")
    print()
    
    while True:
        try:
            run_once(amount, execute_trades)
        except KeyboardInterrupt:
            print("\nInterrupted – exiting.")
            break
        except Exception as exc:  # noqa: BLE001
            print(f"⚠️  {type(exc).__name__}: {exc}", file=sys.stderr)

        time.sleep(interval)


if __name__ == "__main__":
    main()
