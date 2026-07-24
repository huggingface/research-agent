"""Minimal interactive runner that uses the Harness API and research_app intercept."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

from fast_agent import AgentRequest, FastAgent


HERE = Path(__file__).parent

fast = FastAgent(
    "Researcher Harness Chat",
    parse_cli_args=False,
    home=HERE / "research",
)
fast.load_agents(HERE / "research" / "agent-cards")


async def main() -> None:
    session_id = f"tui-{uuid4().hex[:12]}"
    async with fast.harness() as harness:
        async with harness.app().open() as app_session:
            print(f"research harness chat session: {session_id}")
            print("Type Ctrl-D or an empty line to exit.")
            while True:
                try:
                    message = input("> ").strip()
                except EOFError:
                    print()
                    return
                if not message:
                    return
                response = await app_session.invoke(
                    AgentRequest.text(
                        message,
                        agent="researcher",
                        session_id=session_id,
                        metadata={"requested_session_id": session_id},
                    )
                )
                print(response.text_content())


if __name__ == "__main__":
    asyncio.run(main())
