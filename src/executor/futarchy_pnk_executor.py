#!/usr/bin/env python3
"""
Futarchy V5 PNK Executor

Purpose
 - Clone of futarchy_executor.py adapted to use the PNK-specific complete SELL flow
   implemented on-chain: sell_conditional_arbitrage_pnk.
 - Step 2 Balancer "buy company" calldata is not needed; the contract buys PNK
   internally via sDAI→WETH (Balancer Vault) → PNK (Swapr v2).

Usage
  source .env.<proposal>
  python -m src.executor.futarchy_pnk_executor \
    --step12 --amount-in 0.01 --min-profit 0
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


DEPLOYMENTS_GLOB = "deployments/deployment_executor_v5_*.json"


def load_env(env_file: Optional[str]) -> None:
    base_env = Path(".env")
    if base_env.exists():
        load_dotenv(base_env)
    if env_file:
        # Ensure the provided env file overrides any keys set by base .env
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


def _ether_str_to_signed_wei(x: str) -> int:
    """Convert a decimal ether string to a signed wei int (supports negatives)."""
    return int(Decimal(str(x)) * Decimal(10**18))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Call Futarchy V5 PNK executor")
    p.add_argument("--env", dest="env_file", default=None, help="Path to .env file to load")
    p.add_argument("--address", dest="address", default=None, help="Futarchy V5 contract address")
    p.add_argument("--send-wei", dest="send_wei", default="0", help="Wei to send to receive() (default 0)")
    p.add_argument("--step12", action="store_true", help="Execute SELL flow via V5 (PNK variant)")
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
    build_abi = Path("build/FutarchyArbExecutorV5.abi")
    if build_abi.exists():
        try:
            return json.loads(build_abi.read_text())
        except Exception:
            pass
    raise SystemExit("Could not load V5 ABI from deployments/ or build/. Please deploy V5 first.")


_ERC20_MIN_ABI = [
    {
        "constant": False,
        "inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}],
        "name": "approve",
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
    {
        "constant": False,
        "inputs": [{"name": "to", "type": "address"}, {"name": "amount", "type": "uint256"}],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "nonpayable",
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


def main():
    args = parse_args()
    load_env(args.env_file)

    rpc_url = os.getenv("RPC_URL") or os.getenv("GNOSIS_RPC_URL")
    if not rpc_url:
        raise SystemExit("Set RPC_URL or GNOSIS_RPC_URL in env")
    private_key = require_env("PRIVATE_KEY")

    # Resolve V5 address
    if args.address:
        address = Web3.to_checksum_address(args.address)
        src = "cli"
    else:
        resolved, src = discover_v5_address()
        if not resolved:
            raise SystemExit("Could not discover V5 address; pass --address or set env/deployments")
        address = Web3.to_checksum_address(resolved)
    print(f"Using V5: {address} ({src})")

    w3 = Web3(Web3.HTTPProvider(rpc_url))
    try:
        from web3.middleware import geth_poa_middleware
        w3.middleware_onion.inject(geth_poa_middleware, layer=0)
    except Exception:
        pass
    if not w3.is_connected():
        raise SystemExit("Failed to connect to RPC_URL")

    acct = Account.from_key(private_key)
    chain_id = w3.eth.chain_id
    nonce = w3.eth.get_transaction_count(acct.address)

    abi = _load_v5_abi()
    v5 = w3.eth.contract(address=w3.to_checksum_address(address), abi=abi)

    # SELL flow (PNK variant)
    if args.step12:
        if not args.amount_in:
            raise SystemExit("--amount-in is required with --step12 (ether units)")
        amount_in_wei = w3.to_wei(Decimal(str(args.amount_in)), "ether")

        # Resolve required addresses
        swapr_router = _require_addr(w3, "SWAPR_ROUTER_ADDRESS")
        comp = os.getenv("COMPANY_TOKEN_ADDRESS")
        if not comp:
            raise SystemExit("COMPANY_TOKEN_ADDRESS must point to PNK for PNK variant")
        cur = os.getenv("SDAI_TOKEN_ADDRESS") or "0xaf204776c7245bF4147c2612BF6e5972Ee483701"

        fut_router = _first_env("FUTARCHY_ROUTER_ADDRESS") or ZERO_ADDR
        proposal = _first_env("FUTARCHY_PROPOSAL_ADDRESS") or ZERO_ADDR
        yes_comp = require_env("SWAPR_GNO_YES_ADDRESS")
        no_comp  = require_env("SWAPR_GNO_NO_ADDRESS")
        yes_cur  = require_env("SWAPR_SDAI_YES_ADDRESS")
        no_cur   = require_env("SWAPR_SDAI_NO_ADDRESS")

        # Optional prefund of sDAI to executor
        if args.prefund:
            sdai_addr = os.getenv("SDAI_TOKEN_ADDRESS", cur)
            sdai = w3.eth.contract(address=w3.to_checksum_address(sdai_addr), abi=_ERC20_MIN_ABI)
            exec_bal = sdai.functions.balanceOf(address).call()
            if exec_bal < amount_in_wei:
                tx0 = sdai.functions.transfer(address, int(amount_in_wei - exec_bal)).build_transaction({
                    "from": acct.address, "nonce": nonce, "chainId": chain_id
                })
                tx0.update(_eip1559_fees(w3))
                try:
                    tx0["gas"] = int(w3.eth.estimate_gas(tx0) * 1.2)
                except Exception:
                    tx0["gas"] = 150_000
                s0 = acct.sign_transaction(tx0)
                raw0 = getattr(s0, "rawTransaction", None) or getattr(s0, "raw_transaction", None)
                h0 = w3.eth.send_raw_transaction(raw0)
                print(f"Prefund tx: {h0.hex()}")
                w3.eth.wait_for_transaction_receipt(h0)
                nonce += 1

        # Build call to sell_conditional_arbitrage_pnk
        # Support negative min-profit: avoid w3.to_wei (unsigned) and use a signed converter
        min_profit_wei = int(args.min_profit_wei) if args.min_profit_wei is not None else _ether_str_to_signed_wei(args.min_profit)
        tx_params = {"from": acct.address, "nonce": nonce, "chainId": chain_id}
        tx_params.update(_eip1559_fees(w3))
        if args.force_send:
            tx_params["gas"] = int(args.gas)

        values = {
            "buy_company_ops": "0x",          # ignored by contract
            "balancer_router": ZERO_ADDR,      # ignored
            "balancer_vault":  ZERO_ADDR,      # ignored
            "comp":             comp,
            "cur":              cur,
            "futarchy_router": fut_router,
            "proposal":        proposal,
            "yes_comp":        yes_comp,
            "no_comp":         no_comp,
            "yes_cur":         yes_cur,
            "no_cur":          no_cur,
            "swapr_router":    swapr_router,
            "amount_sdai_in":  int(amount_in_wei),
            "min_out_final":   int(min_profit_wei),
        }

        # Build transaction directly (function name is stable)
        try:
            fn = v5.get_function_by_name("sell_conditional_arbitrage_pnk")
        except Exception:
            raise SystemExit("ABI: function sell_conditional_arbitrage_pnk not found — deploy latest V5")

        # Order args by ABI
        args_order = [i["name"] for i in fn.abi.get("inputs", [])]
        call_args = [values[name] for name in args_order]
        tx = fn(*call_args).build_transaction(tx_params)
        if "gas" not in tx:
            try:
                tx["gas"] = int(w3.eth.estimate_gas(tx) * 1.2)
            except Exception:
                tx["gas"] = 1_500_000

        signed = acct.sign_transaction(tx)
        raw = getattr(signed, "rawTransaction", None) or getattr(signed, "raw_transaction", None)
        txh = w3.eth.send_raw_transaction(raw)
        txh_hex = txh.hex()
        print(f"Tx sent: {txh_hex}")
        print(f"GnosisScan:  https://gnosisscan.io/tx/{txh_hex}")
        receipt = w3.eth.wait_for_transaction_receipt(txh)
        print(f"Success: {receipt.status == 1}; Gas used: {receipt.gasUsed}")
        return

    # Withdraw helper
    if args.wd_token:
        to_addr = args.wd_to or acct.address
        if args.wd_amount_wei is not None:
            amount_wei = int(args.wd_amount_wei)
        elif args.wd_amount is not None:
            amount_wei = w3.to_wei(Decimal(str(args.wd_amount)), "ether")
        else:
            raise SystemExit("Provide --withdraw-amount or --withdraw-amount-wei")
        abi = _load_v5_abi()
        v5 = w3.eth.contract(address=w3.to_checksum_address(address), abi=abi)
        tx = v5.functions.withdrawToken(w3.to_checksum_address(args.wd_token), w3.to_checksum_address(to_addr), int(amount_wei)).build_transaction({
            "from": acct.address, "nonce": nonce, "chainId": chain_id
        })
        tx.update(_eip1559_fees(w3))
        try:
            tx["gas"] = int(w3.eth.estimate_gas(tx) * 1.2)
        except Exception:
            tx["gas"] = 120_000
        s = acct.sign_transaction(tx)
        raw = getattr(s, "rawTransaction", None) or getattr(s, "raw_transaction", None)
        h = w3.eth.send_raw_transaction(raw)
        print(f"Tx sent: {h.hex()}")
        w3.eth.wait_for_transaction_receipt(h)
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
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    print(f"Success: {receipt.status == 1}; Gas used: {receipt.gasUsed}")


if __name__ == "__main__":
    main()
