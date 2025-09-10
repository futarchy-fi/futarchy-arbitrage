#!/usr/bin/env python3
"""
Futarchy Arbitrage Executor

Executes arbitrage trades between Balancer and Swapr pools via FutarchyArbExecutorV5 contract.

Usage:
  # SELL flow (Balancer buy → split → sell conditionals)
  python -m src.executor.arbitrage_executor \
    --env .env.0x9590dAF4d5cd4009c3F9767C5E7668175cFd37CF \
    --flow sell \
    --amount 0.01 \
    --cheaper yes \
    --min-profit -0.01 \
    --prefund \
    --execute              # add to actually broadcast

  # BUY flow (split sDAI → buy conditionals → merge → sell)
  python -m src.executor.arbitrage_executor \
    --env .env.0x9590dAF4d5cd4009c3F9767C5E7668175cFd37CF \
    --flow buy \
    --amount 0.01 \
    --cheaper yes \
    --min-profit -0.01 \
    --prefund \
    --execute              # add to actually broadcast

Address resolution order:
  1) --address CLI flag
  2) FUTARCHY_ARB_EXECUTOR_V5 or EXECUTOR_V5_ADDRESS env var
  3) Latest deployments/deployment_executor_v5_*.json

Requires:
  - PRIVATE_KEY and RPC_URL in the sourced env file
  - python-dotenv and web3 installed (see requirements.txt)
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
from src.helpers.balancer_swap import (
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
    # Then load the provided env file with override=True so it takes precedence.
    base_env = Path(".env")
    if base_env.exists():
        # Defaults from repo-level .env
        load_dotenv(base_env, override=False)
    if env_file:
        # CLI-provided env must override any defaults
        load_dotenv(env_file, override=True)


def discover_v5_address() -> Tuple[Optional[str], str]:
    # Prefer env vars first
    env_keys = ["FUTARCHY_ARB_EXECUTOR_V5", "EXECUTOR_V5_ADDRESS"]
    for k in env_keys:
        v = os.getenv(k)
        if v:
            return v, f"env ({k})"

    # Fallback to latest deployments file so changes are picked up automatically
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
    p = argparse.ArgumentParser(description="Execute futarchy arbitrage via FutarchyArbExecutorV5")
    p.add_argument("--env", dest="env_file", default=None, help="Path to .env file to load")
    p.add_argument("--address", dest="address", default=None, help="Futarchy V5 contract address (optional)")
    p.add_argument("--flow", choices=["sell", "buy"], required=True,
                   help="Trade flow: 'sell' = buy on Balancer then sell conditionals; 'buy' = buy conditionals then sell on Balancer")
    p.add_argument("--amount", dest="amount", required=True,
                   help="sDAI amount to use (in ether units, e.g. 0.01)")
    p.add_argument("--cheaper", dest="cheaper", choices=["yes", "no"], required=True,
                   help="Which conditional token is cheaper: 'yes' or 'no'")
    p.add_argument("--min-profit", dest="min_profit", default="0",
                   help="Minimum profit required in ether units (can be negative for testing)")
    p.add_argument("--prefund", action="store_true",
                   help="Transfer sDAI from your wallet to the executor contract before execution")
    # Execution control: default is preview-only; add --execute to send. --force-send forces gas + send.
    p.add_argument("--execute", action="store_true",
                   help="Actually broadcast the transaction (default is preview-only)")
    p.add_argument("--force-send", action="store_true", help=argparse.SUPPRESS)  # Advanced: force gas + send
    p.add_argument("--gas", dest="gas", type=int, default=10_000_000, help=argparse.SUPPRESS)  # Advanced
    return p.parse_args()



def _ether_str_to_signed_wei(value_str: str) -> int:
    """Convert an ether-denominated string (which may be negative) to signed wei.

    Avoids web3.to_wei which rejects negatives. Scales absolute value by 1e18
    and reapplies the original sign.
    """
    d = Decimal(str(value_str))
    sign = -1 if d < 0 else 1
    scaled = int((abs(d) * Decimal(10 ** 18)).to_integral_value(rounding=None))
    return sign * scaled


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

def _encode_sell_company_ops_placeholder(w3: Web3, router_addr: str) -> str:
    """
    Build swapExactIn calldata for composite->sDAI with exactAmountIn=0 (placeholder).
    The contract replaces the amount with mergeAmt on-chain.
    """
    router = w3.eth.contract(address=w3.to_checksum_address(router_addr), abi=BALANCER_ROUTER_ABI)
    steps = [
        (BUFFER_POOL, BUFFER_POOL, True),  # COMP -> buffer (buffer hop)
        (FINAL_POOL, SDAI, False),         # buffer -> sDAI
    ]
    path = (COMPANY_TOKEN, steps, 0, 0)   # exactAmountIn=0, minAmountOut=0
    return router.get_function_by_name("swapExactIn")([path], int(MAX_DEADLINE), False, b"")._encode_transaction_data()


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

ZERO_ADDR = Web3.to_checksum_address("0x0000000000000000000000000000000000000000")

def _first_env(*names: str) -> Optional[str]:
    for k in names:
        v = os.getenv(k)
        if v:
            return v
    return None

def _addr_or_zero(w3: Web3, *names: str) -> str:
    v = _first_env(*names)
    return w3.to_checksum_address(v) if v else ZERO_ADDR

def _require_addr(w3: Web3, *names: str) -> str:
    v = _first_env(*names)
    if not v:
        raise SystemExit(f"Missing required address env var (tried: {', '.join(names)})")
    return w3.to_checksum_address(v)

def _choose_function_abi(abi: list, name: str, available: set[str]) -> dict:
    """Pick the best-matching function ABI by minimizing missing param names."""
    candidates = [f for f in abi if f.get("type") == "function" and f.get("name") == name]
    if not candidates:
        raise SystemExit(f"ABI: function {name} not found")
    def score(fn):
        in_names = [i.get("name") for i in fn.get("inputs", [])]
        missing = [n for n in in_names if n not in available]
        return (len(missing), -len(in_names))  # prefer fewer missing, then more specific (more inputs)
    candidates.sort(key=score)
    return candidates[0]

def _materialize_args(w3: Web3, fn_abi: dict, values: dict) -> list:
    args: list = []
    for inp in fn_abi.get("inputs", []):
        nm, typ = inp["name"], inp["type"]
        if nm not in values:
            raise SystemExit(f"Cannot construct call: missing argument '{nm}' for {fn_abi.get('name')}")
        val = values[nm]
        if typ == "address":
            if isinstance(val, str):
                val = w3.to_checksum_address(val)
            else:
                raise SystemExit(f"Bad address for '{nm}'")
        elif typ == "bool":
            val = bool(val)
        elif typ.startswith("uint") or typ.startswith("int"):
            val = int(val)
        elif typ == "bytes" or typ.startswith("bytes"):
            if isinstance(val, bytes):
                val = Web3.to_hex(val)
            elif isinstance(val, str):
                if not val.startswith("0x"):
                    raise SystemExit(f"Bytes arg '{nm}' must be hex (0x…) or bytes")
            else:
                raise SystemExit(f"Unsupported bytes type for '{nm}'")
        args.append(val)
    return args


def _exec_step12_sell(
    w3: Web3,
    account,
    v5_address: str,
    amount_in_eth: str,
    yes_has_lower_price: bool,
    min_profit_wei: Optional[int],
    ) -> str:
    abi = _load_v5_abi()
    v5 = w3.eth.contract(address=w3.to_checksum_address(v5_address), abi=abi)

    amount_in_wei = w3.to_wei(Decimal(str(amount_in_eth)), "ether")
    # Resolve required addresses strictly from env
    balancer_router = require_env("BALANCER_ROUTER_ADDRESS")
    balancer_vault  = os.getenv("BALANCER_VAULT_ADDRESS") or os.getenv("BALANCER_VAULT_V3_ADDRESS")
    # Optional legacy (older sell signature); newer may omit
    fut_router_opt  = _first_env("FUTARCHY_ROUTER_ADDRESS")
    proposal_opt    = _first_env("FUTARCHY_PROPOSAL_ADDRESS")
    swapr_router    = _require_addr(w3, "SWAPR_ROUTER_ADDRESS")
    yes_comp        = require_env("SWAPR_GNO_YES_ADDRESS")
    no_comp         = require_env("SWAPR_GNO_NO_ADDRESS")
    yes_cur         = require_env("SWAPR_SDAI_YES_ADDRESS")
    no_cur          = require_env("SWAPR_SDAI_NO_ADDRESS")

    buy_ops = _encode_buy_company_ops(w3, balancer_router, amount_in_wei)

    comp = os.getenv("COMPANY_TOKEN_ADDRESS", COMPANY_TOKEN)
    cur = os.getenv("SDAI_TOKEN_ADDRESS", SDAI)
    vault = balancer_vault or ZERO_ADDR

    tx_params = {
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address),
        "chainId": w3.eth.chain_id,
    }
    tx_params.update(_eip1559_fees(w3))
    force_send = bool(getattr(_exec_step12_sell, "force_send_flag", False))
    do_send = bool(getattr(_exec_step12_sell, "do_send_flag", False))
    prefund_flag = bool(getattr(_exec_step12_sell, "prefund_flag", False))
    # Only pre-set gas when force-sending; otherwise allow estimation later
    if force_send:
        tx_params["gas"] = int(getattr(_exec_step12_sell, "force_gas_limit", int(os.getenv("DEFAULT_GAS_LIMIT", "10000000"))))

    # Prefund the executor with sDAI if requested or if balance is insufficient
    sdai_addr = os.getenv("SDAI_TOKEN_ADDRESS", SDAI)
    sdai = w3.eth.contract(address=w3.to_checksum_address(sdai_addr), abi=_ERC20_MIN_ABI)
    exec_bal = sdai.functions.balanceOf(w3.to_checksum_address(v5_address)).call()
    if exec_bal < amount_in_wei:
        missing = amount_in_wei - exec_bal
        if not do_send:
            print(
                f"Preview: executor sDAI balance {w3.from_wei(exec_bal, 'ether')} < needed {w3.from_wei(amount_in_wei, 'ether')} — "
                f"would need prefund of {w3.from_wei(missing, 'ether')} sDAI. Skipping in preview."
            )
        else:
            if not prefund_flag:
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

    # Gas limit already set above; do not override here

    # ABI-adaptive call build
    # Optional pools for newer ABIs (0 if unused)
    # Accept multiple env synonyms for pool addresses (some envs use *_ADDRESS names)
    yes_pool      = _addr_or_zero(w3, "SWAPR_GNO_YES_POOL", "YES_COMP_POOL", "YES_POOL", "SWAPR_POOL_YES_ADDRESS")
    no_pool       = _addr_or_zero(w3, "SWAPR_GNO_NO_POOL",  "NO_COMP_POOL",  "NO_POOL",  "SWAPR_POOL_NO_ADDRESS")
    pred_yes_pool = _addr_or_zero(w3, "SWAPR_SDAI_YES_POOL", "PRED_YES_POOL", "SWAPR_POOL_PRED_YES_ADDRESS")
    pred_no_pool  = _addr_or_zero(w3, "SWAPR_SDAI_NO_POOL",  "PRED_NO_POOL",  "SWAPR_POOL_PRED_NO_ADDRESS")

    values = {
        "buy_company_ops": buy_ops,
        "balancer_router": balancer_router,
        "balancer_vault":  vault,
        "comp":             comp,
        "cur":              cur,
        # Provide both names so either ABI (lower or higher) is satisfied
        "yes_has_lower_price": bool(yes_has_lower_price),
        "yes_has_higher_price": (not bool(yes_has_lower_price)),
        "futarchy_router": fut_router_opt or ZERO_ADDR,
        "proposal":        proposal_opt or ZERO_ADDR,
        "yes_comp":        yes_comp,
        "no_comp":         no_comp,
        "yes_cur":         yes_cur,
        "no_cur":          no_cur,
        "yes_pool":        yes_pool,
        "no_pool":         no_pool,
        "pred_yes_pool":   pred_yes_pool,
        "pred_no_pool":    pred_no_pool,
        "swapr_router":    swapr_router,
        "amount_sdai_in":  int(amount_in_wei),
        # Profit guard param name varies across ABIs; pass both
        "min_profit":      int(min_profit_wei or 0),
        "min_out_final":   int(min_profit_wei or 0),
    }
    fn_abi = _choose_function_abi(abi, "sell_conditional_arbitrage_balancer", set(values.keys()))
    args = _materialize_args(w3, fn_abi, values)
    # Build transaction
    tx = getattr(v5.functions, "sell_conditional_arbitrage_balancer")(*args).build_transaction(tx_params)

    # If we didn't force a gas limit earlier, try to estimate now with a buffer; otherwise keep provided gas
    if "gas" not in tx:
        try:
            gas_est = w3.eth.estimate_gas(tx)
            tx["gas"] = int(gas_est * 1.2)
        except Exception:
            tx["gas"] = int(os.getenv("DEFAULT_GAS_LIMIT", "1500000"))

    if not do_send:
        # Preview-only: print summary and exit without sending
        print("Preview: built sell_conditional_arbitrage_balancer transaction (not sent)")
        print(f"  to:    {w3.to_checksum_address(v5_address)}")
        print(f"  from:  {account.address}")
        print(f"  gas:   {tx.get('gas')}")
        fees = {k: tx.get(k) for k in ("gasPrice", "maxFeePerGas", "maxPriorityFeePerGas") if k in tx}
        if fees:
            print(f"  fees:  {fees}")
        data_len = len(tx.get("data", ""))
        print(f"  data:  {tx.get('data', '')[:66]}... (len={data_len})")
        print("Use --execute to broadcast; add --prefund if executor balance is low.")
        return ""

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


def _exec_buy12(
    w3: Web3,
    account,
    v5_address: str,
    amount_in_eth: str,
    yes_has_lower_price: bool,
) -> str:
    """Symmetric BUY steps 1–3 only: split sDAI; buy cheaper leg exact-in; other leg exact-out."""
    abi = _load_v5_abi()
    v5 = w3.eth.contract(address=w3.to_checksum_address(v5_address), abi=abi)

    amount_in_wei = w3.to_wei(Decimal(str(amount_in_eth)), "ether")
    # Addresses (env)
    balancer_router = require_env("BALANCER_ROUTER_ADDRESS")  # required if steps 4–6 are engaged
    balancer_vault  = os.getenv("BALANCER_VAULT_ADDRESS") or os.getenv("BALANCER_VAULT_V3_ADDRESS") or ZERO_ADDR
    comp            = os.getenv("COMPANY_TOKEN_ADDRESS", COMPANY_TOKEN)
    cur             = os.getenv("SDAI_TOKEN_ADDRESS", SDAI)
    swapr_router    = _require_addr(w3, "SWAPR_ROUTER_ADDRESS")
    fr_opt          = _first_env("FUTARCHY_ROUTER_ADDRESS")
    pr_opt          = _first_env("FUTARCHY_PROPOSAL_ADDRESS")
    yes_comp        = require_env("SWAPR_GNO_YES_ADDRESS")
    no_comp         = require_env("SWAPR_GNO_NO_ADDRESS")
    yes_cur         = require_env("SWAPR_SDAI_YES_ADDRESS")
    no_cur          = require_env("SWAPR_SDAI_NO_ADDRESS")
    # Pools – pass ZERO if ABI asks for them
    # Accept synonyms used in env files (e.g., SWAPR_POOL_*_ADDRESS)
    yes_pool        = _addr_or_zero(w3, "SWAPR_GNO_YES_POOL", "YES_COMP_POOL", "YES_POOL", "SWAPR_POOL_YES_ADDRESS")
    no_pool         = _addr_or_zero(w3, "SWAPR_GNO_NO_POOL",  "NO_COMP_POOL",  "NO_POOL",  "SWAPR_POOL_NO_ADDRESS")
    pred_yes_pool   = _addr_or_zero(w3, "SWAPR_SDAI_YES_POOL", "PRED_YES_POOL", "SWAPR_POOL_PRED_YES_ADDRESS")
    pred_no_pool    = _addr_or_zero(w3, "SWAPR_SDAI_NO_POOL",  "PRED_NO_POOL",  "SWAPR_POOL_PRED_NO_ADDRESS")

    # Prepare Balancer sell ops (composite -> sDAI) for steps 4–6:
    # Always pass a placeholder; the contract overwrites exactAmountIn with mergeAmt on-chain.
    try:
        sell_ops_hex = _encode_sell_company_ops_placeholder(w3, balancer_router)
    except Exception as e:
        raise SystemExit(f"Failed to encode Balancer sell ops placeholder (composite->sDAI): {e}")

    # Ensure the executor is funded with sDAI to split
    sdai_addr = os.getenv("SDAI_TOKEN_ADDRESS", SDAI)
    sdai = w3.eth.contract(address=w3.to_checksum_address(sdai_addr), abi=_ERC20_MIN_ABI)
    exec_bal = sdai.functions.balanceOf(w3.to_checksum_address(v5_address)).call()
    tx_params = {
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address),
        "chainId": w3.eth.chain_id,
    }
    tx_params.update(_eip1559_fees(w3))
    force_send = bool(getattr(_exec_buy12, "force_send_flag", False))
    do_send = bool(getattr(_exec_buy12, "do_send_flag", False))
    prefund_flag = bool(getattr(_exec_buy12, "prefund_flag", False))
    if force_send:
        tx_params["gas"] = int(getattr(_exec_buy12, "force_gas_limit", int(os.getenv("DEFAULT_GAS_LIMIT", "10000000"))))
    # Explicit gas to bypass estimateGas inside build_transaction
    tx_params["gas"] = int(getattr(_exec_buy12, "force_gas_limit", int(os.getenv("DEFAULT_GAS_LIMIT", "10000000"))))
    if exec_bal < amount_in_wei:
        missing = amount_in_wei - exec_bal
        if not do_send:
            print(
                f"Preview: executor sDAI balance {w3.from_wei(exec_bal, 'ether')} < needed {w3.from_wei(amount_in_wei, 'ether')} — "
                f"would need prefund of {w3.from_wei(missing, 'ether')} sDAI. Skipping in preview."
            )
        else:
            if not prefund_flag:
                raise SystemExit(
                    f"Executor sDAI balance {w3.from_wei(exec_bal, 'ether')} < needed {w3.from_wei(amount_in_wei, 'ether')}. "
                    f"Re-run with --prefund to transfer {w3.from_wei(missing, 'ether')} sDAI to the executor."
                )
            fund_tx = sdai.functions.transfer(w3.to_checksum_address(v5_address), missing).build_transaction({
                "from": account.address,
                "nonce": tx_params["nonce"],
                "chainId": tx_params["chainId"],
            })
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

    # Gas limit already set above; do not override here

    # ABI-adaptive construction of buy_conditional_arbitrage_balancer call
    # Debug prints of resolved addresses and pools
    try:
        print(
            "BUY debug:",
            f"amount_sdai_in={w3.from_wei(amount_in_wei, 'ether')}",
            f"cur={cur}",
            f"comp={comp}",
            f"swapr_router={swapr_router}",
            f"futarchy_router={fr_opt or ZERO_ADDR}",
            f"proposal={pr_opt or ZERO_ADDR}",
            f"yes_pool={yes_pool}",
            f"no_pool={no_pool}",
            f"pred_yes_pool={pred_yes_pool}",
            f"pred_no_pool={pred_no_pool}",
        )
    except Exception:
        pass

    values = {
        "sell_company_ops": sell_ops_hex,
        "balancer_router":  balancer_router,
        "balancer_vault":   balancer_vault,
        "comp":             comp,
        "cur":              cur,
        # Support either ABI field name: provide both lower/higher
        "yes_has_lower_price": bool(yes_has_lower_price),
        "yes_has_higher_price": (not bool(yes_has_lower_price)),
        "futarchy_router":  fr_opt or ZERO_ADDR,
        "proposal":         pr_opt or ZERO_ADDR,
        "yes_comp":         yes_comp,
        "no_comp":          no_comp,
        "yes_cur":          yes_cur,
        "no_cur":           no_cur,
        "swapr_router":     swapr_router,
        "yes_pool":         yes_pool,
        "no_pool":          no_pool,
        "pred_yes_pool":    pred_yes_pool,
        "pred_no_pool":     pred_no_pool,
        "amount_sdai_in":   int(amount_in_wei),
        # New on-chain profit guard (signed). ABI-adaptive: ignored on older ABIs.
        "min_out_final":    int(getattr(_exec_buy12, "min_out_final_wei", 0)),
    }
    fn_abi = _choose_function_abi(abi, "buy_conditional_arbitrage_balancer", set(values.keys()))
    args = _materialize_args(w3, fn_abi, values)
    tx = getattr(v5.functions, "buy_conditional_arbitrage_balancer")(*args).build_transaction(tx_params)

    if "gas" not in tx:
        try:
            gas_est = w3.eth.estimate_gas(tx)
            tx["gas"] = int(gas_est * 1.2)
        except Exception:
            tx["gas"] = int(os.getenv("DEFAULT_GAS_LIMIT", "1500000"))

    if not do_send:
        print("Preview: built buy_conditional_arbitrage_balancer transaction (not sent)")
        print(f"  to:    {w3.to_checksum_address(v5_address)}")
        print(f"  from:  {account.address}")
        print(f"  gas:   {tx.get('gas')}")
        fees = {k: tx.get(k) for k in ("gasPrice", "maxFeePerGas", "maxPriorityFeePerGas") if k in tx}
        if fees:
            print(f"  fees:  {fees}")
        data_len = len(tx.get("data", ""))
        print(f"  data:  {tx.get('data', '')[:66]}... (len={data_len})")
        print("Use --execute to broadcast; add --prefund if executor balance is low.")
        return ""

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




def main():
    args = parse_args()
    load_env(args.env_file)
    
    # Map simplified flags to internal variables
    amount_in = args.amount
    yes_cheaper = (args.cheaper == "yes")
    min_profit_wei = _ether_str_to_signed_wei(args.min_profit)
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
    # Helpful visibility: show the sender and contract owner (if callable)
    try:
        abi_dbg = _load_v5_abi()
        v5_dbg = w3.eth.contract(address=w3.to_checksum_address(address), abi=abi_dbg)
        owner_dbg = v5_dbg.functions.owner().call()
        print(f"Using sender: {acct.address}; Contract owner: {owner_dbg}")
    except Exception:
        # Non-fatal if ABI/owner() not available
        print(f"Using sender: {acct.address}")

    # Enforce a minimum gas limit even if the harness passes a lower --gas (when force-sending)
    try:
        min_gas = int(os.getenv("MIN_GAS_LIMIT", "10000000"))
    except Exception:
        min_gas = 10_000_000
    requested_gas = int(args.gas)
    effective_gas = requested_gas if requested_gas >= min_gas else min_gas
    if requested_gas < min_gas:
        print(f"Gas clamp: requested {requested_gas} < min {min_gas}; using {effective_gas}")
    else:
        print(f"Gas clamp: using requested gas {effective_gas}")

    # Decide whether to actually send. --force-send implies --execute.
    do_send = bool(args.execute or args.force_send)

    # Execute SELL flow (Balancer buy + unwind)
    if args.flow == "sell":
        _exec_step12_sell.force_send_flag = bool(args.force_send)
        _exec_step12_sell.do_send_flag = do_send
        _exec_step12_sell.force_gas_limit = effective_gas
        _exec_step12_sell.prefund_flag = bool(args.prefund)
        _exec_step12_sell(w3, acct, address, amount_in, yes_cheaper, min_profit_wei)
    
    # Execute BUY flow (split + dual swaps + merge)
    elif args.flow == "buy":
        _exec_buy12.force_send_flag = bool(args.force_send)
        _exec_buy12.do_send_flag = do_send
        _exec_buy12.force_gas_limit = effective_gas
        _exec_buy12.prefund_flag = bool(args.prefund)
        _exec_buy12.min_out_final_wei = min_profit_wei
        _exec_buy12(w3, acct, address, amount_in, yes_cheaper)
    
    else:
        raise SystemExit("Invalid flow. Use --flow sell or --flow buy")


if __name__ == "__main__":
    main()
