"""Capability-authorized HTTP snapshots for MCP App browser polling."""

from __future__ import annotations

from urllib.parse import quote

from fastmcp import FastMCP
from fastmcp.apps.app import _make_resolver
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .app_jobs import ResearchJobStore
from .app_ui import _ui_snapshot, build_research_ui
from .hf_design import HFDesign
from .status_capability import StatusCapabilityStore

APP_NAME = "Hugging Face Researcher"
STATUS_PATH = "/widget/research/{token}"
RESPONSE_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


def capability_urls(origin: str, token: str) -> tuple[str, str]:
    status_url = f"{origin.rstrip('/')}/widget/research/{quote(token, safe='')}"
    return status_url, f"{status_url}?view=1"


def register_widget_status_route(
    mcp: FastMCP,
    *,
    jobs: ResearchJobStore,
    capabilities: StatusCapabilityStore,
    build_id: str,
    origin: str,
    design: HFDesign,
) -> None:
    @mcp.custom_route(STATUS_PATH, methods=["GET", "OPTIONS"])
    async def widget_status(request: Request) -> Response:
        if request.method == "OPTIONS":
            return Response(
                status_code=204,
                headers={
                    **RESPONSE_HEADERS,
                    "Access-Control-Allow-Methods": "GET, OPTIONS",
                },
            )

        capability = capabilities.resolve(request.path_params["token"])
        if capability is None:
            return JSONResponse(
                {"detail": "Unavailable"},
                status_code=404,
                headers=RESPONSE_HEADERS,
            )
        job = await jobs.get(capability.job_id, capability.owner_id)
        if job is None:
            return JSONResponse(
                {"detail": "Unavailable"},
                status_code=404,
                headers=RESPONSE_HEADERS,
            )

        if request.query_params.get("view") == "1":
            status_url, recovery_url = capability_urls(
                origin, request.path_params["token"]
            )
            snapshot = job.snapshot()
            snapshot["markdown_report_blocks"] = job.markdown_report_blocks
            app = build_research_ui(
                job.topic,
                snapshot,
                build_id=build_id,
                design=design,
                status_url=status_url,
                recovery_url=recovery_url,
            )
            payload = app.to_json(tool_resolver=_make_resolver(APP_NAME))
        else:
            payload = _ui_snapshot(job.snapshot())
            payload["report_blocks"] = job.markdown_report_blocks
            payload["report_ready"] = bool(job.markdown_report_blocks)

        return JSONResponse(payload, headers=RESPONSE_HEADERS)
