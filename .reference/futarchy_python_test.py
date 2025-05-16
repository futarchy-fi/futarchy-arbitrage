from dotenv import load_dotenv
from futarchy import Futarchy
import os

# Load environment variables
load_dotenv()

async def main():
    # Initialize Futarchy
    futarchy = Futarchy(options={
        "use_sushi_v3": True,
        "test_mode": False,
        "debug": True
    })
    
    # Initialize the instance
    await futarchy.initialize()
    
    # Get market name
    market_name = futarchy.get_market_name()
    print(f"Market Name: {market_name}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
