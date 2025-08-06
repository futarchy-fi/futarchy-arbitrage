#!/usr/bin/env python3
"""
Analyze the actual Swapr router interface on Gnosis Chain.
This will help us understand the exact encoding needed.
"""

import os
import sys
import json
from web3 import Web3
from eth_utils import keccak

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.config.abis.swapr import SWAPR_ROUTER_ABI

# Load environment
w3 = Web3(Web3.HTTPProvider(os.environ["RPC_URL"]))

SWAPR_ROUTER = os.environ["SWAPR_ROUTER_ADDRESS"]


def analyze_swapr_interface():
    """Analyze the Swapr router interface."""
    print("=== Swapr Router Interface Analysis ===\n")
    print(f"Router address: {SWAPR_ROUTER}")
    
    # Create contract instance
    router = w3.eth.contract(address=SWAPR_ROUTER, abi=SWAPR_ROUTER_ABI)
    
    print("\n--- Available Functions ---")
    for func in router.abi:
        if func.get('type') == 'function':
            name = func.get('name')
            if name in ['exactInputSingle', 'exactOutputSingle']:
                print(f"\n{name}:")
                print(f"  Inputs: {func.get('inputs')}")
                
                # Generate function signature
                if func.get('inputs'):
                    input_types = []
                    for inp in func['inputs']:
                        if inp['type'] == 'tuple':
                            # Build tuple signature
                            tuple_types = []
                            for comp in inp.get('components', []):
                                tuple_types.append(comp['type'])
                            input_types.append(f"({','.join(tuple_types)})")
                        else:
                            input_types.append(inp['type'])
                    
                    signature = f"{name}({','.join(input_types)})"
                    selector = keccak(text=signature)[:4].hex()
                    print(f"  Signature: {signature}")
                    print(f"  Selector: 0x{selector}")


def test_direct_encoding():
    """Test direct encoding of Swapr calls."""
    print("\n=== Testing Direct Encoding ===\n")
    
    # Load the router contract
    router = w3.eth.contract(address=SWAPR_ROUTER, abi=SWAPR_ROUTER_ABI)
    
    # Test encoding exactInputSingle
    params = (
        Web3.to_checksum_address(os.environ["SWAPR_SDAI_YES_ADDRESS"]),  # tokenIn
        Web3.to_checksum_address(os.environ["SWAPR_GNO_YES_ADDRESS"]),   # tokenOut
        Web3.to_checksum_address("0x0000000000000000000000000000000000000001"),  # recipient
        1234567890,  # deadline
        1000000000000000000,  # amountIn (1 token)
        0,  # amountOutMinimum
        0   # sqrtPriceLimitX96
    )
    
    try:
        # Use the contract's encodeABI method
        encoded = router.encodeABI(fn_name="exactInputSingle", args=[params])
        print("Successfully encoded exactInputSingle:")
        print(f"  Encoded data: {encoded[:10]}...")
        print(f"  Length: {len(encoded)} bytes")
        
        # Extract just the selector
        selector = encoded[:10]
        print(f"  Function selector: {selector}")
        
    except Exception as e:
        print(f"Error encoding: {e}")


def compare_with_working_swap():
    """Compare with the working swap implementation."""
    print("\n=== Comparing with Working Implementation ===\n")
    
    from src.helpers.swapr_swap import router, w3 as swapr_w3
    
    # Test parameters
    params = (
        Web3.to_checksum_address(os.environ["SWAPR_SDAI_YES_ADDRESS"]),
        Web3.to_checksum_address(os.environ["SWAPR_GNO_YES_ADDRESS"]),
        Web3.to_checksum_address("0x0000000000000000000000000000000000000001"),
        1234567890,
        1000000000000000000,
        0,
        0
    )
    
    # Encode using the working method
    data = router.encodeABI(fn_name="exactInputSingle", args=[params])
    print(f"Working encoding selector: {data[:10]}")
    print(f"Working encoding length: {len(data)} bytes")
    
    # Show first 100 bytes
    print(f"First 100 bytes: {data[:100]}")


def main():
    """Main entry point."""
    print("Swapr Interface Analysis Tool")
    print("=" * 50)
    
    analyze_swapr_interface()
    test_direct_encoding()
    compare_with_working_swap()
    
    print("\n" + "=" * 50)
    print("\nAnalysis complete!")


if __name__ == "__main__":
    main()