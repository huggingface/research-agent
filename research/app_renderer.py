"""Versioned Prefab renderer resource for reliable host cache invalidation."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import urlsplit

from fastmcp import FastMCP
from fastmcp.apps.config import UI_MIME_TYPE, AppConfig, ResourceCSP
from fastmcp.server.providers.addressing import hash_tool
from fastmcp.server.transforms import Transform
from fastmcp.tools.base import Tool
from prefab_ui.renderer import get_renderer_csp, get_renderer_html

_RENDERER_MODULE = re.compile(
    r'<script type="module" crossorigin src="([^"]+)"></script>'
)
_COMPATIBLE_RENDERER_DIGESTS = (
    "0e57015a15d4",
    "3217f2d981ea",
    "7cfb45fbe220",
    "aa2fea14c7e0",
)

PREFAB_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["$prefab", "view", "state"],
    "properties": {
        "$prefab": {
            "type": "object",
            "required": ["version"],
            "properties": {"version": {"type": "string"}},
            "additionalProperties": True,
        },
        "view": {"type": "object"},
        "state": {"type": "object"},
        "css": {"type": "array", "items": {"type": "string"}},
        "stylesheets": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "additionalProperties": True,
}


def _with_chatgpt_remount_recovery(
    html: str,
    widget_domain: str | None = None,
) -> str:
    """Recover a remounted ChatGPT widget from its scoped tool output."""
    match = _RENDERER_MODULE.search(html)
    if match is None:
        return html
    renderer_url = json.dumps(match.group(1))
    allowed_origin = json.dumps(widget_domain)
    script = f"""<script type="module">
const isPrefabOutput = (value) =>
  value !== null &&
  typeof value === "object" &&
  !Array.isArray(value) &&
  value.$prefab !== null &&
  typeof value.$prefab === "object" &&
  !Array.isArray(value.$prefab) &&
  value.$prefab.version === "0.3" &&
  value.view !== null &&
  typeof value.view === "object" &&
  !Array.isArray(value.view) &&
  value.state !== null &&
  typeof value.state === "object" &&
  !Array.isArray(value.state) &&
  value.state.job !== null &&
  typeof value.state.job === "object" &&
  !Array.isArray(value.state.job) &&
  typeof value.state.topic === "string" &&
  typeof value.state.job_id === "string" &&
  typeof value.state.app_version === "string";

let standardResultSeen = false;
let fallbackSent = false;
let rendererReady = false;
let graceElapsed = false;
let ignoredToolResultLogged = false;
let recoveryStarted = false;

const validCapability = (value) => {{
  if (
    value === null ||
    typeof value !== "object" ||
    typeof value.statusUrl !== "string" ||
    typeof value.recoveryUrl !== "string"
  ) return false;
  try {{
    return (
      new URL(value.statusUrl).origin === {allowed_origin} &&
      new URL(value.recoveryUrl).origin === {allowed_origin}
    );
  }} catch {{
    return false;
  }}
}};

const attachCapability = (output, capability) => {{
  output.state.status_url = capability.statusUrl;
  output.state.recovery_url = capability.recoveryUrl;
}};

const persistCapability = (capability) => {{
  const setState = window.openai?.setWidgetState;
  if (typeof setState !== "function") return;
  const current = window.openai?.widgetState ?? {{}};
  const next = {{
    ...current,
    privateContent: {{
      ...(current.privateContent ?? {{}}),
      researchPrefab: capability,
    }},
  }};
  try {{
    Promise.resolve(setState(next)).catch(() => {{}});
  }} catch {{}}
}};

const savedCapability = () => {{
  const capability =
    window.openai?.widgetState?.privateContent?.researchPrefab;
  return validCapability(capability) ? capability : null;
}};

const stopRecovery = () => {{
  window.removeEventListener("openai:set_globals", onOpenAIUpdate);
  clearTimeout(graceTimer);
  clearTimeout(expiryTimer);
}};

const onToolResult = (event) => {{
  const message = event.data;
  if (
    event.source !== window.parent ||
    message?.jsonrpc !== "2.0" ||
    message?.method !== "ui/notifications/tool-result"
  ) return;

  if (!isPrefabOutput(message.params?.structuredContent)) {{
    event.stopImmediatePropagation();
    if (!ignoredToolResultLogged) {{
      ignoredToolResultLogged = true;
      console.warn(
        "[research-prefab] ignored non-Prefab tool-result notification"
      );
    }}
    return;
  }}

  const capability = message.params?._meta?.research;
  if (validCapability(capability)) {{
    attachCapability(message.params.structuredContent, capability);
    persistCapability(capability);
  }}
  standardResultSeen = true;
  stopRecovery();
}};

const dispatchOutput = (output) => {{
  fallbackSent = true;
  stopRecovery();
  window.dispatchEvent(new MessageEvent("message", {{
    source: window.parent,
    data: {{
      jsonrpc: "2.0",
      method: "ui/notifications/tool-result",
      params: {{ structuredContent: output }},
    }},
  }}));
}};

const recover = async () => {{
  if (
    standardResultSeen ||
    fallbackSent ||
    recoveryStarted ||
    !rendererReady ||
    !graceElapsed
  ) return;

  const output = window.openai?.toolOutput;
  if (isPrefabOutput(output)) {{
    dispatchOutput(output);
    console.info(
      "[research-prefab] hydrated from window.openai.toolOutput"
    );
    return;
  }}

  const capability = savedCapability();
  if (capability === null) return;
  recoveryStarted = true;
  try {{
    const response = await fetch(capability.recoveryUrl, {{
      cache: "no-store",
      referrerPolicy: "no-referrer",
    }});
    if (!response.ok) throw new Error(`Recovery failed: ${{response.status}}`);
    const recovered = await response.json();
    if (!isPrefabOutput(recovered) || standardResultSeen) return;
    attachCapability(recovered, capability);
    dispatchOutput(recovered);
    console.info(
      "[research-prefab] hydrated from direct status endpoint"
    );
  }} catch (error) {{
    console.warn("[research-prefab] direct recovery failed", error);
    recoveryStarted = false;
  }}
}};

const onOpenAIUpdate = (event) => {{
  if (
    event.detail?.globals?.toolOutput !== undefined ||
    event.detail?.globals?.widgetState !== undefined
  ) recover();
}};

window.addEventListener("message", onToolResult, {{
  capture: true,
  passive: true,
}});
window.addEventListener("openai:set_globals", onOpenAIUpdate, {{
  passive: true,
}});

const graceTimer = setTimeout(() => {{
  graceElapsed = true;
  recover();
}}, 3000);
const expiryTimer = setTimeout(stopRecovery, 30000);

await import({renderer_url});
rendererReady = true;
recover();
</script>"""
    return _RENDERER_MODULE.sub(script, html, count=1)


class RendererUriTransform(Transform):
    """Point one UI tool at a content-addressed renderer resource."""

    def __init__(self, tool_name: str, resource_uri: str) -> None:
        self.tool_name = tool_name
        self.resource_uri = resource_uri

    async def list_tools(self, tools: Sequence[Tool]) -> Sequence[Tool]:
        return [
            self._with_renderer(tool) if tool.name == self.tool_name else tool
            for tool in tools
        ]

    def _with_renderer(self, tool: Tool) -> Tool:
        meta = dict(tool.meta or {})
        ui = dict(meta.get("ui") or {})
        ui["resourceUri"] = self.resource_uri
        meta["ui"] = ui
        meta["ui/resourceUri"] = self.resource_uri
        return tool.model_copy(
            update={
                "meta": meta,
                "output_schema": PREFAB_OUTPUT_SCHEMA,
            }
        )


def install_versioned_renderer(
    mcp: FastMCP,
    *,
    app_name: str,
    tool_name: str,
    build_id: str,
    resource_domains: Sequence[str] = (),
    widget_domain: str | None = None,
) -> str:
    """Register the Prefab renderer at a URI derived from its exact content."""
    widget_domain = widget_domain or default_widget_domain()
    html = _with_chatgpt_remount_recovery(
        get_renderer_html(),
        widget_domain,
    ).replace(
        "</head>",
        '<meta name="referrer" content="no-referrer"></head>',
    )
    digest = hashlib.sha256(html.encode()).hexdigest()[:12]
    tool_digest = hash_tool(app_name, tool_name)
    resource_uri = f"ui://prefab/tool/{tool_digest}/renderer-{digest}.html"
    csp_data = dict(get_renderer_csp() or {})
    domains = list(csp_data.get("resource_domains") or ())
    domains.extend(domain for domain in resource_domains if domain not in domains)
    csp_data["resource_domains"] = domains
    connect_domains = list(csp_data.get("connect_domains") or ())
    if widget_domain and widget_domain not in connect_domains:
        connect_domains.append(widget_domain)
    csp_data["connect_domains"] = connect_domains
    csp = ResourceCSP(**csp_data)

    app_config = AppConfig(csp=csp, prefers_border=True)

    def register_renderer(uri: str, name: str) -> None:
        @mcp.resource(
            uri,
            name=name,
            mime_type=UI_MIME_TYPE,
            app=app_config,
        )
        def prefab_renderer() -> str:
            return html

    register_renderer(resource_uri, "Versioned Prefab Renderer")
    for compatible_digest in _COMPATIBLE_RENDERER_DIGESTS:
        if compatible_digest == digest:
            continue
        register_renderer(
            (
                f"ui://prefab/tool/{tool_digest}/"
                f"renderer-{compatible_digest}.html"
            ),
            f"Compatible Prefab Renderer {compatible_digest}",
        )

    mcp.add_transform(RendererUriTransform(tool_name, resource_uri))
    return digest


def default_widget_domain() -> str | None:
    value = os.getenv("FAST_AGENT_OAUTH_RESOURCE_URL", "").strip().rstrip("/")
    if not value:
        host = os.getenv("SPACE_HOST", "").strip().strip("/")
        value = host if "://" in host else f"https://{host}" if host else ""
    if not value:
        return None
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"Invalid MCP App widget domain: {value!r}")
    return f"{parsed.scheme}://{parsed.netloc}"


def app_build_id(home: Path) -> str:
    """Hash the app code and prompts that shape a rendered research view."""
    digest = hashlib.sha256()
    paths = sorted(home.glob("*.py")) + sorted((home / "agent-cards").glob("*.md"))
    for path in paths:
        digest.update(path.relative_to(home).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:8]
