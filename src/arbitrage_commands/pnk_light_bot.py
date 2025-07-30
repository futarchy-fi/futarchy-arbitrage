"""
pnk_light_bot.py
================
A specialized light bot for monitoring PNK (Kleros) token prices using multi-hop calculation
through WETH as an intermediary. This bot monitors PNK price discovery through:
- PNK/WETH pool for PNK price in WETH
- WETH/WXDAI pool for USD baseline
- sDAI contract for sDAI conversion rate

The bot calculates prices in sDAI, USD, and WETH formats for comprehensive price monitoring.

Usage
-----
    source futarchy_env/bin/activate
    source .env.pnk
    python -m src.arbitrage_commands.pnk_light_bot --interval 60 --min-profit 0.01
"""

from __future__ import annotations

import os
import sys
import time
import asyncio
from typing import Dict, Tuple, Any
from decimal import Decimal

from web3 import Web3
from web3.contract import Contract

from config.pnk_config import get_pnk_config, UNISWAP_V2_POOL_ABI, SDAI_ABI
from config.network import DEFAULT_RPC_URLS


class PNKLightBot:
    """Light bot for monitoring PNK prices through multi-hop calculation."""
    
    def __init__(self):
        self.cfg = get_pnk_config()
        self.w3 = self._make_web3()
        self.pool_id = self.cfg["PNK_WETH_POOL"]
        
    def _make_web3(self) -> Web3:
        """Return a Web3 connected to the RPC in config or fallback."""
        rpc_url = self.cfg.get("RPC_URL", DEFAULT_RPC_URLS[0])
        return Web3(Web3.HTTPProvider(rpc_url))
    
    async def _get_reserves(self, pool_address: str) -> Tuple[int, int]:
        """Get reserves from a Uniswap V2 pool."""
        pool = self.w3.eth.contract(
            address=self.w3.to_checksum_address(pool_address),
            abi=UNISWAP_V2_POOL_ABI
        )
        reserves = pool.functions.getReserves().call()
        return reserves[0], reserves[1]  # reserve0, reserve1
    
    async def _get_token0(self, pool_address: str) -> str:
        """Get token0 address from a pool."""
        pool = self.w3.eth.contract(
            address=self.w3.to_checksum_address(pool_address),
            abi=UNISWAP_V2_POOL_ABI
        )
        return pool.functions.token0().call()
    
    async def _get_sdai_rate(self) -> float:
        """Get current sDAI to DAI conversion rate."""
        sdai_contract = self.w3.eth.contract(
            address=self.w3.to_checksum_address(self.cfg["SDAI_CONTRACT"]),
            abi=SDAI_ABI
        )
        # Get how much DAI 1 sDAI is worth
        dai_amount = sdai_contract.functions.convertToAssets(10**18).call()
        return dai_amount / 10**18
    
    async def _current_price(self) -> Dict[str, float]:
        """Calculate current PNK prices in sDAI, USD, and WETH."""
        # Get WETH price in USD from WETH/WXDAI pool
        weth_address = self.cfg.get("WETH_ADDRESS")
        weth_wxdai_pool = self.cfg.get("WETH_WXDAI_POOL")
        r0, r1 = await self._get_reserves(weth_wxdai_pool)
        t0_weth = await self._get_token0(weth_wxdai_pool)
        weth_usd = (r1/1e18)/(r0/1e18) if t0_weth == weth_address else (r0/1e18)/(r1/1e18)
        
        # Get sDAI rate (how much DAI 1 sDAI is worth)
        sdai_rate = await self._get_sdai_rate()
        
        # Get PNK/WETH pool reserves and calculate PNK price
        p0, p1 = await self._get_reserves(self.pool_id)
        t0_pool = await self._get_token0(self.pool_id)
        price_weth = (p0/1e18)/(p1/1e18) if t0_pool == weth_address else (p1/1e18)/(p0/1e18)
        price_usd = price_weth * weth_usd
        price_sdai = price_usd / sdai_rate
        
        return {"sdai": price_sdai, "usd": price_usd, "weth": price_weth}
    
    def display_prices(self, prices: Dict[str, float]) -> None:
        """Display current PNK prices."""
        print(f"PNK Prices:")
        print(f"  1 PNK = {prices['sdai']:.6f} sDAI")
        print(f"  1 PNK = {prices['usd']:.6f} USD")
        print(f"  1 PNK = {prices['weth']:.6f} WETH")
        print()
    
    async def monitor_once(self) -> None:
        """Execute a single price check."""
        try:
            prices = await self._current_price()
            self.display_prices(prices)
            
            # Additional monitoring logic can be added here
            # For example: alerting on price thresholds, logging to file, etc.
            
        except Exception as e:
            print(f"Error fetching prices: {e}")
            import traceback
            traceback.print_exc()
    
    async def run(self, interval: int) -> None:
        """Main monitoring loop."""
        print(f"Starting PNK price monitor – interval: {interval} seconds")
        print(f"Monitoring PNK/WETH pool: {self.pool_id}")
        print()
        
        while True:
            await self.monitor_once()
            await asyncio.sleep(interval)


def validate_environment() -> bool:
    """Validate required environment variables."""
    required_vars = [
        "WETH_ADDRESS",
        "RPC_URL"
    ]
    
    missing = [var for var in required_vars if not os.getenv(var)]
    
    if missing:
        print(f"Error: Missing required environment variables: {', '.join(missing)}")
        return False
    
    return True


def main() -> None:
    """Entry point for PNK light bot."""
    import argparse
    
    parser = argparse.ArgumentParser(description="PNK price monitoring bot")
    parser.add_argument(
        "--interval", 
        type=int, 
        default=60,
        help="Interval between price checks in seconds (default: 60)"
    )
    parser.add_argument(
        "--min-profit",
        type=float,
        default=0.01,
        help="Minimum profit threshold for alerts (default: 0.01)"
    )
    
    args = parser.parse_args()
    
    # Validate environment
    if not validate_environment():
        sys.exit(1)
    
    # Create and run bot
    bot = PNKLightBot()
    
    try:
        asyncio.run(bot.run(args.interval))
    except KeyboardInterrupt:
        print("\nInterrupted – exiting.")


if __name__ == "__main__":
    main()