"""Loads backend/.env (git-ignored) so local keys work without touching system environment variables.
Values already set in the environment win, so tests can force LLM_PROVIDER=rules."""
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
