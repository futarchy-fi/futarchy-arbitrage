#!/usr/bin/env python3
"""
Fund the FutarchyArbExecutorV5 contract with sDAI (owner wallet sends ERC20 transfer).

Usage
  python -m src.arbitrage_commands.fund_executor \
    --env .env.pnk \
    --amount 0.05 \
    [--address 0xExecutor] \
    [--gas 150000]

Behavior
  - Strict: requires FUTARCHY_ARB_EXECUTOR_V5 in env unless --address provided.
  - Sends sDAI (from SDAI_TOKEN_ADDRESS) from your wallet to the executor address.
  - Amount is in ether units (18 decimals).
"""

from __future__ import annotations

import argparse
import os
from decimal import Decimal
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from web3 import Web3
from eth_account import Account


SDAI_DEFAULT = "0xaf204776c7245bF4147c2612BF6e5972Ee483701"  # Gnosis sDAI

_ERC20_MIN_ABI = [
    {
        "constant": False,
        "inputs": [
            {"name": "to", "type": "address"},
            {"name": "amount", "type": "uint256"}
        ],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [{"name": "owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]


def load_env(env_file: Optional[str]) -> None:
    base_env = Path(".env")
    if base_env.exists():
        load_dotenv(base_env)
    if env_file:
        load_dotenv(env_file, override=True)


def require_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise SystemExit(f"Missing env var: {name}")
    return v


def _eip1559_fees(w3: Web3) -> dict:
    try:
        base_fee = w3.eth.get_block("latest").get("baseFeePerGas")
    except Exception:
        base_fee = None
    if base_fee is not None:
        tip = int(os.getenv("PRIORITY_FEE_WEI", "1"))
        mult = int(os.getenv("MAX_FEE_MULTIPLIER", "2"))
        max_fee = int(base_fee) * mult + tip
        return {"maxFeePerGas": int(max_fee), "maxPriorityFeePerGas": int(tip)}
    else:
        bump = int(os.getenv("MIN_GAS_PRICE_BUMP_WEI", "1"))
        return {"gasPrice": int(w3.eth.gas_price) + bump}


def parse_amount_eth_to_wei(amount_str: str) -> int:
    d = Decimal(str(amount_str))
    if d <= 0:
        raise SystemExit("--amount must be positive")
    return int((d * Decimal(10 ** 18)).to_integral_value(rounding=None))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fund the V5 executor with sDAI (ERC20 transfer)")
    p.add_argument("--env", dest="env_file", default=None, help="Path to .env file to load")
    p.add_argument("--address", dest="address", default=None, help="Executor address (overrides env)")
    p.add_argument("--amount", dest="amount", required=True, help="sDAI amount in ether units (e.g., 0.05)")
    p.add_argument("--gas", dest="gas", type=int, default=None, help="Optional gas limit override")
    return p.parse_args()


def main():
    args = parse_args()
    load_env(args.env_file)

    rpc_url = os.getenv("RPC_URL") or os.getenv("GNOSIS_RPC_URL") or require_env("RPC_URL")
    private_key = require_env("PRIVATE_KEY")
    w3 = Web3(Web3.HTTPProvider(rpc_url))
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
        raise SystemExit("Failed to connect to RPC_URL")

    acct = Account.from_key(private_key)
    exec_addr = args.address or os.getenv("FUTARCHY_ARB_EXECUTOR_V5")
    if not exec_addr:
        raise SystemExit("FUTARCHY_ARB_EXECUTOR_V5 is required and not set (no fallbacks).")
    exec_addr = w3.to_checksum_address(exec_addr)

    sdai_addr = os.getenv("SDAI_TOKEN_ADDRESS", SDAI_DEFAULT)
    sdai_addr = w3.to_checksum_address(sdai_addr)
    sdai = w3.eth.contract(address=sdai_addr, abi=_ERC20_MIN_ABI)

    amount_wei = parse_amount_eth_to_wei(args.amount)
    print(f"Funding executor {exec_addr} with {w3.from_wei(amount_wei, 'ether')} sDAI")

    # Check wallet balance
    wallet_bal = sdai.functions.balanceOf(acct.address).call()
    print(f"Wallet sDAI balance: {w3.from_wei(wallet_bal, 'ether')} sDAI")
    if wallet_bal < amount_wei:
        raise SystemExit("Insufficient sDAI balance in wallet to fund executor")

    tx = sdai.functions.transfer(exec_addr, amount_wei).build_transaction({
        "from": acct.address,
        "nonce": w3.eth.get_transaction_count(acct.address),
        "chainId": w3.eth.chain_id,
    })
    tx.update(_eip1559_fees(w3))
    if args.gas:
        tx["gas"] = int(args.gas)
    else:
        try:
            tx["gas"] = int(w3.eth.estimate_gas(tx) * 1.2)
        except Exception:
            tx["gas"] = 120_000

    signed = acct.sign_transaction(tx)
    raw = getattr(signed, "rawTransaction", None) or getattr(signed, "raw_transaction", None)
    h = w3.eth.send_raw_transaction(raw)
    hx = h.hex()
    if not hx.startswith("0x"):
        hx = "0x" + hx
    print(f"Tx sent: {hx}")
    print(f"GnosisScan:  https://gnosisscan.io/tx/{hx}")
    r = w3.eth.wait_for_transaction_receipt(h)
    print(f"Success: {r.status == 1}; Gas used: {r.gasUsed}")


if __name__ == "__main__":
    main()

