#!/usr/bin/env python3
"""
A minimal price‑watcher that *executes* trades when the Balancer price
moves outside a configurable band around the 'ideal' synthetic price
derived from the two Swapr pools.

Usage
-----
    RPC_URL=<rpc> \
    PRIVATE_KEY=<hex> \
    SWAPR_POOL_YES_ADDRESS=0x… \
    SWAPR_POOL_PRED_YES_ADDRESS=0x… \
    SWAPR_POOL_NO_ADDRESS=0x… \
    BALANCER_POOL_ADDRESS=0x… \
    python -m src.arbitrage_commands.simple_bot \
        --amount  500          \ # sDAI you are willing to deploy
        --interval 300         \ # seconds between checks
        --tolerance 0.3          # % deviation that triggers a trade
"""
from __future__ import annotations

import argparse
import os
import time
from decimal import Decimal

from web3 import Web3
from eth_account import Account

from helpers.swapr_price import get_pool_price as swapr_price
from helpers.balancer_price import get_pool_price as bal_price

# ► stripped‑down on‑chain trade helpers (shown in §3)
from arbitrage_commands.buy_cond_onchain import buy_gno_yes_and_no_amounts_with_sdai
from arbitrage_commands.sell_cond_onchain import sell_gno_yes_and_no_amounts_to_sdai


def make_web3() -> Web3:
    rpc = os.getenv("RPC_URL")
    if not rpc:
        raise SystemExit("❌  RPC_URL env‑var missing")
    return Web3(Web3.HTTPProvider(rpc))


# --------------------------------------------------------------------------- #
# Price fetchers (wrap your existing helpers)                                 #
# --------------------------------------------------------------------------- #
def swapr_yes_price(w3: Web3) -> Decimal:
    pool = os.environ["SWAPR_POOL_YES_ADDRESS"]
    price, *_ = swapr_price(w3, pool, base_token_index=0)
    return Decimal(price)


def swapr_pred_yes_price(w3: Web3) -> Decimal:
    pool = os.environ["SWAPR_POOL_PRED_YES_ADDRESS"]
    price, *_ = swapr_price(w3, pool, base_token_index=0)
    return Decimal(price)


def swapr_no_price(w3: Web3) -> Decimal:
    pool = os.environ["SWAPR_POOL_NO_ADDRESS"]
    price, *_ = swapr_price(w3, pool, base_token_index=1)
    return Decimal(price)


def balancer_price(w3: Web3) -> Decimal:
    pool = os.environ["BALANCER_POOL_ADDRESS"]
    price, *_ = bal_price(w3, pool)
    return Decimal(price)


# --------------------------------------------------------------------------- #
# Main loop                                                                   #
# --------------------------------------------------------------------------- #
def run_loop(amount: Decimal, tolerance_pct: Decimal, interval: int) -> None:
    w3 = make_web3()

    while True:
        try:
            yes_p   = swapr_yes_price(w3)
            pred_p  = swapr_pred_yes_price(w3)
            no_p    = swapr_no_price(w3)
            bal_p   = balancer_price(w3)

            ideal   = pred_p * yes_p + (Decimal("1") - pred_p) * no_p
            diff_pct = (bal_p - ideal) / ideal * 100

            print(f"[{time.strftime('%Y‑%m‑%d %H:%M:%S')}] "
                  f"YES={yes_p:.6f}  NO={no_p:.6f}  PRED={pred_p:.4f}  "
                  f"BAL={bal_p:.6f}  IDEAL={ideal:.6f}  Δ%={diff_pct:+.2f}")

            # Decision logic ------------------------------------------------
            if yes_p < bal_p and no_p < bal_p:
                print(f"📈  Balancer overpriced by {diff_pct:.2f}% → BUY conditional GNO")
                tx_hashes = buy_gno_yes_and_no_amounts_with_sdai(float(amount))
                print(f"✅  Sent {len(tx_hashes)} txs – first hash: {tx_hashes[0]}")
            elif yes_p > bal_p and no_p > bal_p:
                print(f"📉  Balancer under‑priced by {diff_pct:.2f}% → SELL conditional GNO")
                tx_hashes = sell_gno_yes_and_no_amounts_to_sdai(float(amount))
                print(f"✅  Sent {len(tx_hashes)} txs – first hash: {tx_hashes[0]}")
            # else: within band – do nothing

        except KeyboardInterrupt:
            print("\n↩︎  Interrupted – exiting.")
            break
        except Exception as exc:
            print(f"⚠️  {type(exc).__name__}: {exc}")

        time.sleep(interval)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--amount",    type=Decimal, required=True, help="sDAI budget per trade")
    ap.add_argument("--interval",  type=int,     default=300,   help="Seconds between checks")
    ap.add_argument("--tolerance", type=Decimal, default=Decimal("0.3"),
                    help="Trigger threshold in % (e.g. 0.3 = ±0.3%)")
    return ap.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_loop(args.amount, args.tolerance, args.interval)
