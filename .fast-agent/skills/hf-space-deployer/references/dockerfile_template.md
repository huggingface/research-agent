# Dockerfile Template for Fast-Agent Spaces

Production-ready Dockerfile template for deploying fast-agent to Hugging Face Spaces.

## Standard Template

```dockerfile
FROM python:3.13-slim

# Install system dependencies required by fast-agent and HF Spaces
RUN apt-get update && \
    apt-get install -y \
      bash \
      git git-lfs \
      wget curl procps \
      && rm -rf /var/lib/apt/lists/*

# Install uv for fast, reliable package management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Set working directory
WORKDIR /app

# Install fast-agent-mcp from PyPI
RUN uv pip install --system --no-cache fast-agent-mcp

# Copy all files from the Space repository to /app
COPY --link ./ /app

# Ensure /app is owned by uid 1000 (required for HF Spaces)
RUN chown -R 1000:1000 /app

# Switch to non-root user
USER 1000

# Expose port 7860 (HF Spaces default)
EXPOSE 7860

# Run fast-agent serve - replace YOUR_AGENT_NAME.md with your agent card filename
CMD ["fast-agent", "serve", "--agent-cards", "YOUR_AGENT_NAME.md", "--transport", "http", "--host", "0.0.0.0", "--port", "7860"]
```

> **Important**: The AgentCard `name` becomes the MCP tool name. Replace `YOUR_AGENT_NAME.md` with your actual filename (e.g., `hf-api-agent.md`) and set an explicit `name` in the card.

## HF Spaces Requirements

| Requirement | Value | Why |
|-------------|-------|-----|
| Port | 7860 | HF Spaces expects applications on this port |
| User ID | 1000 | Application files must be owned by UID 1000 |
| System packages | bash, git, git-lfs | Required for HF Spaces functionality |

## CMD Options Reference

Customize the CMD by adding flags:

| Option | Flag | Example |
|--------|------|---------|
| Agent card | `--agent-cards` / `--card` | `--agent-cards hf-api-agent.md` |
| Multiple cards | `--agent-cards` / `--card` (repeat) | `--agent-cards agent1.md --agent-cards agent2.md` |
| Override model | `--model` | `--model kimi` |
| Shell access | `--shell` | `--shell` |
| Instance scope | `--instance-scope` | `--instance-scope request` |
| Transport | `--transport` | `--transport http` |

### Example: Token Passthrough Setup

For token passthrough (users pay for their own inference):

```dockerfile
CMD ["fast-agent", "serve", \
     "--agent-cards", "YOUR_AGENT_NAME.md", \
     "--transport", "http", \
     "--instance-scope", "request", \
     "--host", "0.0.0.0", \
     "--port", "7860"]
```

## Adding Dependencies

### Inline packages

```dockerfile
RUN uv pip install --system --no-cache \
    fast-agent-mcp \
    requests \
    pandas \
    numpy
```

### From requirements.txt

```dockerfile
WORKDIR /app
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt
COPY --link ./ /app
```

## Build Optimization

Order instructions from least to most frequently changed for better layer caching:

```dockerfile
# 1. System packages (rarely change)
RUN apt-get update && apt-get install -y ...

# 2. Python package installer (rarely changes)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# 3. Dependencies (change occasionally)
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

# 4. Application code (changes frequently)
COPY --link ./ /app
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "Permission denied" | Ensure `chown -R 1000:1000 /app` runs before `USER 1000` |
| "uv: command not found" | Verify the uv COPY line uses the official image |
| "Cannot bind to port" | Check EXPOSE 7860 and CMD uses --port 7860 |
| Import errors at runtime | Use `--system` flag with uv outside a venv |
