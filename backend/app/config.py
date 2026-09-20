"""
Configuration — loads secrets from a .env file (never committed; see
.gitignore) so the API key lives on disk once, not copy-pasted into code.

Using Gemini, not Claude: free tier, and you've already integrated it
successfully before (gemini-3.6-flash in the breast cancer project). This
only matters once we build the LLM-powered Planner/Synthesis agents
(deferred until you have a key) — nothing in Layers 1-3 needs this.
"""

import os

from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
TARANG_RATE_LIMIT = int(os.getenv("TARANG_RATE_LIMIT", "30"))
TARANG_RATE_WINDOW_SECONDS = int(
    os.getenv("TARANG_RATE_WINDOW_SECONDS", "60")
)
TARANG_MAX_BODY_BYTES = int(
    os.getenv("TARANG_MAX_BODY_BYTES", "65536")
)


def require_gemini_key() -> str:
    """Call this at the point you're about to make a real LLM call — fail
    loudly and clearly rather than letting a blank key cause a confusing
    error three layers deep."""
    if not GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Copy backend/.env.example to "
            "backend/.env and paste your key in from aistudio.google.com/apikey."
        )
    return GEMINI_API_KEY
