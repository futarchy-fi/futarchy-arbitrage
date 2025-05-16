Okay, based on the provided project structure and the goal of simplifying `main.py` by extracting reusable components, here's a refactoring strategy and the resulting code.

**Refactoring Strategy:**

1.  **Create Manager Classes:** Introduce dedicated classes to handle specific functionalities:
    * `SwapManager`: Handles all types of swaps (Balancer, Passthrough Router, sDAI-YES specific).
    * `ConditionalTokenManager`: Handles splitting and merging of collateral (GNO/sDAI <-> YES/NO tokens).
    * `GnoWrapper`: Handles wrapping GNO to waGNO and unwrapping waGNO to GNO.
2.  **Move Logic:** Migrate the core logic for swapping, splitting/merging, and wrapping/unwrapping from `main.py` and potentially other files (like `conditional_token_actions.py`, `aave_balancer.py`) into these manager classes.
3.  **Refactor `main.py`:**
    * Initialize the manager classes within the `main` function after initializing the `FutarchyBot`.
    * Replace direct calls to underlying handlers (e.g., `BalancerSwapHandler`, `PassthroughRouter`, `bot.add_collateral`) with calls to the methods of the new manager classes.
    * Pass the manager instances to the complex arbitrage functions (`execute_arbitrage_sell_synthetic_gno`, `execute_arbitrage_buy_synthetic_gno`).
    * Refactor the arbitrage functions to use the manager methods, significantly simplifying their internal logic.
4.  **Directory Structure:** Create a new directory `futarchy/experimental/managers/` to house the new manager classes.

---

**New Files:**

**1. `futarchy/experimental/managers/__init__.py`**

```python
# futarchy/experimental/managers/__init__.py
from .swap_manager import SwapManager
from .conditional_token_manager import ConditionalTokenManager
from .gno_wrapper import GnoWrapper

__all__ = [
    "SwapManager",
    "ConditionalTokenManager",
    "GnoWrapper"
]
```

**2. `futarchy/experimental/managers/swap_manager.py`**

```python
# futarchy/experimental/managers/swap_manager.py
import os
import math
from typing import Dict, Optional, Tuple

from web3 import Web3
from web3.contract import Contract

# Assuming these paths are correct relative to this file's location
# If not, adjust sys.path or use absolute imports if the project structure allows
try:
    from ..core.futarchy_bot import FutarchyBot # Relative import
    from ..exchanges.balancer.swap import BalancerSwapHandler
    from ..exchanges.passthrough_router import PassthroughRouter
    from ..config.constants import (
        TOKEN_CONFIG, CONTRACT_ADDRESSES, POOL_CONFIG_YES, POOL_CONFIG_NO,
        BALANCER_CONFIG, UNISWAP_V3_POOL_ABI, UNISWAP_V3_PASSTHROUGH_ROUTER_ABI,
        MIN_SQRT_RATIO, MAX_SQRT_RATIO
    )
    from ..utils.web3_utils import get_raw_transaction # Assuming this util is still needed
except ImportError:
    print("Error importing modules in SwapManager. Check relative paths or project structure.")
    raise

class SwapManager:
    """Manages different types of token swaps."""

    def __init__(self, bot: FutarchyBot):
        self.bot = bot
        self.w3 = bot.w3
        self.account = bot.account
        self.verbose = bot.verbose

        # Initialize underlying handlers
        self.balancer_handler = BalancerSwapHandler(bot)
        self.passthrough_router = PassthroughRouter(
            bot.w3,
            os.environ.get("PRIVATE_KEY"),
            CONTRACT_ADDRESSES["uniswapV3PassthroughRouter"] # Use correct key from constants
        )
        self.sdai_yes_pool_address = self.w3.to_checksum_address(CONTRACT_ADDRESSES["sdaiYesPool"])


    def swap_balancer(self, token_in_symbol: str, token_out_symbol: str, amount: float) -> Optional[Dict]:
        """
        Executes a swap on the Balancer sDAI/waGNO pool.

        Args:
            token_in_symbol: 'sDAI' or 'waGNO'
            token_out_symbol: 'sDAI' or 'waGNO'
            amount: Amount of token_in to swap (in ether units).

        Returns:
            Swap result dictionary or None on failure.
        """
        try:
            if token_in_symbol == 'sDAI' and token_out_symbol == 'waGNO':
                print(f"\n🔄 Swapping {amount} sDAI for waGNO on Balancer...")
                return self.balancer_handler.swap_sdai_to_wagno(amount)
            elif token_in_symbol == 'waGNO' and token_out_symbol == 'sDAI':
                print(f"\n🔄 Swapping {amount} waGNO for sDAI on Balancer...")
                return self.balancer_handler.swap_wagno_to_sdai(amount)
            else:
                print(f"❌ Unsupported Balancer swap: {token_in_symbol} -> {token_out_symbol}")
                return None
        except Exception as e:
            print(f"❌ Error during Balancer swap: {e}")
            import traceback
            traceback.print_exc()
            return None


    def _get_pool_data(self, pool_address: str) -> Tuple[Optional[Contract], Optional[int], Optional[str], Optional[str]]:
        """Gets key data from a V3 pool."""
        try:
            pool_contract = self.w3.eth.contract(address=self.w3.to_checksum_address(pool_address), abi=UNISWAP_V3_POOL_ABI)
            slot0 = pool_contract.functions.slot0().call()
            current_sqrt_price = slot0[0]
            token0 = pool_contract.functions.token0().call()
            token1 = pool_contract.functions.token1().call()
            return pool_contract, current_sqrt_price, token0, token1
        except Exception as e:
            print(f"❌ Error getting pool data for {pool_address}: {e}")
            return None, None, None, None


    def _calculate_sqrt_price_limit(self, current_sqrt_price: int, zero_for_one: bool, slippage_tolerance: float = 0.05) -> int:
        """Calculates the sqrtPriceLimitX96 based on direction and slippage."""
        if zero_for_one:
            # Price is decreasing, limit is lower bound
            limit = int(current_sqrt_price * (1 - slippage_tolerance))
            return max(limit, MIN_SQRT_RATIO)
        else:
            # Price is increasing, limit is upper bound
            limit = int(current_sqrt_price * (1 + slippage_tolerance))
            return min(limit, MAX_SQRT_RATIO)


    def swap_conditional(self, pool_address: str, token_in: str, token_out: str, amount: float, zero_for_one: bool, slippage_tolerance: float = 0.05) -> bool:
        """
        Executes a swap using the Passthrough Router for conditional tokens.

        Args:
            pool_address: Address of the Uniswap V3 pool.
            token_in: Address of the input token.
            token_out: Address of the output token.
            amount: Amount of token_in to swap (in ether units).
            zero_for_one: Swap direction (True if swapping token0 for token1).
            slippage_tolerance: Allowed slippage (e.g., 0.05 for 5%).

        Returns:
            True if the swap was successful, False otherwise.
        """
        print(f"\n🔄 Swapping {amount} {token_in} for {token_out} via Passthrough Router...")
        print(f"   Pool: {pool_address}, ZeroForOne: {zero_for_one}")

        pool_contract, current_sqrt_price, _, _ = self._get_pool_data(pool_address)
        if not pool_contract or current_sqrt_price is None:
            return False

        sqrt_price_limit_x96 = self._calculate_sqrt_price_limit(current_sqrt_price, zero_for_one, slippage_tolerance)
        print(f"   Current sqrtPriceX96: {current_sqrt_price}")
        print(f"   Calculated sqrtPriceLimitX96: {sqrt_price_limit_x96} (Slippage: {slippage_tolerance*100}%)")

        try:
            success = self.passthrough_router.execute_swap(
                pool_address=self.w3.to_checksum_address(pool_address),
                token_in=self.w3.to_checksum_address(token_in),
                token_out=self.w3.to_checksum_address(token_out),
                amount=amount,
                zero_for_one=zero_for_one,
                sqrt_price_limit_x96=sqrt_price_limit_x96
            )
            return success
        except Exception as e:
            print(f"❌ Error during conditional swap: {e}")
            import traceback
            traceback.print_exc()
            return False

    def buy_sdai_yes(self, amount_in_sdai: float, slippage_tolerance: float = 0.05) -> bool:
        """Buys sDAI-YES tokens using sDAI."""
        print(f"\n🔄 Buying sDAI-YES with {amount_in_sdai:.6f} sDAI...")

        pool_contract, _, token0, token1 = self._get_pool_data(self.sdai_yes_pool_address)
        if not pool_contract: return False

        sdai_address = self.w3.to_checksum_address(TOKEN_CONFIG["currency"]["address"])
        sdai_yes_address = self.w3.to_checksum_address(TOKEN_CONFIG["currency"]["yes_address"])

        if token0.lower() == sdai_yes_address.lower() and token1.lower() == sdai_address.lower():
            zero_for_one = False # Swapping token1 (sDAI) for token0 (sDAI-YES)
            token_in = sdai_address
            token_out = sdai_yes_address
            print("   Pool order: token0=sDAI-YES, token1=sDAI => zero_for_one=False")
        elif token0.lower() == sdai_address.lower() and token1.lower() == sdai_yes_address.lower():
            zero_for_one = True # Swapping token0 (sDAI) for token1 (sDAI-YES)
            token_in = sdai_address
            token_out = sdai_yes_address
            print("   Pool order: token0=sDAI, token1=sDAI-YES => zero_for_one=True")
        else:
            print("❌ Pool does not contain expected sDAI/sDAI-YES tokens")
            return False

        return self.swap_conditional(self.sdai_yes_pool_address, token_in, token_out, amount_in_sdai, zero_for_one, slippage_tolerance)

    def sell_sdai_yes(self, amount_in_sdai_yes: float, slippage_tolerance: float = 0.05) -> bool:
        """Sells sDAI-YES tokens for sDAI."""
        print(f"\n🔄 Selling {amount_in_sdai_yes:.6f} sDAI-YES for sDAI...")

        pool_contract, _, token0, token1 = self._get_pool_data(self.sdai_yes_pool_address)
        if not pool_contract: return False

        sdai_address = self.w3.to_checksum_address(TOKEN_CONFIG["currency"]["address"])
        sdai_yes_address = self.w3.to_checksum_address(TOKEN_CONFIG["currency"]["yes_address"])

        if token0.lower() == sdai_yes_address.lower() and token1.lower() == sdai_address.lower():
            zero_for_one = True # Swapping token0 (sDAI-YES) for token1 (sDAI)
            token_in = sdai_yes_address
            token_out = sdai_address
            print("   Pool order: token0=sDAI-YES, token1=sDAI => zero_for_one=True")
        elif token0.lower() == sdai_address.lower() and token1.lower() == sdai_yes_address.lower():
            zero_for_one = False # Swapping token1 (sDAI-YES) for token0 (sDAI)
            token_in = sdai_yes_address
            token_out = sdai_address
            print("   Pool order: token0=sDAI, token1=sDAI-YES => zero_for_one=False")
        else:
            print("❌ Pool does not contain expected sDAI/sDAI-YES tokens")
            return False

        return self.swap_conditional(self.sdai_yes_pool_address, token_in, token_out, amount_in_sdai_yes, zero_for_one, slippage_tolerance)

```

**3. `futarchy/experimental/managers/conditional_token_manager.py`**

```python
# futarchy/experimental/managers/conditional_token_manager.py
import traceback
from typing import Optional

# Assuming these paths are correct relative to this file's location
try:
    from ..core.futarchy_bot import FutarchyBot # Relative import
    from ..config.constants import TOKEN_CONFIG, CONTRACT_ADDRESSES
except ImportError:
    print("Error importing modules in ConditionalTokenManager. Check relative paths or project structure.")
    raise

class ConditionalTokenManager:
    """Manages splitting and merging of conditional tokens."""

    def __init__(self, bot: FutarchyBot):
        self.bot = bot
        self.w3 = bot.w3
        self.account = bot.account
        self.address = bot.address
        self.verbose = bot.verbose

    def split(self, token_symbol: str, amount: float) -> bool:
        """
        Splits a base token (GNO or sDAI) into YES/NO conditional tokens.

        Args:
            token_symbol: 'GNO' or 'sDAI'.
            amount: Amount of the base token to split (in ether units).

        Returns:
            True if successful, False otherwise.
        """
        token_type_map = {'GNO': 'company', 'sDAI': 'currency'}
        token_type = token_type_map.get(token_symbol)
        if not token_type:
            print(f"❌ Invalid token symbol for split: {token_symbol}")
            return False

        print(f"\n🔄 Splitting {amount} {token_symbol} into YES/NO tokens...")
        try:
            return self.bot.add_collateral(token_type, amount)
        except Exception as e:
            print(f"❌ Error during split operation: {e}")
            traceback.print_exc()
            return False

    def merge(self, token_symbol: str, amount: float) -> bool:
        """
        Merges YES/NO conditional tokens back into the base token (GNO or sDAI).

        Args:
            token_symbol: 'GNO' or 'sDAI'.
            amount: Amount of YES/NO pairs to merge (in ether units).

        Returns:
            True if successful, False otherwise.
        """
        token_type_map = {'GNO': 'company', 'sDAI': 'currency'}
        token_type = token_type_map.get(token_symbol)
        if not token_type:
            print(f"❌ Invalid token symbol for merge: {token_symbol}")
            return False

        print(f"\n🔄 Merging {amount} {token_symbol}-YES/NO pairs back into {token_symbol}...")
        try:
            return self.bot.remove_collateral(token_type, amount)
        except Exception as e:
            print(f"❌ Error during merge operation: {e}")
            traceback.print_exc()
            return False

```

**4. `futarchy/experimental/managers/gno_wrapper.py`**

```python
# futarchy/experimental/managers/gno_wrapper.py
import traceback
from typing import Optional

# Assuming these paths are correct relative to this file's location
try:
    from ..core.futarchy_bot import FutarchyBot # Relative import
    from ..exchanges.aave_balancer import AaveBalancerHandler
except ImportError:
    print("Error importing modules in GnoWrapper. Check relative paths or project structure.")
    raise

class GnoWrapper:
    """Manages wrapping GNO to waGNO and unwrapping waGNO to GNO."""

    def __init__(self, bot: FutarchyBot):
        self.bot = bot
        self.w3 = bot.w3
        self.account = bot.account
        self.address = bot.address
        self.verbose = bot.verbose
        # Note: FutarchyBot already initializes AaveBalancerHandler as self.aave_balancer
        self.handler = bot.aave_balancer # Use the existing handler

    def wrap(self, amount: float) -> Optional[str]:
        """
        Wraps GNO into waGNO.

        Args:
            amount: Amount of GNO to wrap (in ether units).

        Returns:
            Transaction hash string if successful, None otherwise.
        """
        print(f"\n🔄 Wrapping {amount} GNO into waGNO...")
        try:
            return self.handler.wrap_gno_to_wagno(amount)
        except Exception as e:
            print(f"❌ Error during wrap operation: {e}")
            traceback.print_exc()
            return None

    def unwrap(self, amount: float) -> Optional[str]:
        """
        Unwraps waGNO into GNO.

        Args:
            amount: Amount of waGNO to unwrap (in ether units).

        Returns:
            Transaction hash string if successful, None otherwise.
        """
        print(f"\n🔄 Unwrapping {amount} waGNO into GNO...")
        try:
            return self.handler.unwrap_wagno(amount) # Uses alias in handler
        except Exception as e:
            print(f"❌ Error during unwrap operation: {e}")
            traceback.print_exc()
            return None
```

---

**Updated File:**

**`futarchy/experimental/main.py`**

```python
#!/usr/bin/env python3
"""
Futarchy Trading Bot - Main entry point (Refactored)

This module is currently in EXPERIMENTAL status.
Please use with caution as functionality may change.
"""

import sys
import os
import argparse
from decimal import Decimal
import time
import json
from web3 import Web3
from dotenv import load_dotenv
# from futarchy.experimental.exchanges.sushiswap import SushiSwapExchange # Might be unused now
# from futarchy.experimental.exchanges.passthrough_router import PassthroughRouter # Now used internally by SwapManager

# --- Core and Strategy Imports ---
# Add the project root to the path if necessary, or adjust imports based on your structure
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from futarchy.experimental.core.futarchy_bot import FutarchyBot
from futarchy.experimental.strategies.monitoring import simple_monitoring_strategy
from futarchy.experimental.strategies.probability import probability_threshold_strategy
from futarchy.experimental.strategies.arbitrage import arbitrage_strategy

# --- Manager Imports ---
from futarchy.experimental.managers import (
    SwapManager,
    ConditionalTokenManager,
    GnoWrapper
)

# --- Configuration Imports ---
from futarchy.experimental.config.constants import (
    CONTRACT_ADDRESSES,
    TOKEN_CONFIG,
    POOL_CONFIG_YES,
    POOL_CONFIG_NO,
    BALANCER_CONFIG,
    DEFAULT_SWAP_CONFIG,
    DEFAULT_PERMIT_CONFIG,
    DEFAULT_RPC_URLS,
    UNISWAP_V3_POOL_ABI,
    UNISWAP_V3_PASSTHROUGH_ROUTER_ABI,
    ERC20_ABI,
    MIN_SQRT_RATIO,
    MAX_SQRT_RATIO
)
from eth_account import Account
from eth_account.signers.local import LocalAccount
import math

# Comment out direct action imports if logic is fully moved to managers
# from futarchy.experimental.actions.conditional_token_actions import sell_sdai_yes, buy_sdai_yes
# from futarchy.experimental.exchanges.balancer.swap import BalancerSwapHandler # Now used internally by SwapManager

# --- Argument Parsing (Keep as is) ---
def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(description='Futarchy Trading Bot (Refactored)')

    # General options
    parser.add_argument('--rpc', type=str, help='RPC URL for Gnosis Chain')
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose output')

    # Command mode
    subparsers = parser.add_subparsers(dest='command', help='Command to run')

    # Interactive mode (default)
    interactive_parser = subparsers.add_parser('interactive', help='Run in interactive mode')

    # Monitor mode
    monitor_parser = subparsers.add_parser('monitor', help='Run monitoring strategy')
    monitor_parser.add_argument('--iterations', type=int, default=5, help='Number of monitoring iterations')
    monitor_parser.add_argument('--interval', type=int, default=60, help='Interval between updates (seconds)')

    # Probability strategy mode
    prob_parser = subparsers.add_parser('prices', help='Show current market prices and probabilities')
    # Remove strategy-specific args if prices command only shows prices
    # prob_parser.add_argument('--buy', type=float, default=0.7, help='Buy threshold')
    # prob_parser.add_argument('--sell', type=float, default=0.3, help='Sell threshold')
    # prob_parser.add_argument('--amount', type=float, default=0.1, help='Trade amount')

    # Arbitrage strategy mode
    arb_parser = subparsers.add_parser('arbitrage', help='Run arbitrage strategy')
    arb_parser.add_argument('--diff', type=float, default=0.02, help='Minimum price difference')
    arb_parser.add_argument('--amount', type=float, default=0.1, help='Trade amount')

    # Balance commands
    balances_parser = subparsers.add_parser('balances', help='Show token balances')
    refresh_balances_parser = subparsers.add_parser('refresh_balances', help='Refresh and show token balances')

    # Buy/Wrap/Unwrap GNO commands
    buy_wrapped_gno_parser = subparsers.add_parser('buy_wrapped_gno', help='Buy waGNO with sDAI on Balancer')
    buy_wrapped_gno_parser.add_argument('amount', type=float, help='Amount of sDAI to spend')

    buy_gno_parser = subparsers.add_parser('buy_gno', help='Buy GNO with sDAI (buys waGNO and unwraps it)')
    buy_gno_parser.add_argument('amount', type=float, help='Amount of sDAI to spend')

    wrap_gno_parser = subparsers.add_parser('wrap_gno', help='Wrap GNO to waGNO')
    wrap_gno_parser.add_argument('amount', type=float, help='Amount of GNO to wrap')

    unwrap_wagno_parser = subparsers.add_parser('unwrap_wagno', help='Unwrap waGNO to GNO')
    unwrap_wagno_parser.add_argument('amount', type=float, help='Amount of waGNO to unwrap')

    # Conditional Token Commands
    split_gno_parser = subparsers.add_parser('split_gno', help='Split GNO into GNO-YES/NO tokens')
    split_gno_parser.add_argument('amount', type=float, help='Amount of GNO to split')

    split_sdai_parser = subparsers.add_parser('split_sdai', help='Split sDAI into sDAI-YES/NO tokens')
    split_sdai_parser.add_argument('amount', type=float, help='Amount of sDAI to split')

    merge_gno_parser = subparsers.add_parser('merge_gno', help='Merge GNO-YES/NO pairs back into GNO')
    merge_gno_parser.add_argument('amount', type=float, help='Amount of GNO-YES/NO pairs to merge')

    merge_sdai_parser = subparsers.add_parser('merge_sdai', help='Merge sDAI-YES/NO pairs back into sDAI')
    merge_sdai_parser.add_argument('amount', type=float, help='Amount of sDAI-YES/NO pairs to merge')

    # --- Conditional Swap Commands ---
    swap_gno_yes_to_sdai_yes_parser = subparsers.add_parser('swap_gno_yes_to_sdai_yes', help='Swap GNO YES to sDAI YES')
    swap_gno_yes_to_sdai_yes_parser.add_argument('amount', type=float, help='Amount of GNO YES to swap')

    swap_sdai_yes_to_gno_yes_parser = subparsers.add_parser('swap_sdai_yes_to_gno_yes', help='Swap sDAI YES to GNO YES')
    swap_sdai_yes_to_gno_yes_parser.add_argument('amount', type=float, help='Amount of sDAI YES to swap')

    swap_gno_no_to_sdai_no_parser = subparsers.add_parser('swap_gno_no_to_sdai_no', help='Swap GNO NO to sDAI NO')
    swap_gno_no_to_sdai_no_parser.add_argument('amount', type=float, help='Amount of GNO NO to swap')

    swap_sdai_no_to_gno_no_parser = subparsers.add_parser('swap_sdai_no_to_gno_no', help='Swap sDAI NO to GNO NO')
    swap_sdai_no_to_gno_no_parser.add_argument('amount', type=float, help='Amount of sDAI NO to swap')

    buy_sdai_yes_parser = subparsers.add_parser('buy_sdai_yes', help='Buy sDAI-YES tokens with sDAI using the dedicated sDAI/sDAI-YES pool')
    buy_sdai_yes_parser.add_argument('amount', type=float, help='Amount of sDAI to spend')

    sell_sdai_yes_parser = subparsers.add_parser('sell_sdai_yes', help='Sell sDAI-YES tokens for sDAI using the dedicated sDAI/sDAI-YES pool')
    sell_sdai_yes_parser.add_argument('amount', type=float, help='Amount of sDAI-YES to sell')

    # --- Arbitrage Commands ---
    arbitrage_sell_synthetic_gno_parser = subparsers.add_parser('arbitrage_sell_synthetic_gno',
                                help='Execute full arbitrage: buy GNO spot -> split -> sell YES/NO -> balance & merge')
    arbitrage_sell_synthetic_gno_parser.add_argument('amount', type=float, help='Amount of sDAI to use for arbitrage')

    arbitrage_buy_synthetic_gno_parser = subparsers.add_parser('arbitrage_buy_synthetic_gno',
                                help='Execute full arbitrage: buy sDAI-YES/NO -> buy GNO-YES/NO -> merge -> wrap -> sell')
    arbitrage_buy_synthetic_gno_parser.add_argument('amount', type=float, help='Amount of sDAI to use for arbitrage')

    # Debug and Test commands
    debug_parser = subparsers.add_parser('debug', help='Run in debug mode with additional output')
    test_swaps_parser = subparsers.add_parser('test_swaps', help='Test all swap functions with small amounts')
    test_swaps_parser.add_argument('--amount', type=float, default=0.001, help='Amount to use for testing (default: 0.001)')

    return parser.parse_args()

# --- Main Function ---
def main():
    """Main entry point"""
    args = parse_args()

    # Load environment variables from .env file
    load_dotenv()

    # --- Initialization ---
    try:
        bot = FutarchyBot(rpc_url=args.rpc, verbose=args.verbose)
        swap_manager = SwapManager(bot)
        token_manager = ConditionalTokenManager(bot)
        gno_wrapper = GnoWrapper(bot)
    except ConnectionError as e:
        print(f"❌ Connection Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Initialization Error: {e}")
        traceback.print_exc()
        sys.exit(1)

    # --- Command Handling ---
    try:
        if args.command == 'debug':
            # Debug mode - check pool configuration and balances
            print("\n🔍 Debug Information:")
            try:
                balances = bot.get_balances()
                bot.print_balances(balances)
            except Exception as e:
                print(f"❌ Error getting balances: {e}")

            try:
                prices = bot.get_market_prices()
                bot.print_market_prices(prices)
            except Exception as e:
                print(f"❌ Error getting prices: {e}")
            return

        elif args.command in ['balances', 'refresh_balances']:
            balances = bot.get_balances()
            bot.print_balances(balances)
            return

        # Check if command needs an amount and if it's provided
        if hasattr(args, 'amount') and not args.amount and args.command not in ['test_swaps', 'prices']:
            print("❌ Amount is required for this command")
            return

        # --- Run Commands ---
        if args.command == 'monitor':
            print(f"Running monitoring strategy for {args.iterations} iterations every {args.interval} seconds")
            bot.run_strategy(lambda b: simple_monitoring_strategy(b, args.iterations, args.interval))

        elif args.command == 'prices':
            prices = bot.get_market_prices()
            if prices:
                bot.print_market_prices(prices)
            return

        elif args.command == 'arbitrage':
            print(f"Running arbitrage strategy (min diff: {args.diff}, amount: {args.amount})")
            bot.run_strategy(lambda b: arbitrage_strategy(b, args.diff, args.amount))

        # --- Balancer/Wrap/Unwrap ---
        elif args.command == 'buy_wrapped_gno':
            result = swap_manager.swap_balancer('sDAI', 'waGNO', args.amount)
            if result and result.get('success'):
                print(f"\n✅ Successfully bought waGNO. Tx: {result['tx_hash']}")
            else:
                print(f"\n❌ Failed to buy waGNO.")

        elif args.command == 'buy_gno':
            print(f"\n🔄 Buying and unwrapping GNO using {args.amount} sDAI...")
            # Step 1: Buy waGNO
            buy_result = swap_manager.swap_balancer('sDAI', 'waGNO', args.amount)
            if not buy_result or not buy_result.get('success'):
                print("❌ Failed to buy waGNO")
                sys.exit(1)

            wagno_received = abs(buy_result.get('balance_changes', {}).get('token_out', 0))
            if wagno_received <= 0:
                # Fallback: check balance if change wasn't calculated
                print("⚠️ Could not determine waGNO received from swap result, checking balance...")
                balances_before = bot.get_balances() # Fetch balances just before unwrap
                wagno_received = float(balances_before['wagno']['wallet']) # Assume all waGNO is to be unwrapped
                if wagno_received <= 0:
                    print("❌ No waGNO available to unwrap.")
                    sys.exit(1)

            print(f"\n✅ Successfully bought {wagno_received:.18f} waGNO")

            # Step 2: Unwrap waGNO
            unwrap_result = gno_wrapper.unwrap(wagno_received)
            if unwrap_result:
                print(f"\n✅ Successfully unwrapped waGNO. Tx: {unwrap_result}")
            else:
                print(f"\n❌ Failed to unwrap waGNO.")
            bot.print_balances(bot.get_balances())

        elif args.command == 'wrap_gno':
            tx_hash = gno_wrapper.wrap(args.amount)
            if tx_hash:
                bot.print_balances(bot.get_balances())

        elif args.command == 'unwrap_wagno':
            tx_hash = gno_wrapper.unwrap(args.amount)
            if tx_hash:
                bot.print_balances(bot.get_balances())

        # --- Conditional Token Split/Merge ---
        elif args.command == 'split_gno':
            if token_manager.split('GNO', args.amount):
                bot.print_balances(bot.get_balances())

        elif args.command == 'split_sdai':
            if token_manager.split('sDAI', args.amount):
                bot.print_balances(bot.get_balances())

        elif args.command == 'merge_gno':
            if token_manager.merge('GNO', args.amount):
                bot.print_balances(bot.get_balances())

        elif args.command == 'merge_sdai':
            if token_manager.merge('sDAI', args.amount):
                bot.print_balances(bot.get_balances())

        # --- Conditional Swaps ---
        elif args.command == 'swap_gno_yes_to_sdai_yes':
            # GNO-YES (token0 in YES pool) -> sDAI-YES (token1 in YES pool) => zero_for_one=True
            swap_manager.swap_conditional(
                pool_address=POOL_CONFIG_YES["address"],
                token_in=TOKEN_CONFIG["company"]["yes_address"],
                token_out=TOKEN_CONFIG["currency"]["yes_address"],
                amount=args.amount,
                zero_for_one=True
            )
            bot.print_balances(bot.get_balances())

        elif args.command == 'swap_sdai_yes_to_gno_yes':
            # sDAI-YES (token1 in YES pool) -> GNO-YES (token0 in YES pool) => zero_for_one=False
            swap_manager.swap_conditional(
                pool_address=POOL_CONFIG_YES["address"],
                token_in=TOKEN_CONFIG["currency"]["yes_address"],
                token_out=TOKEN_CONFIG["company"]["yes_address"],
                amount=args.amount,
                zero_for_one=False
            )
            bot.print_balances(bot.get_balances())

        elif args.command == 'swap_gno_no_to_sdai_no':
            # GNO-NO (token1 in NO pool) -> sDAI-NO (token0 in NO pool) => zero_for_one=False
            swap_manager.swap_conditional(
                pool_address=POOL_CONFIG_NO["address"],
                token_in=TOKEN_CONFIG["company"]["no_address"],
                token_out=TOKEN_CONFIG["currency"]["no_address"],
                amount=args.amount,
                zero_for_one=False
            )
            bot.print_balances(bot.get_balances())

        elif args.command == 'swap_sdai_no_to_gno_no':
            # sDAI-NO (token0 in NO pool) -> GNO-NO (token1 in NO pool) => zero_for_one=True
            swap_manager.swap_conditional(
                pool_address=POOL_CONFIG_NO["address"],
                token_in=TOKEN_CONFIG["currency"]["no_address"],
                token_out=TOKEN_CONFIG["company"]["no_address"],
                amount=args.amount,
                zero_for_one=True
            )
            bot.print_balances(bot.get_balances())

        elif args.command == 'buy_sdai_yes':
            swap_manager.buy_sdai_yes(args.amount)
            bot.print_balances(bot.get_balances())

        elif args.command == 'sell_sdai_yes':
            swap_manager.sell_sdai_yes(args.amount)
            bot.print_balances(bot.get_balances())

        # --- Test Swaps ---
        elif args.command == 'test_swaps':
            print("\n🧪 Testing all swap functions with small amounts...")
            test_amount = args.amount if hasattr(args, 'amount') else 0.001

            results = {}

            print("\n\n--- 1. GNO YES -> sDAI YES ---")
            results['gno_yes_to_sdai_yes'] = swap_manager.swap_conditional(
                POOL_CONFIG_YES["address"], TOKEN_CONFIG["company"]["yes_address"], TOKEN_CONFIG["currency"]["yes_address"], test_amount, True)

            print("\n\n--- 2. sDAI YES -> GNO YES ---")
            results['sdai_yes_to_gno_yes'] = swap_manager.swap_conditional(
                POOL_CONFIG_YES["address"], TOKEN_CONFIG["currency"]["yes_address"], TOKEN_CONFIG["company"]["yes_address"], test_amount, False)

            print("\n\n--- 3. GNO NO -> sDAI NO ---")
            results['gno_no_to_sdai_no'] = swap_manager.swap_conditional(
                POOL_CONFIG_NO["address"], TOKEN_CONFIG["company"]["no_address"], TOKEN_CONFIG["currency"]["no_address"], test_amount, False)

            print("\n\n--- 4. sDAI NO -> GNO NO ---")
            results['sdai_no_to_gno_no'] = swap_manager.swap_conditional(
                POOL_CONFIG_NO["address"], TOKEN_CONFIG["currency"]["no_address"], TOKEN_CONFIG["company"]["no_address"], test_amount, True)

            print("\n\n--- 5. Buy sDAI YES ---")
            results['buy_sdai_yes'] = swap_manager.buy_sdai_yes(test_amount)

            print("\n\n--- 6. Sell sDAI YES ---")
            results['sell_sdai_yes'] = swap_manager.sell_sdai_yes(test_amount)

            print("\n\n--- 7. Balancer: sDAI -> waGNO ---")
            balancer_res1 = swap_manager.swap_balancer('sDAI', 'waGNO', test_amount)
            results['sdai_to_wagno'] = balancer_res1 and balancer_res1.get('success', False)

            print("\n\n--- 8. Balancer: waGNO -> sDAI ---")
            balancer_res2 = swap_manager.swap_balancer('waGNO', 'sDAI', test_amount)
            results['wagno_to_sdai'] = balancer_res2 and balancer_res2.get('success', False)

            # Print summary
            print("\n\n============================================")
            print("🧪 Swap Tests Summary")
            print("============================================")
            for name, success in results.items():
                status = '✅ Success' if success else '❌ Failed'
                print(f"{name.replace('_', ' ').title()}: {status}")

            # Show final balances
            bot.print_balances(bot.get_balances())

        # --- Arbitrage Flows ---
        elif args.command == 'arbitrage_sell_synthetic_gno':
            execute_arbitrage_sell_synthetic_gno(bot, args.amount, swap_manager, token_manager, gno_wrapper)

        elif args.command == 'arbitrage_buy_synthetic_gno':
            execute_arbitrage_buy_synthetic_gno(bot, args.amount, swap_manager, token_manager, gno_wrapper)

        else:
            # Default to showing help if no command matched
            print("Please specify a command. Use --help for available commands.")
            sys.exit(1)

    except Exception as e:
        print(f"\n❌ An error occurred: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


# --- Refactored Arbitrage Functions ---

def execute_arbitrage_sell_synthetic_gno(bot, sdai_amount, swap_manager, token_manager, gno_wrapper):
    """
    Execute a full arbitrage operation (Sell Synthetic GNO direction).
    Uses manager classes for simplified logic.
    """
    print(f"\n🔄 Starting Sell Synthetic GNO Arbitrage with {sdai_amount} sDAI")
    initial_balances = bot.get_balances()
    initial_sdai = float(initial_balances['currency']['wallet'])
    initial_wagno = float(initial_balances['wagno']['wallet']) # Track initial waGNO for accurate received amount

    if initial_sdai < sdai_amount:
        print(f"❌ Insufficient sDAI balance. Required: {sdai_amount}, Available: {initial_sdai}")
        return

    print("\n📊 Initial market prices:")
    market_prices = bot.get_market_prices()
    if not market_prices: return # Stop if prices can't be fetched
    bot.print_market_prices(market_prices)
    synthetic_price, spot_price = bot.calculate_synthetic_price()

    # Step 1: Buy waGNO with sDAI
    print(f"\n🔹 Step 1: Buying waGNO with {sdai_amount} sDAI...")
    buy_result = swap_manager.swap_balancer('sDAI', 'waGNO', sdai_amount)
    if not buy_result or not buy_result.get('success'):
        print("❌ Failed to buy waGNO. Aborting.")
        return

    # Calculate waGNO received accurately
    balances_after_buy = bot.get_balances()
    wagno_after_buy = float(balances_after_buy['wagno']['wallet'])
    wagno_received = wagno_after_buy - initial_wagno

    if wagno_received <= 0:
        print("❌ No waGNO received or balance calculation error. Aborting.")
        return
    print(f"✅ Successfully received {wagno_received:.6f} waGNO")

    # Step 2: Unwrap waGNO to GNO
    print(f"\n🔹 Step 2: Unwrapping {wagno_received:.6f} waGNO...")
    gno_before_unwrap = float(balances_after_buy['company']['wallet'])
    unwrap_tx = gno_wrapper.unwrap(wagno_received)
    if not unwrap_tx:
        print("⚠️ Failed to unwrap waGNO, but attempting to continue by checking balance...")
    
    # Verify GNO received
    balances_after_unwrap = bot.get_balances()
    gno_after_unwrap = float(balances_after_unwrap['company']['wallet'])
    gno_amount_unwrapped = gno_after_unwrap - gno_before_unwrap

    if gno_amount_unwrapped <= 0:
        print("❌ No GNO received after unwrapping. Aborting.")
        return
    print(f"✅ Successfully received {gno_amount_unwrapped:.6f} GNO")

    # Step 3: Split GNO into YES/NO tokens
    print(f"\n🔹 Step 3: Splitting {gno_amount_unwrapped:.6f} GNO...")
    gno_yes_before_split = float(balances_after_unwrap['company']['yes'])
    gno_no_before_split = float(balances_after_unwrap['company']['no'])
    
    if not token_manager.split('GNO', gno_amount_unwrapped):
        print("❌ Failed to split GNO. Aborting.")
        return

    # Get amounts received from split
    balances_after_split = bot.get_balances()
    gno_yes_to_sell = float(balances_after_split['company']['yes']) - gno_yes_before_split
    gno_no_to_sell = float(balances_after_split['company']['no']) - gno_no_before_split

    if gno_yes_to_sell <= 0 or gno_no_to_sell <= 0:
        print("❌ Failed to receive GNO-YES/NO tokens after split. Aborting.")
        return
    print(f"✅ Received {gno_yes_to_sell:.6f} GNO-YES and {gno_no_to_sell:.6f} GNO-NO")

    # Step 4: Sell GNO-YES for sDAI-YES
    print(f"\n🔹 Step 4: Selling {gno_yes_to_sell:.6f} GNO-YES...")
    sdai_yes_before_swap = float(balances_after_split['currency']['yes'])
    success_sell_yes = swap_manager.swap_conditional(
        pool_address=POOL_CONFIG_YES["address"],
        token_in=TOKEN_CONFIG["company"]["yes_address"],
        token_out=TOKEN_CONFIG["currency"]["yes_address"],
        amount=gno_yes_to_sell,
        zero_for_one=True
    )
    if not success_sell_yes: print("⚠️ Failed to sell GNO-YES, continuing...")

    # Step 5: Sell GNO-NO for sDAI-NO
    print(f"\n🔹 Step 5: Selling {gno_no_to_sell:.6f} GNO-NO...")
    sdai_no_before_swap = float(balances_after_split['currency']['no'])
    time.sleep(2) # Avoid nonce issues
    success_sell_no = swap_manager.swap_conditional(
        pool_address=POOL_CONFIG_NO["address"],
        token_in=TOKEN_CONFIG["company"]["no_address"],
        token_out=TOKEN_CONFIG["currency"]["no_address"],
        amount=gno_no_to_sell,
        zero_for_one=False
    )
    if not success_sell_no: print("⚠️ Failed to sell GNO-NO, continuing...")

    # Step 6: Balance sDAI-YES and sDAI-NO
    print("\n🔹 Step 6: Balancing sDAI-YES/NO tokens...")
    balances_after_swaps = bot.get_balances()
    sdai_yes_after = float(balances_after_swaps['currency']['yes'])
    sdai_no_after = float(balances_after_swaps['currency']['no'])
    sdai_wallet_balance = float(balances_after_swaps['currency']['wallet'])

    print(f"   Current sDAI-YES: {sdai_yes_after:.6f}")
    print(f"   Current sDAI-NO: {sdai_no_after:.6f}")

    if sdai_yes_after > sdai_no_after:
        difference = sdai_yes_after - sdai_no_after
        print(f"   Selling {difference:.6f} excess sDAI-YES...")
        if not swap_manager.sell_sdai_yes(difference):
            print("⚠️ Failed to sell excess sDAI-YES.")
    elif sdai_no_after > sdai_yes_after:
        difference = sdai_no_after - sdai_yes_after
        print(f"   Need {difference:.6f} more sDAI-YES.")
        if sdai_wallet_balance >= difference:
            print(f"   Buying {difference:.6f} sDAI-YES...")
            if not swap_manager.buy_sdai_yes(difference):
                print("⚠️ Failed to buy required sDAI-YES.")
        else:
            print(f"   Insufficient sDAI ({sdai_wallet_balance:.6f}) to buy {difference:.6f} sDAI-YES.")
    else:
        print("   sDAI-YES and sDAI-NO are already balanced.")

    # Step 7: Merge sDAI-YES and sDAI-NO
    balances_after_balance = bot.get_balances()
    sdai_yes_final = float(balances_after_balance['currency']['yes'])
    sdai_no_final = float(balances_after_balance['currency']['no'])
    merge_amount = min(sdai_yes_final, sdai_no_final)

    print(f"\n🔹 Step 7: Merging {merge_amount:.6f} sDAI-YES/NO pairs...")
    if merge_amount > 0:
        if not token_manager.merge('sDAI', merge_amount):
            print("⚠️ Failed to merge sDAI tokens.")
    else:
        print("   No pairs to merge.")

    # Step 8: Final Report (Simplified from original, add detailed value estimation if needed)
    final_balances = bot.get_balances()
    final_sdai = float(final_balances['currency']['wallet'])
    profit_loss = final_sdai - initial_sdai
    profit_loss_percent = (profit_loss / sdai_amount) * 100 if sdai_amount > 0 else 0

    print("\n📈 Arbitrage Operation Summary")
    print("=" * 40)
    print(f"Initial sDAI: {initial_sdai:.6f}")
    print(f"Final sDAI: {final_sdai:.6f}")
    print(f"Direct Profit/Loss: {profit_loss:.6f} sDAI ({profit_loss_percent:.2f}%)")
    # Add estimation of remaining token values if desired

    synthetic_price_final, spot_price_final = bot.calculate_synthetic_price()
    print("\nMarket Prices:")
    print(f"Initial GNO Spot: {spot_price:.6f} -> Final: {spot_price_final:.6f}")
    print(f"Initial GNO Synthetic: {synthetic_price:.6f} -> Final: {synthetic_price_final:.6f}")

    if profit_loss > 0:
        print("\n✅ Arbitrage was profitable!")
    else:
        print("\n⚠️ Arbitrage was not profitable.")

def execute_arbitrage_buy_synthetic_gno(bot, sdai_amount, swap_manager, token_manager, gno_wrapper):
    """
    Execute a full arbitrage operation (Buy Synthetic GNO direction).
    Uses manager classes for simplified logic.
    """
    print(f"\n🔄 Starting Buy Synthetic GNO Arbitrage with {sdai_amount} sDAI")
    initial_balances = bot.get_balances()
    initial_sdai = float(initial_balances['currency']['wallet'])

    if initial_sdai < sdai_amount:
        print(f"❌ Insufficient sDAI balance. Required: {sdai_amount}, Available: {initial_sdai}")
        return

    # Step 1 & 2: Get prices and calculate optimal amounts
    print("\n🔹 Step 1 & 2: Calculating optimal amounts...")
    market_prices = bot.get_market_prices()
    if not market_prices: return
    bot.print_market_prices(market_prices)

    yes_price = market_prices['yes_price']
    no_price = market_prices['no_price']
    probability = market_prices['probability']
    synthetic_price, spot_price = bot.calculate_synthetic_price()

    if no_price == 0 or yes_price == 0:
        print("❌ Cannot calculate optimal amounts due to zero price for YES or NO tokens.")
        return

    denominator = (yes_price * probability) / no_price + (1 - probability)
    if denominator == 0:
        print("❌ Cannot calculate optimal amounts due to zero denominator.")
        return

    y = sdai_amount / denominator # Target sDAI-NO amount
    x = y * (yes_price / no_price) # Target sDAI-YES amount

    print(f"   Target sDAI-YES (x): {x:.6f}")
    print(f"   Target sDAI-NO (y): {y:.6f}")

    # Step 3, 4, 5: Acquire and Balance sDAI-YES/NO
    print("\n🔹 Step 3-5: Acquiring and balancing sDAI-YES/NO...")
    sda_yes_balance_before = float(initial_balances['currency']['yes'])

    if x > y:
        direct_yes_buy_sdai = (x - y) * probability # Estimate sDAI needed
        print(f"   Need more YES. Buying ~{direct_yes_buy_sdai:.6f} sDAI worth of sDAI-YES...")
        if not swap_manager.buy_sdai_yes(direct_yes_buy_sdai):
            print("⚠️ Failed to buy direct sDAI-YES, continuing...")

    print(f"   Splitting {y:.6f} sDAI into YES/NO...")
    if not token_manager.split('sDAI', y):
        print("❌ Failed to split sDAI. Aborting.")
        return

    # Recheck balance after potential direct buy and split
    balances_after_split = bot.get_balances()
    current_sdai_yes = float(balances_after_split['currency']['yes'])
    sda_yes_acquired = current_sdai_yes - sda_yes_balance_before # Total acquired

    if x < sda_yes_acquired: # Check if we acquired more than target x (happens if x < y)
        excess_yes = sda_yes_acquired - x
        print(f"   Have excess YES. Selling {excess_yes:.6f} sDAI-YES...")
        if not swap_manager.sell_sdai_yes(excess_yes):
            print("⚠️ Failed to sell excess sDAI-YES, continuing...")

    # Get final available amounts for swapping to GNO conditionals
    balances_before_gno_swap = bot.get_balances()
    sdai_yes_available = float(balances_before_gno_swap['currency']['yes'])
    sdai_no_available = float(balances_before_gno_swap['currency']['no'])

    # Step 6: Buy GNO-YES with sDAI-YES
    print(f"\n🔹 Step 6: Buying GNO-YES with {sdai_yes_available:.6f} sDAI-YES...")
    success_buy_gno_yes = swap_manager.swap_conditional(
        pool_address=POOL_CONFIG_YES["address"],
        token_in=TOKEN_CONFIG["currency"]["yes_address"],
        token_out=TOKEN_CONFIG["company"]["yes_address"],
        amount=sdai_yes_available,
        zero_for_one=False
    )
    if not success_buy_gno_yes: print("⚠️ Failed to buy GNO-YES, continuing...")

    # Step 7: Buy GNO-NO with sDAI-NO
    print(f"\n🔹 Step 7: Buying GNO-NO with {sdai_no_available:.6f} sDAI-NO...")
    time.sleep(2) # Avoid nonce issues
    success_buy_gno_no = swap_manager.swap_conditional(
        pool_address=POOL_CONFIG_NO["address"],
        token_in=TOKEN_CONFIG["currency"]["no_address"],
        token_out=TOKEN_CONFIG["company"]["no_address"],
        amount=sdai_no_available,
        zero_for_one=True
    )
    if not success_buy_gno_no: print("⚠️ Failed to buy GNO-NO, continuing...")

    # Step 8: Merge GNO-YES/NO into GNO
    balances_after_gno_buy = bot.get_balances()
    gno_yes_final = float(balances_after_gno_buy['company']['yes'])
    gno_no_final = float(balances_after_gno_buy['company']['no'])
    merge_gno_amount = min(gno_yes_final, gno_no_final)

    print(f"\n🔹 Step 8: Merging {merge_gno_amount:.6f} GNO-YES/NO pairs...")
    if merge_gno_amount > 0:
        if not token_manager.merge('GNO', merge_gno_amount):
            print("⚠️ Failed to merge GNO tokens.")
    else:
        print("   No GNO pairs to merge.")

    # Step 9: Wrap GNO into waGNO
    balances_after_gno_merge = bot.get_balances()
    gno_to_wrap = float(balances_after_gno_merge['company']['wallet'])
    print(f"\n🔹 Step 9: Wrapping {gno_to_wrap:.6f} GNO...")
    if gno_to_wrap > 0:
        wrap_tx = gno_wrapper.wrap(gno_to_wrap)
        if not wrap_tx: print("⚠️ Failed to wrap GNO.")
    else:
        print("   No GNO to wrap.")

    # Step 10: Sell waGNO for sDAI
    balances_after_wrap = bot.get_balances()
    wagno_to_sell = float(balances_after_wrap['wagno']['wallet'])
    print(f"\n🔹 Step 10: Selling {wagno_to_sell:.6f} waGNO...")
    if wagno_to_sell > 0:
        sell_result = swap_manager.swap_balancer('waGNO', 'sDAI', wagno_to_sell)
        if not sell_result or not sell_result.get('success'):
            print("⚠️ Failed to sell waGNO.")
    else:
        print("   No waGNO to sell.")

    # Step 11: Final Report
    final_balances = bot.get_balances()
    final_sdai = float(final_balances['currency']['wallet'])
    profit_loss = final_sdai - initial_sdai
    profit_loss_percent = (profit_loss / sdai_amount) * 100 if sdai_amount > 0 else 0

    print("\n📈 Arbitrage Operation Summary")
    print("=" * 40)
    print(f"Initial sDAI: {initial_sdai:.6f}")
    print(f"Final sDAI: {final_sdai:.6f}")
    print(f"Direct Profit/Loss: {profit_loss:.6f} sDAI ({profit_loss_percent:.2f}%)")
    # Add estimation of remaining token values if desired

    synthetic_price_final, spot_price_final = bot.calculate_synthetic_price()
    print("\nMarket Prices:")
    print(f"Initial GNO Spot: {spot_price:.6f} -> Final: {spot_price_final:.6f}")
    print(f"Initial GNO Synthetic: {synthetic_price:.6f} -> Final: {synthetic_price_final:.6f}")

    if profit_loss > 0:
        print("\n✅ Arbitrage was profitable!")
    else:
        print("\n⚠️ Arbitrage was not profitable.")

# --- Entry Point ---
if __name__ == "__main__":
    main()
```

**Explanation of Changes:**

1.  **Managers:** Three new classes (`SwapManager`, `ConditionalTokenManager`, `GnoWrapper`) are created in the `futarchy/experimental/managers/` directory.
2.  **Logic Migration:**
    * Swap logic (Balancer, Passthrough, sDAI-YES/sDAI) is moved into `SwapManager`. It uses the existing `BalancerSwapHandler` and `PassthroughRouter` internally.
    * Splitting (`add_collateral`) and merging (`remove_collateral`) logic is wrapped by `ConditionalTokenManager`.
    * Wrapping/unwrapping logic is wrapped by `GnoWrapper`, using the existing `AaveBalancerHandler`.
3.  **`main.py` Refactoring:**
    * Imports are updated to bring in the managers.
    * Managers are initialized after the `FutarchyBot`.
    * Individual command handlers (like `buy_wrapped_gno`, `split_gno`, `swap_gno_yes_to_sdai_yes`, etc.) now call the appropriate manager methods instead of directly interacting with lower-level handlers or bot methods. This makes the command handling section cleaner.
    * The `execute_arbitrage_*` functions now accept the manager instances as arguments.
    * Inside the arbitrage functions, each step is replaced by a call to a manager method (e.g., `swap_manager.swap_balancer(...)`, `token_manager.split(...)`, `gno_wrapper.unwrap(...)`). This dramatically simplifies the structure of these complex functions, making the arbitrage *strategy* much clearer.
    * Error handling (checking return values of manager methods) is maintained within the arbitrage flows.
    * Redundant imports within `main.py` are commented out or removed.

**To Use This Refactoring:**

1.  Create the `futarchy/experimental/managers/` directory.
2.  Save the code for `__init__.py`, `swap_manager.py`, `conditional_token_manager.py`, and `gno_wrapper.py` into that directory.
3.  Replace the contents of your existing `futarchy/experimental/main.py` with the updated code provided above.
4.  Ensure necessary imports within the manager files resolve correctly based on your project setup (relative imports `..core.futarchy_bot` assume a standard package structure). Adjust if needed.

This refactoring significantly improves the organization and readability of `main.py` by delegating specific tasks to dedicated manager classes, making the code easier to understand, maintain, and extend.