#!/usr/bin/env python3
"""
CLI wrapper for executing sDAI->Aave GNO via Balancer Vault through FutarchyArbExecutorV4.runTrade.

Usage:
    python scripts/run_balancer_buy.py 0.01 --slippage-bps 50 --dry-run
    python scripts/run_balancer_buy.py 0.01
"""

import os
import sys
import argparse
from decimal import Decimal
from pathlib import Path

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent))

from src.arbitrage_commands.buy_company import run_balancer_buy

def main():
    p = argparse.ArgumentParser(
        description="Execute sDAI->Aave GNO via Balancer **Router** through FutarchyArbExecutorV4.runTrade"
    )
    p.add_argument("amount", type=Decimal, help="Amount of sDAI to spend")
    p.add_argument("--slippage-bps", type=int, default=50, help="Slippage tolerance in basis points (default: 50 = 0.5%)")
    p.add_argument("--dry-run", action="store_true", help="Build transaction without sending")
    args = p.parse_args()

    executor_addr = os.environ.get("EXECUTOR_V4_ADDRESS", "0xb74a98b75B4efde911Bb95F7a2A0E7Bc3376e15B")
    if not os.environ.get("EXECUTOR_V4_ADDRESS"):
        print(f"⚠️  EXECUTOR_V4_ADDRESS not set, using: {executor_addr}")

    required_env = ["RPC_URL", "PRIVATE_KEY", "SDAI_TOKEN_ADDRESS"]
    for env in required_env:
        if not os.environ.get(env):
            raise SystemExit(f"Missing required environment variable: {env}")

    # Aave GNO token address (this is what Pool 1 trades)
    AAVE_GNO = "0x7c16f0185a26db0ae7a9377f23bc18ea7ce5d644"
    # The sDAI/Aave GNO pool
    POOL_SDAI_AAVE_GNO = "0xd1d7fa8871d84d0e77020fc28b7cd5718c446522"

    result = run_balancer_buy(
        rpc_url=os.environ["RPC_URL"],
        private_key=os.environ["PRIVATE_KEY"],
        executor_addr=executor_addr,
        token_cur=os.environ["SDAI_TOKEN_ADDRESS"],
        token_aave_gno=AAVE_GNO,
        balancer_vault=os.environ.get("BALANCER_VAULT_ADDRESS", "0xBA12222222228d8Ba445958a75a0704d566BF2C8"),
        pool_sdai_aave_gno=POOL_SDAI_AAVE_GNO,
        amount_cur_in=args.amount,
        slippage_bps=args.slippage_bps,
        dry_run=args.dry_run,
    )
    
    # Print results
    print(f"\n🎯 Result:")
    for k, v in result.items():
        print(f"  {k}: {v}")

if __name__ == "__main__":
    main()