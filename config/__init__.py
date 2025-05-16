"""
Configuration package for the Futarchy Trading Bot.

This module is currently in EXPERIMENTAL status.
Please use with caution as functionality may change.
"""

from config.network import (
    DEFAULT_RPC_URLS,
    COWSWAP_API_URL,
    CHAIN_ID
)

from config.contracts import (
    CONTRACT_ADDRESSES,
    CONTRACT_WARNINGS,
    is_contract_safe,
    get_contract_warning
)

from config.pools import (
    POOL_CONFIG_YES,
    POOL_CONFIG_NO,
    BALANCER_CONFIG,
    MIN_SQRT_RATIO,
    MAX_SQRT_RATIO,
    UNISWAP_V3_CONFIG
)

from config.tokens import (
    TOKEN_CONFIG,
    DEFAULT_SWAP_CONFIG,
    DEFAULT_PERMIT_CONFIG,
    get_token_info,
    get_token_decimals,
    format_token_amount,
    get_base_token
)

# --- Add ABI imports ---
from config.abis import (
    ERC20_ABI
)
# --- End ABI imports ---

__all__ = [
    # Network
    'DEFAULT_RPC_URLS',
    'COWSWAP_API_URL',
    'CHAIN_ID',
    
    # Contracts
    'CONTRACT_ADDRESSES',
    'CONTRACT_WARNINGS',
    'is_contract_safe',
    'get_contract_warning',
    
    # Pools
    'POOL_CONFIG_YES',
    'POOL_CONFIG_NO',
    'BALANCER_CONFIG',
    'MIN_SQRT_RATIO',
    'MAX_SQRT_RATIO',
    'UNISWAP_V3_CONFIG',
    
    # Tokens
    'TOKEN_CONFIG',
    'DEFAULT_SWAP_CONFIG',
    'DEFAULT_PERMIT_CONFIG',
    'get_token_info',
    'get_token_decimals',
    'format_token_amount',
    'get_base_token',

    # --- Add ABIs to export ---
    'ERC20_ABI'
    # --- End ABIs to export ---
]
