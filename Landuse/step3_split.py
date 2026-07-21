"""Step 3: add a reproducible `random` column and stratified 70:30 train/test split."""

import os

import pandas as pd

import config
from utils import add_split_column, get_bq_client


def load_features():
    table_ref = f"{config.GCP_PROJECT}.{config.BQ_DATASET}.{config.BQ_FEATURES_TABLE}"
    try:
        client = get_bq_client()
        return client.query(f"SELECT * FROM `{table_ref}`").to_dataframe()
    except Exception as e:
        csv_path = os.path.join(config.OUTPUT_DIR, "features_points.csv")
        if os.path.exists(csv_path):
            print(f"Falling back to local CSV ({csv_path}); BigQuery read failed: {e}")
            return pd.read_csv(csv_path)
        raise


def main():
    df = load_features()
    df = add_split_column(df)

    counts = df.groupby(["class_code", "split"]).size().unstack(fill_value=0)
    print("Train/test counts per class:\n", counts)

    dataset_ref = f"{config.GCP_PROJECT}.{config.BQ_DATASET}"
    table_ref = f"{dataset_ref}.{config.BQ_FEATURES_TABLE}"
    client = get_bq_client()
    from google.cloud import bigquery

    client.load_table_from_dataframe(
        df,
        table_ref,
        job_config=bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE"),
    ).result()
    print(f"Updated {table_ref} with random/split columns")

    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    csv_path = os.path.join(config.OUTPUT_DIR, "features_points.csv")
    df.to_csv(csv_path, index=False)
    print(f"Backup saved to {csv_path}")


if __name__ == "__main__":
    main()
