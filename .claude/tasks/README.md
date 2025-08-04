# Claude Tasks

This directory contains task documentation and progress tracking for various development efforts on the futarchy arbitrage bot.

## Active Tasks

### 🔧 pectra-bundled-transactions
**Status**: In Progress  
**Description**: Implementation of Pectra bundled transactions using EIP-7702 for efficient batch execution.
- Developing contracts that avoid 0xEF opcodes
- Testing various Solidity patterns for Pectra compatibility
- Creating production testing plans

### ✅ pnk-price-support-light-bot
**Status**: Completed  
**Description**: Added PNK (Kleros) token price support to the light bot implementation.
- Multi-hop price calculation (PNK → WETH → USD → sDAI)
- Real-time price monitoring in multiple formats
- Complete with documentation and launch scripts

## Task Structure

Each task folder contains:
- `README.md` - Task overview and objectives
- Implementation plans and technical specifications
- Progress tracking and status updates
- Related code samples and analysis

## Completed Tasks Archive

Tasks marked as completed remain in the directory for reference but are no longer actively developed.