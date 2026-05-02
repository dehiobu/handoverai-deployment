"""
Configuration file for GP Triage POC
"""
APP_VERSION = "0.3.1"
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env (local dev)
load_dotenv()

# Paths
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
CHROMA_DIR = BASE_DIR / "chroma_db"
LOGS_DIR = BASE_DIR / "logs"

# Create directories if they don't exist
for dir_path in [DATA_DIR, CHROMA_DIR, LOGS_DIR]:
    dir_path.mkdir(exist_ok=True)


def get_secret(section: str, key: str, env_key: str | None = None,
               default: str | None = None) -> str | None:
    """Read a secret from st.secrets (Streamlit Cloud) then os.getenv (.env).

    Parameters
    ----------
    section : str
        Top-level section in secrets.toml, e.g. "openai".
    key : str
        Key within that section, e.g. "api_key".
    env_key : str | None
        Fallback environment variable name, e.g. "OPENAI_API_KEY".
        Defaults to key.upper() if not provided.
    default : str | None
        Returned when neither source has a value.
    """
    # 1. Streamlit secrets (Streamlit Cloud deployment)
    try:
        import streamlit as st          # noqa: PLC0415
        val = st.secrets[section][key]
        if val:
            return str(val)
    except Exception:
        pass
    # 2. Environment variable / .env file
    return os.getenv(env_key or key.upper(), default)


# OpenAI Configuration
# Try in order:
#   1. st.secrets["openai"]["OPENAI_API_KEY"]  (Streamlit Cloud — uppercase key)
#   2. st.secrets["openai"]["api_key"]          (legacy lowercase key)
#   3. os.getenv("OPENAI_API_KEY")              (local .env file)
OPENAI_API_KEY = (
    get_secret("openai", "OPENAI_API_KEY", "OPENAI_API_KEY")
    or get_secret("openai", "api_key", "OPENAI_API_KEY")
)
if not OPENAI_API_KEY:
    raise ValueError(
        "OPENAI_API_KEY not found. "
        "Streamlit Cloud: add it under [openai] → OPENAI_API_KEY in the Secrets dashboard. "
        "Local: set OPENAI_API_KEY in your .env file."
    )

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
CHAT_MODEL = os.getenv("CHAT_MODEL", "gpt-4o")
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.0"))
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "1000"))

# Vector Store Configuration
COLLECTION_NAME = "gp_triage_cases"
SIMILARITY_TOP_K = 5

# Triage Configuration
TRIAGE_LEVELS = ["RED", "AMBER", "GREEN"]
NICE_GUIDELINES_URL = "https://www.nice.org.uk"

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = LOGS_DIR / "triage.log"

# Dataset file
DATASET_FILE = DATA_DIR / "ai_validated_dataset.json"

# ── Surgery configuration ────────────────────────────────────────────────────
# Configurable at setup time — primary surgery and up to 2 overflow surgeries.
PRIMARY_SURGERY = {
    "name":    os.getenv("PRIMARY_SURGERY_NAME", "Hole in the Wall Surgery"),
    "address": os.getenv("PRIMARY_SURGERY_ADDRESS", ""),
    "phone":   os.getenv("PRIMARY_SURGERY_PHONE", ""),
    "email":   os.getenv("PRIMARY_SURGERY_EMAIL", ""),
}
OVERFLOW_SURGERIES: list[dict] = [
    {
        "name":    os.getenv("OVERFLOW_SURGERY_1_NAME", "Woodlands Surgery"),
        "address": os.getenv("OVERFLOW_SURGERY_1_ADDRESS",
                             "5 Woodlands Rd, Redhill RH1 6EY"),
        "phone":   os.getenv("OVERFLOW_SURGERY_1_PHONE", ""),
        "email":   os.getenv("OVERFLOW_SURGERY_1_EMAIL", ""),
        "note":    "Located directly across the road from the swimming pool complex",
    },
]

# ── Record retention defaults (NHS) ─────────────────────────────────────────
RETENTION_ADULT_YEARS    = 10   # from date of case closure
RETENTION_CHILD_MIN_AGE  = 25   # until patient's 25th birthday, or 10 years, whichever longer
RETENTION_WARNING_MONTHS = 6    # flag records within 6 months of deletion date


# ── NHS number helpers (ISB0149) ─────────────────────────────────────────────

def format_nhs_number(nhs_number: str) -> str:
    """Format NHS number as XXX XXX XXXX per ISB0149 standard.

    Accepts numbers with or without spaces/hyphens. Returns 'Not assigned'
    for empty input. Non-10-digit strings are returned unchanged.
    """
    if not nhs_number:
        return "Not assigned"
    nhs = str(nhs_number).replace(" ", "").replace("-", "")
    if len(nhs) == 10 and nhs.isdigit():
        return f"{nhs[:3]} {nhs[3:6]} {nhs[6:]}"
    return str(nhs_number)


def nhs_reference(nhs_number: str, date: str | None = None) -> str:
    """Generate a standard NHS document reference: NHS-<digits>-<YYYYMMDD>.

    Example: NHS-4867401692-20260502
    """
    from datetime import datetime as _dt
    date_str = date or _dt.now().strftime("%Y%m%d")
    nhs_raw = str(nhs_number).replace(" ", "").replace("-", "")
    return f"NHS-{nhs_raw}-{date_str}"
