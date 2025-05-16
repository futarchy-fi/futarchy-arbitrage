"""
Miscellaneous interface ABIs.

This module is currently in EXPERIMENTAL status.
Contains ABIs for various utility contracts like SDAI Rate Provider, WXDAI, and SDAI Deposit.
"""

SDAI_RATE_PROVIDER_ABI = [
    {"inputs": [], "name": "getRate", "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"}
]

WXDAI_ABI = [
    {"constant": False, "inputs": [], "name": "deposit", "outputs": [], "payable": True, "stateMutability": "payable", "type": "function"},
    {"constant": True, "inputs": [{"name": "", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "payable": False, "stateMutability": "view", "type": "function"},
    {"constant": False, "inputs": [{"name": "guy", "type": "address"}, {"name": "wad", "type": "uint256"}], "name": "approve", "outputs": [{"name": "", "type": "bool"}], "payable": False, "stateMutability": "nonpayable", "type": "function"}
]

SDAI_DEPOSIT_ABI = [
    {"inputs":[{"internalType":"uint256","name":"assets","type":"uint256"},{"internalType":"address","name":"receiver","type":"address"}],"name":"deposit","outputs":[{"internalType":"uint256","name":"","type":"uint256"}],"stateMutability":"nonpayable","type":"function"}
]

WAGNO_ABI = [
    {"inputs":[{"name":"assets","type":"uint256"},{"name":"receiver","type":"address"}],"name":"deposit","outputs":[{"name":"","type":"uint256"}],"stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"name":"owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"name":"shares","type":"uint256"},{"name":"receiver","type":"address"},{"name":"owner","type":"address"}],"name":"redeem","outputs":[{"name":"","type":"uint256"}],"stateMutability":"nonpayable","type":"function"}
]

PERMIT2_ABI = [
    {
        "inputs": [
            {"name": "owner", "type": "address"},
            {
                "components": [
                    {
                        "components": [
                            {"name": "token", "type": "address"},
                            {"name": "amount", "type": "uint160"},
                            {"name": "expiration", "type": "uint48"},
                            {"name": "nonce", "type": "uint48"}
                        ],
                        "name": "details",
                        "type": "tuple"
                    },
                    {"name": "spender", "type": "address"},
                    {"name": "sigDeadline", "type": "uint256"}
                ],
                "name": "permitSingle",
                "type": "tuple"
            },
            {"name": "signature", "type": "bytes"}
        ],
        "name": "permit",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [
            {"name": "from", "type": "address"},
            {"name": "to", "type": "address"},
            {"name": "amount", "type": "uint160"},
            {"name": "token", "type": "address"}
        ],
        "name": "transferFrom",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [
            {"name": "owner", "type": "address"}
        ],
        "name": "nonces",
        "outputs": [
            {"name": "", "type": "uint256"}
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "DOMAIN_SEPARATOR",
        "outputs": [
            {"name": "", "type": "bytes32"}
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [
            {
                "components": [
                    {"name": "token", "type": "address"},
                    {"name": "amount", "type": "uint160"},
                    {"name": "expiration", "type": "uint48"},
                    {"name": "nonce", "type": "uint48"}
                ],
                "name": "details",
                "type": "tuple"
            },
            {"name": "owner", "type": "address"},
            {"name": "spender", "type": "address"}
        ],
        "name": "allowance",
        "outputs": [
            {
                "components": [
                    {"name": "amount", "type": "uint160"},
                    {"name": "expiration", "type": "uint48"},
                    {"name": "nonce", "type": "uint48"}
                ],
                "name": "",
                "type": "tuple"
            }
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [
            {"name": "token", "type": "address"},
            {"name": "spender", "type": "address"},
            {"name": "amount", "type": "uint160"},
            {"name": "expiration", "type": "uint48"}
        ],
        "name": "approve",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    }
] 