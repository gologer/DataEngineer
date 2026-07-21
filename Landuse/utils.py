"""Shared helper functions: GEE init, Sentinel-2 processing, BigQuery client, splitting."""

import ee
import numpy as np
import pandas as pd
from google.cloud import bigquery

import config


def init_ee():
    """Initialize Earth Engine, running the interactive auth flow only if needed."""
    if not config.GCP_PROJECT:
        raise RuntimeError(
            "GCP_PROJECT is not set. Set the GCP_PROJECT environment variable to a "
            "Google Cloud project that has Earth Engine enabled."
        )
    try:
        ee.Initialize(project=config.GCP_PROJECT)
    except Exception:
        ee.Authenticate()
        ee.Initialize(project=config.GCP_PROJECT)


def get_bq_client():
    if not config.GCP_PROJECT:
        raise RuntimeError(
            "GCP_PROJECT is not set. Set the GCP_PROJECT environment variable to a "
            "Google Cloud project with BigQuery billing enabled."
        )
    return bigquery.Client(project=config.GCP_PROJECT)


def bbox_geometry():
    b = config.BBOX
    return ee.Geometry.Rectangle([b["lon_min"], b["lat_min"], b["lon_max"], b["lat_max"]])


def mask_s2_clouds(image):
    """Mask clouds/cirrus using the QA60 bitmask and scale SR bands to reflectance (0-1)."""
    qa = image.select("QA60")
    cloud_bit_mask = 1 << 10
    cirrus_bit_mask = 1 << 11
    mask = qa.bitwiseAnd(cloud_bit_mask).eq(0).And(qa.bitwiseAnd(cirrus_bit_mask).eq(0))
    scaled = image.select(config.S2_BANDS).divide(10000)
    return scaled.updateMask(mask).copyProperties(image, ["system:time_start"])


def add_indices(image):
    """Add NDVI, EVI, NDWI, NDBI bands to a scaled Sentinel-2 image."""
    ndvi = image.normalizedDifference(["B8", "B4"]).rename("NDVI")
    ndwi = image.normalizedDifference(["B3", "B8"]).rename("NDWI")
    ndbi = image.normalizedDifference(["B11", "B8"]).rename("NDBI")
    evi = image.expression(
        "2.5 * ((NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1))",
        {"NIR": image.select("B8"), "RED": image.select("B4"), "BLUE": image.select("B2")},
    ).rename("EVI")
    return image.addBands([ndvi, evi, ndwi, ndbi])


def get_s2_composite():
    """Cloud-masked, index-enriched median Sentinel-2 composite over the study bbox."""
    geom = bbox_geometry()
    collection = (
        ee.ImageCollection(config.S2_COLLECTION)
        .filterBounds(geom)
        .filterDate(config.S2_DATE_START, config.S2_DATE_END)
        .map(mask_s2_clouds)
    )
    composite = collection.median().clip(geom)
    return add_indices(composite)


def add_split_column(df, class_col="class_code", train_ratio=None, seed=None):
    """Add a reproducible `random` column and a stratified `split` (train/test) column."""
    train_ratio = config.TRAIN_RATIO if train_ratio is None else train_ratio
    seed = config.SEED if seed is None else seed

    rng = np.random.RandomState(seed)
    df = df.copy()
    df["random"] = rng.uniform(0.0, 1.0, size=len(df))

    def _split(group):
        threshold = group["random"].quantile(train_ratio)
        group["split"] = np.where(group["random"] <= threshold, "train", "test")
        return group

    df = df.groupby(class_col, group_keys=False).apply(_split)
    return df.reset_index(drop=True)
