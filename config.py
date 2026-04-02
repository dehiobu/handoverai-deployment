"""
Configuration file for GP Triage POC
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Paths
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
CHROMA_DIR = BASE_DIR / "chroma_db"
LOGS_DIR = BASE_DIR / "logs"

# Create directories if they don't exist
for dir_path in [DATA_DIR, CHROMA_DIR, LOGS_DIR]:
    dir_path.mkdir(exist_ok=True)

# OpenAI Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY not found in environment variables. Please create .env file from .env.example")

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
