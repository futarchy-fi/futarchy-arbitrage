"""
Network configuration for the Futarchy Trading Bot.

This module is currently in EXPERIMENTAL status.
Contains RPC URLs and API endpoints for various services.
"""

from typing import List

# Default RPC URLs (fallbacks if not set in environment)
DEFAULT_RPC_URLS: List[str] = [
    "https://gnosis-mainnet.public.blastapi.io",  # Primary
    "https://rpc.gnosischain.com",                # Backup 1
    "https://rpc.ankr.com/gnosis"                 # Backup 2
]

# API Endpoints
COWSWAP_API_URL: str = "https://api.cow.fi/xdai"  # Gnosis Chain (Production)

# Chain configuration
CHAIN_ID: int = 100  # Gnosis Chain
CHAIN_NAME: str = "Gnosis Chain"
BLOCK_TIME: int = 5  # Average block time in seconds
GAS_LIMIT_BUFFER: float = 1.1  # 10% buffer for gas limit estimates

# Network timeouts and retries
RPC_TIMEOUT: int = 30  # seconds
MAX_RETRIES: int = 3
RETRY_DELAY: int = 1  # seconds between retries 