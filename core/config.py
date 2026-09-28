"""App-wide settings: models, prices, limits and paths."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "app.db"
SAMPLES_DIR = ROOT / "samples"

# Selectable in Settings. Prices are USD per 1M tokens. `fallbacks` enables the
# API's server-side fallback, which re-runs a declined request on another model.
MODELS = {
    "claude-opus-5": {"label": "Claude Opus 5 (best quality)", "input": 5.00, "output": 25.00, "fallbacks": True},
    "claude-sonnet-5": {"label": "Claude Sonnet 5 (lower cost)", "input": 2.00, "output": 10.00, "fallbacks": False},
}
DEFAULT_MODEL = "claude-opus-5"

# Prompt-cache pricing as multiples of the base input price.
CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.10

# Warn above this transcript size (a single meeting fits comfortably in one call).
TRANSCRIPT_WARN_TOKENS = 150_000

STAGES = ["extract", "epics", "stories", "tasks", "raid_email"]
STAGE_LABELS = {
    "extract": "1. Extract",
    "epics": "2. Epics",
    "stories": "3. Stories",
    "tasks": "4. Tasks & dependencies",
    "raid_email": "5. RAID log & follow-up email",
}

PRIORITIES = ["High", "Medium", "Low"]
FIBONACCI_POINTS = [1, 2, 3, 5, 8, 13]
DOR_MAX_POINTS = 8
DOR_MIN_ACCEPTANCE_CRITERIA = 2
