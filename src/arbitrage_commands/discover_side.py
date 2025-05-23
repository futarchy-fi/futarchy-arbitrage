"""
discover_side.py
================
CLI helper that prints spot prices for:

    • Swapr YES pool  – env **SWAPR_POOL_YES_ADDRESS**
    • Swapr NO  pool  – env **SWAPR_POOL_NO_ADDRESS**
    • Balancer pool   – env **BALANCER_POOL_ADDRESS**

Usage
-----
    RPC_URL=<json-rpc> \
    SWAPR_POOL_YES_ADDRESS=0x… \
    SWAPR_POOL_NO_ADDRESS=0x…  \
    BALANCER_POOL_ADDRESS=0x…  \
    python -m src.arbitrage_commands.discover_side

The script exits with a non-zero status if any environment variable is missing.
"""

import os
import sys
from typing import Tuple

from web3 import Web3

from helpers.swapr_price    import get_pool_price as swapr_price
from helpers.balancer_price import get_pool_price as bal_price
from config.network import DEFAULT_RPC_URLS

# --------------------------------------------------------------------------- #
# helpers                                                                     #
# --------------------------------------------------------------------------- #


def make_web3() -> Web3:
    """Return a Web3 connected to the RPC in $RPC_URL or the primary fallback."""
    rpc_url = os.getenv("RPC_URL", DEFAULT_RPC_URLS[0])
    return Web3(Web3.HTTPProvider(rpc_url))


def fetch_swapr(pool: str, w3: Web3, base_token_index: int = 0) -> Tuple[str, str, str]:
    """Return 'base', 'quote', price string for an Algebra pool."""
    price, base, quote = swapr_price(w3, pool, base_token_index=base_token_index)
    return base, quote, str(price)


def fetch_balancer(pool: str, w3: Web3) -> Tuple[str, str, str]:
    """Return 'base', 'quote', price string for a Balancer V3 pool."""
    price, base, quote = bal_price(w3, pool)
    return base, quote, str(price)


def main() -> None:
    addr_yes = os.getenv("SWAPR_POOL_YES_ADDRESS")
    addr_no  = os.getenv("SWAPR_POOL_NO_ADDRESS")
    addr_bal = os.getenv("BALANCER_POOL_ADDRESS")

    if not all((addr_yes, addr_no, addr_bal)):
        print("Error: one or more pool address environment variables are unset.", file=sys.stderr)
        sys.exit(1)

    w3 = make_web3()

    yes_base, yes_quote, yes_price = fetch_swapr(addr_yes, w3, base_token_index=0)
    no_base,  no_quote,  no_price  = fetch_swapr(addr_no,  w3, base_token_index=1)
    bal_base, bal_quote, bal_price = fetch_balancer(addr_bal, w3)

    print(f"YES  pool: 1 {yes_base} = {yes_price} {yes_quote}")
    print(f"NO   pool: 1 {no_base}  = {no_price}  {no_quote}")
    print(f"BAL  pool: 1 {bal_base} = {bal_price} {bal_quote}")


# --------------------------------------------------------------------------- #
# entry-point                                                                 #
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    main()
