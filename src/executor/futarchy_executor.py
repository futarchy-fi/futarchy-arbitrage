#!/usr/bin/env python3
"""
Futarchy V5 Executor

Purpose
 - Make a simple successful on-chain call to FutarchyArbExecutorV5 using
   the provided environment (.env.0x959...) and the deployer's key.
 - By default, sends an empty calldata transaction to the contract, which
   hits the payable `receive()` and succeeds (no complex params required).

Usage
  source .env.0x9590dAF4d5cd4009c3F9767C5E7668175cFd37CF
  python -m src.executor.futarchy_executor \
    [--env .env.0x9590dAF4d5cd4009c3F9767C5E7668175cFd37CF] \
    [--address 0x...V5...] \
    [--send-wei 0]

Address resolution order
  1) --address CLI flag
  2) FUTARCHY_ARB_EXECUTOR_V5 or EXECUTOR_V5_ADDRESS env var
  3) Latest deployments/deployment_executor_v5_*.json

Requires
  - PRIVATE_KEY and RPC_URL in the sourced env file.
  - python-dotenv and web3 installed (see requirements.txt).
"""

from __future__ import annotations

import argparse
import glob
import json
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from web3 import Web3
from eth_account import Account


DEPLOYMENTS_GLOB = "deployments/deployment_executor_v5_*.json"


def load_env(env_file: Optional[str]) -> None:
    # Load base .env first if present (some repo env files source it)
    base_env = Path(".env")
    if base_env.exists():
        load_dotenv(base_env)
    if env_file:
        load_dotenv(env_file)


def discover_v5_address() -> Optional[str]:
    # 1) Check env vars
    addr = os.getenv("FUTARCHY_ARB_EXECUTOR_V5") or os.getenv("EXECUTOR_V5_ADDRESS")
    if addr:
        return addr
    # 2) Check latest deployments file
    files = sorted(glob.glob(DEPLOYMENTS_GLOB))
    if not files:
        return None
    latest = files[-1]
    try:
        with open(latest, "r") as f:
            data = json.load(f)
        return data.get("address")
    except Exception:
        return None


def require_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise SystemExit(f"Missing env var: {name}")
    return v


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Call Futarchy V5 contract")
    p.add_argument("--env", dest="env_file", default=None, help="Path to .env file to load")
    p.add_argument("--address", dest="address", default=None, help="Futarchy V5 contract address")
    p.add_argument("--send-wei", dest="send_wei", default="0", help="Wei to send to receive() (default 0)")
    return p.parse_args()


def main():
    args = parse_args()
    load_env(args.env_file)

    rpc_url = require_env("RPC_URL")
    private_key = require_env("PRIVATE_KEY")

    address = args.address or discover_v5_address()
    if not address:
        raise SystemExit(
            "Could not determine V5 address. Pass --address, set FUTARCHY_ARB_EXECUTOR_V5/EXECUTOR_V5_ADDRESS, or keep a deployments file."
        )

    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        raise SystemExit("Failed to connect to RPC_URL")

    acct = Account.from_key(private_key)
    chain_id = w3.eth.chain_id
    nonce = w3.eth.get_transaction_count(acct.address)

    value_wei = int(args.send_wei)

    # Simple successful call: send an empty-data tx to contract's payable receive()
    tx = {
        "from": acct.address,
        "to": Web3.to_checksum_address(address),
        "value": value_wei,
        "nonce": nonce,
        "gasPrice": w3.eth.gas_price,
        "chainId": chain_id,
    }
    # Add a conservative gas limit if estimation fails
    try:
        tx["gas"] = w3.eth.estimate_gas(tx)
    except Exception:
        tx["gas"] = 60_000

    signed = acct.sign_transaction(tx)
    raw = getattr(signed, "rawTransaction", None) or getattr(signed, "raw_transaction", None)
    tx_hash = w3.eth.send_raw_transaction(raw)
    txh = tx_hash.hex()
    txh0x = txh if txh.startswith("0x") else f"0x{txh}"
    print(f"Tx sent: {txh0x}")
    print(f"GnosisScan:  https://gnosisscan.io/tx/{txh0x}")
    print(f"Blockscout: https://gnosis.blockscout.com/tx/{txh0x}")

    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    ok = receipt.status == 1
    print(f"Success: {ok}; Gas used: {receipt.gasUsed}")


if __name__ == "__main__":
    main()
