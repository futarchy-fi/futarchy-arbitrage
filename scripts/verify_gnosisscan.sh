#!/bin/bash
# Verify contract on Gnosisscan using forge

CONTRACT_ADDRESS="0x65eb5a03635c627a0f254707712812B234753F31"
CONTRACT_NAME="FutarchyBatchExecutorMinimal"
COMPILER_VERSION="0.8.17"

# You need GNOSISSCAN_API_KEY in your environment
if [ -z "$GNOSISSCAN_API_KEY" ]; then
    echo "Error: GNOSISSCAN_API_KEY not set"
    echo "Get your API key from: https://gnosisscan.io/myapikey"
    exit 1
fi

echo "Verifying FutarchyBatchExecutorMinimal on Gnosisscan..."

# Using forge verify-contract
forge verify-contract \
    --chain gnosis \
    --etherscan-api-key $GNOSISSCAN_API_KEY \
    --compiler-version $COMPILER_VERSION \
    --optimizer-runs 200 \
    $CONTRACT_ADDRESS \
    contracts/FutarchyBatchExecutorMinimal.sol:$CONTRACT_NAME