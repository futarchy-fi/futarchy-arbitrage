#!/usr/bin/env python3
"""
Prediction Arbitrage Executor (off-chain logic; on-chain execution via PredictionArbExecutorV1)

Logic:
  - Read prices from two Swapr pools: YES_currency<->currency and NO_currency<->currency
  - Orient both prices so they are in {currency} per 1 {conditional_currency}
  - If yes_price + no_price > 1 → SELL: split 'amount' currency into YES/NO and sell both legs exact-in
  - If yes_price + no_price < 1 → BUY: buy both legs exact-out 'amount' each, then merge back into 'amount' currency

Usage:
  python -m src.executor.prediction_arb_executor \
    --env .env.0x9590dAF4d5cd4009c3F9767C5E7668175cFd37CF \
    --amount 0.05 \
    --min-profit -0.001 \
    --force-flow buy \
    --prefund
"""

from __future__ import annotations

import argparse
import glob
import json
import os
from decimal import Decimal
from pathlib import Path
from typing import Optional, Tuple

from dotenv import load_dotenv
from web3 import Web3
from eth_account import Account

from src.helpers.swapr_price import get_pool_price as swapr_price


DEPLOYMENTS_GLOB = "deployments/deployment_prediction_arb_v1_*.json"


def load_env(env_file: Optional[str]) -> None:
    base_env = Path(".env")
    if base_env.exists():
        load_dotenv(base_env)
    if env_file:
        load_dotenv(env_file)


def discover_v1_address() -> Tuple[Optional[str], str]:
    # Prefer env first
    for key in ["PREDICTION_ARB_EXECUTOR_V1", "PREDICTION_EXECUTOR_V1_ADDRESS"]:
        v = os.getenv(key)
        if v:
            return v, f"env ({key})"
    # Fallback to latest deployments JSON
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
    return None, "unresolved"


def require_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise SystemExit(f"Missing env var: {name}")
    return v


def _ether_str_to_signed_wei(value_str: str) -> int:
    d = Decimal(str(value_str))
    sign = -1 if d < 0 else 1
    scaled = int((abs(d) * Decimal(10 ** 18)).to_integral_value(rounding=None))
    return sign * scaled


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
        gas_price = int(w3.eth.gas_price)
        bump = int(os.getenv("MIN_GAS_PRICE_BUMP_WEI", "1"))
        return {"gasPrice": gas_price + bump}


def _load_v1_abi() -> list:
    files = sorted(glob.glob(DEPLOYMENTS_GLOB))
    if files:
        latest = files[-1]
        try:
            with open(latest, "r") as f:
                data = json.load(f)
            abi = data.get("abi")
            if abi:
                print(f"Loaded V1 ABI from deployments ({latest})")
                return abi
        except Exception:
            pass
    build_abi = Path("build/PredictionArbExecutorV1.abi")
    if build_abi.exists():
        try:
            return json.loads(build_abi.read_text())
        except Exception:
            pass
    raise SystemExit("Could not load V1 ABI from deployments/ or build/. Please deploy V1 first.")


def _oriented_price(w3: Web3, pool_addr: str, want_base: str, want_quote: str) -> Decimal:
    """
    Normalize pool price so the result is in {want_quote} units per 1 {want_base}.
    Uses get_pool_price() then orients by matching token addresses.
    """
    px, base, quote = swapr_price(w3, pool_addr)
    base = w3.to_checksum_address(base)
    quote = w3.to_checksum_address(quote)
    want_base = w3.to_checksum_address(want_base)
    want_quote = w3.to_checksum_address(want_quote)
    if base == want_base and quote == want_quote:
        return px
    if base == want_quote and quote == want_base:
        return Decimal(1) / px
    raise SystemExit(
        f"Pool {pool_addr} tokens ({base}->{quote}) do not match expected pair {want_base}<->{want_quote}"
    )


def main():
    p = argparse.ArgumentParser(description="Prediction arbitrage (off-chain logic → on-chain V1 executor)")
    p.add_argument("--env", dest="env_file", default=None, help="Path to .env file")
    p.add_argument("--amount", required=True, help="Amount of {currency} (ether units) for the arb logic")
    p.add_argument("--min-profit", dest="min_profit", default="0", help="Min profit in ether units (signed; can be negative)")
    p.add_argument("--prefund", action="store_true", help="Transfer {currency} to the executor contract if needed")
    # Force decision (override price-based branching)
    p.add_argument(
        "--force-flow",
        dest="force_flow",
        choices=["buy", "sell"],
        default=None,
        help="Force a specific flow regardless of prices (buy or sell)",
    )
    # Advanced controls (hidden): allow bypassing gas estimation and force a gas limit
    p.add_argument("--force-send", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--gas", dest="gas", type=int, default=1_500_000, help=argparse.SUPPRESS)
    args = p.parse_args()

    load_env(args.env_file)
    rpc_url = require_env("RPC_URL")
    private_key = require_env("PRIVATE_KEY")

    # Token & router addresses from env
    currency     = require_env("SDAI_TOKEN_ADDRESS")
    yes_currency = require_env("SWAPR_SDAI_YES_ADDRESS")
    no_currency  = require_env("SWAPR_SDAI_NO_ADDRESS")

    # Pools for conditional-currency <-> currency
    yes_pool = require_env("SWAPR_POOL_PRED_YES_ADDRESS")
    no_pool  = require_env("SWAPR_POOL_PRED_NO_ADDRESS")

    # Futarchy split/merge
    fut_router = require_env("FUTARCHY_ROUTER_ADDRESS")
    proposal   = require_env("FUTARCHY_PROPOSAL_ADDRESS")

    # Swapr router
    swapr_router = require_env("SWAPR_ROUTER_ADDRESS")

    # Resolve V1 executor address
    v1_addr, src = discover_v1_address()
    if not v1_addr:
        raise SystemExit("Could not determine V1 executor address (set PREDICTION_ARB_EXECUTOR_V1 or keep a deployments file).")
    print(f"Resolved V1 address: {v1_addr} (source: {src})")

    # Web3 + middleware (POA safe)
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

    # Load ABI / contract
    abi = _load_v1_abi()
    v1  = w3.eth.contract(address=w3.to_checksum_address(v1_addr), abi=abi)

    # Amounts
    amount_eth = Decimal(str(args.amount))
    amount_wei = w3.to_wei(amount_eth, "ether")
    min_profit_wei = _ether_str_to_signed_wei(args.min_profit)

    # Off-chain price read (skip if forcing flow)
    px_sum = None
    if not args.force_flow:
        yes_px = _oriented_price(w3, yes_pool, yes_currency, currency)   # {currency} per 1 YES_{currency}
        no_px  = _oriented_price(w3, no_pool,  no_currency,  currency)   # {currency} per 1  NO_{currency}
        px_sum = Decimal(str(yes_px)) + Decimal(str(no_px))
        print(f"yes_price: {yes_px:.8f}, no_price: {no_px:.8f}, sum: {px_sum:.8f}")
    else:
        print(f"Forcing flow: {args.force_flow.upper()} (skipping price reads)")

    # Prefund the executor with {currency} if requested or required
    erc20_min_abi = [
        {"constant": True, "inputs":[{"name":"owner","type":"address"}], "name":"balanceOf",
         "outputs":[{"name":"","type":"uint256"}], "stateMutability":"view","type":"function"},
        {"constant": False,"inputs":[{"name":"to","type":"address"},{"name":"amount","type":"uint256"}],
         "name":"transfer","outputs":[{"name":"","type":"bool"}],"stateMutability":"nonpayable","type":"function"},
    ]
    cur = w3.eth.contract(address=w3.to_checksum_address(currency), abi=erc20_min_abi)
    exec_bal = cur.functions.balanceOf(w3.to_checksum_address(v1_addr)).call()

    # We want the executor to have at least `amount_wei` of {currency} for either flow.
    if exec_bal < amount_wei:
        missing = amount_wei - exec_bal
        if not args.prefund:
            raise SystemExit(
                f"Executor balance {w3.from_wei(exec_bal, 'ether')} < needed {amount_eth}. "
                f"Re-run with --prefund to transfer {w3.from_wei(missing, 'ether')} to the executor."
            )
        prefund_params = {
            "from": acct.address,
            "nonce": w3.eth.get_transaction_count(acct.address),
            "chainId": w3.eth.chain_id,
            **_eip1559_fees(w3),
        }
        # Avoid web3 default gas estimation on build by setting a fixed gas when forcing send
        if args.force_send:
            prefund_params["gas"] = min(int(args.gas), 300_000)  # ERC20 transfer fits comfortably
        tx = cur.functions.transfer(w3.to_checksum_address(v1_addr), missing).build_transaction(prefund_params)
        if "gas" not in tx:
            try:
                tx["gas"] = int(w3.eth.estimate_gas(tx) * 1.2)
            except Exception:
                tx["gas"] = 150_000
        signed = acct.sign_transaction(tx)
        raw = getattr(signed, "rawTransaction", None) or getattr(signed, "raw_transaction", None)
        h = w3.eth.send_raw_transaction(raw)
        print(f"Prefund tx: {h.hex()}")
        rcpt = w3.eth.wait_for_transaction_receipt(h)
        if rcpt.status != 1:
            raise SystemExit("Prefund transfer failed (token transfer reverted). Ensure your wallet holds sufficient currency.")
        # Re-read balance and enforce presence before proceeding
        exec_bal = cur.functions.balanceOf(w3.to_checksum_address(v1_addr)).call()
        if exec_bal < amount_wei:
            raise SystemExit(
                f"Executor still underfunded after prefund: {w3.from_wei(exec_bal, 'ether')} < {amount_eth}. "
                "Aborting to avoid router transferFrom() revert."
            )

    # Common tx params
    params = {
        "from": acct.address,
        "nonce": w3.eth.get_transaction_count(acct.address),
        "chainId": w3.eth.chain_id,
        **_eip1559_fees(w3),
    }
    if args.force_send:
        params["gas"] = int(args.gas)

    # Choose flow and build the transaction
    if args.force_flow == "sell":
        print("Decision: FORCE SELL → split & sell conditionals exact-in")
        tx = v1.functions.sell_conditional_arbitrage(
            w3.to_checksum_address(fut_router),
            w3.to_checksum_address(proposal),
            w3.to_checksum_address(currency),
            w3.to_checksum_address(yes_currency),
            w3.to_checksum_address(no_currency),
            w3.to_checksum_address(swapr_router),
            int(amount_wei),
            int(min_profit_wei),
        ).build_transaction(params)
    elif args.force_flow == "buy":
        print("Decision: FORCE BUY → buy both conditionals exact-out & merge")
        tx = v1.functions.buy_conditional_arbitrage(
            w3.to_checksum_address(fut_router),
            w3.to_checksum_address(proposal),
            w3.to_checksum_address(currency),
            w3.to_checksum_address(yes_currency),
            w3.to_checksum_address(no_currency),
            w3.to_checksum_address(yes_pool),
            w3.to_checksum_address(no_pool),
            w3.to_checksum_address(swapr_router),
            int(amount_wei),
            int(min_profit_wei),
        ).build_transaction(params)
    elif px_sum is not None and px_sum > Decimal("1"):
        # SELL: split amount, then sell both legs exact-in
        print("Decision: SELL (sum > 1) → split & sell conditionals exact-in")
        tx = v1.functions.sell_conditional_arbitrage(
            w3.to_checksum_address(fut_router),
            w3.to_checksum_address(proposal),
            w3.to_checksum_address(currency),
            w3.to_checksum_address(yes_currency),
            w3.to_checksum_address(no_currency),
            w3.to_checksum_address(swapr_router),
            int(amount_wei),
            int(min_profit_wei),
        ).build_transaction(params)
    elif px_sum is not None and px_sum < Decimal("1"):
        # BUY: buy both legs exact-out amount, then merge
        print("Decision: BUY (sum < 1) → buy both conditionals exact-out & merge")
        tx = v1.functions.buy_conditional_arbitrage(
            w3.to_checksum_address(fut_router),
            w3.to_checksum_address(proposal),
            w3.to_checksum_address(currency),
            w3.to_checksum_address(yes_currency),
            w3.to_checksum_address(no_currency),
            w3.to_checksum_address(yes_pool),
            w3.to_checksum_address(no_pool),
            w3.to_checksum_address(swapr_router),
            int(amount_wei),
            int(min_profit_wei),
        ).build_transaction(params)
    else:
        print("No-op: yes_price + no_price == 1 (within precision) or no decision available")
        return

    # Gas limit
    if "gas" not in tx:
        try:
            tx["gas"] = int(w3.eth.estimate_gas(tx) * 1.2)
        except Exception:
            tx["gas"] = 1_500_000

    # Send
    signed = acct.sign_transaction(tx)
    raw = getattr(signed, "rawTransaction", None) or getattr(signed, "raw_transaction", None)
    txh = w3.eth.send_raw_transaction(raw).hex()
    if not txh.startswith("0x"):
        txh = "0x" + txh
    print(f"Tx sent: {txh}")
    print(f"GnosisScan:  https://gnosisscan.io/tx/{txh}")
    print(f"Blockscout:  https://gnosis.blockscout.com/tx/{txh}")
    rcpt = w3.eth.wait_for_transaction_receipt(txh)
    print(f"Success: {rcpt.status == 1}; Gas used: {rcpt.gasUsed}")


if __name__ == "__main__":
    main()
