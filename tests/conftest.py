import os
import tempfile

_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_db.name}")
os.environ.setdefault("AI_PROVIDER", "local")
os.environ.setdefault("EMAIL_MODE", "demo")
os.environ["RATE_LIMIT_ENABLED"] = "0"
os.environ["CORS_ORIGINS"] = "http://localhost:5500"
