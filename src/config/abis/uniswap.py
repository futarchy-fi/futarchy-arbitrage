"""
Uniswap V3 interface ABIs.

This module is currently in EXPERIMENTAL status.
Contains ABIs for Uniswap V3 Pool and Router contracts.
"""

UNISWAP_V3_POOL_ABI = [
    {"inputs": [], "name": "token0", "outputs": [{"internalType": "address", "name": "", "type": "address"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "token1", "outputs": [{"internalType": "address", "name": "", "type": "address"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "slot0", "outputs": [{"internalType": "uint160", "name": "sqrtPriceX96", "type": "uint160"}, {"internalType": "int24", "name": "tick", "type": "int24"}, {"internalType": "uint16", "name": "observationIndex", "type": "uint16"}, {"internalType": "uint16", "name": "observationCardinality", "type": "uint16"}, {"internalType": "uint16", "name": "observationCardinalityNext", "type": "uint16"}, {"internalType": "uint8", "name": "feeProtocol", "type": "uint8"}, {"internalType": "bool", "name": "unlocked", "type": "bool"}], "stateMutability": "view", "type": "function"}
]

UNISWAP_V3_PASSTHROUGH_ROUTER_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "pool", "type": "address"},
            {"internalType": "address", "name": "recipient", "type": "address"},
            {"internalType": "bool", "name": "zeroForOne", "type": "bool"},
            {"internalType": "int256", "name": "amountSpecified", "type": "int256"},
            {"internalType": "uint160", "name": "sqrtPriceLimitX96", "type": "uint160"},
            {"internalType": "bytes", "name": "data", "type": "bytes"}
        ],
        "name": "swap",
        "outputs": [
            {"internalType": "int256", "name": "amount0", "type": "int256"},
            {"internalType": "int256", "name": "amount1", "type": "int256"}
        ],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "owner",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [{"internalType": "address", "name": "pool", "type": "address"}],
        "name": "authorizePool",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    }
] 