"""
Contract ABI package for the Futarchy Trading Bot.

This package is currently in EXPERIMENTAL status.
Contains all contract ABIs organized by protocol/type.
"""

from .erc20 import ERC20_ABI
from .uniswap import (
    UNISWAP_V3_POOL_ABI,
    UNISWAP_V3_PASSTHROUGH_ROUTER_ABI
)
from .sushiswap import (
    SUSHISWAP_V3_ROUTER_ABI,
    SUSHISWAP_V3_NFPM_ABI
)
from .balancer import (
    BALANCER_VAULT_ABI,
    BALANCER_VAULT_V3_ABI,
    BALANCER_POOL_ABI,
    BALANCER_BATCH_ROUTER_ABI
)
from .futarchy import FUTARCHY_ROUTER_ABI
from .misc import (
    SDAI_RATE_PROVIDER_ABI,
    WXDAI_ABI,
    SDAI_DEPOSIT_ABI,
    WAGNO_ABI,
    PERMIT2_ABI
)
from .swapr import (
    SWAPR_ROUTER_ABI,
)

__all__ = [
    # ERC20
    'ERC20_ABI',
    
    # Uniswap
    'UNISWAP_V3_POOL_ABI',
    'UNISWAP_V3_PASSTHROUGH_ROUTER_ABI',
    
    # SushiSwap
    'SUSHISWAP_V3_ROUTER_ABI',
    'SUSHISWAP_V3_NFPM_ABI',
    
    # Balancer
    'BALANCER_VAULT_ABI',
    'BALANCER_VAULT_V3_ABI',
    'BALANCER_POOL_ABI',
    'BALANCER_BATCH_ROUTER_ABI',
    
    # Futarchy
    'FUTARCHY_ROUTER_ABI',
    
    # Misc
    'SDAI_RATE_PROVIDER_ABI',
    'WXDAI_ABI',
    'SDAI_DEPOSIT_ABI',
    'WAGNO_ABI',
    'PERMIT2_ABI',
    
    # Swapr/Algebra
    'SWAPR_ROUTER_ABI',
] 