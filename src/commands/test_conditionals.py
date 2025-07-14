#!/usr/bin/env python3
"""
Test script for conditional commands module.
"""

from decimal import Decimal
from src.commands.conditionals import ConditionalCommands, CallBlock
from src.commands.multicall import MulticallCommand, MulticallBuilder
from web3 import Web3

def test_conditional_commands():
    print("Testing Conditional Commands Module")
    print("=" * 50)
    
    # Test configuration
    config = {
        "router": "0x7495a583ba85875d59407781b4958ED6e0E1228f",
        "proposal": "0x9590dAF4d5cd4009c3F9767C5E7668175cFd37CF",
        "collateral_token": "0xaf204776c7245bF4147c2612BF6e5972Ee483701",  # sDAI
        "yes_token": "0x78d2c7da671fd4275836932a3b213b01177c6628",
        "no_token": "0x4d67f9302cde3c4640a99f0908fdf6f32d3ddfb6",
        "company_token": "0x9C58BAcC331c9aa871AFD802DB6379a98e80CEdb",
        "company_yes_token": "0x718be32688b615c2eb24560371ef332b892f69d8",
        "company_no_token": "0x72c185710775f307c9da20424910a1d3d27b8be0"
    }
    
    # Test amount (0.01 sDAI)
    amount = Web3.to_wei(0.01, 'ether')
    
    print("\n1. Testing Split Command")
    print("-" * 30)
    
    # Test split command
    split_call = ConditionalCommands.execute(
        "split",
        {"amount": amount},
        config
    )
    
    print(f"Contract Address: {split_call.contract_address}")
    print(f"Function Signature: {split_call.function_signature}")
    print(f"Calldata Length: {len(split_call.calldata)} bytes")
    print(f"Calldata (hex): 0x{split_call.calldata.hex()[:50]}...")
    
    # Verify it's a CallBlock
    assert isinstance(split_call, CallBlock)
    assert split_call.contract_address == Web3.to_checksum_address(config["router"])
    
    print("\n2. Testing Merge Command")
    print("-" * 30)
    
    # Test merge command
    merge_call = ConditionalCommands.execute(
        "merge",
        {"amount": amount},
        config
    )
    
    print(f"Contract Address: {merge_call.contract_address}")
    print(f"Function Signature: {merge_call.function_signature}")
    print(f"Calldata Length: {len(merge_call.calldata)} bytes")
    
    print("\n3. Testing Approve Command")
    print("-" * 30)
    
    # Test approve command
    approve_call = ConditionalCommands.execute(
        "approve",
        {"spender": config["router"], "amount": amount},
        {"token": config["collateral_token"]}
    )
    
    print(f"Contract Address: {approve_call.contract_address}")
    print(f"Function Signature: {approve_call.function_signature}")
    print(f"Calldata Length: {len(approve_call.calldata)} bytes")
    
    print("\n4. Testing Build Split Sequence")
    print("-" * 30)
    
    # Test building a complete split sequence
    split_sequence = ConditionalCommands.build_split_sequence(amount, config)
    
    print(f"Split sequence contains {len(split_sequence)} calls:")
    for i, call in enumerate(split_sequence):
        print(f"  Call {i+1}: {call.contract_address} - signature: {call.function_signature}")
    
    print("\n5. Testing Multicall Integration")
    print("-" * 30)
    
    # Create multicall command
    executor_address = "0xf276e5d62978F0E79089a4B7867A2AD97E3c9be5"
    multicall = MulticallCommand(executor_address)
    
    # Add calls from conditional commands
    for call in split_sequence:
        multicall.add_call(call)
    
    print(f"Multicall has {len(multicall)} calls")
    print(f"Multicall executor: {multicall.executor_address}")
    
    # Build the calls
    built_calls = multicall.build()
    print(f"\nBuilt {len(built_calls)} calls for multicall execution")
    
    print("\n6. Testing High-Level Builder")
    print("-" * 30)
    
    # Test the high-level builder
    builder = MulticallBuilder(executor_address)
    
    # Add custom configuration
    full_config = {
        "sdai_token": config["collateral_token"],
        "company_token": config["company_token"],
        "company_yes_token": config["company_yes_token"],
        "company_no_token": config["company_no_token"],
        "futarchy_router": config["router"],
        "proposal": config["proposal"]
    }
    
    # Build a buy arbitrage (simplified - without swap params)
    buy_multicall = builder.build_buy_conditional_arbitrage(
        amount,
        full_config,
        {}  # Empty swap params for this test
    )
    
    print(f"Buy arbitrage multicall has {len(buy_multicall)} calls")
    
    print("\n✅ All tests passed!")
    
    # Example of the syntax requested by the user
    print("\n" + "=" * 50)
    print("Example Usage (as requested):")
    print("-" * 30)
    print("""
# Execute a split command
call_block = ConditionalCommands.execute(
    "split", 
    {"amount": 123321000000000000},  # 0.123321 tokens
    {
        "router": "0x7495a583ba85875d59407781b4958ED6e0E1228f",
        "proposal": "0x9590dAF4d5cd4009c3F9767C5E7668175cFd37CF",
        "collateral_token": "0xaf204776c7245bF4147c2612BF6e5972Ee483701"
    }
)

# Add to multicall
multicall = MulticallCommand("0xf276e5d62978F0E79089a4B7867A2AD97E3c9be5")
multicall.add_call(call_block)

# Result:
# call_block.contract_address = "0x7495a583ba85875d59407781b4958ED6e0E1228f"
# call_block.function_signature = "0x0b23e3b4"
# call_block.calldata = <encoded split function call>
""")

if __name__ == "__main__":
    test_conditional_commands()