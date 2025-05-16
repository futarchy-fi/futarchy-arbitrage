import os
import json
from web3 import Web3, HTTPProvider
from eth_account import Account
from eth_account.messages import encode_structured_data
from pathlib import Path

# --- Configuration ---
# Load environment variables
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
USER_ADDRESS = os.getenv("USER_ADDRESS")
GNOSIS_RPC_URL = os.getenv("RPC_URL")
BATCH_ROUTER_ADDRESS = os.getenv("BALANCER_ROUTER_ADDRESS")
if not BATCH_ROUTER_ADDRESS:
    # Default Balancer Vault address on Gnosis Chain
    BATCH_ROUTER_ADDRESS = "0xBA12222222228d8Ba445958a75a0704d566BF2C8"
PERMIT2_ADDRESS = "0x000000000022d473030f116ddee9f6b43ac78ba3"
CHAIN_ID = 100

def load_abi():
    """Load the Balancer Router ABI from a JSON file.
    
    Looks first in a `.reference` directory adjacent to this script, then
    falls back to a project-root `.reference` directory.
    """
    local_path = Path(__file__).parent / ".reference" / "balancer_router.abi.json"
    root_path = Path(__file__).resolve().parent.parent.parent / ".reference" / "balancer_router.abi.json"

    for candidate in (local_path, root_path):
        if candidate.exists():
            with open(candidate, "r") as f:
                return json.load(f)

    raise FileNotFoundError(
        "ABI file not found. Checked: " f"{local_path} and {root_path}")

def connect_to_chain():
    """Establish connection to the Gnosis Chain RPC endpoint."""
    w3 = Web3(Web3.HTTPProvider(GNOSIS_RPC_URL))
    if not w3.is_connected():
        raise Exception(f"Failed to connect to the RPC endpoint: {GNOSIS_RPC_URL}")
    print(f"Connected to Gnosis Chain via {GNOSIS_RPC_URL}")
    return w3

def prepare_permit_data():
    """Prepare the typed data for the Permit2 signature."""
    # Convert all addresses to checksum format
    user_address = Web3.to_checksum_address(USER_ADDRESS)
    batch_router_address = Web3.to_checksum_address(BATCH_ROUTER_ADDRESS)
    permit2_address = Web3.to_checksum_address(PERMIT2_ADDRESS)
    token_address = Web3.to_checksum_address(os.getenv("TOKEN_ADDRESS"))
    vault_address = Web3.to_checksum_address(os.getenv("VAULT_ADDRESS"))
    
    print(f"Using account: {user_address}")
    print(f"Batch router address: {batch_router_address}")
    print(f"Permit2 address: {permit2_address}")
    print(f"Token address: {token_address}")
    print(f"Vault address: {vault_address}")
    
    # Permit2 typed data structure
    typed_data = {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"}
            ],
            "PermitDetails": [
                {"name": "token", "type": "address"},
                {"name": "amount", "type": "uint160"},
                {"name": "expiration", "type": "uint48"},
                {"name": "nonce", "type": "uint48"}
            ],
            "PermitBatch": [
                {"name": "details", "type": "PermitDetails[]"},
                {"name": "spender", "type": "address"},
                {"name": "sigDeadline", "type": "uint256"}
            ]
        },
        "domain": {
            "name": "Permit2",
            "chainId": CHAIN_ID,
            "verifyingContract": permit2_address
        },
        "primaryType": "PermitBatch",
        "message": {
            "details": [
                {
                    "token": token_address,
                    "amount": int(os.getenv("AMOUNT")),
                    "expiration": int(os.getenv("EXPIRATION")),
                    "nonce": int(os.getenv("NONCE"))
                }
            ],
            "spender": vault_address,
            "sigDeadline": int(os.getenv("SIG_DEADLINE"))
        }
    }
    
    print("Permit parameters:")
    print(f"  Amount: {os.getenv('AMOUNT')}")
    print(f"  Expiration: {os.getenv('EXPIRATION')}")
    print(f"  Nonce: {os.getenv('NONCE')}")
    print(f"  Signature Deadline: {os.getenv('SIG_DEADLINE')}")
    
    return typed_data, user_address, batch_router_address, token_address, vault_address

from eth_account.messages import encode_structured_data as _encode_eip712

# --- Signing ---
def sign_permit_message(w3, typed_data):
    """Sign the Permit2 message using the EIP-712 structured data format."""
    print("\n--- Signing Permit2 Message ---")
    encoded_message = _encode_eip712(primitive=typed_data)
    signed_message = Account.sign_message(encoded_message, private_key=PRIVATE_KEY)
    permit2_signature = signed_message.signature
    
    print(f"Message signed with signature: {permit2_signature.hex()[:20]}...{permit2_signature.hex()[-20:]}")
    return permit2_signature

def build_and_send_transaction(w3, router, user_address, batch_router_address, token_address, vault_address, permit2_signature):
    """Build and send the permitBatchAndCall transaction."""
    print("\n--- Building Transaction ---")
    
    # Create the permit batch tuple for the contract call
    permit_batch_details = [(token_address, int(os.getenv("AMOUNT")), int(os.getenv("EXPIRATION")), int(os.getenv("NONCE")))]
    permit_batch = (permit_batch_details, vault_address, int(os.getenv("SIG_DEADLINE")))
    
    # Get current gas price with a small buffer for faster inclusion
    gas_price = int(w3.eth.gas_price * 1.1)
    
    # Prepare permitBatchAndCall transaction
    tx = router.functions.permitBatchAndCall(
        [],  # empty permitBatch
        [],  # empty permitSignatures
        permit_batch,  # Permit2 batch
        permit2_signature,
        []  # empty multicallData
    ).build_transaction({
        'from': user_address,
        'nonce': w3.eth.get_transaction_count(user_address),
        'gasPrice': gas_price,
        'chainId': CHAIN_ID,
        'gas': 500000  # Set a higher gas limit to ensure transaction doesn't fail due to gas
    })
    
    print("Transaction built successfully")
    
    # Sign and send transaction
    print("\n--- Signing Transaction ---")
    signed_tx = w3.eth.account.sign_transaction(tx, private_key=PRIVATE_KEY)
    
    print("\n--- Sending Transaction ---")
    # Handle different attribute names in web3.py versions
    if hasattr(signed_tx, 'rawTransaction'):
        raw_tx = signed_tx.rawTransaction
    elif hasattr(signed_tx, 'raw_transaction'):
        raw_tx = signed_tx.raw_transaction
    else:
        raise ValueError("Could not find rawTransaction in signed transaction object")
    
    tx_hash = w3.eth.send_raw_transaction(raw_tx)
    tx_hash_hex = tx_hash.hex()
    print(f"Transaction sent. Tx hash: {tx_hash_hex}")
    print(f"View on block explorer: https://gnosisscan.io/tx/{tx_hash_hex}")
    
    # Wait for transaction receipt
    print("\n--- Waiting for Transaction Confirmation ---")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    
    # Check if transaction was successful
    if receipt.status == 1:
        print("\n=== Transaction Successful! ===")
    else:
        print("\n=== Transaction Failed! ===")
        print("Check transaction details on block explorer for more information.")
    
    # Calculate gas used
    gas_used = receipt.gasUsed
    gas_price_gwei = w3.from_wei(receipt.effectiveGasPrice, 'gwei')
    gas_cost_eth = gas_used * receipt.effectiveGasPrice / 1e18
    print(f"Gas used: {gas_used}")
    print(f"Gas price: {gas_price_gwei} Gwei")
    print(f"Gas cost: {gas_cost_eth:.6f} xDAI")
    
    return receipt

def main():
    """Main function to execute the Permit2 and call on Gnosis Chain."""
    print("=== Balancer Router Permit2 and Call Script ===")
    
    try:
        # Initialize connection and load ABI
        w3 = connect_to_chain()
        abi = load_abi()
        router = w3.eth.contract(address=Web3.to_checksum_address(BATCH_ROUTER_ADDRESS), abi=abi)
        
        # Prepare permit data
        typed_data, user_address, batch_router_address, token_address, vault_address = prepare_permit_data()
        
        # Sign permit message
        permit2_signature = sign_permit_message(w3, typed_data)
        
        # Build and send transaction
        receipt = build_and_send_transaction(
            w3, router, user_address, batch_router_address, 
            token_address, vault_address, permit2_signature
        )
        
        print("\n=== Process Complete ===")
        
    except Exception as e:
        print(f"\n=== Error Occurred ===\n{str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
