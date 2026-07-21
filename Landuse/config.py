"""Shared constants for the Ayutthaya land-use Random Forest project."""

import os

# --- Load .env from the project root (one level up from this file), if present ---
# The .env holds per-user secrets (GCP project, service-account key path) and is
# git-ignored. python-dotenv only sets vars that aren't already in the environment.
try:
    from dotenv import load_dotenv

    _ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    load_dotenv(_ENV_PATH)
except ImportError:
    pass

# --- Google Cloud project (used for both Earth Engine and BigQuery) ---
# Read from the environment / .env. Accept either GCP_PROJECT or GOOGLE_CLOUD_PROJECT.
GCP_PROJECT = os.environ.get("GCP_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT", "")

# The BigQuery/GEE client libraries auto-detect the service-account key from the
# GOOGLE_APPLICATION_CREDENTIALS env var; loading .env above makes it visible here.

# --- Study area: bbox around Ayutthaya ---
BBOX = {
    "lon_min": 100.45,
    "lon_max": 100.65,
    "lat_min": 14.25,
    "lat_max": 14.45,
}

# --- Reproducibility ---
SEED = 42

# --- Label classes ---
# code -> (english slug, Thai display name)
CLASSES = {
    1: ("water", "น้ำ"),
    2: ("urban", "เมือง"),
    3: ("agriculture", "เกษตร"),
    4: ("forest", "ไม้ยืนต้น"),
}
POINTS_PER_CLASS = 200

# Map colors per class code (per the brief: water=blue, urban=red, agri=yellow, forest=green)
CLASS_COLORS = {
    1: "#0000FF",
    2: "#FF0000",
    3: "#FFFF00",
    4: "#008000",
}

# --- BigQuery ---
BQ_DATASET = "landuse"
BQ_LABELS_TABLE = "labels_points"
BQ_FEATURES_TABLE = "features_points"
BQ_MODEL_TREES_TABLE = "model_trees"

# --- Sentinel-2 ---
S2_COLLECTION = "COPERNICUS/S2_SR_HARMONIZED"
# Dry season composite window (low cloud cover over central Thailand)
S2_DATE_START = "2025-11-01"
S2_DATE_END = "2026-02-28"
S2_BANDS = ["B2", "B3", "B4", "B8", "B11", "B12"]
S2_CLOUD_PROB_MAX = 20  # max allowed cloud probability for masking

# --- Model ---
N_ESTIMATORS = 100
TRAIN_RATIO = 0.7
FEATURE_COLUMNS = ["B2", "B3", "B4", "B8", "B11", "B12", "NDVI", "EVI", "NDWI", "NDBI"]

# --- Local paths ---
OUTPUT_DIR = "outputs"
