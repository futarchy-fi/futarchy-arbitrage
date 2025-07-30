#!/bin/bash

# Script to run the PNK light bot with proper environment setup

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}Starting PNK Light Bot...${NC}"

# Check if virtual environment exists
if [ -d "futarchy_env" ]; then
    echo -e "${YELLOW}Activating futarchy_env...${NC}"
    source futarchy_env/bin/activate
elif [ -d "venv" ]; then
    echo -e "${YELLOW}Activating venv...${NC}"
    source venv/bin/activate
else
    echo -e "${RED}Error: No virtual environment found!${NC}"
    echo "Please create a virtual environment first."
    exit 1
fi

# Check if .env.pnk exists
if [ -f ".env.pnk" ]; then
    echo -e "${YELLOW}Loading .env.pnk...${NC}"
    source .env.pnk
else
    echo -e "${RED}Error: .env.pnk not found!${NC}"
    echo "Please create .env.pnk with the following variables:"
    echo "  - WETH_ADDRESS"
    echo "  - RPC_URL"
    echo "  - PNK_TOKEN_ADDRESS (optional)"
    echo "  - WXDAI_ADDRESS (optional)"
    exit 1
fi

# Set default values if not provided
INTERVAL=${1:-60}
MIN_PROFIT=${2:-0.01}

echo -e "${GREEN}Configuration:${NC}"
echo "  Interval: ${INTERVAL} seconds"
echo "  Min Profit: ${MIN_PROFIT}"
echo "  RPC URL: ${RPC_URL}"
echo ""

# Run the bot
python -m src.arbitrage_commands.pnk_light_bot \
    --interval ${INTERVAL} \
    --min-profit ${MIN_PROFIT}