"""Minimal interactive runner that uses the Harness API and research_app intercept."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

from fast_agent import AgentRequest, AppOpenRequest, FastAgent

from research.app_auth import effective_agent_auth


HERE = Path(__file__).parent

def build_fast_agent() -> FastAgent:
    fast = FastAgent(
        "Researcher Harness Chat",
        parse_cli_args=False,
        quiet=True,
        home=HERE / "research",
    )
    fast.load_agents(HERE / "research" / "agent-cards")
    return fast


def enforce_host_isolation(fast: FastAgent) -> None:
    fast.app.context.no_shell = True


async def main() -> None:
    session_id = f"tui-{uuid4().hex[:12]}"
    fast = build_fast_agent()
    auth = effective_agent_auth(None)
    async with fast.harness() as harness:
        enforce_host_isolation(fast)
        with harness.request_context(auth=auth):
            async with harness.app().open(
                AppOpenRequest(
                    session_id=session_id,
                    agent="researcher",
                    metadata={"requested_session_id": session_id},
                )
            ) as app_session:
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
                    print("Research running; this may take several minutes.")
                    response = await app_session.invoke(
                        AgentRequest.text(
                            message,
                            agent="researcher",
                            session_id=session_id,
                            auth=auth,
                            metadata={"requested_session_id": session_id},
                        )
                    )
                    print(response.text_content())


if __name__ == "__main__":
    asyncio.run(main())
