#!/usr/bin/env python3
import os
import json
from web3 import Web3

def main():
    # Load environment
    rpc_url = os.getenv('RPC_URL')
    tx_hash = "0xf718942f28cf871ca7ab47a343429cbe4cdd91c1fd87fd7e6fd61bd3d3a9283c"
    
    # Connect to network
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    
    # Get transaction details
    tx = w3.eth.get_transaction(tx_hash)
    receipt = w3.eth.get_transaction_receipt(tx_hash)
    
    print(f"Transaction: {tx_hash}")
    print(f"Status: {'Success' if receipt.status == 1 else 'Failed'}")
    print(f"Gas used: {receipt.gasUsed}")
    print(f"From: {tx['from']}")
    print(f"To: {tx['to']}")
    print(f"Value: {tx['value']}")
    
    # Try to get revert reason
    try:
        # Replay the transaction to get the revert reason
        tx_data = {
            'from': tx['from'],
            'to': tx['to'],
            'data': tx['input'],
            'value': tx['value'],
            'gas': tx['gas']
        }
        w3.eth.call(tx_data, tx.blockNumber - 1)
    except Exception as e:
        print(f"\nRevert reason: {str(e)}")
    
    print(f"\nView on Gnosisscan: https://gnosisscan.io/tx/{tx_hash}")

if __name__ == "__main__":
    main()