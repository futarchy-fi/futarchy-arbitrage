import os
import json
from web3 import Web3
from eth_account import Account

from pathlib import Path

# --- Configuration ---
# Load environment variables
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
USER_ADDRESS = os.getenv("USER_ADDRESS") or os.getenv("WALLET_ADDRESS")
GNOSIS_RPC_URL = os.getenv("RPC_URL")

# Balancer configuration
BATCH_ROUTER_ADDRESS = os.getenv("BALANCER_ROUTER_ADDRESS")
SPENDER_ADDRESS = os.getenv("SPENDER_ADDRESS", BATCH_ROUTER_ADDRESS)
BALANCER_VAULT_ADDRESS = os.getenv("BALANCER_VAULT_ADDRESS")

# Permit2 constants
PERMIT2_ADDRESS = "0x000000000022d473030f116ddee9f6b43ac78ba3"

# Chain ID (defaults to Gnosis)
CHAIN_ID = int(os.getenv("CHAIN_ID", 100))


def load_abi():
    """Load the Balancer Router ABI from a JSON file.

    Looks first in a `.reference` directory adjacent to this script, then
    falls back to a project-root `.reference` directory.
    """
    local_path = Path(__file__).parent / ".reference" / "balancer_router.abi.json"
    root_path = (
        Path(__file__).resolve().parent.parent.parent
        / ".reference"
        / "balancer_router.abi.json"
    )

    for candidate in (local_path, root_path):
        if candidate.exists():
            with open(candidate, "r") as f:
                return json.load(f)

    raise FileNotFoundError(
        "ABI file not found. Checked: " f"{local_path} and {root_path}"
    )


def connect_to_chain():
    """Establish connection to the Gnosis Chain RPC endpoint."""
    w3 = Web3(Web3.HTTPProvider(GNOSIS_RPC_URL))
    connected = w3.is_connected() if hasattr(w3, "is_connected") else w3.isConnected()
    if not connected:
        raise Exception(f"Failed to connect to the RPC endpoint: {GNOSIS_RPC_URL}")
    print(f"Connected to Gnosis Chain via {GNOSIS_RPC_URL}")
    return w3


def prepare_permit_data():
    """Prepare the typed data for the Permit2 signature."""
    # Convert all addresses to checksum format
    user_address = Web3.to_checksum_address(USER_ADDRESS)
    batch_router_address = Web3.to_checksum_address(BATCH_ROUTER_ADDRESS)
    permit2_address = Web3.to_checksum_address(PERMIT2_ADDRESS)

    token_addresses = [
        addr
        for addr in (
            os.getenv("GNO_TOKEN_ADDRESS"),
            os.getenv("SDAI_TOKEN_ADDRESS"),
        )
        if addr
    ]

    spender_address = Web3.to_checksum_address(SPENDER_ADDRESS)
    print(f"Using account: {user_address}")
    print(f"Spender address: {spender_address}")
    print(f"Permit2 address: {permit2_address}")
    print("Token addresses:")
    for a in token_addresses:
        print(f"  - {Web3.to_checksum_address(a)}")

    amount = int(os.getenv("PERMIT_AMOUNT", os.getenv("AMOUNT")))
    expiration = int(os.getenv("EXPIRATION"))
    nonce = int(os.getenv("NONCE"))
    sig_deadline = int(os.getenv("SIG_DEADLINE"))

    details = [
        {
            "token": Web3.to_checksum_address(a),
            "amount": amount,
            "expiration": expiration,
            "nonce": nonce,
        }
        for a in token_addresses
    ]

    # Permit2 typed data structure
    typed_data = {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "PermitDetails": [
                {"name": "token", "type": "address"},
                {"name": "amount", "type": "uint160"},
                {"name": "expiration", "type": "uint48"},
                {"name": "nonce", "type": "uint48"},
            ],
            "PermitBatch": [
                {"name": "details", "type": "PermitDetails[]"},
                {"name": "spender", "type": "address"},
                {"name": "sigDeadline", "type": "uint256"},
            ],
        },
        "domain": {
            "name": "Permit2",
            "chainId": CHAIN_ID,
            "verifyingContract": permit2_address,
        },
        "primaryType": "PermitBatch",
        "message": {
            "details": details,
            "spender": spender_address,
            "sigDeadline": sig_deadline,
        },
    }

    print("Permit parameters:")
    print(f"  Amount: {amount}")
    print(f"  Expiration: {expiration}")
    print(f"  Nonce: {nonce}")
    print(f"  Signature Deadline: {sig_deadline}")

    return (
        typed_data,
        user_address,
        batch_router_address,
        token_addresses,
        spender_address,
    )


from eth_account.messages import encode_structured_data as _encode_eip712


# --- Signing ---
def sign_permit_message(w3, typed_data):
    """Sign the Permit2 message using the EIP-712 structured data format."""
    print("\n--- Signing Permit2 Message ---")
    encoded_message = _encode_eip712(primitive=typed_data)
    signed_message = Account.sign_message(encoded_message, private_key=PRIVATE_KEY)
    permit2_signature = signed_message.signature

    print(
        f"Message signed with signature: {permit2_signature.hex()[:20]}...{permit2_signature.hex()[-20:]}"
    )
    return permit2_signature


def build_and_send_transaction(
    w3,
    router,
    user_address,
    batch_router_address,
    token_addresses,
    spender_address,
    permit2_signature,
):
    """Build and send the permitBatchAndCall transaction."""
    print("\n--- Building Transaction ---")

    # Create the permit batch tuple for the contract call
    amount = int(os.getenv("PERMIT_AMOUNT", os.getenv("AMOUNT")))
    expiration = int(os.getenv("EXPIRATION"))
    nonce = int(os.getenv("NONCE"))
    sig_deadline = int(os.getenv("SIG_DEADLINE"))

    permit_batch_details = [
        (addr, amount, expiration, nonce) for addr in token_addresses
    ]
    permit_batch = (permit_batch_details, spender_address, sig_deadline)

    # Get current gas price with a small buffer for faster inclusion
    gas_price = int(w3.eth.gas_price * 1.1)

    # Prepare permitBatchAndCall transaction
    tx = router.functions.permitBatchAndCall(
        [],  # empty permitBatch
        [],  # empty permitSignatures
        permit_batch,  # Permit2 batch
        permit2_signature,
        [],  # empty multicallData
    ).build_transaction(
        {
            "from": user_address,
            "nonce": w3.eth.get_transaction_count(user_address),
            "gasPrice": gas_price,
            "chainId": CHAIN_ID,
            "gas": 500000,  # Set a higher gas limit to ensure transaction doesn't fail due to gas
        }
    )

    print("Transaction built successfully")

    # Sign and send transaction
    print("\n--- Signing Transaction ---")
    signed_tx = w3.eth.account.sign_transaction(tx, private_key=PRIVATE_KEY)

    print("\n--- Sending Transaction ---")
    # Handle different attribute names in web3.py versions
    if hasattr(signed_tx, "rawTransaction"):
        raw_tx = signed_tx.rawTransaction
    elif hasattr(signed_tx, "raw_transaction"):
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
    gas_price_gwei = w3.from_wei(receipt.effectiveGasPrice, "gwei")
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
        router = w3.eth.contract(
            address=Web3.to_checksum_address(BATCH_ROUTER_ADDRESS), abi=abi
        )

        # Prepare permit data
        (
            typed_data,
            user_address,
            batch_router_address,
            token_addresses,
            spender_address,
        ) = prepare_permit_data()

        # Sign permit message
        permit2_signature = sign_permit_message(w3, typed_data)

        # Build and send transaction
        receipt = build_and_send_transaction(
            w3,
            router,
            user_address,
            batch_router_address,
            token_addresses,
            spender_address,
            permit2_signature,
        )

        print("\n=== Process Complete ===")

    except Exception as e:
        print(f"\n=== Error Occurred ===\n{str(e)}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
