"""
EIP-7702 Arbitrage Bot for Futarchy Markets
===========================================

This bot monitors price discrepancies between Swapr and Balancer pools,
executing atomic arbitrage trades using EIP-7702 bundled transactions.

Based on light_bot.py but uses EIP-7702 for atomic execution of all operations.

Usage:
    python -m src.arbitrage_commands.eip7702_bot \
        --amount 0.1 \
        --interval 120 \
        --tolerance 0.02 \
        [--dry-run]
"""

import os
import sys
import time
import argparse
from typing import Dict, Optional, Tuple, Any
from decimal import Decimal
from web3 import Web3
from eth_account import Account

# Import price fetching utilities
from src.helpers.swapr_price import get_pool_price as swapr_price
from src.helpers.balancer_price import get_pool_price as bal_price

# Import EIP-7702 flows
from src.arbitrage_commands.buy_cond_eip7702 import buy_conditional_simple
from src.arbitrage_commands.sell_cond_eip7702 import sell_conditional_simple

# Import utilities
from src.helpers.bundle_helpers import get_token_balance
from src.config.network import DEFAULT_RPC_URLS

# Constants
MIN_SDAI_BALANCE = 0.01  # Minimum sDAI balance in ether
MIN_ETH_BALANCE = 0.001  # Minimum ETH for gas in ether


# --------------------------------------------------------------------------- #
# Price Fetching Functions (from light_bot.py)                                #
# --------------------------------------------------------------------------- #


def make_web3() -> Web3:
    """Return a Web3 connected to the RPC in $RPC_URL or the primary fallback."""
    rpc_url = os.getenv("RPC_URL", DEFAULT_RPC_URLS[0])
    return Web3(Web3.HTTPProvider(rpc_url))


def fetch_swapr(pool: str, w3: Web3) -> Tuple[str, str, str]:
    """Return 'base', 'quote', price string for an Algebra pool."""
    price, base, quote = swapr_price(w3, pool)
    return base, quote, str(price)


def fetch_balancer(pool: str, w3: Web3) -> Tuple[str, str, str]:
    """Return 'base', 'quote', price string for a Balancer pool."""
    price, base, quote = bal_price(w3, pool)
    return base, quote, str(price)


def fetch_all_prices(w3: Web3) -> Dict[str, float]:
    """
    Fetch all relevant prices for arbitrage calculation.
    
    Returns:
        Dictionary with prices:
        - yes_price: YES token price on Swapr
        - no_price: NO token price on Swapr
        - pred_yes_price: Prediction YES price on Swapr
        - ideal_price: Calculated ideal Company price
        - balancer_price: Company price on Balancer
    """
    # Get pool addresses from environment
    addr_yes = os.getenv("SWAPR_POOL_YES_ADDRESS")
    addr_pred_yes = os.getenv("SWAPR_POOL_PRED_YES_ADDRESS")
    addr_no = os.getenv("SWAPR_POOL_NO_ADDRESS")
    addr_bal = os.getenv("BALANCER_POOL_ADDRESS")
    
    if not all((addr_yes, addr_pred_yes, addr_no, addr_bal)):
        raise ValueError("Missing required pool address environment variables")
    
    # Fetch Swapr prices
    yes_base, yes_quote, yes_price = fetch_swapr(addr_yes, w3)
    _, _, pred_yes_price = fetch_swapr(addr_pred_yes, w3)
    no_base, no_quote, no_price = fetch_swapr(addr_no, w3)
    
    # Fetch Balancer price
    bal_base, bal_quote, bal_price = fetch_balancer(addr_bal, w3)
    
    # Calculate ideal price
    ideal_price = float(pred_yes_price) * float(yes_price) + (
        1.0 - float(pred_yes_price)
    ) * float(no_price)
    
    return {
        'yes_price': float(yes_price),
        'no_price': float(no_price),
        'pred_yes_price': float(pred_yes_price),
        'ideal_price': ideal_price,
        'balancer_price': float(bal_price),
        'yes_base': yes_base,
        'yes_quote': yes_quote,
        'no_base': no_base,
        'no_quote': no_quote,
        'bal_base': bal_base,
        'bal_quote': bal_quote
    }


# --------------------------------------------------------------------------- #
# Decision Logic                                                              #
# --------------------------------------------------------------------------- #


def determine_action(balancer_price: float, ideal_price: float, tolerance: float) -> Optional[str]:
    """
    Determine whether to buy or sell based on price discrepancy.
    
    Args:
        balancer_price: Current Company price on Balancer
        ideal_price: Calculated ideal price from prediction markets
        tolerance: Minimum profit threshold (as decimal, e.g., 0.02 for 2%)
    
    Returns:
        'buy': If Balancer price > ideal price (buy conditional)
        'sell': If Balancer price < ideal price (sell conditional)
        None: If within tolerance
    """
    if ideal_price == 0:
        print("Warning: Ideal price is 0, skipping")
        return None
    
    # Calculate percentage difference
    diff = abs(balancer_price - ideal_price) / ideal_price
    
    if diff < tolerance:
        return None  # No profitable opportunity
    
    if balancer_price > ideal_price:
        return 'buy'  # Company expensive on Balancer, buy conditional
    else:
        return 'sell'  # Company cheap on Balancer, sell conditional


def estimate_profit(action: str, amount: float, prices: Dict[str, float]) -> float:
    """
    Estimate expected profit before execution.
    
    Args:
        action: 'buy' or 'sell'
        amount: Amount in sDAI
        prices: Price dictionary from fetch_all_prices
    
    Returns:
        Expected profit in sDAI (negative = loss)
    """
    if action == 'buy':
        # Buy conditional at ideal, sell Company at Balancer
        company_out = amount / prices['ideal_price']
        sdai_back = company_out * prices['balancer_price']
        return sdai_back - amount
    elif action == 'sell':
        # Buy Company at Balancer, sell conditional at ideal
        company_in = amount / prices['balancer_price']
        sdai_back = company_in * prices['ideal_price']
        return sdai_back - amount
    else:
        return 0


# --------------------------------------------------------------------------- #
# Balance and Safety Checks                                                  #
# --------------------------------------------------------------------------- #


def check_balances(w3: Web3, account_address: str) -> Dict[str, Any]:
    """
    Verify sufficient balances before trading.
    
    Args:
        w3: Web3 instance
        account_address: Account address to check
    
    Returns:
        Dict with balance status
    """
    sdai_token = os.environ.get("SDAI_TOKEN_ADDRESS")
    company_token = os.environ.get("COMPANY_TOKEN_ADDRESS")
    
    if not sdai_token or not company_token:
        raise ValueError("Token addresses not configured")
    
    sdai_balance = get_token_balance(w3, sdai_token, account_address)
    company_balance = get_token_balance(w3, company_token, account_address)
    eth_balance = w3.eth.get_balance(account_address)
    
    sdai_ether = w3.from_wei(sdai_balance, 'ether')
    company_ether = w3.from_wei(company_balance, 'ether')
    eth_ether = w3.from_wei(eth_balance, 'ether')
    
    return {
        'sdai': sdai_ether,
        'company': company_ether,
        'eth': eth_ether,
        'sufficient': sdai_ether >= MIN_SDAI_BALANCE and eth_ether >= MIN_ETH_BALANCE
    }


def verify_environment() -> None:
    """Verify all required environment variables are set."""
    required_vars = [
        "RPC_URL",
        "PRIVATE_KEY",
        "SWAPR_POOL_YES_ADDRESS",
        "SWAPR_POOL_PRED_YES_ADDRESS",
        "SWAPR_POOL_NO_ADDRESS",
        "BALANCER_POOL_ADDRESS",
        "SDAI_TOKEN_ADDRESS",
        "COMPANY_TOKEN_ADDRESS",
        "SWAPR_SDAI_YES_ADDRESS",
        "SWAPR_SDAI_NO_ADDRESS",
        "SWAPR_GNO_YES_ADDRESS",
        "SWAPR_GNO_NO_ADDRESS",
        "FUTARCHY_ROUTER_ADDRESS",
        "FUTARCHY_PROPOSAL_ADDRESS",
        "SWAPR_ROUTER_ADDRESS"
    ]
    
    missing = [var for var in required_vars if not os.getenv(var)]
    
    if missing:
        print("❌ Missing required environment variables:")
        for var in missing:
            print(f"  - {var}")
        sys.exit(1)


# --------------------------------------------------------------------------- #
# Arbitrage Execution                                                        #
# --------------------------------------------------------------------------- #


def execute_arbitrage(
    action: str, 
    amount: Decimal, 
    dry_run: bool = False
) -> Dict[str, Any]:
    """
    Execute arbitrage using EIP-7702 bundled transactions.
    
    Args:
        action: 'buy' or 'sell'
        amount: Amount in sDAI
        dry_run: If True, simulate only
    
    Returns:
        Transaction result dictionary
    """
    try:
        if action == 'buy':
            # Buy conditional tokens and sell Company on Balancer
            print(f"Executing BUY conditional with {amount} sDAI")
            result = buy_conditional_simple(
                amount_sdai=amount,
                skip_balancer=False  # Include Balancer swap
            )
        elif action == 'sell':
            # Buy Company on Balancer and sell conditional tokens
            print(f"Executing SELL conditional with {amount} sDAI")
            # Skip merge to stay within 10-operation limit
            # This leaves us with conditional sDAI that can be merged later
            result = sell_conditional_simple(
                amount_sdai=amount,
                skip_merge=True  # Skip merge to stay within 10 ops
            )
            if result.get('status') == 'success':
                print("Note: Conditional sDAI tokens held (merge skipped for 10-op limit)")
        else:
            raise ValueError(f"Unknown action: {action}")
        
        return result
    except Exception as e:
        print(f"❌ Arbitrage execution failed: {e}")
        return {
            'status': 'error',
            'error': str(e)
        }


# --------------------------------------------------------------------------- #
# Main Bot Loop                                                              #
# --------------------------------------------------------------------------- #


def run_bot(
    amount: float, 
    interval: int, 
    tolerance: float, 
    dry_run: bool = False,
    max_iterations: Optional[int] = None
) -> None:
    """
    Main bot loop that monitors and executes arbitrage.
    
    Args:
        amount: Trade amount in sDAI
        interval: Seconds between checks
        tolerance: Minimum profit threshold (as decimal)
        dry_run: If True, simulate trades only
        max_iterations: Stop after N iterations (None = infinite)
    """
    w3 = make_web3()
    account = Account.from_key(os.environ["PRIVATE_KEY"])
    
    iteration = 0
    consecutive_errors = 0
    max_consecutive_errors = 5
    
    print(f"Starting EIP-7702 arbitrage bot...")
    print(f"Account: {account.address}")
    print(f"Amount: {amount} sDAI")
    print(f"Interval: {interval}s")
    print(f"Tolerance: {tolerance * 100:.2f}%")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print()
    
    while max_iterations is None or iteration < max_iterations:
        try:
            print(f"--- Iteration {iteration + 1} ---")
            
            # Check balances
            balances = check_balances(w3, account.address)
            if not balances['sufficient']:
                print(f"⚠️ Insufficient balances - sDAI: {balances['sdai']}, ETH: {balances['eth']}")
                time.sleep(interval)
                continue
            
            # Fetch current prices
            prices = fetch_all_prices(w3)
            
            print(f"YES  pool: 1 {prices['yes_base']} = {prices['yes_price']:.6f} {prices['yes_quote']}")
            print(f"PRED pool: 1 {prices['yes_base']} = {prices['pred_yes_price']:.6f} {prices['yes_quote']}")
            print(f"NO   pool: 1 {prices['no_base']} = {prices['no_price']:.6f} {prices['no_quote']}")
            print(f"BAL  pool: 1 {prices['bal_base']} = {prices['balancer_price']:.6f} {prices['bal_quote']}")
            print(f"Ideal price: {prices['ideal_price']:.6f}")
            
            # Calculate opportunity
            action = determine_action(
                prices['balancer_price'],
                prices['ideal_price'],
                tolerance
            )
            
            if action:
                # Calculate expected profit
                expected_profit = estimate_profit(action, amount, prices)
                print(f"\n🎯 Opportunity detected: {action.upper()}")
                print(f"Balancer: {prices['balancer_price']:.6f}, Ideal: {prices['ideal_price']:.6f}")
                print(f"Expected profit: {expected_profit:.6f} sDAI")
                
                if not dry_run and expected_profit > 0:
                    # Execute arbitrage
                    print(f"Executing {action} arbitrage...")
                    result = execute_arbitrage(action, Decimal(str(amount)), dry_run=False)
                    
                    if result.get('status') == 'success':
                        print(f"✅ Arbitrage successful!")
                        print(f"  TX: {result.get('tx_hash')}")
                        print(f"  Gas used: {result.get('gas_used')}")
                        
                        # Show final balances
                        if action == 'buy':
                            print(f"  Final sDAI: {result.get('sdai_balance')}")
                        else:
                            print(f"  Final Company: {result.get('company_balance')}")
                        
                        consecutive_errors = 0
                    else:
                        print(f"❌ Arbitrage failed: {result.get('error', 'Unknown error')}")
                        consecutive_errors += 1
                elif dry_run:
                    print(f"📊 DRY RUN: Would execute {action} for {expected_profit:.6f} sDAI profit")
                else:
                    print(f"⚠️ Skipping: Expected profit negative ({expected_profit:.6f} sDAI)")
            else:
                diff_pct = abs(prices['balancer_price'] - prices['ideal_price']) / prices['ideal_price'] * 100
                print(f"No opportunity (diff {diff_pct:.2f}% < {tolerance * 100:.2f}%)")
            
            # Check for too many consecutive errors
            if consecutive_errors >= max_consecutive_errors:
                print(f"\n❌ Too many consecutive errors ({consecutive_errors}), stopping bot")
                break
            
            iteration += 1
            
            # Sleep before next iteration
            if max_iterations is None or iteration < max_iterations:
                print(f"\nSleeping {interval}s...")
                time.sleep(interval)
                
        except KeyboardInterrupt:
            print("\n\n👋 Bot stopped by user")
            break
        except Exception as e:
            print(f"\n❌ Error in bot loop: {e}")
            import traceback
            traceback.print_exc()
            
            consecutive_errors += 1
            if consecutive_errors >= max_consecutive_errors:
                print(f"\n❌ Too many consecutive errors ({consecutive_errors}), stopping bot")
                break
            
            print(f"Continuing after error... ({consecutive_errors}/{max_consecutive_errors})")
            time.sleep(interval)
    
    print("\n📊 Bot finished")


# --------------------------------------------------------------------------- #
# CLI Entry Point                                                            #
# --------------------------------------------------------------------------- #


def main():
    """Main entry point for CLI usage."""
    parser = argparse.ArgumentParser(
        description='EIP-7702 Arbitrage Bot for Futarchy Markets',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run with small amount
  python -m src.arbitrage_commands.eip7702_bot --amount 0.001 --interval 30 --dry-run
  
  # Live trading with 2% tolerance
  python -m src.arbitrage_commands.eip7702_bot --amount 0.1 --tolerance 0.02
  
  # Test with limited iterations
  python -m src.arbitrage_commands.eip7702_bot --amount 0.01 --max-iterations 5
        """
    )
    
    parser.add_argument(
        '--amount', 
        type=float, 
        required=True,
        help='Trade amount in sDAI'
    )
    parser.add_argument(
        '--interval', 
        type=int, 
        default=120,
        help='Check interval in seconds (default: 120)'
    )
    parser.add_argument(
        '--tolerance', 
        type=float, 
        default=0.02,
        help='Minimum profit threshold (default: 0.02 = 2%%)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Simulate trades without execution'
    )
    parser.add_argument(
        '--max-iterations',
        type=int,
        help='Stop after N iterations'
    )
    
    args = parser.parse_args()
    
    # Verify environment
    try:
        verify_environment()
    except SystemExit:
        return
    
    # Initialize Web3 and account
    w3 = make_web3()
    account = Account.from_key(os.environ["PRIVATE_KEY"])
    
    # Check initial balances
    print("Checking initial balances...")
    balances = check_balances(w3, account.address)
    print(f"Initial balances:")
    print(f"  sDAI: {balances['sdai']:.6f}")
    print(f"  Company: {balances['company']:.6f}")
    print(f"  ETH: {balances['eth']:.6f}")
    
    if not balances['sufficient']:
        print(f"\n❌ Insufficient balances to start bot")
        print(f"   Minimum required: {MIN_SDAI_BALANCE} sDAI, {MIN_ETH_BALANCE} ETH")
        return
    
    print("\n" + "=" * 60)
    
    # Start bot
    try:
        run_bot(
            amount=args.amount,
            interval=args.interval,
            tolerance=args.tolerance,
            dry_run=args.dry_run,
            max_iterations=args.max_iterations
        )
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()