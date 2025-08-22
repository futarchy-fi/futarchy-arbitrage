#!/usr/bin/env python3
"""
PNK Arbitrage Executor (V5)

Behavior
- Mirrors src/executor/arbitrage_executor.py CLI and flow handling (sell|buy),
  but on SELL path calls the PNK-specific on-chain entrypoint
  sell_conditional_arbitrage_pnk (as in futarchy_pnk_executor.py).
- BUY path is identical to arbitrage_executor: split/buy conditionals/merge/sell.

Usage examples
  # SELL flow (internal PNK buy in Step 2)
  python -m src.executor.arbitrage_pnk_executor \
    --env .env.pnk \
    --flow sell \
    --amount 0.01 \
    --cheaper yes \
    --min-profit -0.01 \
    --prefund

  # BUY flow (unchanged vs arbitrage_executor)
  python -m src.executor.arbitrage_pnk_executor \
    --env .env.pnk \
    --flow buy \
    --amount 0.01 \
    --cheaper yes \
    --min-profit -0.01 \
    --prefund
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
    # Load base .env first if present; then allow provided env file to override keys
    base_env = Path(".env")
    if base_env.exists():
        load_dotenv(base_env)
    if env_file:
        load_dotenv(env_file, override=True)


def discover_v5_address() -> Tuple[Optional[str], str]:
    # Prefer  env vars
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
    """Return a dict of fee fields for EIP-1559 txs with a minimal, consistent tip."""
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
    p = argparse.ArgumentParser(description="Execute futarchy arbitrage (PNK variant) via FutarchyArbExecutorV5")
    p.add_argument("--env", dest="env_file", default=None, help="Path to .env file to load")
    p.add_argument("--address", dest="address", default=None, help="Futarchy V5 contract address (optional)")
    p.add_argument("--flow", choices=["sell", "buy"], required=True,
                   help="Trade flow: 'sell' = buy PNK internally then sell conditionals; 'buy' = buy conditionals then sell on Balancer")
    p.add_argument("--amount", dest="amount", required=True,
                   help="sDAI amount to use (in ether units, e.g. 0.01)")
    p.add_argument("--cheaper", dest="cheaper", choices=["yes", "no"], required=True,
                   help="Which conditional token is cheaper: 'yes' or 'no' (ignored in PNK sell path)")
    p.add_argument("--min-profit", dest="min_profit", default="0",
                   help="Minimum profit required in ether units (can be negative for testing)")
    p.add_argument("--prefund", action="store_true",
                   help="Transfer sDAI from your wallet to the executor contract before execution")
    p.add_argument("--force-send", action="store_true", help=argparse.SUPPRESS)  # Hidden for advanced use
    p.add_argument("--gas", dest="gas", type=int, default=3_000_000, help=argparse.SUPPRESS)  # Hidden
    return p.parse_args()


def _ether_str_to_signed_wei(value_str: str) -> int:
    """Convert an ether-denominated string (which may be negative) to signed wei."""
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
    path = (SDAI, steps, int(amount_in_wei), 0)  # minOut=0
    calldata: str = router.get_function_by_name("swapExactIn")(
        [path], int(MAX_DEADLINE), False, b""
    )._encode_transaction_data()
    return calldata


def _encode_sell_company_ops_placeholder(w3: Web3, router_addr: str) -> str:
    """Build swapExactIn calldata for composite->sDAI with exactAmountIn=0 (placeholder)."""
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
        return (len(missing), -len(in_names))

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


def _exec_step12_sell_pnk(
    w3: Web3,
    account,
    v5_address: str,
    amount_in_eth: str,
    yes_has_lower_price: bool,  # kept for interface parity; ignored in PNK path
    min_profit_wei: Optional[int],
) -> str:
    """SELL flow using PNK-specific on-chain entrypoint (internal sDAI->WETH->PNK)."""
    abi = _load_v5_abi()
    v5 = w3.eth.contract(address=w3.to_checksum_address(v5_address), abi=abi)

    amount_in_wei = w3.to_wei(Decimal(str(amount_in_eth)), "ether")

    # Resolve required addresses
    swapr_router = _require_addr(w3, "SWAPR_ROUTER_ADDRESS")
    comp = os.getenv("COMPANY_TOKEN_ADDRESS")
    if not comp:
        raise SystemExit("COMPANY_TOKEN_ADDRESS must point to PNK for PNK variant")
    cur = os.getenv("SDAI_TOKEN_ADDRESS") or SDAI
    fut_router_opt = _first_env("FUTARCHY_ROUTER_ADDRESS") or ZERO_ADDR
    proposal_opt   = _first_env("FUTARCHY_PROPOSAL_ADDRESS") or ZERO_ADDR
    yes_comp       = require_env("SWAPR_GNO_YES_ADDRESS")
    no_comp        = require_env("SWAPR_GNO_NO_ADDRESS")
    yes_cur        = require_env("SWAPR_SDAI_YES_ADDRESS")
    no_cur         = require_env("SWAPR_SDAI_NO_ADDRESS")

    # Optional prefund of sDAI to executor
    sdai_addr = os.getenv("SDAI_TOKEN_ADDRESS", cur)
    sdai = w3.eth.contract(address=w3.to_checksum_address(sdai_addr), abi=_ERC20_MIN_ABI)
    exec_bal = sdai.functions.balanceOf(w3.to_checksum_address(v5_address)).call()
    tx_params = {
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address),
        "chainId": w3.eth.chain_id,
    }
    tx_params.update(_eip1559_fees(w3))
    if getattr(_exec_step12_sell_pnk, "prefund_flag", False):
        if exec_bal < amount_in_wei:
            missing = amount_in_wei - exec_bal
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
    else:
        if exec_bal < amount_in_wei:
            missing = amount_in_wei - exec_bal
            raise SystemExit(
                f"Executor sDAI balance {w3.from_wei(exec_bal, 'ether')} < needed {w3.from_wei(amount_in_wei, 'ether')}. "
                f"Re-run with --prefund to transfer {w3.from_wei(missing, 'ether')} sDAI to the executor."
            )

    if getattr(_exec_step12_sell_pnk, "force_send_flag", False):
        tx_params["gas"] = getattr(_exec_step12_sell_pnk, "force_gas_limit", 1_500_000)

    # Build call to sell_conditional_arbitrage_pnk (order by ABI input names)
    # Support negative min-profit (signed)
    min_out_final = int(min_profit_wei or 0)
    values = {
        "buy_company_ops": "0x",         # ignored by contract
        "balancer_router": ZERO_ADDR,     # ignored
        "balancer_vault":  ZERO_ADDR,     # ignored
        "comp":             comp,
        "cur":              cur,
        "futarchy_router": fut_router_opt,
        "proposal":        proposal_opt,
        "yes_comp":        yes_comp,
        "no_comp":         no_comp,
        "yes_cur":         yes_cur,
        "no_cur":          no_cur,
        "swapr_router":    swapr_router,
        "amount_sdai_in":  int(amount_in_wei),
        "min_out_final":   min_out_final,
    }

    try:
        fn = v5.get_function_by_name("sell_conditional_arbitrage_pnk")
    except Exception:
        raise SystemExit("ABI: function sell_conditional_arbitrage_pnk not found — deploy latest V5")
    args_order = [i.get("name") for i in fn.abi.get("inputs", [])]
    call_args = [values[name] for name in args_order]

    tx = fn(*call_args).build_transaction(tx_params)

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
    yes_pool        = _addr_or_zero(w3, "SWAPR_GNO_YES_POOL", "YES_COMP_POOL", "YES_POOL")
    no_pool         = _addr_or_zero(w3, "SWAPR_GNO_NO_POOL",  "NO_COMP_POOL",  "NO_POOL")
    pred_yes_pool   = _addr_or_zero(w3, "SWAPR_SDAI_YES_POOL", "PRED_YES_POOL")
    pred_no_pool    = _addr_or_zero(w3, "SWAPR_SDAI_NO_POOL",  "PRED_NO_POOL")

    # No Balancer fallback: require the on-chain PNK entrypoint to be present.

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
    if exec_bal < amount_in_wei:
        missing = amount_in_wei - exec_bal
        if not getattr(_exec_buy12, "prefund_flag", False):
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

    if getattr(_exec_buy12, "force_send_flag", False):
        tx_params["gas"] = getattr(_exec_buy12, "force_gas_limit", 1_500_000)

    # Prefer the PNK-specific on-chain BUY entrypoint if available; fallback to Balancer variant.
    # Build argument maps tailored to each ABI to avoid passing unused params.
    values_pnk = {
        "comp":              comp,
        "cur":               cur,
        # Support either ABI field name: provide both lower/higher
        "yes_has_lower_price":  bool(yes_has_lower_price),
        "yes_has_higher_price": (not bool(yes_has_lower_price)),
        "futarchy_router":   fr_opt or ZERO_ADDR,
        "proposal":          pr_opt or ZERO_ADDR,
        "yes_comp":          yes_comp,
        "no_comp":           no_comp,
        "yes_cur":           yes_cur,
        "no_cur":            no_cur,
        "yes_pool":          yes_pool,
        "no_pool":           no_pool,
        "swapr_router":      swapr_router,
        "amount_sdai_in":    int(amount_in_wei),
        "min_out_final":     int(getattr(_exec_buy12, "min_out_final_wei", 0)),
    }
    try:
        fn_abi = _choose_function_abi(abi, "buy_conditional_arbitrage_pnk", set(values_pnk.keys()))
    except SystemExit:
        raise SystemExit("ABI: buy_conditional_arbitrage_pnk not found. Deploy the updated V5 or use the SELL flow.")
    fn = getattr(v5.functions, "buy_conditional_arbitrage_pnk")
    args = _materialize_args(w3, fn_abi, values_pnk)
    tx = fn(*args).build_transaction(tx_params)

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

    # Follow-up: if company token is PNK and BUY entrypoint did not sell PNK
    # (older deployment without buy_conditional_arbitrage_pnk), sell any leftover PNK now.
    pnk_addr_env = os.getenv("COMPANY_TOKEN_ADDRESS")
    PNK_CHAIN = Web3.to_checksum_address("0x37b60f4E9A31A64cCc0024dce7D0fD07eAA0F7B3")
    if pnk_addr_env:
        try:
            comp_addr_cs = w3.to_checksum_address(comp)
            pnk_cs = w3.to_checksum_address(pnk_addr_env)
        except Exception:
            comp_addr_cs = comp
            pnk_cs = pnk_addr_env
        if comp_addr_cs.lower() == pnk_cs.lower() or comp_addr_cs.lower() == PNK_CHAIN.lower():
            # Query executor's PNK balance
            erc20 = w3.eth.contract(address=pnk_cs, abi=_ERC20_MIN_ABI)
            pnk_bal = int(erc20.functions.balanceOf(w3.to_checksum_address(v5_address)).call())
            if pnk_bal > 0:
                print(f"Found leftover PNK on executor: {w3.from_wei(pnk_bal, 'ether')} — selling to sDAI")
                tx2_params = {
                    "from": account.address,
                    "nonce": w3.eth.get_transaction_count(account.address),
                    "chainId": w3.eth.chain_id,
                }
                tx2_params.update(_eip1559_fees(w3))
                # default gas if force-send set globally on buy
                if getattr(_exec_buy12, "force_send_flag", False):
                    tx2_params["gas"] = getattr(_exec_buy12, "force_gas_limit", 1_500_000)
                tx2 = v5.functions.sellPnkForSdai(int(pnk_bal), 0, 0).build_transaction(tx2_params)
                if "gas" not in tx2:
                    try:
                        tx2["gas"] = int(w3.eth.estimate_gas(tx2) * 1.2)
                    except Exception:
                        tx2["gas"] = 1_500_000
                s2 = account.sign_transaction(tx2)
                raw2 = getattr(s2, "rawTransaction", None) or getattr(s2, "raw_transaction", None)
                h2 = w3.eth.send_raw_transaction(raw2)
                h2x = h2.hex()
                print(f"PNK→sDAI sell tx: {h2x}")
                print(f"GnosisScan:  https://gnosisscan.io/tx/{h2x}")
                w3.eth.wait_for_transaction_receipt(h2)

    return txh0x


def main():
    args = parse_args()
    load_env(args.env_file)

    # Map simplified flags to internal variables
    amount_in = args.amount
    yes_cheaper = (args.cheaper == "yes")
    min_profit_wei = _ether_str_to_signed_wei(args.min_profit)

    rpc_url = os.getenv("RPC_URL") or os.getenv("GNOSIS_RPC_URL") or require_env("RPC_URL")
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

    # Execute SELL flow (PNK-internal buy + unwind)
    if args.flow == "sell":
        _exec_step12_sell_pnk.force_send_flag = bool(args.force_send)
        _exec_step12_sell_pnk.force_gas_limit = int(args.gas)
        _exec_step12_sell_pnk.prefund_flag = bool(args.prefund)
        _exec_step12_sell_pnk(w3, acct, address, amount_in, yes_cheaper, min_profit_wei)

    # Execute BUY flow (split + dual swaps + merge + sell)
    elif args.flow == "buy":
        _exec_buy12.force_send_flag = bool(args.force_send)
        _exec_buy12.force_gas_limit = int(args.gas)
        _exec_buy12.prefund_flag = bool(args.prefund)
        _exec_buy12.min_out_final_wei = min_profit_wei
        _exec_buy12(w3, acct, address, amount_in, yes_cheaper)

    else:
        raise SystemExit("Invalid flow. Use --flow sell or --flow buy")


if __name__ == "__main__":
    main()
