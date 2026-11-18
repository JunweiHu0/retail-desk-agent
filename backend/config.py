"""Local configuration; credentials never leave the backend."""

import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
TAU_ROOT = Path(os.getenv("TAU2_ROOT", str(ROOT.parent / "tau2-bench")))
if not TAU_ROOT.is_absolute():
    TAU_ROOT = (ROOT / TAU_ROOT).resolve()
DATA_PATH = TAU_ROOT / "data/tau2/domains/retail/db.json"
POLICY_PATH = TAU_ROOT / "data/tau2/domains/retail/policy.md"
DB_PATH = Path(os.getenv("RETAIL_DB_PATH", str(ROOT / "runtime/retail.sqlite3")))
if not DB_PATH.is_absolute():
    DB_PATH = ROOT / DB_PATH
MODE = os.getenv("AGENT_MODE", "demo")
BASE_URL = os.getenv("MODEL_BASE_URL") or None
PROVIDER = os.getenv("MODEL_PROVIDER") or (
    "deepseek" if BASE_URL and urlparse(BASE_URL).hostname == "api.deepseek.com" else "openai"
)
IS_DEEPSEEK = PROVIDER == "deepseek"
MODEL = os.getenv("MODEL_NAME") or ("deepseek-flash" if IS_DEEPSEEK else "gpt-4.1-mini")
API_KEY = os.getenv("MODEL_API_KEY") or os.getenv(
    "DEEPSEEK_API_KEY" if IS_DEEPSEEK else "OPENAI_API_KEY", ""
)
if IS_DEEPSEEK and BASE_URL is None:
    BASE_URL = "https://api.deepseek.com"
