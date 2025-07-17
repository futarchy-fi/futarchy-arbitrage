#!/usr/bin/env python3
"""
fetch_market_data.py
===================
Fetch market_event data from Supabase and search metadata for specific pool and token addresses.

Usage:
    python -m src.setup.fetch_market_data [market_event_id]
    python -m src.setup.fetch_market_data --search-addresses
    
Examples:
    python -m src.setup.fetch_market_data 123
    python -m src.setup.fetch_market_data --search-addresses
"""

import os
import json
import argparse
import sys
from typing import Dict, Any, Optional, List
from supabase import create_client, Client

# Target address patterns to search for (no default addresses)
TARGET_ADDRESS_KEYS = [
    'SWAPR_POOL_YES_ADDRESS',
    'SWAPR_POOL_NO_ADDRESS', 
    'SWAPR_POOL_PRED_YES_ADDRESS',
    'SWAPR_POOL_PRED_NO_ADDRESS',
    'SWAPR_SDAI_YES_ADDRESS',
    'SWAPR_SDAI_NO_ADDRESS',
    'SWAPR_GNO_YES_ADDRESS',
    'SWAPR_GNO_NO_ADDRESS'
]


class MarketDataFetcher:
    """Fetches and analyzes market event data from Supabase."""
    
    def __init__(self):
        """Initialize with Supabase connection."""
        # Strictly require environment variables - no defaults
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = (os.getenv("SUPABASE_ANON_KEY") or 
                       os.getenv("SUPABASE_EDGE_TOKEN") or 
                       os.getenv("SUPABASE_SERVICE_ROLE_KEY"))
        
        if not supabase_url:
            raise ValueError("Missing required environment variable: SUPABASE_URL")
        
        if not supabase_key:
            raise ValueError("Missing required environment variable: SUPABASE_ANON_KEY, SUPABASE_EDGE_TOKEN, or SUPABASE_SERVICE_ROLE_KEY")
        
        print(f"Connecting to Supabase: {supabase_url}")
        self.supabase: Client = create_client(supabase_url, supabase_key)
    
    def fetch_market_event(self, market_event_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a specific market event by ID.
        
        Args:
            market_event_id: ID of the market event to fetch
            
        Returns:
            Market event data or None if not found
        """
        try:
            response = self.supabase.table('market_event').select('*').eq('id', market_event_id).execute()
            
            if response.data and len(response.data) > 0:
                return response.data[0]
            else:
                print(f"No market event found with ID: {market_event_id}")
                return None
                
        except Exception as e:
            print(f"Error fetching market event {market_event_id}: {e}")
            return None
    
    def fetch_all_market_events(self) -> List[Dict[str, Any]]:
        """Fetch all market events.
        
        Returns:
            List of all market event data
        """
        try:
            response = self.supabase.table('market_event').select('*').execute()
            return response.data or []
            
        except Exception as e:
            print(f"Error fetching market events: {e}")
            return []
    
    def search_addresses_in_metadata(self, metadata: Dict[str, Any]) -> Dict[str, str]:
        """Search for target address keys in metadata.
        
        Args:
            metadata: Metadata dictionary to search
            
        Returns:
            Dictionary of found addresses with their keys
        """
        found_addresses = {}
        
        def search_recursive(obj, path=""):
            """Recursively search through nested dictionaries and lists."""
            if isinstance(obj, dict):
                for key, value in obj.items():
                    current_path = f"{path}.{key}" if path else key
                    
                    # Check if key matches one of our target address keys
                    if key in TARGET_ADDRESS_KEYS and isinstance(value, str):
                        found_addresses[key] = {
                            'address': value,
                            'path': current_path
                        }
                    
                    # Continue recursive search
                    search_recursive(value, current_path)
                    
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    current_path = f"{path}[{i}]" if path else f"[{i}]"
                    search_recursive(item, current_path)
        
        search_recursive(metadata)
        return found_addresses
    
    def analyze_market_event(self, market_event: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze a market event for target addresses.
        
        Args:
            market_event: Market event data
            
        Returns:
            Analysis results
        """
        result = {
            'market_event_id': market_event.get('id'),
            'title': market_event.get('title', 'N/A'),
            'created_at': market_event.get('created_at'),
            'found_addresses': {},
            'metadata_preview': {}
        }
        
        # Search in metadata
        metadata = market_event.get('metadata', {})
        if metadata:
            result['found_addresses'] = self.search_addresses_in_metadata(metadata)
            
            # Create a preview of the metadata structure
            result['metadata_preview'] = self._create_metadata_preview(metadata)
        
        return result
    
    def _create_metadata_preview(self, metadata: Dict[str, Any], max_depth: int = 3) -> Dict[str, Any]:
        """Create a preview of metadata structure without full content.
        
        Args:
            metadata: Metadata to preview
            max_depth: Maximum depth to traverse
            
        Returns:
            Simplified metadata structure
        """
        def preview_recursive(obj, depth=0):
            if depth >= max_depth:
                return "..." if isinstance(obj, (dict, list)) else str(obj)[:50]
            
            if isinstance(obj, dict):
                return {key: preview_recursive(value, depth + 1) for key, value in list(obj.items())[:5]}
            elif isinstance(obj, list):
                return [preview_recursive(item, depth + 1) for item in obj[:3]]
            else:
                return str(obj)[:100] if isinstance(obj, str) else obj
        
        return preview_recursive(metadata)
    
    def search_all_markets(self) -> List[Dict[str, Any]]:
        """Search all market events for target addresses.
        
        Returns:
            List of analysis results for markets containing target addresses
        """
        all_events = self.fetch_all_market_events()
        results = []
        
        print(f"Searching {len(all_events)} market events...")
        
        for event in all_events:
            analysis = self.analyze_market_event(event)
            if analysis['found_addresses']:
                results.append(analysis)
        
        return results
    
    def extract_addresses_from_metadata(self, metadata: Dict[str, Any]) -> Dict[str, str]:
        """Extract addresses from metadata and map them to environment variable names.
        
        Args:
            metadata: Market event metadata
            
        Returns:
            Dictionary mapping env var names to addresses
        """
        addresses = {}
        
        # Extract pool addresses
        if 'conditional_pools' in metadata:
            if 'yes' in metadata['conditional_pools']:
                addresses['SWAPR_POOL_YES_ADDRESS'] = metadata['conditional_pools']['yes']['address']
            if 'no' in metadata['conditional_pools']:
                addresses['SWAPR_POOL_NO_ADDRESS'] = metadata['conditional_pools']['no']['address']
        
        if 'prediction_pools' in metadata:
            if 'yes' in metadata['prediction_pools']:
                addresses['SWAPR_POOL_PRED_YES_ADDRESS'] = metadata['prediction_pools']['yes']['address']
            if 'no' in metadata['prediction_pools']:
                addresses['SWAPR_POOL_PRED_NO_ADDRESS'] = metadata['prediction_pools']['no']['address']
        
        # Extract token addresses
        if 'currencyTokens' in metadata:
            if 'yes' in metadata['currencyTokens']:
                addresses['SWAPR_SDAI_YES_ADDRESS'] = metadata['currencyTokens']['yes']['wrappedCollateralTokenAddress']
            if 'no' in metadata['currencyTokens']:
                addresses['SWAPR_SDAI_NO_ADDRESS'] = metadata['currencyTokens']['no']['wrappedCollateralTokenAddress']
        
        if 'companyTokens' in metadata:
            if 'yes' in metadata['companyTokens']:
                addresses['SWAPR_GNO_YES_ADDRESS'] = metadata['companyTokens']['yes']['wrappedCollateralTokenAddress']
            if 'no' in metadata['companyTokens']:
                addresses['SWAPR_GNO_NO_ADDRESS'] = metadata['companyTokens']['no']['wrappedCollateralTokenAddress']
        
        return addresses
    
    def update_env_file(self, env_file_path: str, addresses: Dict[str, str]) -> None:
        """Update environment file with extracted addresses.
        
        Args:
            env_file_path: Path to the environment file
            addresses: Dictionary of env var names to addresses
        """
        import re
        
        # Read current env file
        with open(env_file_path, 'r') as f:
            content = f.read()
        
        # Update each address
        updated_content = content
        for env_var, address in addresses.items():
            # Pattern to match the export line
            pattern = rf'^export {env_var}=.*$'
            replacement = f'export {env_var}={address}'
            
            if re.search(pattern, updated_content, re.MULTILINE):
                # Replace existing line
                updated_content = re.sub(pattern, replacement, updated_content, flags=re.MULTILINE)
                print(f"Updated {env_var}={address}")
            else:
                # Add new line if it doesn't exist
                # Find a good place to insert it (after other similar exports)
                if 'SWAPR_POOL' in env_var:
                    # Insert after other pool addresses
                    pool_section = re.search(r'(^export SWAPR_POOL.*\n)', updated_content, re.MULTILINE)
                    if pool_section:
                        insert_pos = pool_section.end()
                        updated_content = updated_content[:insert_pos] + f'export {env_var}={address}\n' + updated_content[insert_pos:]
                elif 'SWAPR_SDAI' in env_var or 'SWAPR_GNO' in env_var:
                    # Insert after other token addresses
                    token_section = re.search(r'(^export SWAPR_.*_ADDRESS=.*\n)', updated_content, re.MULTILINE)
                    if token_section:
                        insert_pos = token_section.end()
                        updated_content = updated_content[:insert_pos] + f'export {env_var}={address}\n' + updated_content[insert_pos:]
                print(f"Added {env_var}={address}")
        
        # Write updated content back
        with open(env_file_path, 'w') as f:
            f.write(updated_content)
        
        print(f"\nEnvironment file {env_file_path} updated successfully!")


def print_analysis_results(results: List[Dict[str, Any]]):
    """Print analysis results in a readable format."""
    if not results:
        print("No market events found containing the target addresses.")
        return
    
    print(f"\nFound {len(results)} market event(s) with matching addresses:\n")
    
    for result in results:
        print(f"Market Event ID: {result['market_event_id']}")
        print(f"Title: {result['title']}")
        print(f"Created: {result['created_at']}")
        print("Found addresses:")
        
        for addr_key, addr_info in result['found_addresses'].items():
            print(f"  {addr_key}: {addr_info['address']}")
            print(f"    → Found at: {addr_info['path']}")
        
        print("\nMetadata preview:")
        print(json.dumps(result['metadata_preview'], indent=2))
        print("-" * 80)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Fetch and analyze market event data from Supabase")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("market_event_id", nargs="?", help="Specific market event ID to fetch")
    group.add_argument("--search-addresses", action="store_true", 
                      help="Search all market events for target addresses")
    group.add_argument("--proposal", action="store_true",
                      help="Fetch market event using FUTARCHY_PROPOSAL_ADDRESS from environment")
    parser.add_argument("--verbose", "-v", action="store_true", 
                      help="Enable verbose output")
    parser.add_argument("--update-env", type=str, metavar="ENV_FILE",
                      help="Update environment file with extracted addresses")
    
    args = parser.parse_args()
    
    try:
        fetcher = MarketDataFetcher()
        
        if args.proposal:
            # Use FUTARCHY_PROPOSAL_ADDRESS as market event ID
            proposal_address = os.getenv("FUTARCHY_PROPOSAL_ADDRESS")
            if not proposal_address:
                print("Error: FUTARCHY_PROPOSAL_ADDRESS environment variable not set")
                sys.exit(1)
            
            print(f"Fetching market event with proposal address: {proposal_address}")
            market_event = fetcher.fetch_market_event(proposal_address)
            
            if market_event:
                print("Found market event!")
                print(f"ID: {market_event.get('id')}")
                print(f"Title: {market_event.get('title', 'N/A')}")
                print(f"Created: {market_event.get('created_at')}")
                
                # Extract addresses if update-env is specified
                if args.update_env:
                    metadata = market_event.get('metadata', {})
                    addresses = fetcher.extract_addresses_from_metadata(metadata)
                    
                    if addresses:
                        print(f"\nExtracting addresses to update {args.update_env}:")
                        for env_var, address in addresses.items():
                            print(f"  {env_var}={address}")
                        
                        fetcher.update_env_file(args.update_env, addresses)
                    else:
                        print("No addresses found in metadata to extract.")
                else:
                    print("\nFull metadata:")
                    print(json.dumps(market_event.get('metadata', {}), indent=2))
            else:
                print(f"No market event found with ID: {proposal_address}")
        
        elif args.market_event_id:
            # Fetch specific market event
            print(f"Fetching market event ID: {args.market_event_id}")
            market_event = fetcher.fetch_market_event(args.market_event_id)
            
            if market_event:
                analysis = fetcher.analyze_market_event(market_event)
                print_analysis_results([analysis])
                
                if args.verbose:
                    print("\nFull metadata:")
                    print(json.dumps(market_event.get('metadata', {}), indent=2))
            
        elif args.search_addresses:
            # Search all market events
            print("Searching all market events for target addresses...")
            results = fetcher.search_all_markets()
            print_analysis_results(results)
        else:
            # Default: use proposal address if available
            proposal_address = os.getenv("FUTARCHY_PROPOSAL_ADDRESS")
            if proposal_address:
                print(f"No arguments provided. Using FUTARCHY_PROPOSAL_ADDRESS: {proposal_address}")
                market_event = fetcher.fetch_market_event(proposal_address)
                
                if market_event:
                    print("Found market event!")
                    print(f"ID: {market_event.get('id')}")
                    print(f"Title: {market_event.get('title', 'N/A')}")
                    print(f"Created: {market_event.get('created_at')}")
                    
                    # Extract addresses if update-env is specified
                    if args.update_env:
                        metadata = market_event.get('metadata', {})
                        addresses = fetcher.extract_addresses_from_metadata(metadata)
                        
                        if addresses:
                            print(f"\nExtracting addresses to update {args.update_env}:")
                            for env_var, address in addresses.items():
                                print(f"  {env_var}={address}")
                            
                            fetcher.update_env_file(args.update_env, addresses)
                        else:
                            print("No addresses found in metadata to extract.")
                    else:
                        print("\nFull metadata:")
                        print(json.dumps(market_event.get('metadata', {}), indent=2))
                else:
                    print(f"No market event found with ID: {proposal_address}")
            else:
                parser.print_help()
            
    except ValueError as e:
        print(f"Configuration error: {e}")
        print("Required environment variables:")
        print("  - SUPABASE_URL")
        print("  - SUPABASE_ANON_KEY (or SUPABASE_EDGE_TOKEN or SUPABASE_SERVICE_ROLE_KEY)")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()