"""Local configuration; credentials never leave the backend."""

import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

from backend.graph_profiles import GRAPH_PROFILES

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
TAU_ROOT = Path(os.getenv("TAU2_ROOT", str(ROOT.parent / "tau2-bench")))
if not TAU_ROOT.is_absolute():
    TAU_ROOT = (ROOT / TAU_ROOT).resolve()
DATA_PATH = TAU_ROOT / "data/tau2/domains/retail/db.json"
POLICY_PATH = TAU_ROOT / "data/tau2/domains/retail/policy.md"
DB_PATH = Path(os.getenv("RETAIL_DB_PATH", str(ROOT.parent / "retail-desk-data/retail.sqlite3")))
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
EVAL_API_TOKEN = os.getenv("EVAL_API_TOKEN", "")
ARTIFACT_DIR = Path(os.getenv("RETAIL_ARTIFACT_DIR", str(DB_PATH.parent / "episodes")))
if not ARTIFACT_DIR.is_absolute():
    ARTIFACT_DIR = ROOT / ARTIFACT_DIR
TAU2_COMMIT = "0c69df456a96aa76a1162591574dad9c427a34d7"
VARIANTS = (
    "b1",
    "tools_described",
    "tools_structured",
    "tools_extended",
    *GRAPH_PROFILES,
)
BROWSER_AGENT_VARIANT = os.getenv("BROWSER_AGENT_VARIANT", "b1")
if BROWSER_AGENT_VARIANT not in VARIANTS:
    raise ValueError("Unknown BROWSER_AGENT_VARIANT")

MODEL_REQUEST_TIMEOUT_SECONDS = 300
STREAM_MODEL = os.getenv("AGENT_STREAM", "0") == "1"
MODEL_THINKING = os.getenv("MODEL_THINKING", "auto")
if MODEL_THINKING not in {"auto", "on", "off"}:
    raise ValueError("MODEL_THINKING must be auto, on or off")
