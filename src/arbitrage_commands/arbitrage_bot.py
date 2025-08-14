#!/usr/bin/env python3
"""
Futarchy Arbitrage Bot

Monitors price discrepancies between Balancer and Swapr pools and executes
arbitrage trades via the FutarchyArbExecutorV5 contract.

Usage:
    python -m src.arbitrage_commands.arbitrage_bot \
        --env .env.0x9590dAF4d5cd4009c3F9767C5E7668175cFd37CF \
        --amount 0.01 \
        --interval 120 \
        --tolerance 0.04 \
        --min-profit -0.01 \
        --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import subprocess
import re
from decimal import Decimal
from pathlib import Path
from typing import Tuple, Optional

from dotenv import load_dotenv
from web3 import Web3
from eth_account import Account

from helpers.swapr_price import get_pool_price as swapr_price
from helpers.balancer_price import get_pool_price as bal_price
from config.network import DEFAULT_RPC_URLS


class ArbitrageBot:
    """Monitors and executes futarchy arbitrage opportunities."""
    
    def __init__(self, env_file: Optional[str] = None):
        """Initialize the bot with environment configuration."""
        self.load_environment(env_file)
        self.w3 = self.create_web3()
        self.validate_environment()
        self.setup_account()
        self.setup_token_contracts()
        
    def load_environment(self, env_file: Optional[str]) -> None:
        """Load environment variables from file."""
        base_env = Path(".env")
        if base_env.exists():
            load_dotenv(base_env)
        if env_file:
            load_dotenv(env_file)
            self.env_file = env_file
        else:
            self.env_file = None
            
    def create_web3(self) -> Web3:
        """Create Web3 connection."""
        rpc_url = os.getenv("RPC_URL", DEFAULT_RPC_URLS[0])
        w3 = Web3(Web3.HTTPProvider(rpc_url))
        
        # Add POA middleware if needed
        try:
            from web3.middleware import geth_poa_middleware
            w3.middleware_onion.inject(geth_poa_middleware, layer=0)
        except Exception:
            try:
                from web3.middleware import ExtraDataToPOAMiddleware
                w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
            except Exception:
                pass
                
        if not w3.is_connected():
            raise SystemExit("Failed to connect to RPC")
            
        return w3
    
    def setup_account(self) -> None:
        """Setup account from private key and get executor address."""
        private_key = os.getenv("PRIVATE_KEY")
        if not private_key:
            raise SystemExit("Missing PRIVATE_KEY")
        self.account = Account.from_key(private_key)
        self.wallet_address = self.account.address
        
        # Get executor contract address
        self.executor_address = self.get_executor_address()
        print(f"Monitoring executor contract: {self.executor_address}")
    
    def get_executor_address(self) -> str:
        """Get the executor contract address from env or deployment files."""
        import glob
        import json
        
        # Try environment variables first
        executor = os.getenv("FUTARCHY_ARB_EXECUTOR_V5") or os.getenv("EXECUTOR_V5_ADDRESS")
        if executor:
            return self.w3.to_checksum_address(executor)
            
        # Try deployment files
        deployment_files = sorted(glob.glob("deployments/deployment_executor_v5_*.json"))
        if deployment_files:
            try:
                with open(deployment_files[-1], "r") as f:
                    data = json.load(f)
                    if data.get("address"):
                        return self.w3.to_checksum_address(data["address"])
            except Exception:
                pass
                
        raise SystemExit("Could not determine executor contract address")
        
    def setup_token_contracts(self) -> None:
        """Setup token contract interfaces for balance checking."""
        # Minimal ERC20 ABI for balance checking
        erc20_abi = [
            {
                "constant": True,
                "inputs": [{"name": "owner", "type": "address"}],
                "name": "balanceOf",
                "outputs": [{"name": "", "type": "uint256"}],
                "stateMutability": "view",
                "type": "function"
            }
        ]
        
        # Setup token contracts
        self.tokens = {}
        token_addresses = {
            "sDAI": os.getenv("SDAI_TOKEN_ADDRESS", "0xaf204776c7245bF4147c2612BF6e5972Ee483701"),
            "GNO": os.getenv("COMPANY_TOKEN_ADDRESS", "0x9C58BAcC331c9aa871AFD802DB6379a98e80CEdb"),
            "YES_GNO": os.getenv("SWAPR_GNO_YES_ADDRESS"),
            "NO_GNO": os.getenv("SWAPR_GNO_NO_ADDRESS"),
            "YES_sDAI": os.getenv("SWAPR_SDAI_YES_ADDRESS"),
            "NO_sDAI": os.getenv("SWAPR_SDAI_NO_ADDRESS")
        }
        
        for name, addr in token_addresses.items():
            if addr:
                self.tokens[name] = self.w3.eth.contract(
                    address=self.w3.to_checksum_address(addr),
                    abi=erc20_abi
                )
        
    def validate_environment(self) -> None:
        """Ensure all required environment variables are set."""
        required = [
            "SWAPR_POOL_YES_ADDRESS",
            "SWAPR_POOL_PRED_YES_ADDRESS", 
            "SWAPR_POOL_NO_ADDRESS",
            "BALANCER_POOL_ADDRESS",
            "PRIVATE_KEY",
            "RPC_URL"
        ]
        
        missing = [var for var in required if not os.getenv(var)]
        if missing:
            raise SystemExit(f"Missing required environment variables: {', '.join(missing)}")
            
    def fetch_prices(self) -> dict:
        """Fetch current prices from all pools."""
        addr_yes = os.getenv("SWAPR_POOL_YES_ADDRESS")
        addr_pred_yes = os.getenv("SWAPR_POOL_PRED_YES_ADDRESS")
        addr_no = os.getenv("SWAPR_POOL_NO_ADDRESS")
        addr_bal = os.getenv("BALANCER_POOL_ADDRESS")
        
        # Fetch Swapr prices (YES and NO pools have GNO as token1)
        yes_price, yes_base, yes_quote = swapr_price(self.w3, addr_yes)
        pred_yes_price, _, _ = swapr_price(self.w3, addr_pred_yes)
        no_price, no_base, no_quote = swapr_price(self.w3, addr_no)
        
        # Fetch Balancer price
        bal_price_val, bal_base, bal_quote = bal_price(self.w3, addr_bal)
        
        return {
            "yes_price": float(yes_price),
            "pred_yes_price": float(pred_yes_price),
            "no_price": float(no_price),
            "bal_price": float(bal_price_val),
            "yes_base": yes_base,
            "yes_quote": yes_quote,
            "no_base": no_base,
            "no_quote": no_quote,
            "bal_base": bal_base,
            "bal_quote": bal_quote
        }
        
    def calculate_ideal_price(self, prices: dict) -> float:
        """Calculate the ideal Balancer price based on prediction market."""
        ideal = prices["pred_yes_price"] * prices["yes_price"] + \
                (1.0 - prices["pred_yes_price"]) * prices["no_price"]
        return ideal
        
    def determine_opportunity(self, prices: dict, tolerance: float) -> Tuple[Optional[str], Optional[str]]:
        """
        Determine if an arbitrage opportunity exists.
        
        Returns:
            (flow, cheaper): 'sell'/'buy' and 'yes'/'no', or (None, None) if no opportunity
        """
        ideal_price = self.calculate_ideal_price(prices)
        bal_price = prices["bal_price"]
        deviation = abs(bal_price - ideal_price)
        
        print(f"\nPrice Analysis:")
        print(f"  YES price:       {prices['yes_price']:.6f}")
        print(f"  NO price:        {prices['no_price']:.6f}")
        print(f"  Prediction YES:  {prices['pred_yes_price']:.6f}")
        print(f"  Balancer price:  {bal_price:.6f}")
        print(f"  Ideal price:     {ideal_price:.6f}")
        print(f"  Deviation:       {deviation:.6f} ({deviation/ideal_price*100:.2f}%)")
        
        if deviation < tolerance:
            print(f"  → No opportunity (deviation {deviation:.6f} < tolerance {tolerance:.6f})")
            return None, None
            
        # Determine flow direction
        if bal_price > ideal_price:
            flow = "buy"  # Buy conditionals cheap, merge, sell composite high
            print(f"  → BUY opportunity: Balancer overpriced by {bal_price - ideal_price:.6f}")
        else:
            flow = "sell"  # Buy composite cheap, split, sell conditionals high
            print(f"  → SELL opportunity: Balancer underpriced by {ideal_price - bal_price:.6f}")
            
        # Determine which conditional is cheaper
        if prices["yes_price"] < prices["no_price"]:
            cheaper = "yes"
            print(f"  → YES is cheaper ({prices['yes_price']:.6f} < {prices['no_price']:.6f})")
        else:
            cheaper = "no"
            print(f"  → NO is cheaper ({prices['no_price']:.6f} < {prices['yes_price']:.6f})")
            
        return flow, cheaper
        
    def get_balances(self, address: Optional[str] = None) -> dict:
        """Get current token balances for the specified address (defaults to executor contract)."""
        target_address = address or self.executor_address
        balances = {}
        for name, contract in self.tokens.items():
            if contract:
                try:
                    balance_wei = contract.functions.balanceOf(target_address).call()
                    balance_ether = self.w3.from_wei(balance_wei, 'ether')
                    balances[name] = float(balance_ether)
                except Exception as e:
                    print(f"Warning: Could not fetch {name} balance: {e}")
                    balances[name] = 0.0
        return balances
    
    def get_wallet_balances(self) -> dict:
        """Get current token balances for the user's wallet."""
        return self.get_balances(self.wallet_address)
    
    def check_residual_balances(self, balances: dict) -> None:
        """Check and warn about non-zero conditional token balances."""
        warnings = []
        
        # Check GNO balance
        if balances.get("GNO", 0) > 0.0001:
            warnings.append(f"⚠️  GNO balance: {balances['GNO']:.6f} (should be ~0)")
            
        # Check conditional token balances
        cond_tokens = ["YES_GNO", "NO_GNO", "YES_sDAI", "NO_sDAI"]
        for token in cond_tokens:
            if balances.get(token, 0) > 0.0001:
                warnings.append(f"⚠️  {token} balance: {balances[token]:.6f} (should be ~0)")
                
        if warnings:
            print("\n" + "\n".join(warnings))
    
    def parse_tx_hash(self, output: str) -> Optional[str]:
        """Parse transaction hash from executor output."""
        # Look for patterns like "Tx sent: 0x..." or "Tx sent: abc123..."
        patterns = [
            r"Tx sent:\s*(?:0x)?([a-fA-F0-9]{64})",
            r"Transaction hash:\s*(?:0x)?([a-fA-F0-9]{64})",
            r"tx:\s*(?:0x)?([a-fA-F0-9]{64})"
        ]
        
        for pattern in patterns:
            match = re.search(pattern, output, re.IGNORECASE)
            if match:
                tx_hash = match.group(1)
                # Ensure it starts with 0x
                if not tx_hash.startswith('0x'):
                    tx_hash = '0x' + tx_hash
                return tx_hash
        return None
    
    def execute_arbitrage(self, flow: str, cheaper: str, amount: float, 
                         min_profit: float, dry_run: bool, prefund: bool) -> Tuple[bool, Optional[str]]:
        """
        Execute arbitrage trade via the arbitrage_executor module.
        
        Returns:
            (success, tx_hash): True if execution was successful and optional transaction hash
        """
        # Build command for arbitrage_executor
        cmd = [
            sys.executable, "-m", "src.executor.arbitrage_executor",
            "--flow", flow,
            "--amount", str(amount),
            "--cheaper", cheaper,
            "--min-profit", str(min_profit)
        ]
        
        if self.env_file:
            cmd.extend(["--env", self.env_file])
            
        if prefund:
            cmd.append("--prefund")
            
        if dry_run:
            print(f"\n[DRY RUN] Would execute: {' '.join(cmd)}")
            return True, None
            
        print(f"\nExecuting arbitrage: {flow.upper()} flow, {cheaper.upper()} cheaper")
        print(f"Command: {' '.join(cmd)}")
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120  # 2 minute timeout
            )
            
            print("\n--- Executor Output ---")
            print(result.stdout)
            if result.stderr:
                print("--- Errors ---")
                print(result.stderr)
            print("--- End Output ---")
            
            # Parse transaction hash from output
            tx_hash = self.parse_tx_hash(result.stdout)
            
            if result.returncode == 0:
                print("✓ Trade executed successfully")
                if tx_hash:
                    print(f"\n🔗 View on GnosisScan: https://gnosisscan.io/tx/{tx_hash}")
                return True, tx_hash
            else:
                print(f"✗ Trade failed with exit code {result.returncode}")
                return False, None
                
        except subprocess.TimeoutExpired:
            print("✗ Trade execution timed out")
            return False
        except Exception as e:
            print(f"✗ Error executing trade: {e}")
            return False
            
    def run_loop(self, amount: float, interval: int, tolerance: float, 
                 min_profit: float, dry_run: bool, prefund: bool) -> None:
        """Main monitoring loop."""
        print(f"\n🤖 Starting Futarchy Arbitrage Bot")
        print(f"   Amount:      {amount} sDAI")
        print(f"   Interval:    {interval} seconds")
        print(f"   Tolerance:   {tolerance}")
        print(f"   Min Profit:  {min_profit} sDAI")
        print(f"   Mode:        {'DRY RUN' if dry_run else 'LIVE'}")
        print(f"   Prefund:     {prefund}")
        print("\nPress Ctrl+C to stop\n")
        
        iteration = 0
        while True:
            iteration += 1
            print(f"\n{'='*60}")
            print(f"Iteration #{iteration} - {time.strftime('%Y-%m-%d %H:%M:%S')}")
            print('='*60)
            
            try:
                # Fetch current prices
                prices = self.fetch_prices()
                
                # Check for arbitrage opportunity
                flow, cheaper = self.determine_opportunity(prices, tolerance)
                
                if flow and cheaper:
                    # Get balances before trade
                    if not dry_run:
                        print("\n--- Pre-trade balances (Executor Contract) ---")
                        balances_before = self.get_balances()  # Executor contract balances
                        sdai_before = balances_before.get("sDAI", 0)
                        print(f"  sDAI: {sdai_before:.6f}")
                        self.check_residual_balances(balances_before)
                        
                        # Also check wallet balance
                        wallet_balances = self.get_wallet_balances()
                        wallet_sdai_before = wallet_balances.get("sDAI", 0)
                        print(f"\n--- Wallet sDAI: {wallet_sdai_before:.6f} ---")
                    
                    # Execute trade
                    success, tx_hash = self.execute_arbitrage(
                        flow, cheaper, amount, min_profit, dry_run, prefund
                    )
                    
                    if success and not dry_run:
                        # Get balances after trade
                        print("\n--- Post-trade balances (Executor Contract) ---")
                        balances_after = self.get_balances()  # Executor contract balances
                        sdai_after = balances_after.get("sDAI", 0)
                        sdai_change = sdai_after - sdai_before
                        
                        print(f"  sDAI: {sdai_after:.6f}")
                        print(f"  Net sDAI change (Executor): {sdai_change:+.6f} {'✅' if sdai_change >= 0 else '❌'}")
                        
                        # Check for residual balances in executor
                        self.check_residual_balances(balances_after)
                        
                        # Also check wallet balance change
                        wallet_balances_after = self.get_wallet_balances()
                        wallet_sdai_after = wallet_balances_after.get("sDAI", 0)
                        wallet_change = wallet_sdai_after - wallet_sdai_before
                        if abs(wallet_change) > 0.000001:
                            print(f"\n--- Wallet sDAI: {wallet_sdai_after:.6f} (change: {wallet_change:+.6f}) ---")
                        
                        # Re-fetch prices to see impact
                        print("\n--- Post-trade prices ---")
                        new_prices = self.fetch_prices()
                        new_ideal = self.calculate_ideal_price(new_prices)
                        print(f"  Balancer:   {new_prices['bal_price']:.6f}")
                        print(f"  Ideal:      {new_ideal:.6f}")
                        print(f"  Deviation:  {abs(new_prices['bal_price'] - new_ideal):.6f}")
                        
                        # Summary
                        print(f"\n📊 Trade Summary:")
                        print(f"   Flow: {flow.upper()}")
                        print(f"   Amount: {amount} sDAI")
                        print(f"   Net Profit (Executor): {sdai_change:+.6f} sDAI")
                        print(f"   Min Profit Target: {min_profit:+.6f} sDAI")
                        print(f"   Target Met: {'✅ Yes' if sdai_change >= min_profit else '❌ No'}")
                        print(f"   Executor Address: {self.executor_address}")
                        if tx_hash:
                            print(f"\n🔗 Transaction: https://gnosisscan.io/tx/{tx_hash}")
                        
            except KeyboardInterrupt:
                print("\n\n👋 Shutting down gracefully...")
                break
            except Exception as e:
                print(f"\n⚠️ Error in iteration #{iteration}: {e}")
                
            # Wait for next iteration
            print(f"\n💤 Sleeping for {interval} seconds...")
            try:
                time.sleep(interval)
            except KeyboardInterrupt:
                print("\n👋 Shutting down gracefully...")
                break


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Futarchy arbitrage bot that monitors and executes trades"
    )
    parser.add_argument(
        "--env", 
        dest="env_file",
        help="Path to .env file with configuration"
    )
    parser.add_argument(
        "--amount",
        type=float,
        required=True,
        help="Amount of sDAI to use for trades"
    )
    parser.add_argument(
        "--interval",
        type=int,
        required=True,
        help="Seconds between price checks"
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        required=True,
        help="Minimum price deviation to trigger trade"
    )
    parser.add_argument(
        "--min-profit",
        type=float,
        default=0.0,
        help="Minimum profit required (can be negative for testing)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate trades without executing"
    )
    parser.add_argument(
        "--prefund",
        action="store_true",
        help="Transfer sDAI to executor contract if needed"
    )
    
    args = parser.parse_args()
    
    # Create and run bot
    try:
        bot = ArbitrageBot(args.env_file)
    except Exception as e:
        print(f"Failed to initialize bot: {e}")
        sys.exit(1)
    bot.run_loop(
        amount=args.amount,
        interval=args.interval,
        tolerance=args.tolerance,
        min_profit=args.min_profit,
        dry_run=args.dry_run,
        prefund=args.prefund
    )


if __name__ == "__main__":
    main()