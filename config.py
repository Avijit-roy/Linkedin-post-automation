# config.py
# LinkedIn AI Daily Post Automation — Configuration Loader
#
# ✅ This file is now SECRET-FREE — safe to commit.
# ✅ All secrets live in .env (already gitignored).
#
# How it works:
#   1. python-dotenv loads .env from the same directory as this file.
#   2. os.environ is used to read every value.
#   3. _validate() fails immediately on startup if any critical key is missing.
#
# To add a new secret: add it to .env, .env.example, and read it here with os.getenv().

import os
from pathlib import Path
from dotenv import load_dotenv

# ── Load .env from the same directory as this file ───────────────────────────
_ENV_PATH = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=_ENV_PATH, override=False)   # override=False: real env vars win


# ── Groq (AI Post Generation) ─────────────────────────────────────────────────
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# ── Tavily (Topic Discovery & Research) ───────────────────────────────────────
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

# ── Pollinations.AI (Image Generation) ───────────────────────────────────────
POLLINATIONS_API_KEY = os.getenv("POLLINATIONS_API_KEY", "")

# ── LinkedIn ──────────────────────────────────────────────────────────────────
LINKEDIN_ACCESS_TOKEN = os.getenv("LINKEDIN_ACCESS_TOKEN", "")
LINKEDIN_PERSON_URN   = os.getenv("LINKEDIN_PERSON_URN", "")

# ── Google Sheets ─────────────────────────────────────────────────────────────
GOOGLE_SHEET_ID         = os.getenv("GOOGLE_SHEET_ID", "")
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials/service-account.json")
SHEET_NAME              = os.getenv("SHEET_NAME", "Posts")

# ── Gmail SMTP ────────────────────────────────────────────────────────────────
GMAIL_SENDER       = os.getenv("GMAIL_SENDER", "")
GMAIL_RECEIVER     = os.getenv("GMAIL_RECEIVER", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")

# ── Behaviour ─────────────────────────────────────────────────────────────────
POST_TIME         = os.getenv("POST_TIME", "10:00")
MAX_RETRIES       = int(os.getenv("MAX_RETRIES", "3"))
QUALITY_MIN_SCORE = int(os.getenv("QUALITY_MIN_SCORE", "6"))


# ── Startup Validation ────────────────────────────────────────────────────────
# Fails fast if any critical secret is missing — prevents silent failures
# mid-workflow after API calls have already been made.
def _validate():
    critical = {
        "GROQ_API_KEY":          GROQ_API_KEY,
        "TAVILY_API_KEY":        TAVILY_API_KEY,
        "POLLINATIONS_API_KEY":  POLLINATIONS_API_KEY,
        "LINKEDIN_ACCESS_TOKEN": LINKEDIN_ACCESS_TOKEN,
        "LINKEDIN_PERSON_URN":   LINKEDIN_PERSON_URN,
        "GOOGLE_SHEET_ID":       GOOGLE_SHEET_ID,
        "GMAIL_SENDER":          GMAIL_SENDER,
        "GMAIL_RECEIVER":        GMAIL_RECEIVER,
        "GMAIL_APP_PASSWORD":    GMAIL_APP_PASSWORD,
    }
    missing = [k for k, v in critical.items() if not v]
    if missing:
        raise ValueError(
            f"\n\n❌ Missing required environment variables (check your .env file):\n"
            + "\n".join(f"  • {k}" for k in missing)
            + "\n\nCopy .env.example to .env and fill in the missing values.\n"
        )

    if not (1 <= MAX_RETRIES <= 5):
        raise ValueError("MAX_RETRIES must be between 1 and 5 (set in .env)")
    if not (1 <= QUALITY_MIN_SCORE <= 9):
        raise ValueError("QUALITY_MIN_SCORE must be between 1 and 9 (set in .env)")


_validate()
