"""
Helper for retrieving the spot price of a Balancer V3 pool.

Public API
----------
get_pool_price(w3, pool_address, *, base_token_index=0, vault_addr=None)
    Return (price, base_token_addr, quote_token_addr) where *price* is a
    Decimal giving the amount of *quote* per 1 *base*.

The layout mirrors `balancer_swap.py`: a tiny ENV-aware helper and no
explicit error handling.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Tuple

from web3 import Web3

from config.abis import BALANCER_VAULT_V3_ABI, ERC20_ABI

__all__ = ["get_pool_price"]

# --------------------------------------------------------------------------- #
# helpers                                                                     #
# --------------------------------------------------------------------------- #

def _get_vault(w3: Web3, vault_addr: str | None = None):
    """Instantiate the Balancer Vault / VaultExtension contract."""
    addr = (
        vault_addr
        or "0xbA1333333333a1BA1108E8412f11850A5C319bA9"  # fallback – override in env if needed
    )
    return w3.eth.contract(address=w3.to_checksum_address(addr), abi=BALANCER_VAULT_V3_ABI)


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
    vault_addr: str | None = None,
) -> Tuple[Decimal, str, str]:
    """
    Spot price of *base* token (index ``base_token_index``) in terms of the
    quote token for any Balancer V3 pool.
    """
    vault = _get_vault(w3, vault_addr)

    # getPoolTokenInfo(address pool) returns:
    #   (address[] tokens, TokenInfo[] tokenInfo, uint256[] balancesRaw, uint256[] lastBalancesLiveScaled18)
    tokens, _, balances_raw, _ = vault.functions.getPoolTokenInfo(
        w3.to_checksum_address(pool_address)
    ).call()

    i = base_token_index
    j = 1 if i == 0 else 0

    bal_i = Decimal(balances_raw[i]) / (10 ** _decimals(w3, tokens[i]))
    bal_j = Decimal(balances_raw[j]) / (10 ** _decimals(w3, tokens[j]))

    return bal_j / bal_i, tokens[i], tokens[j]

# --------------------------------------------------------------------------- #
# CLI utility                                                                 #
# --------------------------------------------------------------------------- #

if __name__ == "__main__":  # pragma: no cover
    """
    Quick helper:

        python -m helpers.balancer_price

    Prints the spot price for the pool address in the ``BALANCER_POOL_ADDRESS``
    environment variable using the RPC defined in ``GNOSIS_RPC_URL`` (or
    fallback ``RPC_URL``).
    """
    import os
    # Web3 is already imported at the top level

    rpc_url = os.getenv("GNOSIS_RPC_URL") or os.getenv("RPC_URL")
    if rpc_url is None:
        raise RuntimeError("Must set GNOSIS_RPC_URL or RPC_URL environment variable")
    print("rpc_url: ", rpc_url)

    w3_cli = Web3(Web3.HTTPProvider(rpc_url))

    pool_addr_cli = os.getenv("BALANCER_POOL_ADDRESS")
    if pool_addr_cli is None:
        raise RuntimeError("Must set BALANCER_POOL_ADDRESS env var")
    
    # vault_addr_cli = os.getenv("BALANCER_VAULT_ADDRESS_CLI") # Example if CLI needs to override vault
    # price, base, quote = get_pool_price(w3_cli, pool_addr_cli, vault_addr=vault_addr_cli)
    price, base, quote = get_pool_price(w3_cli, pool_addr_cli)
    print(f"1 {base} = {price} {quote}")
