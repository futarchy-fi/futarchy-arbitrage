"""Unified Bot implementation using Supabase configuration system.

This bot replaces the old .env-based configuration with a centralized
Supabase-based system that supports multiple bots and markets.
"""

import argparse
import time
import sys
from decimal import Decimal
from typing import Dict, Any, Optional
from web3 import Web3
from eth_account import Account

# Add parent directory to path for imports
sys.path.insert(0, '/home/ubuntu/futarchy-arbitrage')

from src.config.config_manager import ConfigManager
from src.config.network import w3
from src.helpers.balancer_fetcher import BalancerFetcher
from src.helpers.swapr_fetcher import SwaprFetcher
from src.helpers.balancer_swapper import BalancerSwapper
from src.helpers.swapr_swapper import SwaprSwapper
from src.helpers.futarchy_swapper import FutarchySwapper
from src.arbitrage_commands.buy_cond import handle_buy_conditional_transaction
from src.arbitrage_commands.sell_cond import handle_sell_conditional_transaction


class UnifiedBot:
    """Unified arbitrage bot using Supabase configuration."""
    
    def __init__(self, bot_name: str, dry_run: bool = False):
        """Initialize the unified bot.
        
        Args:
            bot_name: Name of the bot in Supabase
            dry_run: If True, simulate trades without executing
        """
        self.bot_name = bot_name
        self.dry_run = dry_run
        
        # Initialize configuration manager
        self.config_manager = ConfigManager()
        
        # Load bot configuration
        self.bot_config = self.config_manager.get_bot_config(bot_name)
        self.account = self.config_manager.get_bot_account(bot_name)
        
        # Extract configuration sections
        self.strategy_config = self.bot_config['config'].get('strategy', {})
        self.risk_config = self.bot_config['config'].get('risk', {})
        self.contract_config = self.bot_config['config'].get('contracts', {})
        self.parameters = self.bot_config['config'].get('parameters', {})
        
        # Initialize Web3 with bot's account
        self.w3 = w3
        self.w3.eth.default_account = self.account.address
        
        # Initialize fetchers and swappers
        self._initialize_components()
        
        # Track daily trades for risk management
        self.daily_trade_count = 0
        self.last_trade_reset = time.time()
        
    def _initialize_components(self):
        """Initialize price fetchers and swappers based on market assignments."""
        # Get active market assignments
        assignments = self.config_manager.get_bot_assignments(self.bot_name)
        
        if not assignments:
            raise ValueError(f"No active market assignments for bot '{self.bot_name}'")
        
        # For now, use the first assignment (can be extended for multi-market support)
        assignment = assignments[0]
        
        # Extract addresses from assignment and config
        self.balancer_pool_address = assignment.get('pool_id')
        self.swapr_pool_yes_address = self.parameters.get('swapr_pool_yes_address')
        self.swapr_pool_no_address = self.parameters.get('swapr_pool_no_address')
        self.swapr_pool_pred_yes_address = self.parameters.get('swapr_pool_pred_yes_address')
        
        # Contract addresses
        self.futarchy_router_address = self.contract_config.get('futarchy_router_address')
        self.futarchy_proposal_address = self.contract_config.get('futarchy_proposal_address')
        
        # Token addresses
        self.sdai_token_address = self.parameters.get('sdai_token_address')
        self.company_token_address = self.parameters.get('company_token_address')
        self.swapr_sdai_yes_address = self.parameters.get('swapr_sdai_yes_address')
        self.swapr_sdai_no_address = self.parameters.get('swapr_sdai_no_address')
        self.swapr_gno_yes_address = self.parameters.get('swapr_gno_yes_address')
        self.swapr_gno_no_address = self.parameters.get('swapr_gno_no_address')
        
        # Initialize fetchers
        self.balancer_fetcher = BalancerFetcher(
            pool_address=self.balancer_pool_address,
            web3=self.w3
        )
        
        self.swapr_fetcher = SwaprFetcher(
            pool_yes_address=self.swapr_pool_yes_address,
            pool_no_address=self.swapr_pool_no_address,
            pool_pred_yes_address=self.swapr_pool_pred_yes_address,
            web3=self.w3
        )
        
        # Initialize swappers
        self.balancer_swapper = BalancerSwapper(
            pool_address=self.balancer_pool_address,
            web3=self.w3,
            account=self.account
        )
        
        self.swapr_swapper = SwaprSwapper(
            pool_yes_address=self.swapr_pool_yes_address,
            pool_no_address=self.swapr_pool_no_address,
            web3=self.w3,
            account=self.account
        )
        
        self.futarchy_swapper = FutarchySwapper(
            router_address=self.futarchy_router_address,
            proposal_address=self.futarchy_proposal_address,
            web3=self.w3,
            account=self.account
        )
        
    def check_risk_limits(self) -> bool:
        """Check if trading is within risk limits.
        
        Returns:
            True if trading is allowed, False otherwise
        """
        # Reset daily counter if needed
        current_time = time.time()
        if current_time - self.last_trade_reset > 86400:  # 24 hours
            self.daily_trade_count = 0
            self.last_trade_reset = current_time
        
        # Check daily trade limit
        max_daily_trades = self.risk_config.get('max_daily_trades', 100)
        if self.daily_trade_count >= max_daily_trades:
            print(f"Daily trade limit reached ({max_daily_trades})")
            return False
        
        # Check account balance against risk limit
        balance = self.w3.eth.get_balance(self.account.address)
        risk_limit = Decimal(self.risk_config.get('risk_limit', '5000'))
        
        if balance < self.w3.to_wei(risk_limit, 'ether'):
            print(f"Account balance below risk limit ({risk_limit} ETH)")
            return False
        
        return True
    
    def calculate_arbitrage_opportunity(self) -> tuple[str, Decimal]:
        """Calculate arbitrage opportunity between Balancer and Swapr.
        
        Returns:
            Tuple of (direction, profit_percentage)
            direction: 'buy' or 'sell' or 'none'
            profit_percentage: Expected profit as decimal
        """
        # Fetch prices
        balancer_price = self.balancer_fetcher.get_price()
        swapr_prices = self.swapr_fetcher.get_prices()
        
        if not balancer_price or not swapr_prices:
            return 'none', Decimal('0')
        
        # Calculate synthetic ideal price
        pred_price = swapr_prices.get('pred_yes_price', Decimal('0.5'))
        yes_price = swapr_prices.get('yes_price', Decimal('0'))
        no_price = swapr_prices.get('no_price', Decimal('0'))
        
        ideal_price = pred_price * yes_price + (Decimal('1') - pred_price) * no_price
        
        # Calculate price difference
        price_diff = (balancer_price - ideal_price) / ideal_price
        
        # Get tolerance from strategy config
        tolerance = Decimal(str(self.strategy_config.get('price_tolerance', 0.02)))
        
        print(f"Balancer price: {balancer_price:.4f}, Ideal price: {ideal_price:.4f}, "
              f"Difference: {price_diff:.2%}")
        
        # Determine arbitrage direction
        if price_diff > tolerance:
            # Balancer price is higher - sell on Balancer, buy on Swapr
            return 'sell', abs(price_diff)
        elif price_diff < -tolerance:
            # Balancer price is lower - buy on Balancer, sell on Swapr
            return 'buy', abs(price_diff)
        else:
            return 'none', Decimal('0')
    
    def execute_trade(self, direction: str, amount: Decimal):
        """Execute arbitrage trade.
        
        Args:
            direction: 'buy' or 'sell'
            amount: Amount to trade in sDAI
        """
        print(f"\nExecuting {direction} trade for {amount} sDAI")
        
        if direction == 'buy':
            # Buy conditional tokens strategy
            if self.dry_run:
                print("DRY RUN: Would execute buy conditional strategy")
                return
            
            result = handle_buy_conditional_transaction(
                amount_sdai=amount,
                futarchy_swapper=self.futarchy_swapper,
                swapr_swapper=self.swapr_swapper,
                balancer_swapper=self.balancer_swapper,
                web3=self.w3,
                account=self.account,
                sdai_token_address=self.sdai_token_address,
                company_token_address=self.company_token_address,
                swapr_sdai_yes_address=self.swapr_sdai_yes_address,
                swapr_sdai_no_address=self.swapr_sdai_no_address,
                swapr_gno_yes_address=self.swapr_gno_yes_address,
                swapr_gno_no_address=self.swapr_gno_no_address
            )
            
        elif direction == 'sell':
            # Sell conditional tokens strategy
            if self.dry_run:
                print("DRY RUN: Would execute sell conditional strategy")
                return
            
            result = handle_sell_conditional_transaction(
                amount_company=amount,  # Convert to company token amount
                futarchy_swapper=self.futarchy_swapper,
                swapr_swapper=self.swapr_swapper,
                balancer_swapper=self.balancer_swapper,
                web3=self.w3,
                account=self.account,
                sdai_token_address=self.sdai_token_address,
                company_token_address=self.company_token_address,
                swapr_sdai_yes_address=self.swapr_sdai_yes_address,
                swapr_sdai_no_address=self.swapr_sdai_no_address,
                swapr_gno_yes_address=self.swapr_gno_yes_address,
                swapr_gno_no_address=self.swapr_gno_no_address
            )
        
        # Increment trade counter
        self.daily_trade_count += 1
        
    def run_once(self):
        """Run a single arbitrage check and execute if profitable."""
        # Check risk limits
        if not self.check_risk_limits():
            print("Risk limits exceeded, skipping trade")
            return
        
        # Calculate arbitrage opportunity
        direction, profit_pct = self.calculate_arbitrage_opportunity()
        
        # Check minimum profit threshold
        min_profit = Decimal(str(self.strategy_config.get('min_profit_threshold', 0.001)))
        
        if direction != 'none' and profit_pct >= min_profit:
            # Calculate trade amount
            trading_amount = Decimal(str(self.parameters.get('trading_amount', '0.1')))
            max_trade_size = Decimal(str(self.strategy_config.get('max_trade_size', '1000')))
            
            # Apply trade size limits
            trade_amount = min(trading_amount, max_trade_size)
            
            print(f"\nArbitrage opportunity found: {direction} with {profit_pct:.2%} profit")
            
            # Execute trade
            self.execute_trade(direction, trade_amount)
        else:
            print("No profitable arbitrage opportunity")
    
    def run(self):
        """Run the bot continuously."""
        # Get check interval from parameters
        interval = int(self.parameters.get('check_interval', 120))
        
        print(f"Starting unified bot '{self.bot_name}'")
        print(f"Account: {self.account.address}")
        print(f"Check interval: {interval} seconds")
        print(f"Dry run: {self.dry_run}")
        
        while True:
            try:
                self.run_once()
            except Exception as e:
                print(f"Error in bot loop: {e}")
            
            # Wait for next check
            time.sleep(interval)


def main():
    """Main entry point for unified bot."""
    parser = argparse.ArgumentParser(description='Unified arbitrage bot')
    parser.add_argument('--bot-name', required=True, help='Bot name in Supabase')
    parser.add_argument('--dry-run', action='store_true', help='Simulate trades without executing')
    parser.add_argument('--once', action='store_true', help='Run once and exit')
    
    args = parser.parse_args()
    
    try:
        # Create and run bot
        bot = UnifiedBot(bot_name=args.bot_name, dry_run=args.dry_run)
        
        if args.once:
            bot.run_once()
        else:
            bot.run()
            
    except KeyboardInterrupt:
        print("\nBot stopped by user")
    except Exception as e:
        print(f"Bot error: {e}")
        raise


if __name__ == "__main__":
    main()