#!/usr/bin/env python3
"""
Analyze bytecode to understand what's causing 0xEF opcodes.
"""

import sys
from pathlib import Path

def analyze_bytecode(bytecode: str, name: str):
    """Analyze bytecode around 0xEF positions."""
    bytecode = bytecode.replace('0x', '')
    
    print(f"\n=== Analyzing {name} ===")
    print(f"Total length: {len(bytecode)} chars ({len(bytecode)//2} bytes)")
    
    # Find all 0xEF positions
    ef_positions = []
    for i in range(0, len(bytecode), 2):
        if bytecode[i:i+2].lower() == 'ef':
            ef_positions.append(i // 2)
    
    if not ef_positions:
        print("No 0xEF opcodes found!")
        return
    
    print(f"Found 0xEF at byte positions: {ef_positions}")
    
    # Analyze context around each 0xEF
    for pos in ef_positions:
        char_pos = pos * 2
        start = max(0, char_pos - 20)
        end = min(len(bytecode), char_pos + 20)
        
        context = bytecode[start:end]
        relative_pos = char_pos - start
        
        print(f"\nContext around position {pos}:")
        print(f"  {context[:relative_pos]}[{context[relative_pos:relative_pos+2]}]{context[relative_pos+2:]}")
        
        # Try to identify the pattern
        # Check if it's part of a push operation
        for push_size in range(1, 33):  # PUSH1 to PUSH32
            push_opcode = 0x60 + push_size - 1
            push_char_pos = char_pos - 2
            if push_char_pos >= 0 and bytecode[push_char_pos:push_char_pos+2] == f"{push_opcode:02x}":
                print(f"  -> Part of PUSH{push_size} data")
                break
        else:
            # Check surrounding opcodes
            if char_pos >= 2:
                prev_opcode = bytecode[char_pos-2:char_pos]
                print(f"  -> Previous opcode: 0x{prev_opcode}")
            if char_pos + 2 < len(bytecode):
                next_opcode = bytecode[char_pos+2:char_pos+4]
                print(f"  -> Next opcode: 0x{next_opcode}")

# Read test compilation output
if __name__ == "__main__":
    # This is a placeholder - in practice, we'd get the bytecode from compilation
    print("This script analyzes bytecode patterns.")
    print("Run test_deployment_fix.py first to get bytecode, then analyze it here.")
    
    # Example analysis of known problematic bytecode
    # In the actual case, we see 0xEF at positions like 838, 870, etc.
    # These are likely part of PUSH operations or other data segments