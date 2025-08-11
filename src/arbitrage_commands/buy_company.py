"""
Orchestration layer for buying Company tokens via Balancer Router.

This module handles:
- Loading executor ABI from deployment artifacts
- Pre-funding the executor with necessary tokens
- Building the Execute10Batch via the trades module
- Calling runTrade on the executor contract
"""

import os
import json
import time
from pathlib import Path
from decimal import Decimal

from web3 import Web3
from eth_account import Account

from src.trades.balancer_vault import (
    VaultConfig,
    quote_aave_gno_out,
    build_execute10_buy_aave_gno,
)

# Minimal ERC20
ERC20_ABI = [
    {"constant": False, "inputs": [{"name": "_to","type": "address"},{"name":"_value","type":"uint256"}],
     "name": "transfer","outputs": [{"name":"","type":"bool"}], "type":"function"},
    {"constant": True, "inputs": [{"name": "owner","type":"address"}],
     "name": "balanceOf","outputs":[{"name":"","type":"uint256"}], "type":"function"},
]

def _load_executor_abi(address: str):
    """Find the deployment JSON with the matching address and return its abi."""
    for p in Path(".").glob("deployment_executor_v4_*.json"):
        with open(p, "r") as f:
            data = json.load(f)
        if data.get("address","").lower() == address.lower():
            return data["abi"]
    raise RuntimeError(f"ABI json not found for executor {address}")

def _maybe_fund_executor(w3: Web3, account, token_addr: str, executor: str, need: int, *, dry_run: bool):
    """Fund executor with tokens if needed."""
    token = w3.eth.contract(address=w3.to_checksum_address(token_addr), abi=ERC20_ABI)
    bal_eoa = token.functions.balanceOf(account.address).call()
    bal_exec = token.functions.balanceOf(executor).call()
    deficit = max(0, need - bal_exec)
    if deficit == 0:
        return None
    if bal_eoa < deficit:
        raise SystemExit(f"Insufficient token balance. Need {w3.from_wei(deficit,'ether')} more.")

    print(f"📤 Funding executor with {w3.from_wei(deficit, 'ether')} tokens...")
    
    tx = token.functions.transfer(executor, deficit).build_transaction({
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address),
        "gasPrice": max(w3.eth.gas_price, w3.to_wei(1, "gwei")),  # gnosis min
        "gas": 100_000,
    })
    if dry_run:
        print(f"[dry-run] Would fund executor with {w3.from_wei(deficit,'ether')} tokens")
        return None
    signed = account.sign_transaction(tx)
    h = w3.eth.send_raw_transaction(signed.raw_transaction)
    rcpt = w3.eth.wait_for_transaction_receipt(h)
    if rcpt.status != 1:
        raise SystemExit("Funding transfer failed")
    print(f"  ✅ Funded: {h.hex()}")
    return h.hex()

def run_balancer_buy(
    *,
    rpc_url: str,
    private_key: str,
    executor_addr: str,
    token_cur: str,
    token_aave_gno: str,  # Aave GNO token
    balancer_vault: str,
    pool_sdai_aave_gno: str,  # The sDAI/Aave GNO pool
    amount_cur_in: Decimal,
    slippage_bps: int = 50,
    dry_run: bool = False,
):
    """Execute a sDAI -> Aave GNO trade via Balancer Vault using FutarchyArbExecutorV4.runTrade."""
    
    print("\n=== Balancer Buy Company (via runTrade) ===\n")
    
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    acct = Account.from_key(private_key)

    # Load ABI
    abi = _load_executor_abi(executor_addr)
    executor = w3.eth.contract(address=w3.to_checksum_address(executor_addr), abi=abi)

    cfg = VaultConfig(
        vault=w3.to_checksum_address(balancer_vault),
        pool_sdai_aave_gno=pool_sdai_aave_gno,
        token_sdai=w3.to_checksum_address(token_cur),
        token_aave_gno=w3.to_checksum_address(token_aave_gno),
        # Router defaults are set in VaultConfig
    )

    amount_in_wei = w3.to_wei(amount_cur_in, "ether")
    
    print(f"📊 Configuration:")
    print(f"  Amount in: {amount_cur_in} sDAI ({amount_in_wei} wei)")
    print(f"  Slippage: {slippage_bps/100:.2f}%")
    
    # Quote the swap
    print(f"\n📈 Getting quote from pool spot price...")
    try:
        quote_out_wei, min_out_wei = quote_aave_gno_out(
            w3, cfg, 
            amount_in=amount_in_wei, 
            slippage_bps=slippage_bps, 
            executor_address=executor.address
        )
    except Exception as e:
        print(f"  ⚠️ Quote failed: {e}")
        print("  Using min_out = 1 wei for debugging")
        min_out_wei = 1

    # Optional: pre-fund the executor with sDAI
    fund_hash = _maybe_fund_executor(w3, acct, token_cur, executor.address, amount_in_wei, dry_run=dry_run)

    # Build the Execute10Batch
    print(f"\n🔧 Building Execute10Batch...")
    batch = build_execute10_buy_aave_gno(
        w3, cfg, amount_in=amount_in_wei, min_out=min_out_wei, executor_address=executor.address
    )

    # Build transaction
    print(f"\n🚀 Preparing runTrade transaction...")
    tx = executor.functions.runTrade(batch).build_transaction({
        "from": acct.address,
        "nonce": w3.eth.get_transaction_count(acct.address),
        "gasPrice": max(w3.eth.gas_price, w3.to_wei(1, "gwei")),
        "gas": 900_000,  # generous; tighten after observing
    })

    print(f"  Gas limit: {tx['gas']}")
    print(f"  Gas price: {w3.from_wei(tx['gasPrice'], 'gwei'):.2f} gwei")

    if dry_run:
        print("\n[dry-run] Built runTrade transaction:")
        print(f"  tokenIn:  {token_cur}")
        print(f"  tokenOut: {token_aave_gno}")
        print(f"  amountIn: {amount_cur_in} ({amount_in_wei} wei)")
        print(f"  minOut:   {min_out_wei} wei")
        return {"status": "dry_run", "tx": tx}

    # Send transaction
    signed = acct.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"\n📡 Transaction sent!")
    print(f"  Tx hash: {tx_hash.hex()}")
    print(f"  https://gnosisscan.io/tx/{tx_hash.hex()}")
    
    print("\n⏳ Waiting for confirmation...")
    rcpt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)

    # Decode TradeExecuted if present (ABI must include it)
    comp_out = None
    if rcpt.status == 1:
        print("✅ Transaction successful!")
        try:
            events = executor.events.TradeExecuted().process_receipt(rcpt)
            if events:
                args = events[0]["args"]
                comp_out = args.get("amountOut")
                print(f"\n📊 TradeExecuted Event:")
                print(f"  tokenIn:   {args.get('tokenIn')}")
                print(f"  tokenOut:  {args.get('tokenOut')}")
                print(f"  amountIn:  {w3.from_wei(args.get('amountIn'), 'ether'):.6f} sDAI")
                print(f"  amountOut: {w3.from_wei(args.get('amountOut'), 'ether'):.6f} Aave GNO")
        except Exception as e:
            print(f"Could not decode event: {e}")
    else:
        print("❌ Transaction reverted!")

    return {
        "status": "success" if rcpt.status == 1 else "reverted",
        "tx_hash": tx_hash.hex(),
        "gas_used": rcpt.gasUsed,
        "comp_out_wei": comp_out,
    }