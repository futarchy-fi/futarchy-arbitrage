#!/usr/bin/env python3
"""
Test script for the 7702 executor module.

Usage:
    # Test building 7702 bundles (no execution)
    python -m src.executor.test_executor --mode bundle --direction sell --amount 0.001

    # Test direct router execution
    python -m src.executor.test_executor --mode direct --direction buy --amount 0.1 --execute

    # Test runTrade execution (requires sender == runner)
    python -m src.executor.test_executor --mode contract --direction sell --amount 0.001 --execute
"""

import os
import sys
import argparse
import logging
from decimal import Decimal
from typing import Optional

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

from src.executor.tx_7702_executor import Tx7702Executor


def setup_logging(verbose: bool = False):
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )


def get_web3() -> Web3:
    """Initialize Web3 connection."""
    rpc_url = os.getenv("RPC_URL") or os.getenv("GNOSIS_RPC_URL")
    if not rpc_url:
        raise EnvironmentError("Set RPC_URL or GNOSIS_RPC_URL environment variable")
    
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    
    if not w3.is_connected():
        raise ConnectionError("Could not connect to RPC endpoint")
    
    return w3


def main():
    parser = argparse.ArgumentParser(description="Test 7702 executor for Balancer swaps")
    
    # Execution mode
    parser.add_argument(
        "--mode",
        choices=["bundle", "direct", "contract"],
        default="bundle",
        help="Execution mode: bundle (7702), direct (router), contract (runTrade)"
    )
    
    # Trade direction
    parser.add_argument(
        "--direction",
        choices=["sell", "buy"],
        default="sell",
        help="Trade direction: sell (Company→sDAI) or buy (sDAI→Company)"
    )
    
    # Trade parameters
    parser.add_argument(
        "--amount",
        type=float,
        default=0.001,
        help="Amount to trade (in ether units)"
    )
    
    parser.add_argument(
        "--min-out",
        type=float,
        default=0.0001,
        help="Minimum output amount (in ether units)"
    )
    
    # Execution flags
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually execute the transaction (requires PRIVATE_KEY)"
    )
    
    parser.add_argument(
        "--gas",
        type=int,
        help="Gas limit override"
    )
    
    parser.add_argument(
        "--gas-price",
        type=float,
        help="Gas price in gwei"
    )
    
    # Other options
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    
    parser.add_argument(
        "--runner-check",
        action="store_true",
        default=True,
        help="Check runner permission for contract mode (default: True)"
    )
    
    args = parser.parse_args()
    
    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)
    
    # Initialize Web3 and executor
    w3 = get_web3()
    executor = Tx7702Executor(w3)
    
    # Get wallet address
    sender = os.getenv("WALLET_ADDRESS") or os.getenv("SENDER_ADDRESS")
    if not sender:
        raise EnvironmentError("Set WALLET_ADDRESS or SENDER_ADDRESS environment variable")
    
    # Convert amounts to wei
    amount_wei = w3.to_wei(Decimal(str(args.amount)), "ether")
    min_out_wei = w3.to_wei(Decimal(str(args.min_out)), "ether")
    
    # Convert gas price if provided
    gas_price_wei = None
    if args.gas_price:
        gas_price_wei = w3.to_wei(Decimal(str(args.gas_price)), "gwei")
    
    logger.info(f"Mode: {args.mode}")
    logger.info(f"Direction: {args.direction} Company token")
    logger.info(f"Amount: {args.amount} ({amount_wei} wei)")
    logger.info(f"Min output: {args.min_out} ({min_out_wei} wei)")
    logger.info(f"Sender: {sender}")
    
    # Check runner if in contract mode
    if args.mode == "contract" and args.runner_check:
        runner = executor.fetch_runner()
        if runner:
            logger.info(f"Contract runner: {runner}")
            if w3.to_checksum_address(sender) != w3.to_checksum_address(runner):
                logger.warning(f"⚠️  Sender {sender} != Runner {runner}")
                if args.execute:
                    logger.error("Cannot execute: sender is not the runner")
                    return
    
    # Handle different modes
    if args.mode == "bundle":
        # Build 7702 bundle
        if args.direction == "sell":
            bundle = executor.build_7702_bundle_sell(amount_wei, min_out_wei)
        else:
            bundle = executor.build_7702_bundle_buy(amount_wei, min_out_wei)
        
        logger.info("📦 7702 Bundle built:")
        for i, call in enumerate(bundle):
            call_dict = call.as_dict()
            logger.info(f"  Call {i}:")
            logger.info(f"    To: {call_dict['to']}")
            logger.info(f"    Data: {call_dict['data'][:66]}...")
            logger.info(f"    Value: {call_dict['value']}")
        
        if args.execute:
            logger.warning("⚠️  Bundle execution requires external 7702 bundler")
            logger.info("Pass the bundle to your 7702 infrastructure")
    
    elif args.mode == "direct":
        # Direct router execution
        if not args.execute:
            logger.info("🔍 Preview mode - add --execute to send transaction")
            return
        
        private_key = os.getenv("PRIVATE_KEY")
        if not private_key:
            raise EnvironmentError("Set PRIVATE_KEY to execute transactions")
        
        try:
            if args.direction == "sell":
                tx_hash = executor.send_direct_router_sell(
                    sender=sender,
                    private_key=private_key,
                    amount_in_wei=amount_wei,
                    min_amount_out_wei=min_out_wei,
                    gas=args.gas,
                    gas_price_wei=gas_price_wei,
                )
            else:
                tx_hash = executor.send_direct_router_buy(
                    sender=sender,
                    private_key=private_key,
                    amount_in_wei=amount_wei,
                    min_amount_out_wei=min_out_wei,
                    gas=args.gas,
                    gas_price_wei=gas_price_wei,
                )
            
            logger.info(f"✅ Transaction sent: {tx_hash}")
            logger.info(f"🔗 https://gnosisscan.io/tx/{tx_hash}")
            
            # Wait for receipt
            logger.info("⏳ Waiting for confirmation...")
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            
            if receipt.status == 1:
                logger.info(f"✅ Transaction successful!")
                logger.info(f"   Gas used: {receipt.gasUsed}")
            else:
                logger.error(f"❌ Transaction reverted!")
                
        except Exception as e:
            logger.error(f"❌ Error: {e}")
    
    elif args.mode == "contract":
        # Contract runTrade execution
        if not args.execute:
            logger.info("🔍 Preview mode - add --execute to send transaction")
            return
        
        private_key = os.getenv("PRIVATE_KEY")
        if not private_key:
            raise EnvironmentError("Set PRIVATE_KEY to execute transactions")
        
        try:
            if args.direction == "sell":
                tx_hash = executor.send_run_trade_sell(
                    sender=sender,
                    private_key=private_key,
                    amount_in_wei=amount_wei,
                    min_amount_out_wei=min_out_wei,
                    must_be_runner=args.runner_check,
                    gas=args.gas,
                    gas_price_wei=gas_price_wei,
                )
            else:
                tx_hash = executor.send_run_trade_buy(
                    sender=sender,
                    private_key=private_key,
                    amount_in_wei=amount_wei,
                    min_amount_out_wei=min_out_wei,
                    must_be_runner=args.runner_check,
                    gas=args.gas,
                    gas_price_wei=gas_price_wei,
                )
            
            logger.info(f"✅ Transaction sent: {tx_hash}")
            logger.info(f"🔗 https://gnosisscan.io/tx/{tx_hash}")
            
            # Wait for receipt
            logger.info("⏳ Waiting for confirmation...")
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            
            if receipt.status == 1:
                logger.info(f"✅ Transaction successful!")
                logger.info(f"   Gas used: {receipt.gasUsed}")
                
                # Try to decode TradeExecuted event
                result = executor.decode_trade_executed(receipt)
                if result:
                    amount_in, amount_out = result
                    logger.info(f"   Trade: {w3.from_wei(amount_in, 'ether')} → {w3.from_wei(amount_out, 'ether')}")
            else:
                logger.error(f"❌ Transaction reverted!")
                
        except Exception as e:
            logger.error(f"❌ Error: {e}")


if __name__ == "__main__":
    main()