# Hugging Face CLI Commands Reference

Complete reference for deploying fast-agent to HF Spaces using the `hf` CLI tool.

## Installation

```bash
uv tool install -U huggingface_hub
```

## Authentication

```bash
# Login (opens browser)
hf auth login

# Check authentication status
hf auth whoami

# Logout
hf auth logout
```

## Creating Spaces

### Basic Space Creation

```bash
hf repo create <username>/<space-name> --repo-type space --space-sdk docker
```

### With Options

```bash
# Create private Space
hf repo create <username>/<space-name> \
  --repo-type space \
  --space-sdk docker \
  --private

# Allow overwriting if exists
hf repo create <username>/<space-name> \
  --repo-type space \
  --space-sdk docker \
  --exist-ok
```

### Arguments

- `REPO_ID`: Format `username/repo-name` (required)
- `--repo-type`: Must be `space` for Spaces
- `--space-sdk`: Must be `docker` for Docker-based Spaces
- `--private`: Create as private Space
- `--exist-ok`: Don't error if Space already exists
- `--token TEXT`: Use specific access token

## Uploading Files

### Upload Directory

```bash
hf upload <username>/<space-name> <local-directory> --repo-type space
```

### Upload Specific Files

```bash
hf upload <username>/<space-name> ./Dockerfile --repo-type space
hf upload <username>/<space-name> ./agent.md --repo-type space
```

### With Commit Message

```bash
hf upload <username>/<space-name> <directory> \
  --repo-type space \
  --commit-message "Initial deployment"
```

### With Path in Repo

```bash
# Upload to specific path in repo
hf upload <username>/<space-name> ./local/file.txt remote/path/file.txt \
  --repo-type space
```

### Upload Options

- `--commit-message TEXT`: Custom commit message
- `--commit-description TEXT`: Detailed commit description
- `--private`: Create private repo if doesn't exist
- `--include TEXT`: Glob patterns to include
- `--exclude TEXT`: Glob patterns to exclude
- `--delete TEXT`: Glob patterns to delete from repo
- `--create-pr`: Upload as Pull Request
- `--revision TEXT`: Target branch/tag/commit

## Managing Spaces

### Delete Space

```bash
hf repo delete <username>/<space-name> --repo-type space
```

### Update Settings

```bash
hf repo settings <username>/<space-name> --repo-type space --private
```

### List Files

```bash
hf repo-files list <username>/<space-name> --repo-type space
```

### Download Space Files

```bash
hf download <username>/<space-name> --repo-type space --local-dir ./space-backup
```

## Working with Branches

### Create Branch

```bash
hf repo branch <username>/<space-name> create dev --repo-type space
```

### List Branches

```bash
hf repo branch <username>/<space-name> list --repo-type space
```

### Delete Branch

```bash
hf repo branch <username>/<space-name> delete dev --repo-type space
```

## Environment Variables & Secrets

### Via Python API (Recommended)

Use `huggingface_hub` to manage secrets and variables programmatically:

```python
from huggingface_hub import add_space_secret, add_space_variable

# Add secrets (hidden values - for API keys)
add_space_secret(
    repo_id="username/my-space",
    key="HF_TOKEN",
    value="hf_xxx",
    description="HuggingFace API token for fallback"
)

add_space_secret(
    repo_id="username/my-space",
    key="OPENAI_API_KEY",
    value="sk-xxx",
    description="OpenAI API key"
)

# Add variables (visible values - for configuration)
add_space_variable(
    repo_id="username/my-space",
    key="FAST_AGENT_SERVE_OAUTH",
    value="huggingface",
    description="Enable HuggingFace OAuth authentication"
)

add_space_variable(
    repo_id="username/my-space",
    key="FAST_AGENT_OAUTH_SCOPES",
    value="inference-api",
    description="Required OAuth scopes"
)

add_space_variable(
    repo_id="username/my-space",
    key="FAST_AGENT_OAUTH_RESOURCE_URL",
    value="https://username-my-space.hf.space",
    description="Public URL for OAuth metadata"
)
```

For token passthrough, also set `hf_oauth: true` and the needed `hf_oauth_scopes` in the Space README frontmatter. Do not add a shared `HF_TOKEN` unless you intentionally want a server credential fallback.

### Other Python API Methods

```python
from huggingface_hub import (
    get_space_variables,    # List all variables
    delete_space_secret,    # Remove a secret
    delete_space_variable,  # Remove a variable
)

# List current variables
variables = get_space_variables("username/my-space")
for var in variables:
    print(f"{var.key}: {var.value}")

# Delete a secret or variable
delete_space_secret("username/my-space", "OLD_API_KEY")
delete_space_variable("username/my-space", "OLD_CONFIG")
```

### Via Web UI

1. Navigate to Space Settings
2. Go to "Repository secrets" section
3. Add secrets (hidden) or variables (visible)

### Secrets vs Variables

| Type | Visibility | Use For |
|------|------------|---------|
| **Secrets** | Hidden (admin only) | API keys, tokens, passwords |
| **Variables** | Public/visible | Configuration, feature flags |

## Common Workflows

### Complete Deployment

```bash
# 1. Create Space
hf repo create evalstate/my-agent \
  --repo-type space \
  --space-sdk docker \
  --exist-ok

# 2. Upload all files
hf upload evalstate/my-agent ./space-files \
  --repo-type space \
  --commit-message "Deploy fast-agent with custom tools"

# 3. Monitor at https://huggingface.co/spaces/evalstate/my-agent
```

### Update Existing Space

```bash
# Upload specific files
hf upload evalstate/my-agent ./agent.md \
  --repo-type space \
  --commit-message "Update agent card"

# Or upload entire directory
hf upload evalstate/my-agent ./updated-files \
  --repo-type space \
  --commit-message "Update configuration"
```

### Clone Space for Local Editing

```bash
# Clone the Space repo
git clone https://huggingface.co/spaces/<username>/<space-name>
cd <space-name>

# Make changes
# ...

# Push changes
git add .
git commit -m "Update agent"
git push
```

## Troubleshooting

### Authentication Errors

```bash
# Check if logged in
hf auth whoami

# Re-authenticate
hf auth logout
hf auth login
```

### Permission Errors

Ensure you have write access to the namespace (username or organization).

### Upload Fails

```bash
# Use --exist-ok to skip errors if repo exists
hf repo create ... --exist-ok

# Use --quiet to reduce output
hf upload ... --quiet
```

### View Upload Progress

By default, upload shows progress bars. Use `--quiet` to disable:

```bash
hf upload evalstate/my-agent ./files --repo-type space --quiet
```

## Advanced Usage

### Upload with Patterns

```bash
# Include only Python files
hf upload evalstate/my-agent . \
  --repo-type space \
  --include "*.py"

# Exclude test files
hf upload evalstate/my-agent . \
  --repo-type space \
  --exclude "*test*.py"
```

### Delete Files During Upload

```bash
# Delete old files while uploading new
hf upload evalstate/my-agent ./new-files \
  --repo-type space \
  --delete "old-*.md"
```

### Create Pull Request

```bash
# Upload as PR instead of direct commit
hf upload evalstate/my-agent ./changes \
  --repo-type space \
  --create-pr \
  --commit-message "Proposed changes"
```

## Reference Links

- HF CLI Documentation: https://huggingface.co/docs/huggingface_hub/guides/cli
- Spaces Documentation: https://huggingface.co/docs/hub/spaces
- Docker Spaces: https://huggingface.co/docs/hub/spaces-sdks-docker
