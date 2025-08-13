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
from typing import Optional, Tuple
from decimal import Decimal

from dotenv import load_dotenv
from web3 import Web3
from eth_account import Account

# Reuse Balancer helpers for encoding swapExactIn calldata (module under src/trades)
from src.trades.balancer_swap import (
    BALANCER_ROUTER_ABI,
    SDAI,
    COMPANY_TOKEN,
    BUFFER_POOL,
    FINAL_POOL,
    MAX_DEADLINE,
)


DEPLOYMENTS_GLOB = "deployments/deployment_executor_v5_*.json"


def load_env(env_file: Optional[str]) -> None:
    # Load base .env first if present (some repo env files source it)
    base_env = Path(".env")
    if base_env.exists():
        load_dotenv(base_env)
    if env_file:
        load_dotenv(env_file)


def discover_v5_address() -> Tuple[Optional[str], str]:
    # Prefer latest deployments file so changes are picked up automatically
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
    # Fallback to env vars
    env_keys = ["FUTARCHY_ARB_EXECUTOR_V5", "EXECUTOR_V5_ADDRESS"]
    for k in env_keys:
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
    """Return a dict of fee fields for EIP-1559 txs with a minimal, consistent tip.

    - On EIP-1559 chains: sets maxPriorityFeePerGas to PRIORITY_FEE_WEI (default 1 wei)
      and maxFeePerGas = baseFee * MAX_FEE_MULTIPLIER + priority.
    - On non-EIP-1559 chains: returns legacy gasPrice bumped by MIN_GAS_PRICE_BUMP_WEI (default 1 wei).
    """
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
    p = argparse.ArgumentParser(description="Call Futarchy V5 contract")
    p.add_argument("--env", dest="env_file", default=None, help="Path to .env file to load")
    p.add_argument("--address", dest="address", default=None, help="Futarchy V5 contract address")
    p.add_argument("--send-wei", dest="send_wei", default="0", help="Wei to send to receive() (default 0)")
    # Step1/2 Balancer buy flow
    p.add_argument("--step12", action="store_true", help="Execute Step 1&2 Balancer buy flow via V5")
    p.add_argument("--amount-in", dest="amount_in", default=None, help="Amount of sDAI to spend (ether units)")
    p.add_argument("--force-send", action="store_true", help="Skip gas estimation and force on-chain send")
    p.add_argument("--gas", dest="gas", type=int, default=1_500_000, help="Gas limit when using --force-send (default 1.5M)")
    p.add_argument("--min-profit", dest="min_profit", default="0", help="Required profit in ether units (default 0)")
    p.add_argument("--min-profit-wei", dest="min_profit_wei", default=None, help="Required profit in wei (overrides --min-profit)")
    p.add_argument("--prefund", action="store_true", help="Transfer --amount-in sDAI from your EOA to the V5 executor before calling")
    # Withdraw helpers (requires owner-enabled V5)
    p.add_argument("--withdraw-token", dest="wd_token", default=None, help="ERC20 token address to withdraw from V5")
    p.add_argument("--withdraw-to", dest="wd_to", default=None, help="Recipient address (defaults to your EOA)")
    p.add_argument("--withdraw-amount", dest="wd_amount", default=None, help="Amount in ether units (assumes 18 decimals)")
    p.add_argument("--withdraw-amount-wei", dest="wd_amount_wei", default=None, help="Amount in wei (overrides --withdraw-amount)")
    return p.parse_args()


def _load_v5_abi() -> list:
    files = sorted(glob.glob(DEPLOYMENTS_GLOB))
    if files:
        latest = files[-1]
        try:
            with open(latest, "r") as f:
                data = json.load(f)
            abi = data.get("abi")
            if abi:
                print(f"Loaded V5 ABI from deployments ({latest})")
                return abi
        except Exception:
            pass
    # Fallback to build artifact
    build_abi = Path("build/FutarchyArbExecutorV5.abi")
    if build_abi.exists():
        try:
            return json.loads(build_abi.read_text())
        except Exception:
            pass
    raise SystemExit("Could not load V5 ABI from deployments/ or build/. Please deploy V5 first.")


def _encode_buy_company_ops(w3: Web3, router_addr: str, amount_in_wei: int) -> str:
    """Encode Balancer BatchRouter.swapExactIn calldata for buying Company with sDAI."""
    router = w3.eth.contract(address=w3.to_checksum_address(router_addr), abi=BALANCER_ROUTER_ABI)
    steps = [
        (FINAL_POOL, BUFFER_POOL, False),  # sDAI -> buffer
        (BUFFER_POOL, COMPANY_TOKEN, True),  # buffer -> Company
    ]
    # No minOut protection by request: set to 0
    path = (SDAI, steps, int(amount_in_wei), 0)
    # web3.py v6: encode function calldata via ContractFunction
    calldata: str = router.get_function_by_name("swapExactIn")(
        [path], int(MAX_DEADLINE), False, b""
    )._encode_transaction_data()  # returns hex str
    return calldata


_ERC20_MIN_ABI = [
    {
        "constant": False,
        "inputs": [{"name": "to", "type": "address"}, {"name": "amount", "type": "uint256"}],
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


def _exec_step12_buy(
    w3: Web3,
    account,
    v5_address: str,
    amount_in_eth: str,
    min_profit_wei: int,
    ) -> str:
    abi = _load_v5_abi()
    v5 = w3.eth.contract(address=w3.to_checksum_address(v5_address), abi=abi)

    amount_in_wei = w3.to_wei(Decimal(str(amount_in_eth)), "ether")
    # Resolve required addresses strictly from env
    balancer_router = require_env("BALANCER_ROUTER_ADDRESS")
    balancer_vault  = os.getenv("BALANCER_VAULT_ADDRESS") or os.getenv("BALANCER_VAULT_V3_ADDRESS")
    fut_router      = require_env("FUTARCHY_ROUTER_ADDRESS")
    proposal        = require_env("FUTARCHY_PROPOSAL_ADDRESS")
    swapr_router    = require_env("SWAPR_ROUTER_ADDRESS")
    yes_comp        = require_env("SWAPR_GNO_YES_ADDRESS")
    no_comp         = require_env("SWAPR_GNO_NO_ADDRESS")
    yes_cur         = require_env("SWAPR_SDAI_YES_ADDRESS")
    no_cur          = require_env("SWAPR_SDAI_NO_ADDRESS")

    buy_ops = _encode_buy_company_ops(w3, balancer_router, amount_in_wei)

    comp = os.getenv("COMPANY_TOKEN_ADDRESS", COMPANY_TOKEN)
    cur = os.getenv("SDAI_TOKEN_ADDRESS", SDAI)
    zero = Web3.to_checksum_address("0x0000000000000000000000000000000000000000")
    vault = balancer_vault or zero

    tx_params = {
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address),
        "chainId": w3.eth.chain_id,
    }
    tx_params.update(_eip1559_fees(w3))

    # Prefund the executor with sDAI if requested or if balance is insufficient
    sdai_addr = os.getenv("SDAI_TOKEN_ADDRESS", SDAI)
    sdai = w3.eth.contract(address=w3.to_checksum_address(sdai_addr), abi=_ERC20_MIN_ABI)
    exec_bal = sdai.functions.balanceOf(w3.to_checksum_address(v5_address)).call()
    if exec_bal < amount_in_wei:
        missing = amount_in_wei - exec_bal
        if not getattr(_exec_step12_buy, "prefund_flag", False):
            raise SystemExit(
                f"Executor sDAI balance {w3.from_wei(exec_bal, 'ether')} < needed {w3.from_wei(amount_in_wei, 'ether')}. "
                f"Re-run with --prefund to transfer {w3.from_wei(missing, 'ether')} sDAI to the executor."
            )
        fund_tx = sdai.functions.transfer(w3.to_checksum_address(v5_address), missing).build_transaction({
            "from": account.address,
            "nonce": tx_params["nonce"],
            "chainId": tx_params["chainId"],
        })
        # ensure consistent EIP-1559 fees
        fund_tx.update(_eip1559_fees(w3))
        try:
            fund_tx["gas"] = int(w3.eth.estimate_gas(fund_tx) * 1.2)
        except Exception:
            fund_tx["gas"] = 150_000
        signed_fund = account.sign_transaction(fund_tx)
        raw_fund = getattr(signed_fund, "rawTransaction", None) or getattr(signed_fund, "raw_transaction", None)
        fund_hash = w3.eth.send_raw_transaction(raw_fund)
        print(f"Prefund tx: {fund_hash.hex()}")
        w3.eth.wait_for_transaction_receipt(fund_hash)
        tx_params["nonce"] += 1

    # If caller wants to force-send, provide a gas limit up front to avoid web3's estimation
    if getattr(_exec_step12_buy, "force_send_flag", False):
        tx_params["gas"] = getattr(_exec_step12_buy, "force_gas_limit", 1_500_000)

    # Always call the extended overload (Steps 1–6); addresses come from env
    tx = v5.functions.sell_conditional_arbitrage_balancer(
        buy_ops,
        Web3.to_checksum_address(balancer_router),
        Web3.to_checksum_address(vault) if isinstance(vault, str) else vault,
        Web3.to_checksum_address(comp),
        Web3.to_checksum_address(cur),
        Web3.to_checksum_address(fut_router),
        Web3.to_checksum_address(proposal),
        Web3.to_checksum_address(yes_comp),
        Web3.to_checksum_address(no_comp),
        Web3.to_checksum_address(yes_cur),
        Web3.to_checksum_address(no_cur),
        Web3.to_checksum_address(swapr_router),
        0,
        int(min_profit_wei),
    ).build_transaction(tx_params)

    # If we didn't force a gas limit earlier, try to estimate now with a buffer; otherwise keep provided gas
    if "gas" not in tx:
        try:
            gas_est = w3.eth.estimate_gas(tx)
            tx["gas"] = int(gas_est * 1.2)
        except Exception:
            tx["gas"] = 1_500_000

    signed = account.sign_transaction(tx)
    raw = getattr(signed, "rawTransaction", None) or getattr(signed, "raw_transaction", None)
    tx_hash = w3.eth.send_raw_transaction(raw)
    txh = tx_hash.hex()
    txh0x = txh if txh.startswith("0x") else f"0x{txh}"
    print(f"Tx sent: {txh0x}")
    print(f"GnosisScan:  https://gnosisscan.io/tx/{txh0x}")
    print(f"Blockscout: https://gnosis.blockscout.com/tx/{txh0x}")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    print(f"Success: {receipt.status == 1}; Gas used: {receipt.gasUsed}")
    return txh0x


def _withdraw_token(
    w3: Web3,
    account,
    v5_address: str,
    token: str,
    to_addr: str,
    amount_wei: int,
) -> str:
    abi = _load_v5_abi()
    v5 = w3.eth.contract(address=w3.to_checksum_address(v5_address), abi=abi)
    tx = v5.functions.withdrawToken(
        Web3.to_checksum_address(token), Web3.to_checksum_address(to_addr), int(amount_wei)
    ).build_transaction({
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address),
        "chainId": w3.eth.chain_id,
    })
    tx.update(_eip1559_fees(w3))
    try:
        tx["gas"] = int(w3.eth.estimate_gas(tx) * 1.2)
    except Exception:
        tx["gas"] = 200_000
    signed = account.sign_transaction(tx)
    raw = getattr(signed, "rawTransaction", None) or getattr(signed, "raw_transaction", None)
    h = w3.eth.send_raw_transaction(raw)
    txh = h.hex()
    txh0x = txh if txh.startswith("0x") else f"0x{txh}"
    print(f"Withdraw tx: {txh0x}")
    print(f"GnosisScan:  https://gnosisscan.io/tx/{txh0x}")
    print(f"Blockscout: https://gnosis.blockscout.com/tx/{txh0x}")
    receipt = w3.eth.wait_for_transaction_receipt(h)
    print(f"Success: {receipt.status == 1}; Gas used: {receipt.gasUsed}")
    return txh0x


def main():
    args = parse_args()
    load_env(args.env_file)
    # No CLI overrides for addresses; all read from env

    rpc_url = require_env("RPC_URL")
    private_key = require_env("PRIVATE_KEY")

    if args.address:
        address = args.address
        source_label = "cli --address"
    else:
        address, source_label = discover_v5_address()
    if not address:
        raise SystemExit(
            "Could not determine V5 address. Pass --address, set FUTARCHY_ARB_EXECUTOR_V5/EXECUTOR_V5_ADDRESS, or keep a deployments file."
        )
    print(f"Resolved V5 address: {address} (source: {source_label})")

    w3 = Web3(Web3.HTTPProvider(rpc_url))
    # POA chains (e.g., Gnosis) may require this middleware; harmless elsewhere.
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
    chain_id = w3.eth.chain_id
    nonce = w3.eth.get_transaction_count(acct.address)

    # If user requested Step 1/2 flow
    if args.step12:
        if not args.amount_in:
            raise SystemExit("--amount-in is required with --step12 (ether units)")
        # compute min_profit_wei from CLI
        if args.min_profit_wei is not None:
            min_profit_wei = int(args.min_profit_wei)
        else:
            # Support negative values; avoid web3.to_wei (unsigned). Assumes 18 decimals.
            min_profit_wei = int(Decimal(str(args.min_profit)) * Decimal(10**18))
        # plumb force-send flags into helper via attributes to avoid changing signature widely
        _exec_step12_buy.force_send_flag = bool(args.force_send)
        _exec_step12_buy.force_gas_limit = int(args.gas)
        _exec_step12_buy.prefund_flag = bool(args.prefund)
        _exec_step12_buy(w3, acct, address, args.amount_in, min_profit_wei)
        return

    # Withdraw flow (requires owner-enabled V5; redeploy if your V5 has no owner)
    if args.wd_token:
        to_addr = args.wd_to or acct.address
        if args.wd_amount_wei is not None:
            amount_wei = int(args.wd_amount_wei)
        elif args.wd_amount is not None:
            # assumes 18 decimals token like sDAI/GNO
            amount_wei = w3.to_wei(Decimal(str(args.wd_amount)), "ether")
        else:
            raise SystemExit("Provide --withdraw-amount or --withdraw-amount-wei")
        _withdraw_token(w3, acct, address, args.wd_token, to_addr, amount_wei)
        return

    # Default: simple receive() call
    value_wei = int(args.send_wei)
    tx = {
        "from": acct.address,
        "to": Web3.to_checksum_address(address),
        "value": value_wei,
        "nonce": nonce,
        "chainId": chain_id,
    }
    tx.update(_eip1559_fees(w3))
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
    print(f"Success: {receipt.status == 1}; Gas used: {receipt.gasUsed}")


if __name__ == "__main__":
    main()
