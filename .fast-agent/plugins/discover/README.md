# Agent Resource Discovery

Adds `/discover <query>` for discovering skills and MCP servers, then applying a selected result to the current session.

## Configuration

Add additional ARD registries with `plugins.config.discover.urls` in `fast-agent.yaml`:

```yaml
plugins:
  enabled:
    - discover
  config:
    discover:
      urls:
        - https://huggingface-hf-discover.hf.space/search
        - https://example.com/my-ard-registry/search
```

Registry URLs may be supplied with or without a trailing `/search`; the plugin
normalizes them before querying. Defaults are included unless disabled:

```yaml
plugins:
  config:
    discover:
      include_default_urls: false
      urls:
        - https://example.com/private-registry
```

For a local development install named `discover-dev`, use the same keys under
`plugins.config.discover-dev`.
