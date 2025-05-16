"""
Constants for the Futarchy Trading Bot.

This module is deprecated and will be removed in a future version.
Please use the new configuration modules in config instead.
"""

from config import (
    # Network
    DEFAULT_RPC_URLS,
    COWSWAP_API_URL,
    
    # Contracts
    CONTRACT_ADDRESSES,
    CONTRACT_WARNINGS,
    is_contract_safe,
    get_contract_warning,
    
    # Pools
    POOL_CONFIG_YES,
    POOL_CONFIG_NO,
    BALANCER_CONFIG,
    MIN_SQRT_RATIO,
    MAX_SQRT_RATIO,
    UNISWAP_V3_CONFIG,
    
    # Tokens
    TOKEN_CONFIG,
    DEFAULT_SWAP_CONFIG,
    DEFAULT_PERMIT_CONFIG,
    get_token_info,
    get_token_decimals,
    format_token_amount,
    get_base_token
)

from config.abis import (
    # ERC20
    ERC20_ABI,
    
    # Uniswap
    UNISWAP_V3_POOL_ABI,
    UNISWAP_V3_PASSTHROUGH_ROUTER_ABI,
    
    # SushiSwap
    SUSHISWAP_V3_ROUTER_ABI,
    SUSHISWAP_V3_NFPM_ABI,
    
    # Balancer
    BALANCER_VAULT_ABI,
    BALANCER_POOL_ABI,
    BALANCER_BATCH_ROUTER_ABI,
    
    # Futarchy
    FUTARCHY_ROUTER_ABI,
    
    # Misc
    SDAI_RATE_PROVIDER_ABI,
    WXDAI_ABI,
    SDAI_DEPOSIT_ABI,
    WAGNO_ABI,
    PERMIT2_ABI
)

# Re-export everything for backward compatibility
__all__ = [
    # Network
    'DEFAULT_RPC_URLS',
    'COWSWAP_API_URL',
    
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
    
    # ABIs
    'ERC20_ABI',
    'UNISWAP_V3_POOL_ABI',
    'UNISWAP_V3_PASSTHROUGH_ROUTER_ABI',
    'SUSHISWAP_V3_ROUTER_ABI',
    'SUSHISWAP_V3_NFPM_ABI',
    'BALANCER_VAULT_ABI',
    'BALANCER_POOL_ABI',
    'BALANCER_BATCH_ROUTER_ABI',
    'FUTARCHY_ROUTER_ABI',
    'SDAI_RATE_PROVIDER_ABI',
    'WXDAI_ABI',
    'SDAI_DEPOSIT_ABI',
    'WAGNO_ABI',
    'PERMIT2_ABI',

    # Swapr/Algebra
    'SWAPR_ROUTER_ABI',
    'ALGEBRA_POOL_ABI'
]