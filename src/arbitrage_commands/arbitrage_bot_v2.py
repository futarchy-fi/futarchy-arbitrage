#!/usr/bin/env python3
"""
Futarchy Arbitrage Bot V2 - JSON Configuration Support

Monitors price discrepancies between Balancer and Swapr pools and executes
arbitrage trades via the FutarchyArbExecutorV5 contract.

Usage with JSON config:
    python -m src.arbitrage_commands.arbitrage_bot_v2 \
        --config config/proposal_0x9590.json

Usage with .env (backward compatible):
    python -m src.arbitrage_commands.arbitrage_bot_v2 \
        --env .env.0x9590dAF4d5cd4009c3F9767C5E7668175cFd37CF \
        --amount 0.01 \
        --interval 120 \
        --tolerance 0.04 \
        --min-profit -0.01
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import subprocess
import re
from decimal import Decimal
from pathlib import Path
from typing import Tuple, Optional, Dict, Any

from dotenv import load_dotenv
from web3 import Web3
from eth_account import Account

from helpers.swapr_price import get_pool_price as swapr_price
from helpers.balancer_price import get_pool_price as bal_price
from config.network import DEFAULT_RPC_URLS


class ConfigManager:
    """Manages configuration from both JSON and environment sources."""
    
    def __init__(self, config_path: Optional[str] = None, env_file: Optional[str] = None):
        """Initialize configuration from JSON or environment file."""
        self.config = {}
        self.env_file = env_file
        
        if config_path:
            self.load_json_config(config_path)
        elif env_file:
            self.load_env_config(env_file)
        else:
            # Try to load from default locations
            self.load_default_config()
    
    def load_json_config(self, config_path: str) -> None:
        """Load configuration from JSON file."""
        with open(config_path, 'r') as f:
            self.config = json.load(f)
            
    def load_env_config(self, env_file: str) -> None:
        """Load configuration from .env file and map to JSON structure."""
        # Load base .env if exists
        base_env = Path(".env")
        if base_env.exists():
            load_dotenv(base_env)
        if env_file:
            load_dotenv(env_file)
            
        # Map env variables to config structure
        self.config = self._map_env_to_config()
    
    def load_default_config(self) -> None:
        """Try to load from default locations."""
        # Check for JSON configs in config directory
        config_dir = Path("config")
        if config_dir.exists():
            json_files = list(config_dir.glob("proposal_*.json"))
            if json_files:
                self.load_json_config(str(json_files[0]))
                return
        
        # Fall back to environment
        base_env = Path(".env")
        if base_env.exists():
            load_dotenv(base_env)
        self.config = self._map_env_to_config()
    
    def _map_env_to_config(self) -> Dict[str, Any]:
        """Map environment variables to JSON config structure."""
        return {
            "bot": {
                "type": os.getenv("BOT_TYPE", "balancer"),
                # run_options can be filled/overridden later by set_runtime_params
            },
            "network": {
                "rpc_url": os.getenv("RPC_URL"),
                "chain_id": int(os.getenv("CHAIN_ID", "100"))
            },
            "wallet": {
                "private_key": os.getenv("PRIVATE_KEY")
            },
            "contracts": {
                "executor_v5": os.getenv("FUTARCHY_ARB_EXECUTOR_V5") or os.getenv("EXECUTOR_V5_ADDRESS"),
                "routers": {
                    "balancer": os.getenv("BALANCER_ROUTER_ADDRESS"),
                    "balancer_vault": os.getenv("BALANCER_VAULT_ADDRESS") or os.getenv("BALANCER_VAULT_V3_ADDRESS"),
                    "swapr": os.getenv("SWAPR_ROUTER_ADDRESS"),
                    "futarchy": os.getenv("FUTARCHY_ROUTER_ADDRESS")
                }
            },
            "proposal": {
                "address": os.getenv("FUTARCHY_PROPOSAL_ADDRESS"),
                "tokens": {
                    "currency": {
                        "address": os.getenv("SDAI_TOKEN_ADDRESS", "0xaf204776c7245bF4147c2612BF6e5972Ee483701"),
                        "symbol": "sDAI"
                    },
                    "company": {
                        "address": os.getenv("COMPANY_TOKEN_ADDRESS", "0x9C58BAcC331c9aa871AFD802DB6379a98e80CEdb"),
                        "symbol": "GNO"
                    },
                    "yes_currency": {
                        "address": os.getenv("SWAPR_SDAI_YES_ADDRESS")
                    },
                    "no_currency": {
                        "address": os.getenv("SWAPR_SDAI_NO_ADDRESS")
                    },
                    "yes_company": {
                        "address": os.getenv("SWAPR_GNO_YES_ADDRESS")
                    },
                    "no_company": {
                        "address": os.getenv("SWAPR_GNO_NO_ADDRESS")
                    }
                },
                "pools": {
                    "balancer_company_currency": {
                        "address": os.getenv("BALANCER_POOL_ADDRESS")
                    },
                    "swapr_yes_company_yes_currency": {
                        "address": os.getenv("SWAPR_POOL_YES_ADDRESS")
                    },
                    "swapr_no_company_no_currency": {
                        "address": os.getenv("SWAPR_POOL_NO_ADDRESS")
                    },
                    "swapr_yes_currency_currency": {
                        "address": os.getenv("SWAPR_POOL_PRED_YES_ADDRESS")
                    },
                    "swapr_no_currency_currency": {
                        "address": os.getenv("SWAPR_POOL_PRED_NO_ADDRESS")
                    }
                }
            }
        }
    
    def get(self, path: str, default: Any = None) -> Any:
        """Get a value from config using dot notation path."""
        keys = path.split('.')
        value = self.config
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
                if value is None:
                    return default
            else:
                return default
        return value
    
    def set_runtime_params(self, amount: Optional[float] = None, 
                          interval: Optional[int] = None,
                          tolerance: Optional[float] = None,
                          min_profit: Optional[float] = None) -> None:
        """Override runtime parameters from command line."""
        if "bot" not in self.config:
            self.config["bot"] = {"run_options": {}}
        if "run_options" not in self.config["bot"]:
            self.config["bot"]["run_options"] = {}
            
        if amount is not None:
            self.config["bot"]["run_options"]["amount"] = amount
        if interval is not None:
            self.config["bot"]["run_options"]["interval_seconds"] = interval
        if tolerance is not None:
            self.config["bot"]["run_options"]["tolerance"] = tolerance
        if min_profit is not None:
            self.config["bot"]["run_options"]["min_profit"] = min_profit
    
    def to_env_dict(self) -> Dict[str, str]:
        """Convert config back to environment variable format for subprocess."""
        env_dict = {}
        
        # Network and wallet
        if self.get("network.rpc_url"):
            env_dict["RPC_URL"] = self.get("network.rpc_url")
        if self.get("network.chain_id"):
            env_dict["CHAIN_ID"] = str(self.get("network.chain_id"))
        if self.get("wallet.private_key"):
            env_dict["PRIVATE_KEY"] = self.get("wallet.private_key")
            
        # Contracts
        if self.get("contracts.executor_v5"):
            env_dict["FUTARCHY_ARB_EXECUTOR_V5"] = self.get("contracts.executor_v5")
        if self.get("contracts.routers.balancer"):
            env_dict["BALANCER_ROUTER_ADDRESS"] = self.get("contracts.routers.balancer")
        if self.get("contracts.routers.balancer_vault"):
            env_dict["BALANCER_VAULT_ADDRESS"] = self.get("contracts.routers.balancer_vault")
        if self.get("contracts.routers.swapr"):
            env_dict["SWAPR_ROUTER_ADDRESS"] = self.get("contracts.routers.swapr")
        if self.get("contracts.routers.futarchy"):
            env_dict["FUTARCHY_ROUTER_ADDRESS"] = self.get("contracts.routers.futarchy")
            
        # Proposal and tokens
        if self.get("proposal.address"):
            env_dict["FUTARCHY_PROPOSAL_ADDRESS"] = self.get("proposal.address")
        if self.get("proposal.tokens.currency.address"):
            env_dict["SDAI_TOKEN_ADDRESS"] = self.get("proposal.tokens.currency.address")
        if self.get("proposal.tokens.company.address"):
            env_dict["COMPANY_TOKEN_ADDRESS"] = self.get("proposal.tokens.company.address")
        if self.get("proposal.tokens.yes_currency.address"):
            env_dict["SWAPR_SDAI_YES_ADDRESS"] = self.get("proposal.tokens.yes_currency.address")
        if self.get("proposal.tokens.no_currency.address"):
            env_dict["SWAPR_SDAI_NO_ADDRESS"] = self.get("proposal.tokens.no_currency.address")
        if self.get("proposal.tokens.yes_company.address"):
            env_dict["SWAPR_GNO_YES_ADDRESS"] = self.get("proposal.tokens.yes_company.address")
        if self.get("proposal.tokens.no_company.address"):
            env_dict["SWAPR_GNO_NO_ADDRESS"] = self.get("proposal.tokens.no_company.address")
            
        # Pools
        if self.get("proposal.pools.balancer_company_currency.address"):
            env_dict["BALANCER_POOL_ADDRESS"] = self.get("proposal.pools.balancer_company_currency.address")
        if self.get("proposal.pools.swapr_yes_company_yes_currency.address"):
            env_dict["SWAPR_POOL_YES_ADDRESS"] = self.get("proposal.pools.swapr_yes_company_yes_currency.address")
        if self.get("proposal.pools.swapr_no_company_no_currency.address"):
            env_dict["SWAPR_POOL_NO_ADDRESS"] = self.get("proposal.pools.swapr_no_company_no_currency.address")
        if self.get("proposal.pools.swapr_yes_currency_currency.address"):
            env_dict["SWAPR_POOL_PRED_YES_ADDRESS"] = self.get("proposal.pools.swapr_yes_currency_currency.address")
        if self.get("proposal.pools.swapr_no_currency_currency.address"):
            env_dict["SWAPR_POOL_PRED_NO_ADDRESS"] = self.get("proposal.pools.swapr_no_currency_currency.address")
            
        return env_dict


class ArbitrageBot:
    """Monitors and executes futarchy arbitrage opportunities."""
    
    def __init__(self, config: ConfigManager):
        """Initialize the bot with configuration."""
        self.config = config
        self.w3 = self.create_web3()
        self.validate_configuration()
        self.setup_account()
        self.setup_token_contracts()
        
    def create_web3(self) -> Web3:
        """Create Web3 connection."""
        rpc_url = self.config.get("network.rpc_url")
        if not rpc_url:
            rpc_url = DEFAULT_RPC_URLS[0]
            
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
        private_key = self.config.get("wallet.private_key")
        if not private_key:
            raise SystemExit("Missing private key in configuration")
        self.account = Account.from_key(private_key)
        self.wallet_address = self.account.address
        
        # Get executor contract address
        self.executor_address = self.get_executor_address()
        print(f"Monitoring executor contract: {self.executor_address}")
    
    def get_executor_address(self) -> str:
        """Get the executor contract address from config or deployment files."""
        import glob
        import json
        
        # Try configuration first
        executor = self.config.get("contracts.executor_v5")
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
        token_mapping = {
            "sDAI": "proposal.tokens.currency.address",
            "GNO": "proposal.tokens.company.address",
            "YES_GNO": "proposal.tokens.yes_company.address",
            "NO_GNO": "proposal.tokens.no_company.address",
            "YES_sDAI": "proposal.tokens.yes_currency.address",
            "NO_sDAI": "proposal.tokens.no_currency.address"
        }
        
        for name, path in token_mapping.items():
            addr = self.config.get(path)
            if addr:
                self.tokens[name] = self.w3.eth.contract(
                    address=self.w3.to_checksum_address(addr),
                    abi=erc20_abi
                )
        
    def validate_configuration(self) -> None:
        """Ensure all required configuration values are set."""
        required_paths = [
            "proposal.pools.swapr_yes_company_yes_currency.address",
            "proposal.pools.swapr_yes_currency_currency.address",
            "proposal.pools.swapr_no_company_no_currency.address",
            "proposal.pools.balancer_company_currency.address",
            "wallet.private_key",
            "network.rpc_url"
        ]
        
        missing = []
        for path in required_paths:
            if not self.config.get(path):
                missing.append(path)
                
        if missing:
            raise SystemExit(f"Missing required configuration: {', '.join(missing)}")
            
    def fetch_prices(self) -> dict:
        """Fetch current prices from all pools."""
        addr_yes = self.config.get("proposal.pools.swapr_yes_company_yes_currency.address")
        addr_pred_yes = self.config.get("proposal.pools.swapr_yes_currency_currency.address")
        addr_no = self.config.get("proposal.pools.swapr_no_company_no_currency.address")
        addr_bal = self.config.get("proposal.pools.balancer_company_currency.address")
        
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
        patterns = [
            r"Tx sent:\s*(?:0x)?([a-fA-F0-9]{64})",
            r"Transaction hash:\s*(?:0x)?([a-fA-F0-9]{64})",
            r"tx:\s*(?:0x)?([a-fA-F0-9]{64})"
        ]
        
        for pattern in patterns:
            match = re.search(pattern, output, re.IGNORECASE)
            if match:
                tx_hash = match.group(1)
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
        # Select executor module by bot type (default: balancer)
        bot_type = str(self.config.get("bot.type", "balancer") or "balancer").lower()
        module = "src.executor.arbitrage_pnk_executor" if bot_type == "pnk" else "src.executor.arbitrage_executor"

        # Build command for chosen executor
        cmd = [
            sys.executable, "-m", module,
            "--flow", flow,
            "--amount", str(amount),
            "--cheaper", cheaper,
            "--min-profit", str(min_profit)
        ]
        
        if prefund:
            cmd.append("--prefund")
            
        if dry_run:
            print(f"\n[DRY RUN] Would execute: {' '.join(cmd)}")
            return True, None
            
        print(f"\nExecuting arbitrage: {flow.upper()} flow, {cheaper.upper()} cheaper")
        print(f"Executor type: {bot_type}")
        print(f"Command: {' '.join(cmd)}")
        
        # Create environment with all necessary variables
        env = os.environ.copy()
        env.update(self.config.to_env_dict())
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,  # 2 minute timeout
                env=env
            )
            
            # Parse transaction hash from output
            tx_hash = self.parse_tx_hash(result.stdout)
            
            if result.returncode == 0:
                print("✓ Trade executed successfully")
                if tx_hash:
                    print(f"🔗 View on GnosisScan: https://gnosisscan.io/tx/{tx_hash}")
                return True, tx_hash
            else:
                # Check if it's a "min profit not met" error which is expected
                if "min profit not met" in result.stderr:
                    print("⚠️  Trade skipped: Min profit threshold not met")
                    return False, None
                else:
                    print(f"✗ Trade failed with exit code {result.returncode}")
                    # Only show error details for unexpected failures
                    if result.stderr:
                        # Extract just the error message, not the full trace
                        error_lines = result.stderr.strip().split('\n')
                        for line in reversed(error_lines):
                            if 'Error' in line or 'error' in line or 'Exception' in line:
                                print(f"   Error: {line.strip()}")
                                break
                return False, None
                
        except subprocess.TimeoutExpired:
            print("✗ Trade execution timed out")
            return False, None
        except Exception as e:
            print(f"✗ Error executing trade: {e}")
            return False, None
            
    def run_loop(self, dry_run: bool = False, prefund: bool = False) -> None:
        """Main monitoring loop."""
        # Get runtime parameters from config
        amount = self.config.get("bot.run_options.amount", 0.01)
        interval = self.config.get("bot.run_options.interval_seconds", 120)
        tolerance = self.config.get("bot.run_options.tolerance", 0.04)
        min_profit = self.config.get("bot.run_options.min_profit", 0.0)
        
        print(f"\n🤖 Starting Futarchy Arbitrage Bot")
        print(f"   Proposal:    {self.config.get('proposal.address', 'N/A')}")
        print(f"   Amount:      {amount} {self.config.get('proposal.tokens.currency.symbol', 'sDAI')}")
        print(f"   Interval:    {interval} seconds")
        print(f"   Tolerance:   {tolerance}")
        print(f"   Min Profit:  {min_profit}")
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
                        balances_before = self.get_balances()
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
                        balances_after = self.get_balances()
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
        description="Futarchy arbitrage bot with JSON configuration support"
    )
    
    # Configuration source (mutually exclusive)
    config_group = parser.add_mutually_exclusive_group()
    config_group.add_argument(
        "--config",
        help="Path to JSON configuration file"
    )
    config_group.add_argument(
        "--env", 
        dest="env_file",
        help="Path to .env file with configuration (backward compatibility)"
    )
    
    # Runtime parameters (can override config)
    parser.add_argument(
        "--amount",
        type=float,
        help="Amount of base currency to use for trades (overrides config)"
    )
    parser.add_argument(
        "--interval",
        type=int,
        help="Seconds between price checks (overrides config)"
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        help="Minimum price deviation to trigger trade (overrides config)"
    )
    parser.add_argument(
        "--min-profit",
        type=float,
        help="Minimum profit required (can be negative for testing, overrides config)"
    )
    
    # Execution flags
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
    
    # Load configuration
    try:
        config = ConfigManager(config_path=args.config, env_file=args.env_file)
        
        # Override runtime parameters if provided
        config.set_runtime_params(
            amount=args.amount,
            interval=args.interval,
            tolerance=args.tolerance,
            min_profit=args.min_profit
        )
        
        # Validate we have required runtime parameters
        if not config.get("bot.run_options.amount") and not args.amount:
            if args.env_file:
                parser.error("--amount is required when using --env")
            else:
                parser.error("bot.run_options.amount not found in config and --amount not provided")
                
        if not config.get("bot.run_options.interval_seconds") and not args.interval:
            if args.env_file:
                parser.error("--interval is required when using --env")
            else:
                parser.error("bot.run_options.interval_seconds not found in config and --interval not provided")
                
        if not config.get("bot.run_options.tolerance") and not args.tolerance:
            if args.env_file:
                parser.error("--tolerance is required when using --env")
            else:
                parser.error("bot.run_options.tolerance not found in config and --tolerance not provided")
        
        # Create and run bot
        bot = ArbitrageBot(config)
        bot.run_loop(dry_run=args.dry_run, prefund=args.prefund)
        
    except Exception as e:
        print(f"Failed to initialize bot: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
