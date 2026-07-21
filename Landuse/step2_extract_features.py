"""Step 2: extract Sentinel-2 band + index values (Xs) at each label point."""

import os

import ee
import pandas as pd

import config
from utils import get_bq_client, get_s2_composite, init_ee


def load_labels():
    """Prefer the BigQuery labels table; fall back to the local CSV backup from step 1."""
    table_ref = f"{config.GCP_PROJECT}.{config.BQ_DATASET}.{config.BQ_LABELS_TABLE}"
    try:
        client = get_bq_client()
        return client.query(f"SELECT * FROM `{table_ref}`").to_dataframe()
    except Exception as e:
        csv_path = os.path.join(config.OUTPUT_DIR, "labels_points.csv")
        if os.path.exists(csv_path):
            print(f"Falling back to local CSV ({csv_path}); BigQuery read failed: {e}")
            return pd.read_csv(csv_path)
        raise


def labels_to_feature_collection(df):
    features = [
        ee.Feature(
            ee.Geometry.Point([row.lon, row.lat]),
            {"point_id": int(row.point_id), "class_code": int(row.class_code)},
        )
        for row in df.itertuples()
    ]
    return ee.FeatureCollection(features)


def main():
    init_ee()
    labels_df = load_labels()
    print(f"Loaded {len(labels_df)} label points")

    fc = labels_to_feature_collection(labels_df)
    composite = get_s2_composite()

    feature_bands = config.S2_BANDS + ["NDVI", "EVI", "NDWI", "NDBI"]
    sampled = composite.select(feature_bands).sampleRegions(
        collection=fc, scale=10, geometries=False
    )
    rows = sampled.getInfo()["features"]
    records = [f["properties"] for f in rows]
    features_df = pd.DataFrame.from_records(records)

    missing = len(labels_df) - len(features_df)
    if missing > 0:
        print(
            f"WARNING: {missing} of {len(labels_df)} points had no valid pixel "
            "(likely masked by clouds in the whole composite window) and were dropped"
        )

    na_rows = features_df[feature_bands].isna().any(axis=1)
    if na_rows.any():
        print(f"Dropping {na_rows.sum()} rows with NaN feature values")
        features_df = features_df[~na_rows]

    merged = features_df.merge(
        labels_df[["point_id", "lon", "lat"]], on="point_id", how="left"
    )
    print("Final feature table shape:", merged.shape)

    dataset_ref = f"{config.GCP_PROJECT}.{config.BQ_DATASET}"
    table_ref = f"{dataset_ref}.{config.BQ_FEATURES_TABLE}"
    client = get_bq_client()
    client.create_dataset(dataset_ref, exists_ok=True)
    from google.cloud import bigquery

    client.load_table_from_dataframe(
        merged,
        table_ref,
        job_config=bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE"),
    ).result()
    print(f"Wrote {len(merged)} rows to {table_ref}")

    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    csv_path = os.path.join(config.OUTPUT_DIR, "features_points.csv")
    merged.to_csv(csv_path, index=False)
    print(f"Backup saved to {csv_path}")


if __name__ == "__main__":
    main()
