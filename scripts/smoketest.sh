#!/usr/bin/env bash
set -euo pipefail

# End-to-end check that the Exa key works — before installing any Python deps.
# Run it with the secret injected from 1Password:
#   op run --env-file=.env -- ./scripts/smoketest.sh
# (or export EXA_API_KEY yourself first)

: "${EXA_API_KEY:?Set EXA_API_KEY, e.g.: op run --env-file=.env -- ./scripts/smoketest.sh}"

resp=$(curl -sS -X POST 'https://api.exa.ai/search' \
  -H "x-api-key: ${EXA_API_KEY}" \
  -H 'Content-Type: application/json' \
  -d '{"query":"exa api smoke test","type":"fast","numResults":1,"contents":{"highlights":true}}')

echo "$resp" | python3 -m json.tool 2>/dev/null | head -n 30 || echo "$resp" | head -c 1000
echo
