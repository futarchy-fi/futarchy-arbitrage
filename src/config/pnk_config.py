"""Configuration for PNK token price monitoring and arbitrage."""

import os
from typing import Dict, Any

# Pool addresses
PNK_WETH_POOL = "0x2613Cb099C12CECb1bd290Fd0eF6833949374165"
WETH_WXDAI_POOL = "0x1865d5445010e0baf8be2eb410d3eae4a68683c2"

# Contract addresses
SDAI_CONTRACT = "0x89C80A4540A00b5270347E02e2E144c71da2EceD"

def get_pnk_config() -> Dict[str, Any]:
    """Get PNK configuration from environment variables."""
    return {
        # Token addresses
        "PNK_ADDRESS": os.getenv("PNK_TOKEN_ADDRESS", ""),
        "WETH_ADDRESS": os.getenv("WETH_ADDRESS", ""),
        "WXDAI_ADDRESS": os.getenv("WXDAI_ADDRESS", ""),
        
        # Pool addresses
        "PNK_WETH_POOL": PNK_WETH_POOL,
        "WETH_WXDAI_POOL": WETH_WXDAI_POOL,
        
        # Contract addresses
        "SDAI_CONTRACT": SDAI_CONTRACT,
        
        # Network configuration
        "RPC_URL": os.getenv("RPC_URL", "https://rpc.gnosischain.com"),
        
        # Pool configuration
        "pools": {
            "pnk_weth": {
                "address": PNK_WETH_POOL,
                "decimals0": 18,
                "decimals1": 18,
                "fee": 0.003  # 0.3%
            },
            "weth_wxdai": {
                "address": WETH_WXDAI_POOL,
                "decimals0": 18,
                "decimals1": 18,
                "fee": 0.003  # 0.3%
            }
        },
        
        # Token configuration
        "tokens": {
            "PNK": {
                "decimals": 18,
                "symbol": "PNK"
            },
            "WETH": {
                "decimals": 18,
                "symbol": "WETH"
            },
            "WXDAI": {
                "decimals": 18,
                "symbol": "WXDAI"
            },
            "sDAI": {
                "decimals": 18,
                "symbol": "sDAI",
                "address": SDAI_CONTRACT
            }
        }
    }

# ABI for Uniswap V2 pool methods
UNISWAP_V2_POOL_ABI = [
    {
        "constant": True,
        "inputs": [],
        "name": "getReserves",
        "outputs": [
            {"name": "reserve0", "type": "uint112"},
            {"name": "reserve1", "type": "uint112"},
            {"name": "blockTimestampLast", "type": "uint32"}
        ],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "token0",
        "outputs": [{"name": "", "type": "address"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "token1",
        "outputs": [{"name": "", "type": "address"}],
        "type": "function"
    }
]

# ABI for sDAI contract methods
SDAI_ABI = [
    {
        "inputs": [{"name": "shares", "type": "uint256"}],
        "name": "convertToAssets",
        "outputs": [{"name": "assets", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [{"name": "shares", "type": "uint256"}],
        "name": "previewRedeem",
        "outputs": [{"name": "assets", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    }
]