FROM ghcr.io/astral-sh/uv:python3.13-bookworm

RUN apt-get update && \
    apt-get install -y bash git git-lfs wget curl procps && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN uv pip install --system --no-cache \
    fast-agent-mcp==0.9.27 \
    'fastmcp[apps]==3.4.4' \
    prefab-ui==0.20.2 \
    huggingface_hub==1.24.0 \
    hf-xet==1.5.2 \
    pillow

COPY --link ./ /app
RUN mkdir -p /app/.cache/huggingface/xet /app/tmp && \
    chown -R 1000:1000 /app
USER 1000

EXPOSE 7860

ENV FAST_AGENT_SERVE_OAUTH=huggingface
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV HOME=/app
ENV XDG_CACHE_HOME=/app/.cache
ENV HF_HOME=/app/.cache/huggingface
ENV HF_HUB_CACHE=/app/.cache/huggingface/hub
ENV HF_XET_CACHE=/app/.cache/huggingface/xet
ENV TMPDIR=/app/tmp
ENV HF_TOKEN=hf_dummy_startup_token
ENV RESEARCH_OAUTH_DIAGNOSTICS=1
ENV PORT=7860
ENV FASTMCP_HTTP_ALLOWED_HOSTS="[\"*\"]"
ENV FASTMCP_HTTP_HOST_ORIGIN_PROTECTION=false

CMD ["python", "fastmcp_research_app.py", "--host", "0.0.0.0", "--port", "7860"]
