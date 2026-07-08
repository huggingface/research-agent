"""Agent Resource Discovery plugin command."""

from __future__ import annotations

import asyncio
import io
import json
import re
import shlex
import shutil
import tarfile
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

from prompt_toolkit.application import Application
from prompt_toolkit.application.current import get_app_or_none
from prompt_toolkit.data_structures import Point
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.margins import ScrollbarMargin
from prompt_toolkit.widgets import Frame

from fast_agent.command_actions import PluginCommandActionContext, PluginCommandActionResult
from fast_agent.config import MCPServerSettings
from fast_agent.marketplace.formatting import iso_utc_now
from fast_agent.skills.direct_sources import is_direct_skill_source
from fast_agent.skills.models import SKILL_SOURCE_SCHEMA_VERSION, InstalledSkillSource
from fast_agent.skills.provenance import (
    compute_skill_content_fingerprint,
    write_installed_skill_source,
)
from fast_agent.skills.scope import get_manager_directory
from fast_agent.skills.service import install_direct_skill
from fast_agent.ui.picker_theme import build_picker_style

ARD_REGISTRY_URLS = (
    "https://huggingface-hf-discover.hf.space/search",
)
ARD_SERVICE_URL_REWRITES = {
    "https://evalstate-hf-discover.hf.space": "https://huggingface-hf-discover.hf.space",
}
AI_SKILL_MEDIA_TYPE = "application/ai-skill"
MCP_SERVER_MEDIA_TYPE = "application/mcp-server-card+json"
LEGACY_MCP_SERVER_MEDIA_TYPE = "application/mcp-server+json"
A2A_AGENT_CARD_MEDIA_TYPE = "application/a2a-agent-card+json"
AI_REGISTRY_MEDIA_TYPE = "application/ai-registry+json"
MAX_SKILL_ARCHIVE_BYTES = 50 * 1024 * 1024
MAX_SKILL_ARCHIVE_UNPACKED_BYTES = 100 * 1024 * 1024
MAX_ERROR_SNIPPET_CHARS = 240
FEDERATION_MODES = {"auto", "referrals", "none"}


@dataclass(frozen=True, slots=True)
class SkillAction:
    label: str
    value: str
    enabled: bool = True
    hint: str = ""


@dataclass(frozen=True, slots=True)
class FinderRegistry:
    index: int
    url: str

    @property
    def display_name(self) -> str:
        return self.url.removesuffix("/search").removeprefix("https://").removeprefix("http://")


@dataclass(frozen=True, slots=True)
class DiscoverOptions:
    query: str
    federation: str = "auto"
    follow_referrals: bool = False


@dataclass(frozen=True, slots=True)
class FinderResult:
    index: int
    identifier: str
    display_name: str
    media_type: str
    description: str
    score: float
    url: str | None
    data: dict[str, Any] | None
    metadata: dict[str, Any] | None
    source: str | None

    @property
    def kind(self) -> str:
        if self.media_type in {MCP_SERVER_MEDIA_TYPE, LEGACY_MCP_SERVER_MEDIA_TYPE}:
            return "mcp"
        if self.media_type == AI_SKILL_MEDIA_TYPE:
            return "skill"
        if self.media_type == A2A_AGENT_CARD_MEDIA_TYPE:
            return "a2a"
        if self.media_type == AI_REGISTRY_MEDIA_TYPE:
            return "registry"
        return self.media_type.rsplit("/", 1)[-1][:12]


async def discover(ctx: PluginCommandActionContext) -> PluginCommandActionResult:
    """Search Agent Resource Discovery and interactively apply one selected result."""
    try:
        options = _parse_discover_arguments(ctx.arguments)
    except ValueError as exc:
        return PluginCommandActionResult(message=str(exc))

    try:
        registry_url = await _select_registry(ctx)
    except KeyboardInterrupt:
        return PluginCommandActionResult()

    if registry_url is None:
        return PluginCommandActionResult()

    try:
        results = await _search_ard(
            registry_url,
            options.query,
            federation=options.federation,
            follow_referrals=options.follow_referrals,
        )
    except Exception as exc:  # noqa: BLE001
        return PluginCommandActionResult(message=f"Agent Resource Discovery search failed: {exc}")

    if not results:
        return PluginCommandActionResult(
            message=f"No Agent Resource Discovery results for: {options.query}"
        )

    if not ctx.is_tui:
        return PluginCommandActionResult(markdown=_render_results_markdown(options.query, results))

    visited_registries = {registry_url}
    try:
        while True:
            selected = await _select_result(options.query, results)
            if selected is None or selected.media_type != AI_REGISTRY_MEDIA_TYPE:
                break

            nested_url = _registry_result_search_url(selected)
            if nested_url is None:
                return PluginCommandActionResult(
                    message="Selected registry did not include a search URL."
                )
            if nested_url in visited_registries:
                return PluginCommandActionResult(
                    message=f"Registry already visited: {nested_url}"
                )
            visited_registries.add(nested_url)
            results = await _search_ard(
                nested_url,
                options.query,
                federation="none",
                follow_referrals=False,
            )
            if not results:
                return PluginCommandActionResult(
                    message=f"No Agent Resource Discovery results in registry: {nested_url}"
                )
    except KeyboardInterrupt:
        return PluginCommandActionResult()
    except Exception as exc:  # noqa: BLE001
        return PluginCommandActionResult(message=f"Agent Resource Discovery search failed: {exc}")

    if selected is None:
        return PluginCommandActionResult()

    if selected.media_type in {MCP_SERVER_MEDIA_TYPE, LEGACY_MCP_SERVER_MEDIA_TYPE}:
        return await _handle_mcp_result(ctx, selected)

    if selected.media_type == AI_SKILL_MEDIA_TYPE:
        return await _handle_skill_result(ctx, options.query, selected)

    return PluginCommandActionResult(
        message=f"Selected result has unsupported media type: {selected.media_type}"
    )


def _parse_discover_arguments(arguments: str) -> DiscoverOptions:
    tokens = shlex.split(arguments)
    federation = "auto"
    follow_referrals = False
    query_parts: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "--follow-referrals":
            follow_referrals = True
            index += 1
            continue
        if token == "--no-follow-referrals":
            follow_referrals = False
            index += 1
            continue
        if token == "--federation":
            if index + 1 >= len(tokens):
                raise ValueError(_discover_usage())
            federation = tokens[index + 1].lower()
            if federation not in FEDERATION_MODES:
                raise ValueError("federation must be one of: auto, referrals, none")
            index += 2
            continue
        if token.startswith("--federation="):
            federation = token.partition("=")[2].lower()
            if federation not in FEDERATION_MODES:
                raise ValueError("federation must be one of: auto, referrals, none")
            index += 1
            continue
        query_parts.append(token)
        index += 1

    query = " ".join(query_parts).strip()
    if not query:
        raise ValueError(_discover_usage())
    if follow_referrals and federation == "none":
        federation = "referrals"
    return DiscoverOptions(query=query, federation=federation, follow_referrals=follow_referrals)


def _discover_usage() -> str:
    return (
        "Usage: /discover [--federation none|auto|referrals] "
        "[--follow-referrals] <thing you need>"
    )


async def _select_registry(ctx: PluginCommandActionContext) -> str | None:
    urls = _configured_registry_urls(ctx)
    if not urls:
        return None
    if len(urls) == 1 or not ctx.is_tui:
        return urls[0]
    registries = [FinderRegistry(index=index, url=url) for index, url in enumerate(urls, start=1)]
    selected = await _RegistryPicker(registries=registries).run_async()
    return selected.url if selected else None


def _configured_registry_urls(ctx: PluginCommandActionContext) -> list[str]:
    config = _discover_plugin_config(ctx)
    include_defaults = config.get("include_default_urls", True) is not False
    urls: list[str] = list(ARD_REGISTRY_URLS) if include_defaults else []

    configured_urls = config.get("urls")
    if isinstance(configured_urls, str):
        urls.append(configured_urls)
    elif isinstance(configured_urls, list):
        urls.extend(url for url in configured_urls if isinstance(url, str))

    configured_registries = config.get("registries")
    if isinstance(configured_registries, str):
        urls.append(configured_registries)
    elif isinstance(configured_registries, list):
        urls.extend(url for url in configured_registries if isinstance(url, str))

    return list(dict.fromkeys(_registry_search_url(_normalize_ard_service_url(url)) for url in urls))


def _discover_plugin_config(ctx: PluginCommandActionContext) -> dict[str, Any]:
    if ctx.settings is None:
        return {}

    merged: dict[str, Any] = {}
    names = list(dict.fromkeys(("discover", "discover-dev", ctx.command_name)))
    for name in names:
        config = ctx.settings.plugins.config.get(name)
        if isinstance(config, dict):
            merged.update(config)
    return merged


async def _search_ard(
    registry_url: str,
    query: str,
    *,
    federation: str = "auto",
    follow_referrals: bool = False,
) -> list[FinderResult]:
    payload = {
        "query": {
            "text": query,
        },
        "federation": federation,
        "pageSize": 10,
    }
    body = await asyncio.to_thread(_post_json, registry_url, payload)
    results = _parse_results(body.get("results", []), start_index=1)
    referrals = _parse_results(body.get("referrals", []), start_index=len(results) + 1)

    if not follow_referrals:
        return [*results, *referrals]

    seen = {result.identifier for result in results}
    for referral in referrals:
        if not referral.url:
            continue
        nested_url = _registry_search_url(referral.url)
        nested_body = await asyncio.to_thread(
            _post_json,
            nested_url,
            {
                "query": {"text": query},
                "federation": "none",
                "pageSize": 10,
            },
        )
        for result in _parse_results(nested_body.get("results", []), start_index=len(results) + 1):
            if result.identifier in seen:
                continue
            seen.add(result.identifier)
            results.append(result)

    return results


def _parse_results(raw_results: object, *, start_index: int) -> list[FinderResult]:
    if not isinstance(raw_results, list):
        return []

    results: list[FinderResult] = []
    for index, item in enumerate(raw_results, start=start_index):
        if not isinstance(item, dict):
            continue
        media_type = _str(item.get("type")) or _str(item.get("mediaType"))
        results.append(
            FinderResult(
                index=index,
                identifier=_str(item.get("identifier")),
                display_name=_str(item.get("displayName")) or _str(item.get("identifier")),
                media_type=media_type,
                description=_str(item.get("description")),
                score=_float(item.get("score")),
                url=_optional_url(item.get("url")),
                data=item.get("data") if isinstance(item.get("data"), dict) else None,
                metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else None,
                source=_optional_url(item.get("source")),
            )
        )
    return results


def _registry_search_url(url: str) -> str:
    stripped = url.rstrip("/")
    return stripped if stripped.endswith("/search") else f"{stripped}/search"


def _registry_result_search_url(result: FinderResult) -> str | None:
    url = result.url or _optional_url((result.data or {}).get("url"))
    return _registry_search_url(url) if url else None


def _post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=data,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "fast-agent-discover-plugin/0.2",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:  # noqa: S310 - user-invoked registry URL
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        raise RuntimeError(_http_error_message(exc)) from exc
    except URLError as exc:
        raise RuntimeError(str(exc.reason)) from exc

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Registry returned invalid JSON: {_snippet(raw)}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("Agent Resource Discovery returned a non-object JSON response.")
    return parsed


async def _select_result(query: str, results: list[FinderResult]) -> FinderResult | None:
    picker = _FinderPicker(query=query, results=results)
    return await picker.run_async()


def _row_label(result: FinderResult) -> str:
    score = f"{result.score:5.1f}"
    kind = result.kind[:5].ljust(5)
    name = _truncate(result.display_name, 32).ljust(32)
    description = _truncate(result.description, 82)
    return f"{score}  {kind}  {name}  {description}"


class _FinderPicker:
    VISIBLE_ROWS = 10
    DETAILS_ROWS = 5

    def __init__(self, *, query: str, results: list[FinderResult]) -> None:
        self.query = query
        self.results = results
        self.index = 0

        self.selection_control = FormattedTextControl(
            self._render_results,
            focusable=True,
            show_cursor=False,
            get_cursor_position=self._cursor_position,
        )
        self.header_control = FormattedTextControl(self._render_header)
        self.details_control = FormattedTextControl(self._render_details)

        selection_window = Window(
            self.selection_control,
            wrap_lines=False,
            height=Dimension.exact(min(self.VISIBLE_ROWS, max(1, len(results)))),
            dont_extend_height=True,
            ignore_content_width=True,
            always_hide_cursor=True,
            right_margins=[ScrollbarMargin(display_arrows=False)],
        )
        header_window = Window(
            self.header_control,
            height=Dimension.exact(1),
            dont_extend_height=True,
        )
        details_window = Window(
            self.details_control,
            height=Dimension.exact(self.DETAILS_ROWS),
            dont_extend_height=True,
        )
        body = HSplit(
            [
                Frame(
                    HSplit(
                        [
                            header_window,
                            selection_window,
                        ]
                    ),
                    title=f"Agent Resource Discovery: {query}",
                ),
                details_window,
            ]
        )
        self.app: Application[FinderResult | None] = Application(
            layout=Layout(body, focused_element=selection_window),
            key_bindings=self._create_key_bindings(),
            style=build_picker_style(),
            full_screen=False,
            mouse_support=False,
            erase_when_done=True,
        )

    @property
    def selected(self) -> FinderResult:
        self.index = max(0, min(self.index, len(self.results) - 1))
        return self.results[self.index]

    def _cursor_position(self) -> Point | None:
        if not self.results:
            return None
        return Point(x=0, y=self.index)

    def _terminal_cols(self) -> int:
        app = get_app_or_none()
        if app is not None:
            try:
                return max(1, app.output.get_size().columns)
            except Exception:
                pass
        return max(1, shutil.get_terminal_size((100, 20)).columns)

    def _result_widths(self) -> tuple[int, int]:
        width = max(60, self._terminal_cols() - 4)
        name_width = max(18, min(32, width // 3))
        description_width = max(20, width - name_width - 18)
        return name_width, description_width

    def _render_header(self) -> list[tuple[str, str]]:
        name_width, _ = self._result_widths()
        return [
            ("class:muted", f"  {'score':>5}  {'type':<5}  {'name':<{name_width}}  description")
        ]

    def _render_results(self) -> list[tuple[str, str]]:
        name_width, description_width = self._result_widths()
        fragments: list[tuple[str, str]] = [
        ]

        for index, result in enumerate(self.results):
            selected = index == self.index
            cursor = "❯ " if selected else "  "
            style = _row_style(
                selected=selected,
                supported=_is_supported_media_type(result.media_type),
                registry=result.media_type == AI_REGISTRY_MEDIA_TYPE,
            )
            fragments.append(
                (
                    style,
                    f"{cursor}{result.score:5.1f}  "
                    f"{result.kind[:5]:<5}  "
                    f"{_truncate(result.display_name, name_width):<{name_width}}  "
                    f"{_truncate(result.description, description_width)}\n",
                )
            )
        return fragments

    def _render_details(self) -> list[tuple[str, str]]:
        result = self.selected
        action = (
            "Enter: MCP actions"
            if result.media_type in {MCP_SERVER_MEDIA_TYPE, LEGACY_MCP_SERVER_MEDIA_TYPE}
            else "Enter: skill actions"
            if result.media_type == AI_SKILL_MEDIA_TYPE
            else "Enter: open registry"
            if result.media_type == AI_REGISTRY_MEDIA_TYPE
            else "unsupported"
        )
        location = result.url or _str((result.data or {}).get("url")) or result.identifier
        title_style = (
            "ansiblue"
            if result.media_type == AI_REGISTRY_MEDIA_TYPE
            else "class:focus"
            if _is_supported_media_type(result.media_type)
            else "ansired"
        )
        return [
            (title_style, f"{result.display_name} · {result.kind} · score {result.score:.1f}\n"),
            ("", f"{_truncate(result.description, self._terminal_cols() - 2)}\n"),
            ("class:muted", f"{_truncate(location, self._terminal_cols() - 2)}\n"),
            ("class:muted", f"Keys: ↑/↓ move · {action} · q/Esc/Ctrl-C cancel"),
        ]

    def _move(self, delta: int) -> None:
        if not self.results:
            return
        self.index = (self.index + delta) % len(self.results)

    def _create_key_bindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("up")
        def _up(event) -> None:
            self._move(-1)
            event.app.invalidate()

        @kb.add("down")
        def _down(event) -> None:
            self._move(1)
            event.app.invalidate()

        @kb.add("enter")
        def _accept(event) -> None:
            event.app.exit(result=self.selected)

        @kb.add("q")
        @kb.add("escape")
        @kb.add("c-c")
        def _quit(event) -> None:
            event.app.exit(result=None)

        return kb

    async def run_async(self) -> FinderResult | None:
        with nullcontext():
            return await self.app.run_async()


class _SkillActionPicker:
    VISIBLE_ROWS = 3

    def __init__(self, *, result: FinderResult) -> None:
        self.result = result
        self.actions = [
            SkillAction("Install Skill", "install"),
            SkillAction(
                "Add to User Prompt",
                "prompt",
                enabled=_can_add_skill_to_prompt(result),
                hint="" if _can_add_skill_to_prompt(result) else "not available for bundles/repos",
            ),
            SkillAction("Cancel", "cancel"),
        ]
        self.index = 0
        self._normalize_index()

        self.selection_control = FormattedTextControl(
            self._render_actions,
            focusable=True,
            show_cursor=False,
            get_cursor_position=self._cursor_position,
        )
        self.details_control = FormattedTextControl(self._render_details)

        selection_window = Window(
            self.selection_control,
            wrap_lines=False,
            height=Dimension.exact(self.VISIBLE_ROWS),
            dont_extend_height=True,
            ignore_content_width=True,
            always_hide_cursor=True,
        )
        details_window = Window(
            self.details_control,
            height=Dimension.exact(4),
            dont_extend_height=True,
        )
        body = HSplit(
            [
                Frame(selection_window, title=f"Skill: {result.display_name}"),
                details_window,
            ]
        )
        self.app: Application[str | None] = Application(
            layout=Layout(body, focused_element=selection_window),
            key_bindings=self._create_key_bindings(),
            style=build_picker_style(),
            full_screen=False,
            mouse_support=False,
            erase_when_done=True,
        )

    @property
    def selected(self) -> SkillAction:
        self._normalize_index()
        return self.actions[self.index]

    def _normalize_index(self) -> None:
        self.index = max(0, min(self.index, len(self.actions) - 1))
        if self.actions[self.index].enabled:
            return
        for offset in range(1, len(self.actions) + 1):
            candidate = (self.index + offset) % len(self.actions)
            if self.actions[candidate].enabled:
                self.index = candidate
                return

    def _cursor_position(self) -> Point | None:
        return Point(x=0, y=self.index)

    def _terminal_cols(self) -> int:
        app = get_app_or_none()
        if app is not None:
            try:
                return max(1, app.output.get_size().columns)
            except Exception:
                pass
        return max(1, shutil.get_terminal_size((100, 20)).columns)

    def _render_actions(self) -> list[tuple[str, str]]:
        fragments: list[tuple[str, str]] = []
        for index, action in enumerate(self.actions):
            selected = index == self.index
            cursor = "❯ " if selected else "  "
            suffix = f" ({action.hint})" if action.hint else ""
            style = _action_style(selected=selected, enabled=action.enabled)
            fragments.append((style, f"{cursor}{action.label}{suffix}\n"))
        return fragments

    def _render_details(self) -> list[tuple[str, str]]:
        location = self.result.url or self.result.identifier
        return [
            ("class:focus", f"{self.result.display_name} · score {self.result.score:.1f}\n"),
            ("", f"{_truncate(self.result.description, self._terminal_cols() - 2)}\n"),
            ("class:muted", f"{_truncate(location, self._terminal_cols() - 2)}\n"),
            ("class:muted", "Keys: ↑/↓ move · Enter select · q/Esc/Ctrl-C cancel"),
        ]

    def _move(self, delta: int) -> None:
        for offset in range(1, len(self.actions) + 1):
            candidate = (self.index + (delta * offset)) % len(self.actions)
            if self.actions[candidate].enabled:
                self.index = candidate
                return

    def _create_key_bindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("up")
        def _up(event) -> None:
            self._move(-1)
            event.app.invalidate()

        @kb.add("down")
        def _down(event) -> None:
            self._move(1)
            event.app.invalidate()

        @kb.add("enter")
        def _accept(event) -> None:
            action = self.selected
            event.app.exit(result=action.value if action.enabled else None)

        @kb.add("q")
        @kb.add("escape")
        @kb.add("c-c")
        def _quit(event) -> None:
            event.app.exit(result=None)

        return kb

    async def run_async(self) -> str | None:
        with nullcontext():
            return await self.app.run_async()


class _McpActionPicker:
    VISIBLE_ROWS = 3

    def __init__(self, *, result: FinderResult, can_connect: bool) -> None:
        self.result = result
        self.actions = [
            SkillAction(
                "Connect MCP Server",
                "connect",
                enabled=can_connect,
                hint="" if can_connect else "runtime MCP unavailable",
            ),
            SkillAction(
                "Add MCP Config to User Prompt",
                "prompt",
                enabled=_can_add_mcp_to_prompt(result),
                hint="" if _can_add_mcp_to_prompt(result) else "no server data/card URL",
            ),
            SkillAction("Cancel", "cancel"),
        ]
        self.index = 0
        self._normalize_index()

        self.selection_control = FormattedTextControl(
            self._render_actions,
            focusable=True,
            show_cursor=False,
            get_cursor_position=self._cursor_position,
        )
        self.details_control = FormattedTextControl(self._render_details)

        selection_window = Window(
            self.selection_control,
            wrap_lines=False,
            height=Dimension.exact(self.VISIBLE_ROWS),
            dont_extend_height=True,
            ignore_content_width=True,
            always_hide_cursor=True,
        )
        details_window = Window(
            self.details_control,
            height=Dimension.exact(4),
            dont_extend_height=True,
        )
        body = HSplit(
            [
                Frame(selection_window, title=f"MCP Server: {result.display_name}"),
                details_window,
            ]
        )
        self.app: Application[str | None] = Application(
            layout=Layout(body, focused_element=selection_window),
            key_bindings=self._create_key_bindings(),
            style=build_picker_style(),
            full_screen=False,
            mouse_support=False,
            erase_when_done=True,
        )

    @property
    def selected(self) -> SkillAction:
        self._normalize_index()
        return self.actions[self.index]

    def _normalize_index(self) -> None:
        self.index = max(0, min(self.index, len(self.actions) - 1))
        if self.actions[self.index].enabled:
            return
        for offset in range(1, len(self.actions) + 1):
            candidate = (self.index + offset) % len(self.actions)
            if self.actions[candidate].enabled:
                self.index = candidate
                return

    def _cursor_position(self) -> Point | None:
        return Point(x=0, y=self.index)

    def _terminal_cols(self) -> int:
        app = get_app_or_none()
        if app is not None:
            try:
                return max(1, app.output.get_size().columns)
            except Exception:
                pass
        return max(1, shutil.get_terminal_size((100, 20)).columns)

    def _render_actions(self) -> list[tuple[str, str]]:
        fragments: list[tuple[str, str]] = []
        for index, action in enumerate(self.actions):
            selected = index == self.index
            cursor = "❯ " if selected else "  "
            suffix = f" ({action.hint})" if action.hint else ""
            style = _action_style(selected=selected, enabled=action.enabled)
            fragments.append((style, f"{cursor}{action.label}{suffix}\n"))
        return fragments

    def _render_details(self) -> list[tuple[str, str]]:
        location = (
            self.result.url or _str((self.result.data or {}).get("url")) or self.result.identifier
        )
        return [
            ("class:focus", f"{self.result.display_name} · score {self.result.score:.1f}\n"),
            ("", f"{_truncate(self.result.description, self._terminal_cols() - 2)}\n"),
            ("class:muted", f"{_truncate(location, self._terminal_cols() - 2)}\n"),
            ("class:muted", "Keys: ↑/↓ move · Enter select · q/Esc/Ctrl-C cancel"),
        ]

    def _move(self, delta: int) -> None:
        for offset in range(1, len(self.actions) + 1):
            candidate = (self.index + (delta * offset)) % len(self.actions)
            if self.actions[candidate].enabled:
                self.index = candidate
                return

    def _create_key_bindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("up")
        def _up(event) -> None:
            self._move(-1)
            event.app.invalidate()

        @kb.add("down")
        def _down(event) -> None:
            self._move(1)
            event.app.invalidate()

        @kb.add("enter")
        def _accept(event) -> None:
            action = self.selected
            event.app.exit(result=action.value if action.enabled else None)

        @kb.add("q")
        @kb.add("escape")
        @kb.add("c-c")
        def _quit(event) -> None:
            event.app.exit(result=None)

        return kb

    async def run_async(self) -> str | None:
        with nullcontext():
            return await self.app.run_async()


class _RegistryPicker:
    VISIBLE_ROWS = 6

    def __init__(self, *, registries: list[FinderRegistry]) -> None:
        self.registries = registries
        self.index = 0

        self.selection_control = FormattedTextControl(
            self._render_registries,
            focusable=True,
            show_cursor=False,
            get_cursor_position=self._cursor_position,
        )
        self.header_control = FormattedTextControl(lambda: [("class:muted", "  Registry")])
        selection_window = Window(
            self.selection_control,
            wrap_lines=False,
            height=Dimension.exact(min(self.VISIBLE_ROWS, max(1, len(registries)))),
            dont_extend_height=True,
            ignore_content_width=True,
            always_hide_cursor=True,
            right_margins=[ScrollbarMargin(display_arrows=False)],
        )
        header_window = Window(
            self.header_control,
            height=Dimension.exact(1),
            dont_extend_height=True,
        )
        body = Frame(
            HSplit(
                [
                    header_window,
                    selection_window,
                ]
            ),
            title="Choose ARD registry",
        )
        self.app: Application[FinderRegistry | None] = Application(
            layout=Layout(body, focused_element=selection_window),
            key_bindings=self._create_key_bindings(),
            style=build_picker_style(),
            full_screen=False,
            mouse_support=False,
            erase_when_done=True,
        )

    @property
    def selected(self) -> FinderRegistry:
        self.index = max(0, min(self.index, len(self.registries) - 1))
        return self.registries[self.index]

    def _cursor_position(self) -> Point | None:
        if not self.registries:
            return None
        return Point(x=0, y=self.index)

    def _terminal_cols(self) -> int:
        app = get_app_or_none()
        if app is not None:
            try:
                return max(1, app.output.get_size().columns)
            except Exception:
                pass
        return max(1, shutil.get_terminal_size((100, 20)).columns)

    def _render_registries(self) -> list[tuple[str, str]]:
        width = max(60, self._terminal_cols() - 4)
        fragments: list[tuple[str, str]] = []
        for index, registry in enumerate(self.registries):
            selected = index == self.index
            cursor = "❯ " if selected else "  "
            style = "class:selected" if selected else ""
            fragments.append(
                (
                    style,
                    f"{cursor}{_truncate(registry.display_name, width - 2)}\n",
                )
            )
        return fragments

    def _move(self, delta: int) -> None:
        if not self.registries:
            return
        self.index = (self.index + delta) % len(self.registries)

    def _create_key_bindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("up")
        def _up(event) -> None:
            self._move(-1)
            event.app.invalidate()

        @kb.add("down")
        def _down(event) -> None:
            self._move(1)
            event.app.invalidate()

        @kb.add("enter")
        def _accept(event) -> None:
            event.app.exit(result=self.selected)

        @kb.add("q")
        @kb.add("escape")
        @kb.add("c-c")
        def _quit(event) -> None:
            event.app.exit(result=None)

        return kb

    async def run_async(self) -> FinderRegistry | None:
        with nullcontext():
            return await self.app.run_async()


async def _attach_mcp_result(
    ctx: PluginCommandActionContext,
    result: FinderResult,
) -> PluginCommandActionResult:
    if ctx.runtime is None:
        return PluginCommandActionResult(message="Runtime MCP capabilities are not available.")

    server_name = _server_name(result)
    try:
        server_config = await _mcp_server_settings(result, server_name)
    except Exception as exc:  # noqa: BLE001
        return PluginCommandActionResult(message=f"Failed to prepare MCP server config: {exc}")
    await ctx.runtime.attach_mcp_server(
        server_name=server_name,
        server_config=server_config,
    )
    return PluginCommandActionResult(
        message=f"Connected MCP server: {server_name}\n\n{result.description}"
    )


async def _handle_mcp_result(
    ctx: PluginCommandActionContext,
    result: FinderResult,
) -> PluginCommandActionResult:
    if ctx.is_tui:
        try:
            action = await _McpActionPicker(
                result=result,
                can_connect=ctx.runtime is not None,
            ).run_async()
        except KeyboardInterrupt:
            return PluginCommandActionResult()
        if action in {None, "cancel"}:
            return PluginCommandActionResult()
        if action == "connect":
            return await _attach_mcp_result(ctx, result)
        if action == "prompt":
            return await _prefill_mcp_result(result)

    return await _prefill_mcp_result(result)


async def _mcp_server_settings(result: FinderResult, server_name: str) -> MCPServerSettings:
    data = dict(result.data or {})
    data.setdefault("name", server_name)
    data.setdefault("description", result.description or result.display_name)
    if not data.get("url") and result.url:
        data["url"] = (
            await asyncio.to_thread(_mcp_url_from_ard_reference, result.url)
            if result.media_type == MCP_SERVER_MEDIA_TYPE
            else result.url
        )
    return MCPServerSettings.model_validate(data)


def _server_name(result: FinderResult) -> str:
    data_name = _str((result.data or {}).get("name"))
    if data_name:
        return _slug(data_name)
    metadata_space_id = _str(((result.data or {}).get("metadata") or {}).get("spaceId"))
    if metadata_space_id:
        return _slug(f"hf-space-{metadata_space_id}")
    return _slug(result.display_name or result.identifier or "discover-mcp")


async def _prefill_mcp_result(result: FinderResult) -> PluginCommandActionResult:
    if not _can_add_mcp_to_prompt(result):
        return PluginCommandActionResult(
            message="Add to User Prompt requires MCP server data or a server card URL."
        )

    try:
        payload, label = await _mcp_prompt_payload(result)
    except Exception as exc:  # noqa: BLE001
        return PluginCommandActionResult(message=f"Failed to prepare MCP prompt config: {exc}")

    prefill = (
        "Use this discovered MCP server configuration if it is useful for the task below.\n\n"
        f"Discovered MCP server: {result.display_name}\n\n"
        f"{result.description}\n\n"
        f"{label}:\n\n"
        "```json\n"
        f"{json.dumps(payload, indent=2, sort_keys=True)}\n"
        "```\n"
    )
    return PluginCommandActionResult(
        message=f"Added MCP config to prompt: {result.display_name}",
        buffer_prefill=prefill,
    )


async def _mcp_prompt_payload(result: FinderResult) -> tuple[dict[str, Any], str]:
    server_name = _server_name(result)
    if result.media_type == MCP_SERVER_MEDIA_TYPE and result.url:
        card = await asyncio.to_thread(_get_json, result.url)
        return card, "MCP server card"

    data = dict(result.data or {})
    data.setdefault("name", server_name)
    data.setdefault("description", result.description or result.display_name)
    if not data.get("url") and result.url:
        data["url"] = result.url

    server_config = {key: value for key, value in data.items() if key != "name"}
    return {"mcpServers": {server_name: server_config}}, "mcp.json"


async def _handle_skill_result(
    ctx: PluginCommandActionContext,
    query: str,
    result: FinderResult,
) -> PluginCommandActionResult:
    if ctx.is_tui:
        try:
            action = await _SkillActionPicker(result=result).run_async()
        except KeyboardInterrupt:
            return PluginCommandActionResult()
        if action in {None, "cancel"}:
            return PluginCommandActionResult()
        if action == "install":
            return await _install_skill_result(ctx, result)
        if action == "prompt":
            return await _prefill_skill_result(query, result)

    return await _prefill_skill_result(query, result)


async def _install_skill_result(
    ctx: PluginCommandActionContext,
    result: FinderResult,
) -> PluginCommandActionResult:
    if not result.url:
        return PluginCommandActionResult(message="Selected skill did not include an install URL.")

    destination_root = get_manager_directory(
        ctx.settings,
        cwd=ctx.session_cwd or Path.cwd(),
    )
    try:
        if is_direct_skill_source(result.url):
            installed = await install_direct_skill(result.url, destination_root=destination_root)
            skill_dir = installed.skill_dir
            name = installed.name
        elif _looks_like_skill_archive(result.url):
            skill_dir = await asyncio.to_thread(
                _install_skill_archive,
                result,
                destination_root,
            )
            name = skill_dir.name
        else:
            return PluginCommandActionResult(
                message=(
                    "Selected skill URL is not directly installable. "
                    f"Try `/skills add {result.url}`."
                )
            )
    except Exception as exc:  # noqa: BLE001
        return PluginCommandActionResult(message=f"Failed to install skill: {exc}")

    return PluginCommandActionResult(
        message=f"Installed skill: {name}\n\nlocation: {skill_dir}",
        refresh_agents=True,
    )


async def _prefill_skill_result(query: str, result: FinderResult) -> PluginCommandActionResult:
    if not result.url:
        return PluginCommandActionResult(message="Selected skill did not include a download URL.")

    if not _can_add_skill_to_prompt(result):
        return PluginCommandActionResult(
            message="Add to User Prompt is only available for text SKILL.md results."
        )

    try:
        skill_markdown = await asyncio.to_thread(_get_text, result.url)
    except Exception as exc:  # noqa: BLE001
        return PluginCommandActionResult(message=f"Failed to download selected skill: {exc}")

    prefill = (
        "Use this discovered skill to help with the task below.\n\n"
        f"Task: {query}\n\n"
        "Discovered skill:\n\n"
        f"{skill_markdown.strip()}\n"
    )
    return PluginCommandActionResult(
        message=f"Downloaded skill: {result.display_name}",
        buffer_prefill=prefill,
    )


def _install_skill_archive(result: FinderResult, destination_root: Path) -> Path:
    destination_root.mkdir(parents=True, exist_ok=True)
    install_dir = destination_root / _skill_install_dir_name(result)
    if install_dir.exists():
        raise FileExistsError(f"Skill already exists: {install_dir}")

    if result.url is None:
        raise RuntimeError("Selected skill did not include an install URL.")

    archive_bytes = _get_bytes(result.url, max_bytes=MAX_SKILL_ARCHIVE_BYTES)
    try:
        _extract_skill_archive(archive_bytes, install_dir)
        if not (install_dir / "SKILL.md").is_file():
            raise RuntimeError("Skill archive must contain SKILL.md at the root.")
        _write_ard_skill_provenance(install_dir, result)
    except Exception:
        if install_dir.exists():
            shutil.rmtree(install_dir)
        raise
    return install_dir


def _write_ard_skill_provenance(skill_dir: Path, result: FinderResult) -> None:
    metadata = result.metadata or {}
    source = InstalledSkillSource(
        schema_version=SKILL_SOURCE_SCHEMA_VERSION,
        installed_via="marketplace",
        source_origin="remote",
        repo_url=_ard_repo_url(result),
        repo_ref=None,
        repo_path=_ard_repo_path(result),
        source_url=result.url or _optional_str(metadata.get("artifactUrl")),
        installed_commit=None,
        installed_path_oid=None,
        installed_revision=_ard_installed_revision(result),
        installed_at=iso_utc_now(),
        content_fingerprint=compute_skill_content_fingerprint(skill_dir),
        artifact_digest=_optional_str(metadata.get("digest")),
        artifact_type=_optional_str(metadata.get("agentSkillsType")),
    )
    write_installed_skill_source(skill_dir, source)


def _ard_repo_url(result: FinderResult) -> str:
    metadata = result.metadata or {}
    return (
        result.source
        or _optional_str(metadata.get("sourceUrl"))
        or _optional_str(metadata.get("repo"))
        or result.identifier
        or "ard"
    )


def _ard_repo_path(result: FinderResult) -> str:
    metadata = result.metadata or {}
    return (
        _optional_str(metadata.get("path"))
        or _optional_str(metadata.get("skill"))
        or _optional_str(metadata.get("skill_name"))
        or _skill_install_dir_name(result)
    )


def _ard_installed_revision(result: FinderResult) -> str:
    metadata = result.metadata or {}
    return (
        _optional_str(metadata.get("version"))
        or _optional_str(metadata.get("digest"))
        or result.identifier
        or "ard"
    )


def _extract_skill_archive(archive_bytes: bytes, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    total_size = 0
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:*") as archive:
        for member in archive.getmembers():
            _validate_archive_member(member)
            if member.isfile():
                total_size += member.size
                if total_size > MAX_SKILL_ARCHIVE_UNPACKED_BYTES:
                    raise RuntimeError("Skill archive unpacked size exceeds limit.")
        archive.extractall(destination, filter="data")


def _validate_archive_member(member: tarfile.TarInfo) -> None:
    path = Path(member.name)
    if path.is_absolute() or ".." in path.parts:
        raise RuntimeError(f"Unsafe path in skill archive: {member.name}")
    if member.issym() or member.islnk():
        raise RuntimeError("Skill archives must not contain links.")


def _skill_install_dir_name(result: FinderResult) -> str:
    metadata = result.data or {}
    name = _str(metadata.get("name")) or _filename_stem(result.url) or result.display_name
    return _slug(name).lower()


def _filename_stem(url: str | None) -> str:
    if not url:
        return ""
    name = Path(unquote(urlparse(url).path)).name
    for suffix in (".tar.gz", ".tgz", ".tar", ".zip", ".md", ".txt"):
        if name.lower().endswith(suffix):
            return name[: -len(suffix)]
    return Path(name).stem


def _mcp_url_from_ard_reference(url: str) -> str:
    descriptor = _get_json(url)
    remotes = descriptor.get("remotes")
    if isinstance(remotes, list):
        for remote in remotes:
            if not isinstance(remote, dict):
                continue
            remote_url = _optional_str(remote.get("url"))
            if remote_url:
                return remote_url

    direct_url = _optional_str(descriptor.get("url"))
    if direct_url:
        return direct_url

    raise RuntimeError("MCP server card did not include a usable remote URL.")


def _get_json(url: str) -> dict[str, Any]:
    raw = _get_text(url)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"ARD reference returned invalid JSON: {_snippet(raw)}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("ARD reference returned a non-object JSON response.")
    return parsed


def _get_text(url: str) -> str:
    return _get_bytes(url).decode("utf-8")


def _get_bytes(url: str, *, max_bytes: int | None = None) -> bytes:
    request = Request(url, headers={"User-Agent": "fast-agent-discover-plugin/0.2"})
    try:
        with urlopen(request, timeout=30) as response:  # noqa: S310 - Agent Resource Discovery result URL
            if max_bytes is None:
                return response.read()
            data = response.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise RuntimeError(f"Response exceeds {max_bytes} bytes.")
            return data
    except HTTPError as exc:
        raise RuntimeError(_http_error_message(exc)) from exc
    except URLError as exc:
        raise RuntimeError(str(exc.reason)) from exc


def _http_error_message(exc: HTTPError) -> str:
    content_type = (exc.headers.get_content_type() if exc.headers else "") or "unknown"
    reason = str(exc.reason or "").strip()
    detail = _http_error_detail(exc, content_type=content_type)
    parts = [f"HTTP {exc.code}"]
    if reason:
        parts.append(reason)
    parts.append(f"content-type: {content_type}")
    if detail:
        parts.append(detail)
    return " · ".join(parts)


def _http_error_detail(exc: HTTPError, *, content_type: str) -> str:
    raw = exc.read(2048)
    if not raw:
        return ""
    text = raw.decode("utf-8", errors="replace")
    if _is_html_response(content_type, text):
        title = _html_title(text)
        return f"HTML error page: {title}" if title else "HTML error page"
    return _snippet(text)


def _is_html_response(content_type: str, text: str) -> bool:
    lowered = content_type.lower()
    if "html" in lowered:
        return True
    stripped = text.lstrip().lower()
    return stripped.startswith("<!doctype html") or stripped.startswith("<html")


def _html_title(text: str) -> str | None:
    match = re.search(r"<title[^>]*>(.*?)</title>", text, flags=re.IGNORECASE | re.DOTALL)
    if match is None:
        return None
    return _snippet(re.sub(r"\s+", " ", match.group(1)))


def _snippet(text: str) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= MAX_ERROR_SNIPPET_CHARS:
        return normalized
    return normalized[: MAX_ERROR_SNIPPET_CHARS - 1] + "…"


def _render_results_markdown(query: str, results: list[FinderResult]) -> str:
    lines = [
        f"# Agent Resource Discovery results for `{query}`",
        "",
        "| score | type | result |",
        "| ---: | --- | --- |",
    ]
    for result in results:
        description = result.description.replace("|", "\\|")
        name = result.display_name.replace("|", "\\|")
        lines.append(f"| {result.score:.1f} | {result.kind} | **{name}** — {description} |")
    lines.append("")
    lines.append("Interactive selection is only available from the terminal UI.")
    return "\n".join(lines)


def _str(value: object) -> str:
    return value if isinstance(value, str) else ""


def _optional_str(value: object) -> str | None:
    text = _str(value).strip()
    return text or None


def _optional_url(value: object) -> str | None:
    text = _optional_str(value)
    return _normalize_ard_service_url(text) if text is not None else None


def _normalize_ard_service_url(url: str) -> str:
    for old, new in ARD_SERVICE_URL_REWRITES.items():
        if url.startswith(old):
            return f"{new}{url[len(old):]}"
    return url


def _float(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _is_supported_media_type(media_type: str) -> bool:
    return media_type in {
        AI_SKILL_MEDIA_TYPE,
        MCP_SERVER_MEDIA_TYPE,
        LEGACY_MCP_SERVER_MEDIA_TYPE,
        AI_REGISTRY_MEDIA_TYPE,
    }


def _looks_like_text_skill(url: str) -> bool:
    path = url.split("?", 1)[0].lower()
    return path.endswith((".md", ".txt"))


def _looks_like_skill_archive(url: str) -> bool:
    path = url.split("?", 1)[0].lower()
    return path.endswith((".tar.gz", ".tgz", ".tar"))


def _can_add_skill_to_prompt(result: FinderResult) -> bool:
    return bool(result.url and _looks_like_text_skill(result.url))


def _can_add_mcp_to_prompt(result: FinderResult) -> bool:
    return bool(result.data or result.url)


def _action_style(*, selected: bool, enabled: bool) -> str:
    if selected:
        return "class:selected" if enabled else "reverse ansired"
    return "" if enabled else "class:muted"


def _row_style(*, selected: bool, supported: bool, registry: bool = False) -> str:
    if selected:
        return "class:selected" if supported else "reverse ansired"
    if registry:
        return "ansiblue"
    return "" if supported else "ansired"


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value.strip()).strip("-")
    return slug or "discover-mcp"


def _truncate(value: str, max_len: int) -> str:
    text = " ".join(value.split())
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"
