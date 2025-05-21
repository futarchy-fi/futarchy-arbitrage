"""
Helper for retrieving the spot price of an Algebra/Swapr pool.

Public API
----------
get_pool_price(w3, pool_address, *, base_token_index=0)
    Return (price, base_token_addr, quote_token_addr) where *price* is a
    Decimal giving the amount of *quote* per 1 *base*.
"""
from __future__ import annotations

import sys
import os
from decimal import Decimal
from typing import Tuple

# If this script is run directly, ensure the project root is in sys.path
# so that 'config' module can be found.
if __name__ == "__main__":
    # Get the absolute path of the directory containing this script (e.g., /path/to/project/helpers)
    _current_dir = os.path.dirname(os.path.abspath(__file__))
    # Get the project root directory (e.g., /path/to/project)
    _project_root = os.path.dirname(_current_dir)
    # Add project_root to the beginning of sys.path if it's not already there
    if _project_root not in sys.path:
        sys.path.insert(0, _project_root)

# Now that sys.path is configured, these imports should work
from web3 import Web3
from config.abis.swapr import ALGEBRA_POOL_ABI
from config.abis import ERC20_ABI

__all__ = ["get_pool_price"]

# --------------------------------------------------------------------------- #
# helpers                                                                     #
# --------------------------------------------------------------------------- #


def _decimals(w3: Web3, token_addr: str) -> int:
    return w3.eth.contract(address=token_addr, abi=ERC20_ABI).functions.decimals().call()


# --------------------------------------------------------------------------- #
# public                                                                      #
# --------------------------------------------------------------------------- #


def get_pool_price(
    w3: Web3,
    pool_address: str,
    *,
    base_token_index: int = 0,
) -> Tuple[Decimal, str, str]:
    """
    Spot price of *base* token (index ``base_token_index``) in terms of the
    quote token for any Algebra pool.
    """
    pool = w3.eth.contract(
        address=w3.to_checksum_address(pool_address), abi=ALGEBRA_POOL_ABI
    )

    sqrt_price_x96, *_ = pool.functions.globalState().call()

    # raw price = token1 / token0 with token amounts (not human units)
    ratio = (Decimal(sqrt_price_x96) / (1 << 96)) ** 2

    token0 = pool.functions.token0().call()
    token1 = pool.functions.token1().call()

    dec0 = _decimals(w3, token0)
    dec1 = _decimals(w3, token1)

    price_0_in_1 = ratio * Decimal(10 ** (dec0 - dec1))

    if base_token_index == 0:
        return price_0_in_1, token0, token1
    else:
        return Decimal(1) / price_0_in_1, token1, token0

# --------------------------------------------------------------------------- #
# CLI utility (mirrors balancer_price)                                        #
# --------------------------------------------------------------------------- #

if __name__ == "__main__":  # pragma: no cover
    import os
    import argparse

    parser = argparse.ArgumentParser(description="Get Swapr/Algebra pool price.")
    parser.add_argument("--pool_address", help="The address of the Algebra pool.")
    parser.add_argument("--base-token-index", type=int, default=0, help="Index of the base token (0 or 1). Default: 0")

    args = parser.parse_args()

    rpc_url = os.getenv("RPC_URL")
    if rpc_url is None:
        raise RuntimeError("Must set RPC_URL environment variable")
    print("rpc_url: ", rpc_url)

    w3_cli = Web3(Web3.HTTPProvider(rpc_url))

    pool_addr_cli = args.pool_address
    idx = args.base_token_index

    price, base, quote = get_pool_price(w3_cli, pool_addr_cli, base_token_index=idx)
    print(f"1 {base} = {price} {quote}")
