fetch("https://app.seer.pm/subgraph?_subgraph=algebra&_chainId=100", {
  "headers": {
    "accept": "*/*",
    "accept-language": "en-US,en;q=0.9,pt;q=0.8",
    "cache-control": "no-cache",
    "content-type": "application/json",
    "pragma": "no-cache",
    "priority": "u=1, i",
    "sec-ch-ua": "\"Not;A=Brand\";v=\"99\", \"Google Chrome\";v=\"139\", \"Chromium\";v=\"139\"",
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": "\"macOS\"",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "Referer": "https://app.seer.pm/markets/100/0x9590dAF4d5cd4009c3F9767C5E7668175cFd37CF?outcome=Yes-GNO"
  },
  "body": "{\"query\":\"query GetTicks($skip: Int = 0, $first: Int, $where: Tick_filter, $orderBy: Tick_orderBy, $orderDirection: OrderDirection, $block: Block_height, $subgraphError: _SubgraphErrorPolicy_! = deny) {\\n  ticks(\\n    skip: $skip\\n    first: $first\\n    orderBy: $orderBy\\n    orderDirection: $orderDirection\\n    where: $where\\n    block: $block\\n    subgraphError: $subgraphError\\n  ) {\\n    tickIdx\\n    liquidityNet\\n  }\\n}\",\"variables\":{\"first\":1000,\"orderBy\":\"tickIdx\",\"orderDirection\":\"asc\",\"where\":{\"poolAddress\":\"0x4ff34e270ca54944955b2f595cec4cf53bdc9e0c\"}},\"operationName\":\"GetTicks\"}",
  "method": "POST"
});

<- Response:
{"data":{"ticks":[{"liquidityNet":"28674125081915649513","tickIdx":"-887220"},{"liquidityNet":"-28674125081915649513","tickIdx":"887220"}]}}