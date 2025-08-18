#!/usr/bin/env python3
from __future__ import annotations

import os
import argparse
from decimal import Decimal
from dotenv import load_dotenv
from web3 import Web3


ABI_BUY = [
    {
        "name": "buyPnkWithSdai",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "amountSdaiIn", "type": "uint256"},
            {"name": "minWethOut", "type": "uint256"},
            {"name": "minPnkOut", "type": "uint256"},
        ],
        "outputs": [],
    }
]

ERC20_MIN_ABI = [
    {"constant": True, "inputs": [{"name": "owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"constant": False, "inputs": [{"name": "to", "type": "address"}, {"name": "amount", "type": "uint256"}], "name": "transfer", "outputs": [{"name": "", "type": "bool"}], "stateMutability": "nonpayable", "type": "function"}
]


def eip1559(w3: Web3) -> dict:
    try:
        base = w3.eth.get_block("latest").get("baseFeePerGas")
        tip = 1
        return {"maxFeePerGas": int(base) * 2 + tip, "maxPriorityFeePerGas": tip}
    except Exception:
        return {"gasPrice": int(w3.eth.gas_price) + 1}


def main():
    load_dotenv()

    ap = argparse.ArgumentParser(description="Call FutarchyArbExecutorV5.buyPnkWithSdai")
    ap.add_argument("--env", help=".env file path", default=None)
    ap.add_argument("--amount", help="sDAI amount (ether units)", default="0.01")
    ap.add_argument("--min-weth", help="min WETH out (ether units)", default="0")
    ap.add_argument("--min-pnk", help="min PNK out (ether units)", default="0")
    ap.add_argument("--prefund", action="store_true", help="Transfer sDAI to the executor before calling")
    args = ap.parse_args()

    if args.env:
        load_dotenv(args.env)

    rpc = os.getenv("RPC_URL") or os.getenv("GNOSIS_RPC_URL")
    priv = os.getenv("PRIVATE_KEY")
    v5_addr = os.getenv("FUTARCHY_ARB_EXECUTOR_V5") or os.getenv("EXECUTOR_V5_ADDRESS") or os.getenv("ARBITRAGE_EXECUTOR_ADDRESS")
    if not rpc or not priv or not v5_addr:
        raise SystemExit("Missing RPC_URL, PRIVATE_KEY, or FUTARCHY_ARB_EXECUTOR_V5/ARBITRAGE_EXECUTOR_ADDRESS in env")

    w3 = Web3(Web3.HTTPProvider(rpc))
    try:
        from web3.middleware import geth_poa_middleware
        w3.middleware_onion.inject(geth_poa_middleware, layer=0)
    except Exception:
        pass
    if not w3.is_connected():
        raise SystemExit("Failed to connect to RPC")

    acct = w3.eth.account.from_key(priv)

    amount_wei = w3.to_wei(Decimal(str(args.amount)), "ether")
    min_weth_wei = w3.to_wei(Decimal(str(args.min_weth)), "ether")
    min_pnk_wei = w3.to_wei(Decimal(str(args.min_pnk)), "ether")

    v5 = w3.eth.contract(address=w3.to_checksum_address(v5_addr), abi=ABI_BUY)

    # Pre-state: print sDAI/WETH/PNK balances for the contract
    SDAI = w3.to_checksum_address("0xaf204776c7245bF4147c2612BF6e5972Ee483701")
    WETH = w3.to_checksum_address("0x6A023CCd1ff6F2045C3309768eAd9E68F978f6e1")
    PNK  = w3.to_checksum_address("0x37b60f4E9A31A64cCc0024dce7D0fD07eAA0F7B3")
    erc = lambda a: w3.eth.contract(address=a, abi=ERC20_MIN_ABI)
    caddr = w3.to_checksum_address(v5_addr)
    sdai_before = erc(SDAI).functions.balanceOf(caddr).call()
    weth_before = erc(WETH).functions.balanceOf(caddr).call()
    pnk_before  = erc(PNK).functions.balanceOf(caddr).call()
    print(f"Pre: sDAI={w3.from_wei(sdai_before,'ether')} WETH={w3.from_wei(weth_before,'ether')} PNK={w3.from_wei(pnk_before,'ether')}")

    # Optionally prefund the executor with sDAI from the caller wallet
    if args.prefund and sdai_before < amount_wei:
        sdai = erc(SDAI)
        transfer_tx = sdai.functions.transfer(caddr, int(amount_wei)).build_transaction({
            "from": acct.address,
            "nonce": w3.eth.get_transaction_count(acct.address),
            "chainId": w3.eth.chain_id,
        })
        transfer_tx.update(eip1559(w3))
        try:
            transfer_tx["gas"] = int(w3.eth.estimate_gas(transfer_tx) * 1.2)
        except Exception:
            transfer_tx["gas"] = 120_000
        s = acct.sign_transaction(transfer_tx)
        rh = w3.eth.send_raw_transaction(getattr(s, "rawTransaction", None) or getattr(s, "raw_transaction", None))
        print(f"Prefund sDAI tx: {rh.hex()}")
        w3.eth.wait_for_transaction_receipt(rh)

    tx = v5.functions.buyPnkWithSdai(int(amount_wei), int(min_weth_wei), int(min_pnk_wei)).build_transaction({
        "from": acct.address,
        "nonce": w3.eth.get_transaction_count(acct.address),
        "chainId": w3.eth.chain_id,
        "gas": 1_200_000,
    })
    tx.update(eip1559(w3))
    signed = acct.sign_transaction(tx)
    raw = getattr(signed, "rawTransaction", None) or getattr(signed, "raw_transaction", None)
    h = w3.eth.send_raw_transaction(raw)
    print(f"Tx: {h.hex()}")
    rcpt = w3.eth.wait_for_transaction_receipt(h)
    print(f"Status: {rcpt.status}; Gas used: {rcpt.gasUsed}")

    sdai_after = erc(SDAI).functions.balanceOf(caddr).call()
    weth_after = erc(WETH).functions.balanceOf(caddr).call()
    pnk_after  = erc(PNK).functions.balanceOf(caddr).call()
    print(f"Post: sDAI={w3.from_wei(sdai_after,'ether')} WETH={w3.from_wei(weth_after,'ether')} PNK={w3.from_wei(pnk_after,'ether')}")


if __name__ == "__main__":
    main()
