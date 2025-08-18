#!/usr/bin/env python3
"""
Pull all sDAI from the deployed FutarchyArbExecutorV5 contract (owner only).

Usage
  python -m src.arbitrage_commands.pull_sdai \
    --env .env.pnk \
    [--address 0xExecutor] \
    [--to 0xYourWallet]

Behavior
  - Resolves the V5 executor address from --address, deployments/, or env.
  - Reads executor’s sDAI balance and calls sweepToken(sDAI, to).
  - Requires PRIVATE_KEY of the contract owner.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
from pathlib import Path
from typing import Optional, Tuple

from dotenv import load_dotenv
from web3 import Web3
from eth_account import Account


ZERO_ADDR = Web3.to_checksum_address("0x0000000000000000000000000000000000000000")
SDAI_DEFAULT = "0xaf204776c7245bF4147c2612BF6e5972Ee483701"  # Gnosis sDAI
DEPLOYMENTS_GLOB = "deployments/deployment_executor_v5_*.json"


_EXECUTOR_MIN_ABI = [
    {"inputs": [], "name": "owner", "outputs": [{"internalType": "address", "name": "", "type": "address"}], "stateMutability": "view", "type": "function"},
    {"inputs": [
        {"internalType": "contract IERC20", "name": "token", "type": "address"},
        {"internalType": "address", "name": "to", "type": "address"},
        {"internalType": "uint256", "name": "amount", "type": "uint256"}
     ], "name": "withdrawToken", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [
        {"internalType": "contract IERC20", "name": "token", "type": "address"},
        {"internalType": "address", "name": "to", "type": "address"}
     ], "name": "sweepToken", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
]

_ERC20_MIN_ABI = [
    {"constant": True, "inputs": [{"name": "owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
]


def load_env(env_file: Optional[str]) -> None:
    base_env = Path(".env")
    if base_env.exists():
        load_dotenv(base_env)
    if env_file:
        load_dotenv(env_file, override=True)


def discover_v5_address() -> Tuple[Optional[str], str]:
    files = sorted(glob.glob(DEPLOYMENTS_GLOB))
    if files:
        latest = files[-1]
        try:
            with open(latest, "r") as f:
                data = json.load(f)
            addr = data.get("address")
            if addr:
                return addr, f"deployments ({latest})"
        except Exception:
            pass
    for k in ("FUTARCHY_ARB_EXECUTOR_V5", "EXECUTOR_V5_ADDRESS"):
        v = os.getenv(k)
        if v:
            return v, f"env ({k})"
    return None, "unresolved"


def require_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise SystemExit(f"Missing env var: {name}")
    return v


def _eip1559_fees(w3: Web3) -> dict:
    try:
        latest = w3.eth.get_block("latest")
        base_fee = latest.get("baseFeePerGas")
    except Exception:
        base_fee = None
    if base_fee is not None:
        tip = int(os.getenv("PRIORITY_FEE_WEI", "1"))
        mult = int(os.getenv("MAX_FEE_MULTIPLIER", "2"))
        max_fee = int(base_fee) * mult + tip
        return {"maxFeePerGas": int(max_fee), "maxPriorityFeePerGas": int(tip)}
    else:
        gas_price = int(w3.eth.gas_price)
        bump = int(os.getenv("MIN_GAS_PRICE_BUMP_WEI", "1"))
        return {"gasPrice": gas_price + bump}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Sweep all sDAI from FutarchyArbExecutorV5 (owner only)")
    p.add_argument("--env", dest="env_file", default=None, help="Path to .env file to load")
    p.add_argument("--address", dest="address", default=None, help="Executor V5 address (optional)")
    p.add_argument("--to", dest="to", default=None, help="Recipient address (default: your wallet)")
    p.add_argument("--gas", dest="gas", type=int, default=None, help="Optional gas limit override")
    return p.parse_args()


def main():
    args = parse_args()
    load_env(args.env_file)

    rpc_url = os.getenv("RPC_URL") or os.getenv("GNOSIS_RPC_URL") or require_env("RPC_URL")
    private_key = require_env("PRIVATE_KEY")
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    # POA middleware for Gnosis compatibility
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
    to_addr = args.to or acct.address

    if args.address:
        exec_addr, src = args.address, "cli --address"
    else:
        exec_addr, src = discover_v5_address()
        if not exec_addr:
            raise SystemExit("Could not determine V5 address. Pass --address or set FUTARCHY_ARB_EXECUTOR_V5/EXECUTOR_V5_ADDRESS.")

    exec_addr = w3.to_checksum_address(exec_addr)
    print(f"Executor V5: {exec_addr} (source: {src})")
    print(f"Recipient:  {to_addr}")

    # Contracts
    sdai_addr = w3.to_checksum_address(os.getenv("SDAI_TOKEN_ADDRESS", SDAI_DEFAULT))
    sdai = w3.eth.contract(address=sdai_addr, abi=_ERC20_MIN_ABI)
    v5 = w3.eth.contract(address=exec_addr, abi=_EXECUTOR_MIN_ABI)

    # Ownership check
    try:
        owner_addr = v5.functions.owner().call()
    except Exception:
        owner_addr = None
    if owner_addr and owner_addr.lower() != acct.address.lower():
        print(f"⚠️  Warning: Your wallet is not the owner (owner={owner_addr}). This call will revert.")

    # Read balance
    bal = sdai.functions.balanceOf(exec_addr).call()
    print(f"Executor sDAI balance: {w3.from_wei(bal, 'ether')} sDAI")
    if bal == 0:
        print("Nothing to sweep.")
        return

    # Build and send sweep
    tx = v5.functions.sweepToken(sdai_addr, w3.to_checksum_address(to_addr)).build_transaction({
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
            tx["gas"] = 250_000

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

