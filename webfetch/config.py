import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _secret(name: str) -> str | None:
    """Read an env var, resolving a 1Password `op://` reference via the op CLI."""
    return _resolve_secret(os.getenv(name))


def _resolve_secret(value: str | None) -> str | None:
    if value and value.startswith("op://"):
        import subprocess

        try:
            done = subprocess.run(["op", "read", value], capture_output=True, text=True, check=True)
            return done.stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return value  # left as-is so the caller surfaces a clear auth error
    return value


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


# Paths & cache
CACHE_DIR = Path(os.getenv("WEBFETCH_CACHE_DIR", "~/.cache/webfetch")).expanduser()
STATE_PATH = Path(os.getenv("WEBFETCH_STATE", "~/.config/webfetch/storage_state.json")).expanduser()
CACHE_TTL = _int("WEBFETCH_CACHE_TTL", 86_400)

# Fetch behavior
ENGINE = os.getenv("WEBFETCH_ENGINE", "auto")
ALLOW_PRIVATE = os.getenv("WEBFETCH_ALLOW_PRIVATE", "").strip().lower() in {"1", "true", "yes"}
MAX_BYTES = _int("WEBFETCH_MAX_BYTES", 100 * 1024 * 1024)
MAX_REDIRECTS = _int("WEBFETCH_MAX_REDIRECTS", 5)
MIN_TEXT_CHARS = _int("WEBFETCH_MIN_TEXT_CHARS", 200)
USER_AGENT = os.getenv(
    "WEBFETCH_UA",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36",
)

# Rate limiting & retries
MAX_RETRIES = _int("WEBFETCH_MAX_RETRIES", 3)
RETRY_BACKOFF = _float("WEBFETCH_RETRY_BACKOFF", 0.5)
MIN_INTERVAL = _float("WEBFETCH_MIN_INTERVAL", 0.0)

# Proxy / IP masking. WEBFETCH_PROXY: single proxy (point at a rotating-gateway
# provider for rotation). WEBFETCH_PROXIES: comma-separated pool, rotated per request.
PROXY = os.getenv("WEBFETCH_PROXY") or None
PROXIES = [p.strip() for p in os.getenv("WEBFETCH_PROXIES", "").split(",") if p.strip()]
# Route only these hosts (+ subdomains) through the proxy; others go direct.
PROXY_HOSTS = [h.strip() for h in os.getenv("WEBFETCH_PROXY_HOSTS", "").split(",") if h.strip()]

# API endpoints (override to point at a proxy or a mock)
EXA_SEARCH_URL = os.getenv("EXA_SEARCH_URL", "https://api.exa.ai/search")
TAVILY_SEARCH_URL = os.getenv("TAVILY_SEARCH_URL", "https://api.tavily.com/search")
FIRECRAWL_SCRAPE_URL = os.getenv("FIRECRAWL_SCRAPE_URL", "https://api.firecrawl.dev/v1/scrape")

# Secrets (resolved from 1Password refs when present)
EXA_API_KEY = _secret("EXA_API_KEY")
TAVILY_API_KEY = _secret("TAVILY_API_KEY")
FIRECRAWL_API_KEY = _secret("FIRECRAWL_API_KEY")
