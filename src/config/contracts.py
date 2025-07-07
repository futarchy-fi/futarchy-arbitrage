"""
Contract addresses for the Futarchy Trading Bot.

This module is currently in EXPERIMENTAL status.
Contains contract addresses and related warnings/notes.
"""

from typing import Dict, Any

# Contract addresses with documentation
CONTRACT_ADDRESSES: Dict[str, str] = {
    # Core protocol contracts
    "futarchyRouter": "0x7495a583ba85875d59407781b4958ED6e0E1228f",
    "market": "0x6242AbA055957A63d682e9D3de3364ACB53D053A",
    "conditionalTokens": "0xCeAfDD6bc0bEF976fdCd1112955828E00543c0Ce",
    "wrapperService": "0xc14f5d2B9d6945EF1BA93f8dB20294b90FA5b5b1",
    
    # DEX contracts
    "sushiswap": "0xE592427A0AEce92De3Edee1F18E0157C05861564",  # Using Uniswap V3 Router
    "sushiswapNFPM": "0xaB235da7f52d35fb4551AfBa11BFB56e18774A65",  # SushiSwap V3 NonFungiblePositionManager
    "uniswapV3PassthroughRouter": "0x77DBE0441C950cE9C97a5F9A79CF316947aAa578",  # UniswapV3PassthroughRouter
    
    # Cowswap contracts
    "vaultRelayer": "0xC92E8bdf79f0507f65a392b0ab4667716BFE0110",
    "cowSettlement": "0x9008D19f58AAbD9eD0D60971565AA8510560ab41",
    
    # Token contracts
    "baseCurrencyToken": "0xaf204776c7245bF4147c2612BF6e5972Ee483701",  # SDAI
    "baseCompanyToken": "0x9C58BAcC331c9aa871AFD802DB6379a98e80CEdb",  # Company token
    "currencyYesToken": "0x493A0D1c776f8797297Aa8B34594fBd0A7F8968a",
    "currencyNoToken": "0xE1133Ef862f3441880adADC2096AB67c63f6E102",
    "companyYesToken": "0x177304d505eCA60E1aE0dAF1bba4A4c4181dB8Ad",
    "companyNoToken": "0xf1B3E5Ffc0219A4F8C0ac69EC98C97709EdfB6c9",
    "wxdai": "0xe91D153E0b41518A2Ce8Dd3D7944Fa863463a97d",
    "wagno": "0x7c16f0185a26db0ae7a9377f23bc18ea7ce5d644",
    
    # Pool contracts
    "poolYes": "0x9a14d28909f42823ee29847f87a15fb3b6e8aed3",
    "poolNo": "0x6E33153115Ab58dab0e0F1E3a2ccda6e67FA5cD7",
    "sdaiYesPool": "0xC7405C82cFc9A652a469fAf21B7FE88D6E7d675c",  # SushiSwap V3 YES_sDAI/sDAI pool
    
    # Other contracts
    "sdaiRateProvider": "0x89C80A4540A00b5270347E02e2E144c71da2EceD",
    "permit2": "0x000000000022D473030F116dDEE9F6B43aC78BA3",
    "batchRouter": "0xe2fa4e1d17725e72dcdAfe943Ecf45dF4B9E285b",
    "balancerVault": "0xBA12222222228d8Ba445958a75a0704d566BF2C8",
    "balancerPool": "0xd1d7fa8871d84d0e77020fc28b7cd5718c446522",
    
    # Swapr V3 (Algebra) Router
    "swaprRouterV3": "0xfFB643E73f280B97809A8b41f7232AB401a04ee1",
}

# Contract warnings and notes
CONTRACT_WARNINGS: Dict[str, str] = {
    "0x592abc3734cd0d458e6e44a2db2992a3d00283a4": """
    WARNING: NEVER USE THIS ROUTER ADDRESS
    This SushiSwap V3 Passthrough Router has a critical flaw where tokens get permanently stuck 
    if a swap fails. We lost funds to this issue. Use a different router implementation.
    """.strip()
}

def is_contract_safe(address: str) -> bool:
    """Check if a contract address is known to be safe."""
    return address.lower() not in [addr.lower() for addr in CONTRACT_WARNINGS.keys()]

def get_contract_warning(address: str) -> str:
    """Get warning message for a contract address if any."""
    return CONTRACT_WARNINGS.get(address.lower(), "") 