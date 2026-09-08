"""Point the whole test session at a throwaway database before any app module
imports settings."""

import os
import tempfile
from pathlib import Path

os.environ.setdefault(
    "DATABASE_URL", f"sqlite:///{Path(tempfile.gettempdir()) / 'remas_test.db'}"
)
os.environ.setdefault("ENVIRONMENT", "development")
