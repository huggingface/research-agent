"""Run the research FastMCP App server."""

import asyncio

from research.fastmcp_server import main


if __name__ == "__main__":
    asyncio.run(main())
