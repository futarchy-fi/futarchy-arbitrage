import sys
import types
import unittest

# Provide a dummy 'web3' module so split_position can be imported without the
# real Web3 dependency installed.
web3_stub = types.ModuleType("web3")
class Web3:  # minimal stub
    pass
web3_stub.Web3 = Web3
sys.modules.setdefault("web3", web3_stub)

# Stub out 'requests' to avoid missing dependency errors when importing helpers.
requests_stub = types.ModuleType("requests")
sys.modules.setdefault("requests", requests_stub)

from helpers import split_position

class DummyContract:
    def __init__(self):
        self.encode_args = None
        self.address = "contract-address"
    def encodeABI(self, fn_name=None, args=None):
        self.encode_args = (fn_name, args)
        return "0xabc123"

class DummyEth:
    def __init__(self):
        self.contract_args = None
        self.instance = DummyContract()
    def contract(self, address=None, abi=None):
        self.contract_args = {"address": address, "abi": abi}
        return self.instance

class DummyWeb3:
    def __init__(self):
        self.eth = DummyEth()
        self.from_wei_called = None
    def to_checksum_address(self, addr):
        return addr
    def from_wei(self, value, unit):
        self.from_wei_called = (value, unit)
        return value / 10**18

class DummyClient:
    def __init__(self):
        self.built = None
        self.simulated = None
    def build_tx(self, to, data, sender, gas=50000000, value="0"):
        self.built = {"to": to, "data": data, "sender": sender, "gas": gas, "value": value}
        return self.built
    def simulate(self, txs):
        self.simulated = txs
        return {"simulation_results": [{"transaction": {"status": True}}]}

class ParseTracker:
    def __init__(self):
        self.called = None
    def __call__(self, results, w3):
        self.called = (results, w3)

class SplitPositionTests(unittest.TestCase):
    def test_build_split_tx(self):
        w3 = DummyWeb3()
        client = DummyClient()
        tx = split_position.build_split_tx(
            w3,
            client,
            "router",
            "proposal",
            "collateral",
            123,
            "sender",
        )
        self.assertEqual(tx, client.built)
        self.assertEqual(w3.eth.contract_args["address"], "router")
        self.assertEqual(w3.eth.contract_args["abi"], split_position.FUTARCHY_ROUTER_ABI)
        self.assertEqual(w3.eth.instance.encode_args, ("splitPosition", ["proposal", "collateral", 123]))

    def test_simulate_split_calls_parse(self):
        w3 = DummyWeb3()
        client = DummyClient()
        tracker = ParseTracker()
        original = split_position.parse_split_results
        split_position.parse_split_results = tracker
        try:
            result = split_position.simulate_split(
                w3, client, "router", "proposal", "collateral", 1, "sender"
            )
        finally:
            split_position.parse_split_results = original
        self.assertIn("simulation_results", result)
        self.assertEqual(tracker.called[0], result["simulation_results"])
        self.assertIs(tracker.called[1], w3)

    def test_parse_split_results_success(self):
        w3 = DummyWeb3()
        results = [
            {
                "transaction": {"status": True},
                "balance_changes": {"0xToken": "1000000000000000000"},
            }
        ]
        split_position.parse_split_results(results, w3)
        self.assertIsNotNone(w3.from_wei_called)

if __name__ == "__main__":
    unittest.main()
