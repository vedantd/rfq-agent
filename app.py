"""Root entrypoint so `uvicorn app:app` keeps working after the folder reorg."""
from api.app import app

__all__ = ["app"]
