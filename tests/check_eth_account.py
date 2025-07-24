"""Check eth-account capabilities."""

from eth_account import Account
import eth_account

print(f"eth-account version: {eth_account.__version__}")
print("\nAccount class methods:")
methods = [m for m in dir(Account) if not m.startswith('_')]
for method in sorted(methods):
    print(f"  - {method}")

# Check LocalAccount methods
print("\nLocalAccount methods (from Account.create()):")
test_account = Account.create()
local_methods = [m for m in dir(test_account) if not m.startswith('_')]
for method in sorted(local_methods):
    print(f"  - {method}")

# Try to find anything related to 7702 or authorization
print("\nSearching for EIP-7702 related methods:")
all_attrs = dir(Account) + dir(test_account)
for attr in all_attrs:
    if '7702' in attr.lower() or 'auth' in attr.lower():
        print(f"  Found: {attr}")