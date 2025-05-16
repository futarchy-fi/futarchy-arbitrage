"""
Balancer interface ABIs.

This module is currently in EXPERIMENTAL status.
Contains ABIs for Balancer Vault, Pool, and BatchRouter contracts.
"""

BALANCER_VAULT_ABI = [
    {"inputs":[{"components":[{"internalType":"bytes32","name":"poolId","type":"bytes32"},{"internalType":"address","name":"assetIn","type":"address"},{"internalType":"address","name":"assetOut","type":"address"},{"internalType":"uint256","name":"amount","type":"uint256"},{"internalType":"bytes","name":"userData","type":"bytes"}],"internalType":"struct IVault.SingleSwap","name":"singleSwap","type":"tuple"},{"components":[{"internalType":"address","name":"sender","type":"address"},{"internalType":"bool","name":"fromInternalBalance","type":"bool"},{"internalType":"address payable","name":"recipient","type":"address"},{"internalType":"bool","name":"toInternalBalance","type":"bool"}],"internalType":"struct IVault.FundManagement","name":"funds","type":"tuple"},{"internalType":"uint256","name":"limit","type":"uint256"},{"internalType":"uint256","name":"deadline","type":"uint256"}],"name":"swap","outputs":[{"internalType":"uint256","name":"amountCalculated","type":"uint256"}],"stateMutability":"payable","type":"function"},
    {"inputs":[{"internalType":"bytes32","name":"poolId","type":"bytes32"}],"name":"getPoolTokens","outputs":[{"internalType":"address[]","name":"tokens","type":"address[]"},{"internalType":"uint256[]","name":"balances","type":"uint256[]"},{"internalType":"uint256","name":"lastChangeBlock","type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"internalType":"bytes32","name":"poolId","type":"bytes32"},{"internalType":"address","name":"tokenIn","type":"address"},{"internalType":"address","name":"tokenOut","type":"address"},{"internalType":"uint256","name":"amount","type":"uint256"}],"name":"querySwap","outputs":[{"internalType":"uint256","name":"","type":"uint256"}],"stateMutability":"nonpayable","type":"function"}
]

BALANCER_POOL_ABI = [
    {"inputs":[],"name":"getPoolId","outputs":[{"internalType":"bytes32","name":"","type":"bytes32"}],"stateMutability":"view","type":"function"}
]

BALANCER_BATCH_ROUTER_ABI = [
    {
        "inputs": [
            {
                "components": [
                    {
                        "internalType": "contract IERC20",
                        "name": "tokenIn",
                        "type": "address"
                    },
                    {
                        "components": [
                            {
                                "internalType": "address",
                                "name": "pool",
                                "type": "address"
                            },
                            {
                                "internalType": "contract IERC20",
                                "name": "tokenOut",
                                "type": "address"
                            },
                            {
                                "internalType": "bool",
                                "name": "isBuffer",
                                "type": "bool"
                            }
                        ],
                        "internalType": "struct IBatchRouter.SwapPathStep[]",
                        "name": "steps",
                        "type": "tuple[]"
                    },
                    {
                        "internalType": "uint256",
                        "name": "exactAmountIn",
                        "type": "uint256"
                    },
                    {
                        "internalType": "uint256",
                        "name": "minAmountOut",
                        "type": "uint256"
                    }
                ],
                "internalType": "struct IBatchRouter.SwapPathExactAmountIn[]",
                "name": "paths",
                "type": "tuple[]"
            },
            {
                "internalType": "uint256",
                "name": "deadline",
                "type": "uint256"
            },
            {
                "internalType": "bool",
                "name": "wethIsEth",
                "type": "bool"
            },
            {
                "internalType": "bytes",
                "name": "userData",
                "type": "bytes"
            }
        ],
        "name": "swapExactIn",
        "outputs": [
            {
                "internalType": "uint256[]",
                "name": "pathAmountsOut",
                "type": "uint256[]"
            },
            {
                "internalType": "address[]",
                "name": "tokensOut",
                "type": "address[]"
            },
            {
                "internalType": "uint256[]",
                "name": "amountsOut",
                "type": "uint256[]"
            }
        ],
        "stateMutability": "payable",
        "type": "function"
    },
    {
        "inputs": [
            {
                "components": [
                    {
                        "internalType": "contract IERC20",
                        "name": "tokenIn",
                        "type": "address"
                    },
                    {
                        "components": [
                            {
                                "internalType": "address",
                                "name": "pool",
                                "type": "address"
                            },
                            {
                                "internalType": "contract IERC20",
                                "name": "tokenOut",
                                "type": "address"
                            },
                            {
                                "internalType": "bool",
                                "name": "isBuffer",
                                "type": "bool"
                            }
                        ],
                        "internalType": "struct IBatchRouter.SwapPathStep[]",
                        "name": "steps",
                        "type": "tuple[]"
                    },
                    {
                        "internalType": "uint256",
                        "name": "exactAmountIn",
                        "type": "uint256"
                    },
                    {
                        "internalType": "uint256",
                        "name": "minAmountOut",
                        "type": "uint256"
                    }
                ],
                "internalType": "struct IBatchRouter.SwapPathExactAmountIn[]",
                "name": "paths",
                "type": "tuple[]"
            },
            {
                "internalType": "address",
                "name": "sender",
                "type": "address"
            },
            {
                "internalType": "bytes",
                "name": "userData",
                "type": "bytes"
            }
        ],
        "name": "querySwapExactIn",
        "outputs": [
            {
                "internalType": "uint256[]",
                "name": "pathAmountsOut",
                "type": "uint256[]"
            },
            {
                "internalType": "address[]",
                "name": "tokensOut",
                "type": "address[]"
            },
            {
                "internalType": "uint256[]",
                "name": "amountsOut",
                "type": "uint256[]"
            }
        ],
        "stateMutability": "nonpayable",
        "type": "function"
    }
] 