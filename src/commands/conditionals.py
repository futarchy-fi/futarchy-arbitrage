from typing import Dict, Any, Tuple, NamedTuple, List
from decimal import Decimal
from web3 import Web3
from eth_abi import encode

class CallBlock(NamedTuple):
    contract_address: str
    function_signature: str
    calldata: bytes

class ConditionalCommands:
    
    @staticmethod
    def execute(command: str, args: Dict[str, Any], config: Dict[str, Any]) -> CallBlock:
        """
        Execute a conditional token command and return a call block for multicall.
        
        Args:
            command: The command to execute (e.g., "split", "merge", "wrap", "unwrap")
            args: Command-specific arguments
            config: Configuration including addresses and other settings
            
        Returns:
            CallBlock: A named tuple containing contract_address, function_signature, and calldata
        """
        
        if command == "split":
            return ConditionalCommands._split_position(args, config)
        elif command == "merge":
            return ConditionalCommands._merge_position(args, config)
        elif command == "wrap":
            return ConditionalCommands._wrap_tokens(args, config)
        elif command == "unwrap":
            return ConditionalCommands._unwrap_tokens(args, config)
        elif command == "approve":
            return ConditionalCommands._approve_token(args, config)
        else:
            raise ValueError(f"Unknown command: {command}")
    
    @staticmethod
    def _split_position(args: Dict[str, Any], config: Dict[str, Any]) -> CallBlock:
        """
        Split collateral tokens into conditional YES/NO tokens.
        
        Args:
            args: {"amount": Decimal or int in wei}
            config: {"router": router_address, "proposal": proposal_address, 
                    "collateral_token": token_address}
        """
        router_address = config["router"]
        proposal_address = config["proposal"]
        collateral_token = config["collateral_token"]
        amount = int(args["amount"]) if isinstance(args["amount"], (int, Decimal)) else args["amount"]
        
        # Function signature for splitPosition(address,address,uint256)
        function_signature = "0x0b23e3b4"
        
        # Encode the calldata
        calldata = function_signature.encode() + encode(
            ["address", "address", "uint256"],
            [
                Web3.to_checksum_address(proposal_address),
                Web3.to_checksum_address(collateral_token),
                amount
            ]
        )
        
        return CallBlock(
            contract_address=Web3.to_checksum_address(router_address),
            function_signature=function_signature,
            calldata=calldata
        )
    
    @staticmethod
    def _merge_position(args: Dict[str, Any], config: Dict[str, Any]) -> CallBlock:
        """
        Merge conditional YES/NO tokens back into collateral tokens.
        
        Args:
            args: {"amount": Decimal or int in wei}
            config: {"router": router_address, "proposal": proposal_address,
                    "collateral_token": token_address}
        """
        router_address = config["router"]
        proposal_address = config["proposal"]
        collateral_token = config["collateral_token"]
        amount = int(args["amount"]) if isinstance(args["amount"], (int, Decimal)) else args["amount"]
        
        # Function signature for mergePosition(address,address,uint256)
        function_signature = "0x5bb47808"
        
        # Encode the calldata
        calldata = function_signature.encode() + encode(
            ["address", "address", "uint256"],
            [
                Web3.to_checksum_address(proposal_address),
                Web3.to_checksum_address(collateral_token),
                amount
            ]
        )
        
        return CallBlock(
            contract_address=Web3.to_checksum_address(router_address),
            function_signature=function_signature,
            calldata=calldata
        )
    
    @staticmethod
    def _wrap_tokens(args: Dict[str, Any], config: Dict[str, Any]) -> CallBlock:
        """
        Wrap regular tokens into wrapped tokens (e.g., GNO -> WXDAI).
        
        Args:
            args: {"amount": Decimal or int in wei}
            config: {"wrapper": wrapper_contract_address}
        """
        wrapper_address = config["wrapper"]
        amount = int(args["amount"]) if isinstance(args["amount"], (int, Decimal)) else args["amount"]
        
        # Function signature for deposit(uint256) or wrap(uint256)
        # Using standard WETH-like deposit function
        function_signature = "0xb6b55f25"  # deposit(uint256)
        
        # Encode the calldata
        calldata = function_signature.encode() + encode(
            ["uint256"],
            [amount]
        )
        
        return CallBlock(
            contract_address=Web3.to_checksum_address(wrapper_address),
            function_signature=function_signature,
            calldata=calldata
        )
    
    @staticmethod
    def _unwrap_tokens(args: Dict[str, Any], config: Dict[str, Any]) -> CallBlock:
        """
        Unwrap wrapped tokens back to regular tokens.
        
        Args:
            args: {"amount": Decimal or int in wei}
            config: {"wrapper": wrapper_contract_address}
        """
        wrapper_address = config["wrapper"]
        amount = int(args["amount"]) if isinstance(args["amount"], (int, Decimal)) else args["amount"]
        
        # Function signature for withdraw(uint256) or unwrap(uint256)
        # Using standard WETH-like withdraw function
        function_signature = "0x2e1a7d4d"  # withdraw(uint256)
        
        # Encode the calldata
        calldata = function_signature.encode() + encode(
            ["uint256"],
            [amount]
        )
        
        return CallBlock(
            contract_address=Web3.to_checksum_address(wrapper_address),
            function_signature=function_signature,
            calldata=calldata
        )
    
    @staticmethod
    def _approve_token(args: Dict[str, Any], config: Dict[str, Any]) -> CallBlock:
        """
        Approve token spending.
        
        Args:
            args: {"spender": address, "amount": Decimal or int in wei}
            config: {"token": token_address}
        """
        token_address = config["token"]
        spender = args["spender"]
        amount = int(args["amount"]) if isinstance(args["amount"], (int, Decimal)) else args["amount"]
        
        # Function signature for approve(address,uint256)
        function_signature = "0x095ea7b3"
        
        # Encode the calldata
        calldata = function_signature.encode() + encode(
            ["address", "uint256"],
            [
                Web3.to_checksum_address(spender),
                amount
            ]
        )
        
        return CallBlock(
            contract_address=Web3.to_checksum_address(token_address),
            function_signature=function_signature,
            calldata=calldata
        )
    
    @staticmethod
    def build_split_sequence(amount: int, config: Dict[str, str]) -> List[CallBlock]:
        """
        Build a complete sequence for splitting tokens.
        
        Args:
            amount: Amount to split in wei
            config: Configuration with all necessary addresses
            
        Returns:
            List of CallBlocks for the complete split operation
        """
        calls = []
        
        # 1. Approve router to spend collateral tokens
        approve_call = ConditionalCommands.execute(
            "approve",
            {"spender": config["router"], "amount": amount},
            {"token": config["collateral_token"]}
        )
        calls.append(approve_call)
        
        # 2. Split position
        split_call = ConditionalCommands.execute(
            "split",
            {"amount": amount},
            config
        )
        calls.append(split_call)
        
        return calls
    
    @staticmethod
    def build_merge_sequence(amount: int, config: Dict[str, str]) -> List[CallBlock]:
        """
        Build a complete sequence for merging conditional tokens.
        
        Args:
            amount: Amount to merge in wei
            config: Configuration with all necessary addresses
            
        Returns:
            List of CallBlocks for the complete merge operation
        """
        calls = []
        
        # 1. Approve router to spend YES tokens
        approve_yes = ConditionalCommands.execute(
            "approve",
            {"spender": config["router"], "amount": amount},
            {"token": config["yes_token"]}
        )
        calls.append(approve_yes)
        
        # 2. Approve router to spend NO tokens
        approve_no = ConditionalCommands.execute(
            "approve",
            {"spender": config["router"], "amount": amount},
            {"token": config["no_token"]}
        )
        calls.append(approve_no)
        
        # 3. Merge position
        merge_call = ConditionalCommands.execute(
            "merge",
            {"amount": amount},
            config
        )
        calls.append(merge_call)
        
        return calls