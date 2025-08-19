"""
Helper for retrieving the spot price of an Algebra/Swapr pool.

Public API
----------
get_pool_price(w3, pool_address, *, base_token_index=None)
    Return (price, base_token_addr, quote_token_addr) where *price* is a
    Decimal giving the amount of *quote* per 1 *base*.
    
    If base_token_index is not provided, it auto-detects the base token:
    - If a token name contains "sdai" (case insensitive), the OTHER token is base
    - This ensures prices are denominated in sDAI (sDAI as quote token)
    - If neither token contains "sdai", defaults to token0 as base
"""
from __future__ import annotations

import sys
import os
from decimal import Decimal
from typing import Tuple, Optional

# If this script is run directly, ensure the project root is in sys.path
# so that 'config' module can be found.
if __name__ == "__main__":
    # This block adjusts sys.path when the script is run directly,
    # to allow 'from src.xxx' imports to work.
    # It adds the main project root directory (parent of 'src') to sys.path.
    import os  # os is used by os.path.abspath further down if not for Path
    import sys # sys is used for sys.path
    from pathlib import Path # Using pathlib for robust path manipulation
    
    # Path(__file__).resolve() is .../PROJECT_ROOT/src/helpers/swapr_price.py
    # .parents[2] navigates up two levels to get .../PROJECT_ROOT/
    _project_main_root = str(Path(__file__).resolve().parents[2])
    
    if _project_main_root not in sys.path:
        sys.path.insert(0, _project_main_root)

# Now that sys.path is configured, these imports should work
from web3 import Web3
from src.config.abis.swapr import ALGEBRA_POOL_ABI
from src.config.abis import ERC20_ABI

__all__ = ["get_pool_price"]

# --------------------------------------------------------------------------- #
# helpers                                                                     #
# --------------------------------------------------------------------------- #


def _decimals(w3: Web3, token_addr: str) -> int:
    return w3.eth.contract(address=token_addr, abi=ERC20_ABI).functions.decimals().call()


def _get_token_name(w3: Web3, token_addr: str) -> str:
    """Get the name of a token, returning empty string if name() is not available."""
    try:
        # Ensure address is checksummed
        checksum_addr = w3.to_checksum_address(token_addr)
        token_contract = w3.eth.contract(address=checksum_addr, abi=ERC20_ABI)
        return token_contract.functions.name().call()
    except Exception:
        return ""


# --------------------------------------------------------------------------- #
# public                                                                      #
# --------------------------------------------------------------------------- #


def get_pool_price(
    w3: Web3,
    pool_address: str,
    *,
    base_token_index: Optional[int] = None,
) -> Tuple[Decimal, str, str]:
    """
    Spot price of *base* token (index ``base_token_index``) in terms of the
    quote token for any Algebra pool.
    
    If base_token_index is not provided, it will be auto-detected based on token names:
    1. If one token has name exactly "sdai" (case insensitive), the OTHER token becomes base
    2. Otherwise, if one token name contains "sdai", the OTHER token becomes base
    3. This ensures sDAI is the quote token (price denominated in sDAI)
    4. If neither token contains "sdai", defaults to token0 as base
    """
    pool = w3.eth.contract(
        address=w3.to_checksum_address(pool_address), abi=ALGEBRA_POOL_ABI
    )

    sqrt_price_x96, *_ = pool.functions.globalState().call()

    # raw price = token1 / token0 with token amounts (not human units)
    ratio = (Decimal(sqrt_price_x96) / (1 << 96)) ** 2

    token0 = pool.functions.token0().call()
    token1 = pool.functions.token1().call()

    # Auto-detect base token if not specified
    if base_token_index is None:
        name0 = _get_token_name(w3, token0).lower()
        name1 = _get_token_name(w3, token1).lower()
        
        # sDAI should be the quote token, so the OTHER token is base
        # Check for exact match first
        if name0 == "savings xdai":
            base_token_index = 1  # token1 is base (GNO)
        elif name1 == "savings xdai":
            base_token_index = 0  # token0 is base (GNO)
        # Then check for partial match
        elif "sdai" in name0:
            base_token_index = 1  # token1 is base (GNO)
        elif "sdai" in name1:
            base_token_index = 0  # token0 is base (GNO)
        else:
            # Default to token0 as base
            base_token_index = 0
        print(f"Auto-detected base token index: {base_token_index} (pool: {pool_address}, token0: {name0}, token1: {name1})", file=sys.stderr)

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
    parser.add_argument("--base_token_index", type=int, default=None, help="Index of the base token (0 or 1). If not provided, auto-detects based on 'sdai' in token name.")

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
