import asyncio
import os
import shlex
import subprocess
import tempfile
from pathlib import Path

from fast_agent.command_actions import (
    PluginCommandActionContext,
    PluginCommandActionResult,
)



async def editlast(ctx: PluginCommandActionContext) -> PluginCommandActionResult:
    """Open the last assistant message in $VISUAL/$EDITOR and prefill edits."""
    for message in reversed(ctx.message_history):
        if message.role != "assistant" or (original := message.last_text()) is None:
            continue

        try:
            edited, saved = await asyncio.to_thread(
                _edit_text,
                original,
                cwd=ctx.session_cwd,
            )
        except subprocess.CalledProcessError as exc:
            return PluginCommandActionResult(
                message=f"Editor exited with status {exc.returncode}."
            )
        except (OSError, UnicodeError, ValueError) as exc:
            return PluginCommandActionResult(message=f"Editor failed: {exc}")

        prefill = _extract_annotated_reply(edited)
        if prefill == original:
            return PluginCommandActionResult(
                message=(
                    "Editor saved without changing the message."
                    if saved
                    else "No saved editor changes detected."
                )
            )

        return PluginCommandActionResult(
            message="Edited last assistant message; review before sending.",
            buffer_prefill=prefill,
        )

    return PluginCommandActionResult(message="No assistant text found.")


def _extract_annotated_reply(text: str) -> str:
    """Return only `:: `-prefixed reply lines when annotations are present."""
    prefix = ":: "
    lines = text.splitlines(keepends=True)
    if not any(line.startswith(prefix) for line in lines):
        return text
    return "".join(line[len(prefix) :] for line in lines if line.startswith(prefix))


def _edit_text(initial_text: str, *, cwd: Path | None = None) -> tuple[str, bool]:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        temp_path = Path(temp_dir, "message.md")
        temp_path.write_text(initial_text, encoding="utf-8")
        before_mtime = temp_path.stat().st_mtime_ns
        subprocess.run([*_editor_args(), str(temp_path)], cwd=cwd, check=True)
        after_mtime = temp_path.stat().st_mtime_ns
        return temp_path.read_text(encoding="utf-8"), after_mtime != before_mtime


def _editor_args() -> list[str]:
    editor_cmd = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    editor_args = shlex.split(editor_cmd or _default_editor(), posix=os.name != "nt")
    if not editor_args:
        raise ValueError("editor command is empty")
    return editor_args


def _default_editor() -> str:
    return "notepad" if os.name == "nt" else "nano"