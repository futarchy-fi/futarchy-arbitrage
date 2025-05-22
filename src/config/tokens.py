"""
Token configurations for the Futarchy Trading Bot.

This module is currently in EXPERIMENTAL status.
Contains token configurations, settings, and metadata.
"""

from typing import Dict, Any
from decimal import Decimal
from .contracts import CONTRACT_ADDRESSES

# Token configurations
TOKEN_CONFIG = {
    "currency": {
        "name": "SDAI",
        "address": "0xaf204776c7245bF4147c2612BF6e5972Ee483701",
        "decimals": 18,
        "yes_address": "0x493A0D1c776f8797297Aa8B34594fBd0A7F8968a",
        "no_address": "0xE1133Ef862f3441880adADC2096AB67c63f6E102"
    },
    "company": {
        "name": "GNO",
        "address": "0x9C58BAcC331c9aa871AFD802DB6379a98e80CEdb",
        "decimals": 18,
        "yes_address": "0x177304d505eCA60E1aE0dAF1bba4A4c4181dB8Ad",
        "no_address": "0xf1B3E5Ffc0219A4F8C0ac69EC98C97709EdfB6c9"
    },
    "wagno": {
        "name": "waGNO",
        "address": "0x7c16f0185a26db0ae7a9377f23bc18ea7ce5d644",
        "decimals": 18
    },
    "currency_yes": {
        "name": "SDAI-YES",
        "symbol": "sDAI-YES",
        "address": CONTRACT_ADDRESSES["currencyYesToken"],
        "decimals": 18,
        "base_token": CONTRACT_ADDRESSES["baseCurrencyToken"],
        "description": "Conditional YES token for sDAI",
        "type": "currency",
        "is_conditional": True,
        "condition": "yes"
    },
    "currency_no": {
        "name": "SDAI-NO",
        "symbol": "sDAI-NO",
        "address": CONTRACT_ADDRESSES["currencyNoToken"],
        "decimals": 18,
        "base_token": CONTRACT_ADDRESSES["baseCurrencyToken"],
        "description": "Conditional NO token for sDAI",
        "type": "currency",
        "is_conditional": True,
        "condition": "no"
    },
    "company_yes": {
        "name": "GNO-YES",
        "symbol": "GNO-YES",
        "address": CONTRACT_ADDRESSES["companyYesToken"],
        "decimals": 18,
        "base_token": CONTRACT_ADDRESSES["baseCompanyToken"],
        "description": "Conditional YES token for GNO",
        "type": "company",
        "is_conditional": True,
        "condition": "yes"
    },
    "company_no": {
        "name": "GNO-NO",
        "symbol": "GNO-NO",
        "address": CONTRACT_ADDRESSES["companyNoToken"],
        "decimals": 18,
        "base_token": CONTRACT_ADDRESSES["baseCompanyToken"],
        "description": "Conditional NO token for GNO",
        "type": "company",
        "is_conditional": True,
        "condition": "no"
    }
}

# Default swap configuration
DEFAULT_SWAP_CONFIG = {
    "amount_to_swap": 100000000000000,  # 0.0001 tokens with 18 decimals
    "slippage_percentage": 0.5,  # 0.5% slippage
}

# Default permit configuration
DEFAULT_PERMIT_CONFIG = {
    "amount": 1000000000000000,  # 0.001 tokens with 18 decimals
    "expiration_hours": 24,
    "sig_deadline_hours": 1
}

def get_token_info(token_address: str) -> dict:
    """Get token information for a specific token address."""
    # Check main tokens
    for token_type, info in TOKEN_CONFIG.items():
        if info["address"].lower() == token_address.lower():
            return {**info, "type": token_type}
        
        # Check conditional tokens if they exist
        if "yes_address" in info and info["yes_address"].lower() == token_address.lower():
            return {**info, "type": f"{token_type}_yes"}
        if "no_address" in info and info["no_address"].lower() == token_address.lower():
            return {**info, "type": f"{token_type}_no"}
    
    return None

def get_token_decimals(token_address: str) -> int:
    """Get the number of decimals for a specific token address."""
    token_info = get_token_info(token_address)
    return token_info["decimals"] if token_info else 18  # Default to 18 decimals

def format_token_amount(amount: int, token_address: str) -> float:
    """Format a token amount from wei to its decimal representation."""
    decimals = get_token_decimals(token_address)
    return amount / (10 ** decimals)

def get_base_token(conditional_token_address: str) -> str:
    """Get the base token address for a conditional token."""
    for token_type, info in TOKEN_CONFIG.items():
        if "yes_address" in info and info["yes_address"].lower() == conditional_token_address.lower():
            return info["address"]
        if "no_address" in info and info["no_address"].lower() == conditional_token_address.lower():
            return info["address"]
    return None 