# codex - welcome to `fast-agent`

With `gpt-5.5`, `gpt-5.4-codex`, `spark` and other models. WebSockets are enabled by default, and an `apply_patch` tool matching the Codex CLI tool signature is supplied. A filesystem search subagent is active by default (powered by `spark`).

## CLI Commands

- Start with `fast-agent go`
- Update your System Prompt in `.fast-agent/agent-cards/dev.md`. `AGENTS.md` is included by default

## Next Steps

From the fast-agent prompt:

- Use `/peek <message>` to ask a one-off question without keeping it in the active chat history.
- Use `/edit-last` (`c-x e`) to open the last assistant response in `$VISUAL`/`$EDITOR` and prefill your edited reply.
- Use `/skills` to view and manage skills. Use to configure hooks, compaction and automation - `/skills registry` to choose source.
- Optional: use `/skills add lsp-setup` and ask your agent to configure LSP for this workspace.
- Other skills available help you configure/design compaction if needed, set up agent hooks or automate `fast-agent`
- Create new agents in this environment  by asking the assistant, or adding markdown files to `.fast-agent/agent-cards/`. Switch agents with `@`.
- Use `/connect` to connect to MCP Servers (Hugging Face and OpenAI preconfigured)
