#!/usr/bin/env python3
"""
Example usage of the multicall and conditionals command modules.
Demonstrates the exact pattern requested in the instructions.
"""

from decimal import Decimal
from web3 import Web3
from src.commands.conditionals import ConditionalCommands, CallBlock
from src.commands.multicall import MulticallCommand, MulticallBuilder

def example_basic_usage():
    """
    Example of basic usage pattern as specified in the instructions:
    
    {
        contract_address="0x123",
        function_signature="0x456", 
        calldata=calldata
    } = call_block = ConditionalCommands.execute("split", {amount: 123.321}, {from: "0x123", "router": "0x123"})
    multicall.add_call(call_block)
    """
    
    print("=== Basic Usage Example ===")
    print()
    
    # Create multicall instance
    multicall = MulticallCommand(executor_address="0xf276e5d62978F0E79089a4B7867A2AD97E3c9be5")
    
    # Execute split command with exact pattern from instructions
    call_block = ConditionalCommands.execute(
        "split",
        {"amount": Web3.to_wei(123.321, 'ether')},  # Convert 123.321 to wei
        {
            "from": "0x1234567890123456789012345678901234567890",  # Sender address
            "router": "0x7495a583ba85875d59407781b4958ED6e0E1228f",
            "proposal": "0x9590dAF4d5cd4009c3F9767C5E7668175cFd37CF",
            "collateral_token": "0xaf204776c7245bF4147c2612BF6e5972Ee483701"
        }
    )
    
    # Access call_block fields as shown in instructions
    print(f"contract_address = {call_block.contract_address}")
    print(f"function_signature = {call_block.function_signature}")
    print(f"calldata = 0x{call_block.calldata.hex()[:32]}...")  # Show first 32 chars
    print()
    
    # Add to multicall
    multicall.add_call(call_block)
    print(f"Added call to multicall. Total calls: {len(multicall.calls)}")
    print()


def example_complete_arbitrage():
    """
    Example of a complete arbitrage flow using multicall.
    """
    
    print("=== Complete Arbitrage Example ===")
    print()
    
    # Configuration
    config = {
        "from": "0x1234567890123456789012345678901234567890",
        "router": "0x7495a583ba85875d59407781b4958ED6e0E1228f", 
        "proposal": "0x9590dAF4d5cd4009c3F9767C5E7668175cFd37CF",
        "collateral_token": "0xaf204776c7245bF4147c2612BF6e5972Ee483701",  # sDAI
        "yes_token": "0x6F5e4988dc97C3cDce465e95dF4f49Cd969Ad21E",  # sDAI YES
        "no_token": "0xfCC67E1d1730f4d5300f07F9a8Fb2Fb31Be1DE1f",   # sDAI NO
        "company_yes_token": "0x4B592311dFfafa32DF0b96cd7D0E16B1fAB07774",  # Company YES
        "company_no_token": "0x411d18F43bcf7C5E8D007007FC3ac6302C54CF05",   # Company NO
        "company_token": "0x9C58BAcC331c9aa871AFD802DB6379a98e80CEdb",  # Company token
        "swapr_yes_pool": "0x5BAc492b43A548fD03e1Df1669873Ed44DC44CA9",
        "swapr_no_pool": "0xC5A96777166022780bd7fB3B80e3d73677aC5cD3",
        "balancer_pool": "0xBA12222222228d8Ba445958a75a0704d566BF2C8"
    }
    
    # Create multicall builder
    builder = MulticallBuilder(executor_address="0xf276e5d62978F0E79089a4B7867A2AD97E3c9be5")
    
    # Amount to arbitrage: 100 sDAI
    amount = Web3.to_wei(100, 'ether')
    
    # Step 1: Approve and split sDAI into YES/NO conditional sDAI
    print("Step 1: Split sDAI into conditional tokens")
    approve_sdai = ConditionalCommands.execute(
        "approve",
        {"spender": config["router"], "amount": amount},
        {"token": config["collateral_token"]}
    )
    builder.multicall.add_call(approve_sdai)
    
    split_call = ConditionalCommands.execute(
        "split",
        {"amount": amount},
        config
    )
    builder.multicall.add_call(split_call)
    print(f"  Added {len(builder.multicall.calls)} calls")
    
    # Step 2: Approve conditional sDAI tokens for Swapr pools
    print("\nStep 2: Approve conditional sDAI for swapping")
    approve_yes_sdai = ConditionalCommands.execute(
        "approve", 
        {"spender": config["swapr_yes_pool"], "amount": amount},
        {"token": config["yes_token"]}
    )
    builder.multicall.add_call(approve_yes_sdai)
    
    approve_no_sdai = ConditionalCommands.execute(
        "approve",
        {"spender": config["swapr_no_pool"], "amount": amount}, 
        {"token": config["no_token"]}
    )
    builder.multicall.add_call(approve_no_sdai)
    print(f"  Total calls: {len(builder.multicall.calls)}")
    
    # Step 3: Swap conditional sDAI to conditional Company tokens
    print("\nStep 3: Swap to conditional Company tokens")
    # Note: In real implementation, you'd add swap calls here
    # This is just showing the pattern
    
    # Step 4: Merge conditional Company tokens back to regular Company token
    print("\nStep 4: Merge conditional Company tokens")
    merge_amount = Web3.to_wei(50, 'ether')  # Assuming we got 50 of each
    
    approve_yes_company = ConditionalCommands.execute(
        "approve",
        {"spender": config["router"], "amount": merge_amount},
        {"token": config["company_yes_token"]}
    )
    builder.multicall.add_call(approve_yes_company)
    
    approve_no_company = ConditionalCommands.execute(
        "approve",
        {"spender": config["router"], "amount": merge_amount},
        {"token": config["company_no_token"]}
    )
    builder.multicall.add_call(approve_no_company)
    
    merge_call = ConditionalCommands.execute(
        "merge",
        {"amount": merge_amount},
        {
            "router": config["router"],
            "proposal": config["proposal"],
            "collateral_token": config["company_token"]
        }
    )
    builder.multicall.add_call(merge_call)
    print(f"  Total calls: {len(builder.multicall.calls)}")
    
    # Get the multicall instance
    multicall = builder.multicall
    print(f"\nBuilt multicall with {len(multicall.calls)} total calls")
    print(f"Multicall executor: {multicall.executor_address}")
    
    # Show summary
    print("\nCall Summary:")
    for i, (target, calldata) in enumerate(multicall.calls):
        func_sig = calldata[:4].hex() if len(calldata) >= 4 else "unknown"
        print(f"  Call {i+1}: {target[:10]}... - 0x{func_sig}")
    

def example_wrap_unwrap():
    """
    Example of wrap/unwrap operations.
    """
    
    print("=== Wrap/Unwrap Example ===")
    print()
    
    multicall = MulticallCommand(executor_address="0xf276e5d62978F0E79089a4B7867A2AD97E3c9be5")
    wrapper_address = "0xe91D153E0b41518A2Ce8Dd3D7944Fa863463a97d"  # WXDAI
    
    # Wrap 10 tokens
    amount = Web3.to_wei(10, 'ether')
    
    # Create wrap call
    wrap_call = ConditionalCommands.execute(
        "wrap",
        {"amount": amount},
        {"wrapper": wrapper_address}
    )
    
    print(f"Wrap call:")
    print(f"  Contract: {wrap_call.contract_address}")
    print(f"  Function: {wrap_call.function_signature}")
    print(f"  Amount: {Web3.from_wei(amount, 'ether')} tokens")
    
    multicall.add_call(wrap_call)
    
    # Create unwrap call
    unwrap_call = ConditionalCommands.execute(
        "unwrap",
        {"amount": amount},
        {"wrapper": wrapper_address}
    )
    
    print(f"\nUnwrap call:")
    print(f"  Contract: {unwrap_call.contract_address}")
    print(f"  Function: {unwrap_call.function_signature}")
    print(f"  Amount: {Web3.from_wei(amount, 'ether')} tokens")
    
    multicall.add_call(unwrap_call)
    
    print(f"\nTotal multicall operations: {len(multicall.calls)}")


if __name__ == "__main__":
    print("Multicall & Conditionals Command Module Examples")
    print("=" * 50)
    print()
    
    # Run examples
    example_basic_usage()
    print("\n" + "=" * 50 + "\n")
    
    example_complete_arbitrage()
    print("\n" + "=" * 50 + "\n")
    
    example_wrap_unwrap()
    
    print("\n✅ Examples completed!")