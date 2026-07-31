"""Public connection guide for the Researcher MCP server."""

from __future__ import annotations

import html
import os
import re

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .hf_design import HF_LOGO_DATA_URI

LANDING_PAGE_CSP = (
    "default-src 'none'; "
    "base-uri 'none'; "
    "object-src 'none'; "
    "script-src 'unsafe-inline'; "
    "style-src 'unsafe-inline'; "
    "img-src data:; "
    "form-action 'none'"
)
QVALUE = re.compile(r"^(?:0(?:\.\d{0,3})?|1(?:\.0{0,3})?)$")


class McpBrowserRedirectMiddleware:
    """Send browser GETs for the protocol endpoint to the connection guide."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if (
            scope["type"] == "http"
            and scope["method"] == "GET"
            and scope["path"] == "/mcp"
            and not _accepts_event_stream(scope)
        ):
            response = RedirectResponse(
                "/",
                status_code=303,
                headers={
                    "Cache-Control": "no-store",
                    "Vary": "Accept",
                },
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def _accepts_event_stream(scope: Scope) -> bool:
    values = [
        value.decode("latin-1")
        for key, value in scope.get("headers", [])
        if key.decode("latin-1").lower() == "accept"
    ]
    for item in ",".join(values).split(","):
        media_type, *parameters = (part.strip() for part in item.split(";"))
        if media_type.lower() != "text/event-stream":
            continue
        quality = next(
            (
                value
                for parameter in parameters
                if parameter.lower().startswith("q=")
                for value in (parameter.split("=", 1)[1].strip(),)
            ),
            "1",
        )
        if not QVALUE.fullmatch(quality):
            continue
        if float(quality) > 0:
            return True
    return False


def register_landing_page(mcp: FastMCP) -> None:
    """Expose a public connection guide beside the protected MCP endpoint."""

    @mcp.custom_route("/", methods=["GET"], include_in_schema=False)
    async def landing_page(request: Request) -> HTMLResponse:
        connection_url = _connection_url(request)
        return HTMLResponse(
            landing_page_html(connection_url),
            headers={
                "Cache-Control": "public, max-age=300",
                "Content-Security-Policy": LANDING_PAGE_CSP,
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
            },
        )


def _connection_url(
    request: Request,
    space_host: str | None = None,
) -> str:
    space_host = (
        (space_host if space_host is not None else os.getenv("SPACE_HOST", ""))
        .strip()
        .strip("/")
    )
    if space_host:
        base = space_host if "://" in space_host else f"https://{space_host}"
        return f"{base}/mcp"
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.url.netloc)
    return f"{scheme.split(',', 1)[0].strip()}://{host.split(',', 1)[0].strip()}/mcp"


def landing_page_html(connection_url: str) -> str:
    connection_url = html.escape(connection_url, quote=True)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Hugging Face Research MCP Server</title>
  <style>
    :root {{
      color-scheme: light dark;
      font-family: ui-sans-serif, system-ui, sans-serif;
      background: #f9fafb;
      color: #111827;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      min-height: 100vh;
      margin: 0;
      display: grid;
      place-items: center;
      padding: 32px 20px;
      background:
        radial-gradient(circle at top, rgba(255, 210, 30, .18), transparent 42%),
        #f9fafb;
    }}
    main {{
      width: min(680px, 100%);
      padding: 36px;
      border: 1px solid #e5e7eb;
      border-top: 4px solid #ffd21e;
      border-radius: 16px;
      background: #fff;
      box-shadow: 0 18px 48px rgba(15, 23, 42, .09);
    }}
    .brand {{ display: flex; align-items: center; gap: 12px; font-weight: 700; }}
    .logo {{ width: 38px; height: 36px; object-fit: contain; }}
    .status {{
      display: inline-block;
      margin-left: auto;
      padding: 5px 10px;
      border: 1px solid #a7f3d0;
      border-radius: 999px;
      background: #ecfdf5;
      color: #047857;
      font-size: 12px;
    }}
    h1 {{
      margin: 28px 0 12px;
      font-size: clamp(30px, 6vw, 46px);
      line-height: 1.05;
    }}
    p {{ color: #4b5563; font-size: 17px; line-height: 1.65; }}
    .label {{
      margin: 28px 0 8px;
      color: #6b7280;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: .08em;
      text-transform: uppercase;
    }}
    code {{
      flex: 1;
      padding: 16px;
      overflow-wrap: anywhere;
      border: 1px solid #d1d5db;
      border-radius: 10px;
      background: #f3f4f6;
      color: #b45309;
      font-family: ui-monospace, monospace;
      font-size: 14px;
      user-select: all;
    }}
    .endpoint {{ display: flex; align-items: stretch; gap: 10px; }}
    button {{
      min-width: 92px;
      padding: 0 16px;
      border: 1px solid #d97706;
      border-radius: 10px;
      background: #fffbeb;
      color: #b45309;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
    }}
    button:hover {{ background: #fef3c7; }}
    .examples {{
      display: inline-block;
      margin-top: 22px;
      color: #b45309;
      font-weight: 650;
      text-decoration: none;
    }}
    .examples:hover {{ text-decoration: underline; }}
    small {{ display: block; margin-top: 22px; color: #9ca3af; }}
    @media (max-width: 560px) {{
      main {{ padding: 28px 22px; }}
      .endpoint {{ flex-direction: column; }}
      button {{ min-height: 46px; }}
    }}
    @media (prefers-color-scheme: dark) {{
      :root, body {{ background: #0b0f19; color: #e5e7eb; }}
      body {{
        background:
          radial-gradient(circle at top, rgba(255, 210, 30, .1), transparent 42%),
          #0b0f19;
      }}
      main {{ border-color: #263044; background: #101623; box-shadow: none; }}
      p {{ color: #9ca3af; }}
      code {{ border-color: #374151; background: #141c2e; color: #fbbf24; }}
      button {{
        border-color: #f59e0b;
        background: #29200c;
        color: #fbbf24;
      }}
    }}
  </style>
</head>
<body>
  <main>
    <div class="brand">
      <img
        class="logo"
        src="{HF_LOGO_DATA_URI}"
        alt=""
        aria-hidden="true"
      >
      <span>Hugging Face</span>
      <span class="status">MCP server online</span>
    </div>
    <h1>Research MCP Server</h1>
    <p>
      Conduct sourced research on Hugging Face models, datasets, papers,
      Spaces, and ecosystem activity. Connect an MCP-compatible client using
      the endpoint below.
    </p>
    <div class="label">MCP connection URL</div>
    <div class="endpoint">
      <code id="mcp-url">{connection_url}</code>
      <button id="copy-url" type="button">Copy</button>
    </div>
    <small>
      OAuth authentication is handled by Hugging Face when your client connects.
    </small>
    <a
      class="examples"
      href="https://huggingface.co/spaces/evalstate/researcher-reports"
      target="_blank"
      rel="noopener noreferrer"
    >View example research reports ↗</a>
  </main>
  <script>
    const button = document.getElementById("copy-url");
    button.addEventListener("click", async () => {{
      const value = document.getElementById("mcp-url").textContent.trim();
      try {{
        await navigator.clipboard.writeText(value);
        button.textContent = "Copied";
      }} catch {{
        const range = document.createRange();
        range.selectNodeContents(document.getElementById("mcp-url"));
        const selection = window.getSelection();
        selection.removeAllRanges();
        selection.addRange(range);
        button.textContent = "Select & copy";
      }}
      window.setTimeout(() => {{ button.textContent = "Copy"; }}, 1800);
    }});
  </script>
</body>
</html>
"""
