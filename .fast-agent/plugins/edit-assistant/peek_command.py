from __future__ import annotations

from fast_agent.command_actions import PluginCommandActionContext, PluginCommandActionResult
from fast_agent.ui.display_suppression import suppress_interactive_display
from fast_agent.ui.progress_display import progress_display


async def peek(ctx: PluginCommandActionContext) -> PluginCommandActionResult:
    """Send a prompt, show the response, then restore the prior chat history."""
    prompt = ctx.arguments.strip()
    if not prompt:
        return PluginCommandActionResult(message="Usage: /peek <message>")

    history = list(ctx.message_history)
    try:
        progress_display.resume()
        with suppress_interactive_display():
            response = await ctx.agent.send(prompt)
    finally:
        ctx.load_message_history(history)

    return PluginCommandActionResult(markdown=response.strip() or "_No response._")
