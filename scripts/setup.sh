#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# 1. Environment + browser (uv creates .venv from pyproject/uv.lock)
uv sync
uv run playwright install chromium

# 2. Register MCP servers globally in Claude Code (user scope = every project).
#    Single quotes keep ${EXA_API_KEY} as a literal reference in the config so
#    Claude Code expands it from its environment at launch — no key on disk.
#    Launch Claude Code with the secret present, e.g. `op run -- claude`.
if command -v claude >/dev/null 2>&1; then
  claude mcp add exa        -s user -e 'EXA_API_KEY=${EXA_API_KEY}' -- npx -y exa-mcp-server
  claude mcp add playwright -s user -- npx -y @playwright/mcp@latest
  # Optional:
  # claude mcp add firecrawl -s user -e 'FIRECRAWL_API_KEY=${FIRECRAWL_API_KEY}' -- npx -y firecrawl-mcp
  echo "Claude Code MCP servers registered."
else
  echo "claude CLI not found — merge configs/claude-mcp.example.json into ~/.claude.json manually."
fi

# 3. Codex is config-file based
echo "For Codex: merge configs/codex-config.example.toml into ~/.codex/config.toml"
