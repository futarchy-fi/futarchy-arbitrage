"""Key Manager for HD wallet key derivation.

This module provides secure key derivation for bot wallets using a master private key.
Each bot gets a unique derived key based on its derivation path.
"""

from eth_account import Account
import hashlib
import logging

logger = logging.getLogger(__name__)


class KeyManager:
    """Manages HD wallet key derivation for bot accounts."""
    
    def __init__(self, master_private_key: str):
        """Initialize with master private key from .env
        
        Args:
            master_private_key: Master private key in hex format (with or without 0x prefix)
        """
        # Ensure the key has 0x prefix
        if not master_private_key.startswith('0x'):
            master_private_key = '0x' + master_private_key
            
        self.master_key = master_private_key
        self.master_account = Account.from_key(master_private_key)
        
    def derive_key(self, derivation_path: str) -> str:
        """Derive a child private key from master using path.
        
        Args:
            derivation_path: HD wallet derivation path (e.g., "m/44'/60'/0'/0/1")
            
        Returns:
            Derived private key as hex string (with 0x prefix)
            
        Note:
            This is a simplified derivation that creates deterministic keys
            from the master key and path. For production use, consider
            implementing full BIP32/BIP44 compliance.
        """
        # Create a deterministic seed from master key and path
        seed_input = f"{self.master_key}{derivation_path}"
        seed = hashlib.sha256(seed_input.encode()).digest()
        
        # Use the seed to create a new private key
        derived_private_key = hashlib.sha256(seed).hexdigest()
        
        # Ensure it's a valid private key (32 bytes)
        if len(derived_private_key) > 64:
            derived_private_key = derived_private_key[:64]
            
        return '0x' + derived_private_key
    
    def get_account(self, bot_config: dict) -> Account:
        """Get derived account for a specific bot.
        
        Args:
            bot_config: Bot configuration dictionary containing 'key_derivation_path'
            
        Returns:
            Derived eth_account.Account instance
        """
        derivation_path = bot_config.get('key_derivation_path')
        if not derivation_path:
            raise ValueError("Bot configuration missing 'key_derivation_path'")
            
        derived_key = self.derive_key(derivation_path)
        return Account.from_key(derived_key)
    
    def get_address(self, derivation_path: str) -> str:
        """Get the address for a given derivation path.
        
        Args:
            derivation_path: HD wallet derivation path
            
        Returns:
            Ethereum address for the derived key
        """
        derived_key = self.derive_key(derivation_path)
        account = Account.from_key(derived_key)
        return account.address
    
    def validate_derivation_path(self, path: str) -> bool:
        """Validate that a derivation path follows BIP44 format.
        
        Args:
            path: Derivation path to validate
            
        Returns:
            True if valid, False otherwise
        """
        # Basic validation for BIP44 format: m/purpose'/coin_type'/account'/change/index
        parts = path.split('/')
        
        if len(parts) != 6:
            return False
            
        if parts[0] != 'm':
            return False
            
        # Check that hardened derivation levels have apostrophe
        for i in [1, 2, 3]:
            if not parts[i].endswith("'"):
                return False
                
        # Check that all parts after 'm' are numeric (ignoring apostrophes)
        for part in parts[1:]:
            numeric_part = part.rstrip("'")
            if not numeric_part.isdigit():
                return False
                
        return True
    
    def generate_next_path(self, base_path: str = "m/44'/60'/0'/0", 
                          current_index: int = 0) -> str:
        """Generate the next derivation path in sequence.
        
        Args:
            base_path: Base path without the final index
            current_index: Current highest index in use
            
        Returns:
            Next derivation path
        """
        return f"{base_path}/{current_index + 1}"


# Utility functions for key management
def create_deterministic_address(bot_name: str, master_key: str) -> tuple[str, str]:
    """Create a deterministic address and derivation path from bot name.
    
    Args:
        bot_name: Name of the bot
        master_key: Master private key
        
    Returns:
        Tuple of (address, derivation_path)
    """
    # Create a deterministic index from bot name
    name_hash = int(hashlib.sha256(bot_name.encode()).hexdigest()[:8], 16)
    index = name_hash % 1000000  # Keep index reasonable
    
    # Standard BIP44 path for Ethereum
    derivation_path = f"m/44'/60'/0'/0/{index}"
    
    key_manager = KeyManager(master_key)
    address = key_manager.get_address(derivation_path)
    
    return address, derivation_path
