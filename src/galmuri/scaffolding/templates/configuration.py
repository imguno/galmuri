MANAGE = '''"""Portable project entrypoint: python manage.py --help."""
from pathlib import Path
from galmuri.cli import main

if __name__ == "__main__":
    raise SystemExit(main(project_root=Path(__file__).resolve().parent))
'''

SETTINGS = """from pathlib import Path
from galmuri import Principal

ROOT = Path(__file__).resolve().parent.parent
DATABASE = ROOT / ".runtime" / "state.sqlite"
APPS = ["apps.sample.app:sample"]
# Explicit legacy host identity, not a verified human account.
LOCAL_PRINCIPAL = Principal("developer", frozenset({"dev"}), administrator=True)
EXPOSURES = {
    "http": {"host": "127.0.0.1", "port": 8000},
    "grpc": {"host": "127.0.0.1", "port": 50051},
    "mcp": {},
}
# Register custom exposure factories here; each receives Service and options.
EXPOSURE_ADAPTERS = {}
"""

ACCOUNT_SETTINGS = """from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATABASE = ROOT / ".runtime" / "state.sqlite"
IDENTITY_DATABASE = ROOT / ".runtime" / "accounts.sqlite"
# This may also name a DATABASES alias, e.g. "default", for shared accounts.
APPS = ["apps.sample.app:sample"]
# Omitted App grants inherit these; explicit empty collections deny access.
DEFAULT_PERMISSIONS = {"read": ["*"], "write": ["*"]}
EXPOSURES = {
    "http": {"host": "127.0.0.1", "port": 8000, "allow_insecure_loopback": True},
    "grpc": {"host": "127.0.0.1", "port": 50051},
    "mcp": {},
}
EXPOSURE_ADAPTERS = {}
"""
