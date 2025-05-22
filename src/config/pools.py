"""
Pool configurations for the Futarchy Trading Bot.

This module is currently in EXPERIMENTAL status.
Contains pool configurations, settings, and constants.
"""

from typing import Dict, Any
from .contracts import CONTRACT_ADDRESSES

# Pool configurations with token slot information
POOL_CONFIG_YES: Dict[str, Any] = {
    "address": "0x9a14d28909f42823ee29847f87a15fb3b6e8aed3",
    "tokenCompanySlot": 0,  # GNO YES is token0
    "fee": 3000,  # 0.3% fee tier
    "description": "GNO YES / sDAI YES pool"
}

POOL_CONFIG_NO: Dict[str, Any] = {
    "address": "0x6E33153115Ab58dab0e0F1E3a2ccda6e67FA5cD7",
    "tokenCompanySlot": 1,  # GNO NO is token1
    "fee": 3000,  # 0.3% fee tier
    "description": "GNO NO / sDAI NO pool"
}

# Balancer pool configuration
BALANCER_CONFIG: Dict[str, Any] = {
    "vault_address": "0xBA12222222228d8Ba445958a75a0704d566BF2C8",
    "pool_address": "0xd1d7fa8871d84d0e77020fc28b7cd5718c446522",
    "pool_id": "0xd1d7fa8871d84d0e77020fc28b7cd5718c4465220000000000000000000001d7",
    "fee": 0.003,  # 0.3% fee
    "description": "Balancer pool"
}

# Uniswap V3 style pool constants
MIN_SQRT_RATIO: int = 4295128739
MAX_SQRT_RATIO: int = 1461446703485210103287273052203988822378723970342

# Pool price impact thresholds
PRICE_IMPACT_THRESHOLDS: Dict[str, float] = {
    "warning": 0.01,    # 1% price impact triggers warning
    "critical": 0.05,   # 5% price impact triggers critical warning
    "max": 0.10        # 10% maximum allowed price impact
}

# UniswapV3 specific configuration
UNISWAP_V3_CONFIG = {
    "sqrt_price_limit_x96": 4295128740,  # Default sqrt price limit
    "zero_for_one": True,  # Default direction for NO pool swaps
    "recipient_address": "0x33A0b5d7DA5314594D2C163D448030b9F1cADcb2"  # Default recipient
}

def get_pool_config(pool_address: str) -> Dict[str, Any]:
    """
    Get configuration for a specific pool address.
    
    Args:
        pool_address: The pool address to get configuration for
        
    Returns:
        Dict containing pool configuration or None if not found
    """
    pool_address = pool_address.lower()
    
    if pool_address == POOL_CONFIG_YES["address"].lower():
        return POOL_CONFIG_YES
    elif pool_address == POOL_CONFIG_NO["address"].lower():
        return POOL_CONFIG_NO
    elif pool_address == BALANCER_CONFIG["pool_address"].lower():
        return BALANCER_CONFIG
    
    return None

def is_valid_sqrt_price(sqrt_price: int) -> bool:
    """
    Check if a sqrt price is within valid bounds.
    
    Args:
        sqrt_price: The sqrt price to check
        
    Returns:
        bool: True if price is valid, False otherwise
    """
    return MIN_SQRT_RATIO <= sqrt_price <= MAX_SQRT_RATIO 