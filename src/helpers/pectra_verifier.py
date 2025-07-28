"""
Pectra Infrastructure Verifier
==============================

This module verifies that all EIP-7702 infrastructure is properly deployed
and configured for bundled transaction execution.

Usage:
    python -m src.helpers.pectra_verifier
"""

import os
import sys
import json
from typing import Dict, Any, List, Tuple
from pathlib import Path
from decimal import Decimal
from web3 import Web3
from eth_account import Account
from eth_utils import is_address, to_checksum_address

from src.config.network import DEFAULT_RPC_URLS
from src.helpers.eip7702_builder import EIP7702TransactionBuilder


# --------------------------------------------------------------------------- #
# Verification Checks                                                         #
# --------------------------------------------------------------------------- #

class PectraVerifier:
    """Verifies Pectra/EIP-7702 infrastructure readiness."""
    
    def __init__(self, w3: Web3):
        self.w3 = w3
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.info: List[str] = []
        
    def add_error(self, msg: str) -> None:
        """Add an error message."""
        self.errors.append(f"❌ {msg}")
        
    def add_warning(self, msg: str) -> None:
        """Add a warning message."""
        self.warnings.append(f"⚠️  {msg}")
        
    def add_info(self, msg: str) -> None:
        """Add an info message."""
        self.info.append(f"ℹ️  {msg}")
        
    def check_environment_variables(self) -> bool:
        """Check all required environment variables."""
        print("\n🔍 Checking Environment Variables...")
        
        required_vars = {
            'IMPLEMENTATION_ADDRESS': 'FutarchyBatchExecutor contract address',
            'PRIVATE_KEY': 'EOA private key for signing',
            'RPC_URL': 'Gnosis Chain RPC endpoint',
            'PECTRA_ENABLED': 'Feature flag for EIP-7702',
            'FUTARCHY_ROUTER_ADDRESS': 'FutarchyRouter contract',
            'SDAI_TOKEN_ADDRESS': 'sDAI token contract',
            'COMPANY_TOKEN_ADDRESS': 'Company token contract',
        }
        
        optional_vars = {
            'EIP7702_GAS_BUFFER': 'Additional gas for authorization',
            'BUNDLE_SIMULATION_ENDPOINT': 'Simulation endpoint',
            'GNOSISSCAN_API_KEY': 'For contract verification',
        }
        
        all_good = True
        
        # Check required variables
        for var, description in required_vars.items():
            value = os.getenv(var)
            if not value:
                self.add_error(f"{var} not set ({description})")
                all_good = False
            else:
                # Validate addresses
                if var.endswith('_ADDRESS'):
                    if not is_address(value):
                        self.add_error(f"{var} is not a valid address: {value}")
                        all_good = False
                    else:
                        self.add_info(f"{var} = {value}")
                elif var == 'PECTRA_ENABLED':
                    if value.lower() not in ['true', 'false']:
                        self.add_warning(f"{var} should be 'true' or 'false', got: {value}")
                
        # Check optional variables
        for var, description in optional_vars.items():
            value = os.getenv(var)
            if not value:
                self.add_warning(f"{var} not set ({description})")
            else:
                self.add_info(f"{var} = {value}")
                
        return all_good
    
    def check_network_connection(self) -> bool:
        """Verify network connection and chain ID."""
        print("\n🌐 Checking Network Connection...")
        
        try:
            if not self.w3.is_connected():
                self.add_error("Not connected to network")
                return False
                
            chain_id = self.w3.eth.chain_id
            self.add_info(f"Connected to chain ID: {chain_id}")
            
            if chain_id != 100:
                self.add_warning(f"Not on Gnosis Chain (expected 100, got {chain_id})")
                
            # Check if EIP-7702 is supported
            latest_block = self.w3.eth.get_block('latest')
            self.add_info(f"Latest block: {latest_block.number}")
            
            # Check node client version
            client_version = self.w3.client_version
            self.add_info(f"Node client: {client_version}")
            
            return True
            
        except Exception as e:
            self.add_error(f"Network check failed: {e}")
            return False
    
    def check_implementation_contract(self) -> bool:
        """Verify the FutarchyBatchExecutor implementation contract."""
        print("\n📄 Checking Implementation Contract...")
        
        impl_address = os.getenv('IMPLEMENTATION_ADDRESS')
        if not impl_address:
            self.add_error("IMPLEMENTATION_ADDRESS not set")
            return False
            
        try:
            # Check if contract exists
            code = self.w3.eth.get_code(impl_address)
            if code == b'':
                self.add_error(f"No contract deployed at {impl_address}")
                return False
                
            self.add_info(f"Contract found at {impl_address}")
            self.add_info(f"Contract size: {len(code)} bytes")
            
            # Load and check ABI
            abi_path = Path("src/config/abis/FutarchyBatchExecutor.json")
            if not abi_path.exists():
                self.add_warning("FutarchyBatchExecutor ABI not found")
                return True  # Not critical
                
            with open(abi_path, 'r') as f:
                abi = json.load(f)
                
            # Create contract instance
            contract = self.w3.eth.contract(address=impl_address, abi=abi)
            
            # Check for expected functions
            expected_functions = ['execute', 'executeWithResults', 'setApprovals']
            contract_functions = [func.fn_name for func in contract.all_functions()]
            
            for func in expected_functions:
                if func in contract_functions:
                    self.add_info(f"✓ Function '{func}' found")
                else:
                    self.add_error(f"Function '{func}' not found in contract")
                    
            return True
            
        except Exception as e:
            self.add_error(f"Contract check failed: {e}")
            return False
    
    def check_eoa_account(self) -> bool:
        """Verify the EOA account configuration."""
        print("\n👤 Checking EOA Account...")
        
        private_key = os.getenv('PRIVATE_KEY')
        if not private_key:
            self.add_error("PRIVATE_KEY not set")
            return False
            
        try:
            account = Account.from_key(private_key)
            address = account.address
            self.add_info(f"EOA Address: {address}")
            
            # Check balance
            balance = self.w3.eth.get_balance(address)
            balance_eth = self.w3.from_wei(balance, 'ether')
            self.add_info(f"Balance: {balance_eth:.6f} ETH")
            
            if balance == 0:
                self.add_warning("EOA has zero balance")
            elif balance_eth < 0.01:
                self.add_warning(f"Low balance: {balance_eth:.6f} ETH")
                
            # Check nonce
            nonce = self.w3.eth.get_transaction_count(address)
            self.add_info(f"Nonce: {nonce}")
            
            return True
            
        except Exception as e:
            self.add_error(f"Account check failed: {e}")
            return False
    
    def test_basic_authorization(self) -> bool:
        """Test basic EIP-7702 authorization signing."""
        print("\n🔐 Testing EIP-7702 Authorization...")
        
        impl_address = os.getenv('IMPLEMENTATION_ADDRESS')
        private_key = os.getenv('PRIVATE_KEY')
        
        if not impl_address or not private_key:
            self.add_error("Missing IMPLEMENTATION_ADDRESS or PRIVATE_KEY")
            return False
            
        try:
            account = Account.from_key(private_key)
            builder = EIP7702TransactionBuilder(self.w3, impl_address)
            
            # Try to build an authorization
            auth = builder.build_authorization(account)
            
            required_fields = ['chainId', 'address', 'nonce', 'yParity', 'r', 's']
            for field in required_fields:
                if field not in auth:
                    self.add_error(f"Authorization missing field: {field}")
                    return False
                    
            self.add_info("✓ Successfully created EIP-7702 authorization")
            self.add_info(f"  Chain ID: {auth['chainId']}")
            self.add_info(f"  Implementation: {auth['address']}")
            self.add_info(f"  Nonce: {auth['nonce']}")
            
            return True
            
        except Exception as e:
            self.add_error(f"Authorization test failed: {e}")
            return False
    
    def test_bundle_creation(self) -> bool:
        """Test creating a simple transaction bundle."""
        print("\n📦 Testing Bundle Creation...")
        
        impl_address = os.getenv('IMPLEMENTATION_ADDRESS')
        private_key = os.getenv('PRIVATE_KEY')
        
        if not impl_address or not private_key:
            self.add_error("Missing IMPLEMENTATION_ADDRESS or PRIVATE_KEY")
            return False
            
        try:
            account = Account.from_key(private_key)
            builder = EIP7702TransactionBuilder(self.w3, impl_address)
            
            # Add a test approval
            test_token = "0x0000000000000000000000000000000000000001"
            test_spender = "0x0000000000000000000000000000000000000002"
            builder.add_approval(test_token, test_spender, 2**256 - 1)
            
            # Build transaction
            tx = builder.build_transaction(account)
            
            # Check transaction structure
            required_fields = ['type', 'chainId', 'nonce', 'to', 'data', 'authorizationList']
            for field in required_fields:
                if field not in tx:
                    self.add_error(f"Transaction missing field: {field}")
                    return False
                    
            if tx['type'] != 4:
                self.add_error(f"Wrong transaction type: expected 4, got {tx['type']}")
                return False
                
            if tx['to'] != account.address:
                self.add_error(f"Wrong 'to' address: expected {account.address}, got {tx['to']}")
                return False
                
            self.add_info("✓ Successfully created EIP-7702 bundled transaction")
            self.add_info(f"  Transaction type: {tx['type']}")
            self.add_info(f"  Authorization count: {len(tx['authorizationList'])}")
            self.add_info(f"  Data length: {len(tx['data'])} bytes")
            
            return True
            
        except Exception as e:
            self.add_error(f"Bundle creation test failed: {e}")
            return False
    
    def check_token_contracts(self) -> bool:
        """Verify all required token contracts exist."""
        print("\n💰 Checking Token Contracts...")
        
        tokens = {
            'SDAI_TOKEN_ADDRESS': 'sDAI token',
            'COMPANY_TOKEN_ADDRESS': 'Company token',
            'SWAPR_SDAI_YES_ADDRESS': 'Conditional sDAI YES',
            'SWAPR_SDAI_NO_ADDRESS': 'Conditional sDAI NO',
            'SWAPR_GNO_YES_ADDRESS': 'Conditional Company YES',
            'SWAPR_GNO_NO_ADDRESS': 'Conditional Company NO',
        }
        
        all_good = True
        
        for var, description in tokens.items():
            address = os.getenv(var)
            if not address:
                self.add_warning(f"{var} not set ({description})")
                continue
                
            try:
                # Convert to checksum address
                checksum_address = to_checksum_address(address)
                code = self.w3.eth.get_code(checksum_address)
                if code == b'':
                    self.add_error(f"No contract at {var}: {checksum_address}")
                    all_good = False
                else:
                    self.add_info(f"✓ {description} found at {checksum_address}")
            except Exception as e:
                self.add_error(f"Failed to check {var}: {e}")
                all_good = False
                
        return all_good
    
    def run_all_checks(self) -> bool:
        """Run all verification checks."""
        print("🔧 Pectra Infrastructure Verification")
        print("=" * 50)
        
        checks = [
            self.check_environment_variables(),
            self.check_network_connection(),
            self.check_implementation_contract(),
            self.check_eoa_account(),
            self.test_basic_authorization(),
            self.test_bundle_creation(),
            self.check_token_contracts(),
        ]
        
        all_passed = all(checks)
        
        # Print summary
        print("\n" + "=" * 50)
        print("📊 Verification Summary")
        print("=" * 50)
        
        if self.info:
            print("\n📋 Information:")
            for msg in self.info:
                print(f"   {msg}")
                
        if self.warnings:
            print(f"\n⚠️  Warnings ({len(self.warnings)}):")
            for msg in self.warnings:
                print(f"   {msg}")
                
        if self.errors:
            print(f"\n❌ Errors ({len(self.errors)}):")
            for msg in self.errors:
                print(f"   {msg}")
        
        if all_passed and not self.errors:
            print("\n✅ All checks passed! Infrastructure is ready for EIP-7702 bundled transactions.")
        else:
            print("\n❌ Some checks failed. Please fix the errors above.")
            
        return all_passed


# --------------------------------------------------------------------------- #
# Main Function                                                               #
# --------------------------------------------------------------------------- #

def main():
    """Main verification function."""
    # Connect to network
    rpc_url = os.getenv("RPC_URL", DEFAULT_RPC_URLS[0])
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    
    # Run verification
    verifier = PectraVerifier(w3)
    success = verifier.run_all_checks()
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()