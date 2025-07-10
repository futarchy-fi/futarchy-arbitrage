"""
Tiny wrapper around the CowSwap (GPv2) HTTP API on Gnosis.

It mirrors the style of `balancer_swap.py` and `swapr_swap.py`, but stays
extremely small on purpose – only the essentials to:

  • build an order dict
  • sign its EIP‑712 payload
  • POST it to the CowSwap backend
  • poll order status

Assumptions
-----------
* Environment variables `PRIVATE_KEY`, `RPC_URL` and optionally
  `COW_API_URL` (defaults to the canonical Gnosis endpoint).
* ERC‑20 allowances for the GPv2 Settlement contract are already set
  (see Section 2 of this report).
* All inputs are trusted; no explicit validation or logging.
"""

from __future__ import annotations

import os
import time
import requests
import json
from decimal import Decimal
from typing import Any, Dict, Optional
from datetime import datetime

from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import Web3
from web3.middleware import geth_poa_middleware
from eth_utils import keccak, to_bytes
from eth_abi import encode

__all__ = [
    "build_order",
    "sign_order",
    "submit_order",
    "get_order",
]

# --------------------------------------------------------------------------- #
# Constants                                                                   #
# --------------------------------------------------------------------------- #

COW_API_URL = os.getenv("COW_API_URL", "https://api.cow.fi/xdai/api/v1")
SETTLEMENT_CONTRACT = "0x9008d19f58aabd9ed0d60971565aa8510560ab41"

# --------------------------------------------------------------------------- #
# Web3 / signer                                                               #
# --------------------------------------------------------------------------- #

_w3 = Web3(Web3.HTTPProvider(os.environ["RPC_URL"]))
_w3.middleware_onion.inject(geth_poa_middleware, layer=0)
_acct = Account.from_key(os.environ["PRIVATE_KEY"])

# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #

def _save_debug_data(filename: str, data: Any) -> None:
    """Save debug data to .debug/ folder."""
    debug_dir = ".debug"
    if not os.path.exists(debug_dir):
        os.makedirs(debug_dir)
    
    filepath = os.path.join(debug_dir, filename)
    with open(filepath, 'w') as f:
        if isinstance(data, (dict, list)):
            json.dump(data, f, indent=2)
        else:
            f.write(str(data))
    print(f"Debug data saved to {filepath}")


def _to_wei(amount: Decimal, decimals: int = 18) -> int:
    return int(amount * (10 ** decimals))


def _compute_order_uid(order: Dict[str, Any], owner: str) -> str:
    """Compute the order UID according to CowSwap's formula."""
    # Encode packed order data
    order_data = encode(
        ['address', 'address', 'address', 'uint256', 'uint256', 'uint32', 'bytes32', 
         'uint256', 'bytes32', 'bool', 'bytes32', 'bytes32'],
        [
            _w3.to_checksum_address(order["sellToken"]),
            _w3.to_checksum_address(order["buyToken"]),
            _w3.to_checksum_address(order["receiver"]),
            int(order["sellAmount"]),
            int(order["buyAmount"]),
            order["validTo"],
            to_bytes(hexstr=order["appData"]),
            int(order["feeAmount"]),
            keccak(text=order["kind"])[:32],
            order["partiallyFillable"],
            keccak(text=order["sellTokenBalance"])[:32],
            keccak(text=order["buyTokenBalance"])[:32]
        ]
    )
    
    # Compute hash
    order_digest = keccak(order_data)
    
    # Append owner address
    uid_data = order_digest + to_bytes(hexstr=owner)
    return "0x" + uid_data.hex()


def _hash_typed_data(domain_separator: bytes, struct_hash: bytes) -> bytes:
    """Compute EIP-712 hash."""
    return keccak(b'\x19\x01' + domain_separator + struct_hash)


def _get_domain_separator() -> bytes:
    """Get the domain separator for Gnosis Chain CowSwap."""
    domain_type_hash = keccak(text="EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)")
    name_hash = keccak(text="Gnosis Protocol")
    version_hash = keccak(text="v2")
    
    encoded_domain = encode(
        ['bytes32', 'bytes32', 'bytes32', 'uint256', 'address'],
        [domain_type_hash, name_hash, version_hash, 100, _w3.to_checksum_address(SETTLEMENT_CONTRACT)]
    )
    
    return keccak(encoded_domain)


def _get_struct_hash(order: Dict[str, Any]) -> bytes:
    """Get the struct hash for the order."""
    order_type_hash = keccak(text="Order(address sellToken,address buyToken,address receiver,uint256 sellAmount,uint256 buyAmount,uint32 validTo,bytes32 appData,uint256 feeAmount,string kind,bool partiallyFillable,string sellTokenBalance,string buyTokenBalance)")
    
    # Encode the order
    encoded_order = encode(
        ['bytes32', 'address', 'address', 'address', 'uint256', 'uint256', 'uint32', 
         'bytes32', 'uint256', 'bytes32', 'bool', 'bytes32', 'bytes32'],
        [
            order_type_hash,
            _w3.to_checksum_address(order["sellToken"]),
            _w3.to_checksum_address(order["buyToken"]),
            _w3.to_checksum_address(order["receiver"]),
            int(order["sellAmount"]),
            int(order["buyAmount"]),
            order["validTo"],
            to_bytes(hexstr=order["appData"]),
            int(order["feeAmount"]),
            keccak(text=order["kind"]),
            order["partiallyFillable"],
            keccak(text=order["sellTokenBalance"]),
            keccak(text=order["buyTokenBalance"])
        ]
    )
    
    return keccak(encoded_order)


# --------------------------------------------------------------------------- #
# Public‑facing helpers                                                       #
# --------------------------------------------------------------------------- #

def build_order(
    sell_token: str,
    buy_token: str,
    sell_amount: Decimal,
    *,
    buy_amount: Optional[Decimal] = None,
    valid_for: int = 20 * 60,
    app_data: str = "0x0000000000000000000000000000000000000000000000000000000000000000",
) -> Dict[str, Any]:
    """
    Return a dict ready to be signed / submitted to CowSwap.

    If *buy_amount* is omitted the order is `fillOrKill` with whatever price
    the solvers find.  Quantities are decimal ETH units for convenience.
    """
    now = int(time.time())

    order = {
        "sellToken": Web3.to_checksum_address(sell_token),
        "buyToken": Web3.to_checksum_address(buy_token),
        "receiver": _acct.address,
        "sellAmount": str(_to_wei(sell_amount)),
        "buyAmount": str(_to_wei(buy_amount)) if buy_amount else "1",  # Min 1 wei
        "validTo": now + valid_for,
        "feeAmount": "0",          # implicit fee model on Gnosis
        "kind": "sell",
        "partiallyFillable": False,
        "appData": app_data,
        "sellTokenBalance": "erc20",
        "buyTokenBalance": "erc20",
    }
    return order


def sign_order(order: Dict[str, Any]) -> str:
    """
    Sign the order using EIP-712.
    """
    domain_separator = _get_domain_separator()
    struct_hash = _get_struct_hash(order)
    signing_hash = _hash_typed_data(domain_separator, struct_hash)
    
    # Sign the hash directly
    signature = _acct.unsafe_sign_hash(signing_hash)
    
    return signature.signature.hex()


def submit_order(order: Dict[str, Any], signature: str) -> str:
    """
    POST the signed *order* and return CowSwap's order UID.
    """
    payload = {
        "sellToken": order["sellToken"],
        "buyToken": order["buyToken"],
        "receiver": order["receiver"],
        "sellAmount": order["sellAmount"],
        "buyAmount": order["buyAmount"],
        "validTo": order["validTo"],
        "appData": order["appData"],
        "feeAmount": order["feeAmount"],
        "kind": order["kind"],
        "partiallyFillable": order["partiallyFillable"],
        "sellTokenBalance": order["sellTokenBalance"],
        "buyTokenBalance": order["buyTokenBalance"],
        "from": _acct.address,
        "signature": signature,
        "signingScheme": "eip712"
    }
    
    # Save request payload
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    _save_debug_data(f"cowswap_submit_request_{timestamp}.json", {
        "url": f"{COW_API_URL}/orders",
        "method": "POST",
        "payload": payload
    })
    
    r = requests.post(f"{COW_API_URL}/orders", json=payload)
    
    # Save response
    _save_debug_data(f"cowswap_submit_response_{timestamp}.json", {
        "status_code": r.status_code,
        "headers": dict(r.headers),
        "body": r.text,
        "json": r.json() if r.headers.get('content-type', '').startswith('application/json') else None
    })
    
    if r.status_code != 201:
        print(f"Error {r.status_code}: {r.text}")
        # Try to parse error
        try:
            error_data = r.json()
            if "errorType" in error_data:
                print(f"Error type: {error_data['errorType']}")
                if "description" in error_data:
                    print(f"Description: {error_data['description']}")
        except:
            pass
    r.raise_for_status()
    
    # Get the UID from the response
    uid_from_response = r.json()
    
    # Also compute our own for debugging
    uid_computed = _compute_order_uid(order, _acct.address)
    
    _save_debug_data(f"cowswap_order_uid_{timestamp}.json", {
        "uid_from_api": uid_from_response,
        "uid_computed": uid_computed,
        "match": uid_from_response == uid_computed
    })
    
    # Return the UID from the API response
    return uid_from_response


def get_order(uid: str) -> Dict[str, Any]:
    """Fetch order details / status by UID."""
    url = f"{COW_API_URL}/orders/{uid}"
    
    # Save request info
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    _save_debug_data(f"cowswap_get_request_{timestamp}.json", {
        "url": url,
        "method": "GET",
        "uid": uid
    })
    
    r = requests.get(url)
    
    # Save response
    _save_debug_data(f"cowswap_get_response_{timestamp}.json", {
        "status_code": r.status_code,
        "headers": dict(r.headers),
        "body": r.text,
        "json": r.json() if r.headers.get('content-type', '').startswith('application/json') else None
    })
    
    r.raise_for_status()
    return r.json()