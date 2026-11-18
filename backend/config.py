"""Local configuration; credentials never leave the backend."""

import os
from pathlib import Path

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
MODEL = os.getenv("MODEL_NAME", "gpt-4.1-mini")
API_KEY = os.getenv("MODEL_API_KEY") or os.getenv("OPENAI_API_KEY", "")
BASE_URL = os.getenv("MODEL_BASE_URL") or None
EVAL_API_TOKEN = os.getenv("EVAL_API_TOKEN", "")
ARTIFACT_DIR = Path(os.getenv("RETAIL_ARTIFACT_DIR", str(ROOT / "runtime/episodes")))
if not ARTIFACT_DIR.is_absolute():
    ARTIFACT_DIR = ROOT / ARTIFACT_DIR
TAU2_COMMIT = "0c69df456a96aa76a1162591574dad9c427a34d7"
VARIANTS = ("b1", "state", "errors", "guide", "enhanced", "c1", "c2")

MODEL_REQUEST_TIMEOUT_SECONDS = 300
MODEL_THINKING = os.getenv("MODEL_THINKING", "auto")
if MODEL_THINKING not in {"auto", "on", "off"}:
    raise ValueError("MODEL_THINKING must be auto, on or off")
