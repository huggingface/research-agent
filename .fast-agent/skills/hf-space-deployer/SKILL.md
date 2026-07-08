---
name: hf-space-deployer
description: Deploy fast-agent MCP Servers to Hugging Face Spaces using Docker. Use when the user wants to deploy an "agent card" as an MCP Server. Includes templates and CLI commands for deploying agent cards with custom tools to HF Spaces.
---

# HF Space Deployer for Fast-Agent

Deploy fast-agent agents as MCP servers to Hugging Face Spaces using the `hf` CLI tool.

## Choose Your Deployment Model

| | Shared Secrets | Token Passthrough |
|---|---|---|
| **Who pays?** | You (Space owner) | Users (their HF account) |
| **Setup** | Add API keys as Space secrets | Enable Space OAuth + `FAST_AGENT_SERVE_OAUTH=huggingface` + request scope |
| **Best for** | Internal tools, demos | Public deployments, multi-tenant |
| **Models** | Any provider | HF Inference only |
| **Client auth** | None required | Bearer token in header |

### How Token Passthrough Works

When `FAST_AGENT_SERVE_OAUTH=huggingface` is set, clients can authenticate two ways:

1. **Direct Bearer token**: Send `Authorization: Bearer <HF_TOKEN>` header
   - Simpler for programmatic clients
   - Client manages their own token

2. **MCP OAuth flow**: Full OAuth 2.1 discovery and authorization
   - Better for interactive clients (like Claude Desktop)
   - Server exposes `/.well-known/oauth-protected-resource` for discovery

Both methods work - the server accepts either `Authorization` or `X-HF-Authorization` headers. `FAST_AGENT_SERVE_OAUTH=hf` is also accepted, but current docs use `huggingface`.

---

## Quick Start

```bash
# 1. Create a Space
hf repo create <username>/<space-name> --repo-type space --space-sdk docker --exist-ok

# 2. Prepare files (see structure below)

# 3. Upload to Space
hf upload <username>/<space-name> <local-directory> --repo-type space --commit-message "Deploy fast-agent"
```

## Space File Structure

> **Important**: The AgentCard `name` becomes the MCP tool name. Use an explicit, stable `name`; the filename is only the path you pass to `--agent-cards`/`--card`.

```
space-directory/
├── README.md              # HF Space config with YAML header
├── Dockerfile             # Docker setup with Python 3.13 + uv
├── hf-api-agent.md        # Your agent card (card name = MCP tool name)
└── hf_api_tool.py         # Optional: Python tools referenced in agent card
```

## File Templates

### README.md (Space Configuration)

See [references/readme_template.md](references/readme_template.md) for the complete template with YAML frontmatter.

Key fields:
- `title`: Space display name
- `sdk: docker` (required)
- `app_port: 7860` (HF Spaces default)
- For token passthrough: `hf_oauth: true` plus `hf_oauth_scopes`

Token passthrough frontmatter example:

```yaml
---
title: My fast-agent MCP server
sdk: docker
app_port: 7860
hf_oauth: true
hf_oauth_expiration_minutes: 480
hf_oauth_scopes:
  - inference-api
---
```

### Dockerfile

See [references/dockerfile_template.md](references/dockerfile_template.md) for the complete template.

```dockerfile
FROM python:3.13-slim

RUN apt-get update && \
    apt-get install -y bash git git-lfs wget curl procps && \
    rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
RUN uv pip install --system --no-cache fast-agent-mcp

COPY --link ./ /app
RUN chown -R 1000:1000 /app
USER 1000

EXPOSE 7860

# Replace YOUR_AGENT_NAME.md with your actual agent card filename
CMD ["fast-agent", "serve", "--agent-cards", "YOUR_AGENT_NAME.md", "--transport", "http", "--host", "0.0.0.0", "--port", "7860"]
```

### Agent Card

Your agent card defines the agent's capabilities. The `name` becomes the MCP tool name:

```yaml
---
type: agent
name: my-agent
function_tools:
  - tool_file.py:my_function
model: kimi
default: true
description: Agent description
---

# Agent Instructions

Your agent's instructions and capabilities...
```

## Configuration Reference

### CMD Options

| Option | Flag | Example |
|--------|------|---------|
| Agent card | `--agent-cards` / `--card` | `--agent-cards hf-api-agent.md` |
| Multiple cards | `--agent-cards` / `--card` (repeat) | `--agent-cards agent1.md --agent-cards agent2.md` |
| Override model | `--model` | `--model kimi` |
| Shell access | `--shell` | `--shell` |
| Instance scope | `--instance-scope` | `--instance-scope request` |
| Transport | `--transport` | `--transport http` |

### Instance Scope

Controls how agent instances are managed per MCP client:

| Scope | Behavior | Use Case |
|-------|----------|----------|
| `shared` (default) | Single instance for all requests | Trusted/private deployments, demos |
| `connection` | New instance per MCP connection/session | Multi-user with MCP session continuity |
| `request` | New instance per tool call; MCP sessions disabled | Public/token passthrough, per-request isolation |

**Required for token passthrough**: Use `--instance-scope request` so each request uses the caller's token, not a shared one.

### Environment Variables

#### For Shared Secrets (you pay)

Set API keys as Space secrets. All users share your keys:

```python
from huggingface_hub import add_space_secret

add_space_secret("username/my-space", "HF_TOKEN", "hf_xxx")
add_space_secret("username/my-space", "OPENAI_API_KEY", "sk-xxx")
```

Or via Space Settings > Repository Secrets in the web UI.

#### For Token Passthrough (users pay)

| Variable | Value | Description |
|----------|-------|-------------|
| `FAST_AGENT_SERVE_OAUTH` | `huggingface` | Enable HF authentication (`hf` is accepted alias) |
| `FAST_AGENT_OAUTH_SCOPES` | `${OAUTH_SCOPES}` or `inference-api` | Required scopes; Spaces sets `OAUTH_SCOPES` when `hf_oauth` is enabled |
| `FAST_AGENT_OAUTH_RESOURCE_URL` | `https://your-space.hf.space` | Your Space's public URL; auto-derived from `SPACE_HOST` on Spaces if omitted |

```python
from huggingface_hub import add_space_variable

SPACE_ID = "username/my-space"

add_space_variable(SPACE_ID, "FAST_AGENT_SERVE_OAUTH", "huggingface")
add_space_variable(SPACE_ID, "FAST_AGENT_OAUTH_SCOPES", "inference-api")
add_space_variable(SPACE_ID, "FAST_AGENT_OAUTH_RESOURCE_URL", "https://username-my-space.hf.space")
```

Do not set a shared `HF_TOKEN` for user-scoped inference unless you intentionally want a server credential fallback. Enable Hugging Face OAuth in the Space README frontmatter with `hf_oauth: true` and `hf_oauth_scopes`.

## Deployment Workflow

1. **Create Space**:
   ```bash
   hf repo create evalstate/my-agent-space --repo-type space --space-sdk docker
   ```

2. **Prepare directory** with files:
   - README.md (use template)
   - Dockerfile (use template, update CMD with your agent card filename)
   - Your agent card (e.g., `hf-api-agent.md`)
   - Any tool Python files

3. **Upload**:
   ```bash
   hf upload evalstate/my-agent-space ./space-files --repo-type space
   ```

4. **Monitor build** at `https://huggingface.co/spaces/<username>/<space-name>`

5. **Access** deployed agent at Space URL once built

## Advanced Topics

### Multiple Agent Cards

Serve multiple agents from one Space:

```dockerfile
CMD ["fast-agent", "serve", \
     "--agent-cards", "agent1.md", \
     "--agent-cards", "agent2.md", \
     "--transport", "http", \
     "--host", "0.0.0.0", \
     "--port", "7860", \
     "--instance-scope", "request"]
```

### Additional Dependencies

Add packages to the Dockerfile:

```dockerfile
RUN uv pip install --system --no-cache \
    fast-agent-mcp \
    requests \
    pandas
```

Or use a requirements.txt:

```dockerfile
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt
```

## Troubleshooting

**Build fails**: Check Space build logs for missing dependencies or syntax errors

**Space runs but errors**: Verify:
- Port is 7860
- Tool files exist and have correct paths
- API keys are configured in secrets

**Tool import errors**: Ensure tool files are in the Space root directory with your agent card

**Token passthrough not working**: Check:
- `FAST_AGENT_SERVE_OAUTH=huggingface` is set
- README frontmatter has `hf_oauth: true` and the needed `hf_oauth_scopes`
- `--instance-scope request` in CMD
- Client is sending `Authorization: Bearer <token>` header

## Reference Files

- [README template](references/readme_template.md) - Complete Space README.md with YAML
- [Dockerfile template](references/dockerfile_template.md) - Production-ready Dockerfile
- [HF CLI reference](references/hf_cli_commands.md) - Detailed hf command documentation
