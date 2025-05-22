#!/usr/bin/env python3
from eth_account._utils.signing import to_standard_v
from eth_account._utils.structured_data.hashing import hash_domain, hash_struct_message
from eth_utils import to_hex, keccak, to_bytes
from eth_keys import keys
import sys

def verify_signature(digest_hex, r_hex, s_hex, v_int):
    """
    Verify a signature by recovering the address from digest and signature components
    
    Args:
        digest_hex: Hex string of the message digest (without 0x prefix)
        r_hex: Hex string of the r component (without 0x prefix)
        s_hex: Hex string of the s component (without 0x prefix)
        v_int: Integer of the v component (usually 27 or 28)
    """
    try:
        # Convert inputs to appropriate formats
        digest = bytes.fromhex(digest_hex)
        r = int(r_hex, 16)
        s = int(s_hex, 16)
        v = v_int
        
        # Recover the public key
        pub = keys.ecdsa_recover(digest, v, r, s)
        
        # Convert to checksum address
        addr = pub.to_checksum_address()
        
        print(f"Recovered address: {addr}")
        print(f"Expected signer address: 0x0000000000000000000000000000000000000041")
        
        if addr.lower() == "0x0000000000000000000000000000000000000041":
            print("✅ MATCH: The recovered address matches the expected user address")
        else:
            print("❌ MISMATCH: The recovered address does not match the expected user address")
            
    except Exception as e:
        print(f"Error during signature verification: {str(e)}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Allow command line arguments
        if len(sys.argv) != 5:
            print("Usage: python verify_sig.py <digest_hex> <r_hex> <s_hex> <v_int>")
            sys.exit(1)
        
        digest_hex = sys.argv[1]
        r_hex = sys.argv[2]
        s_hex = sys.argv[3]
        v_int = int(sys.argv[4])
        
        verify_signature(digest_hex, r_hex, s_hex, v_int)
    else:
        # Parameters extracted from the provided data
        # Full signature: 0x635a48fd417044c7c577d2e5c4270674c2b60ec8bada2c12a24e2fbf5eeffb0a14b9510b50eaf101fefc8cfeedfd4ad3cdac55ea6e2dd15e401f502579c3914a1c
        # Hash: 0x1e069242a7902a2c6ef1a30bd1ac3ff425580622021e4f582d9ae122d58683ee
        # ClaimedSigner: 0x0000000000000000000000000000000000000041
        
        # Extract r, s, v from signature
        digest_hex = "1e069242a7902a2c6ef1a30bd1ac3ff425580622021e4f582d9ae122d58683ee"  # Hash without 0x prefix
        r_hex = "635a48fd417044c7c577d2e5c4270674c2b60ec8bada2c12a24e2fbf5eeffb0a"      # First 32 bytes of signature
        s_hex = "14b9510b50eaf101fefc8cfeedfd4ad3cdac55ea6e2dd15e401f502579c3914a"      # Second 32 bytes of signature
        v_int = 28  # Last byte "1c" of signature in decimal (27 + (1c - 1b))
        
        print("Running with example values. Replace with actual values in the script.")
        print("Or run with: python verify_sig.py <digest_hex> <r_hex> <s_hex> <v_int>")
        print("-" * 70)
        
        verify_signature(digest_hex, r_hex, s_hex, v_int)
        
        print("\nIf the printed address is not 0xf9fd…b006, your signature does not match the digest the contract received.")
        print("If it does match, the problem is elsewhere (e.g. the claimedSigner you passed when the router called SignatureVerification.verify).")
