"""Step 7: persist the trained Random Forest in BigQuery so it can be reloaded later
without retraining.

Two tables are written:
  - `model_trees`    -- one row per tree with a human-readable rule dump (for inspection).
  - `model_artifact` -- a single row holding the whole model, joblib-serialized and
                        base64-encoded, so `load_model()` can restore the exact sklearn
                        object (readable text rules alone can't be re-parsed back into a
                        working classifier).
"""

import base64
import io
import os

import joblib
import pandas as pd
from sklearn.tree import export_text

import config
from utils import get_bq_client

MODEL_TREES_TABLE = config.BQ_MODEL_TREES_TABLE
MODEL_ARTIFACT_TABLE = "model_artifact"


def save_model(model_path=None):
    model_path = model_path or os.path.join(config.OUTPUT_DIR, "rf_model.joblib")
    model = joblib.load(model_path)

    rules_df = pd.DataFrame(
        {
            "tree_id": range(len(model.estimators_)),
            "tree_rules": [
                export_text(tree, feature_names=config.FEATURE_COLUMNS)
                for tree in model.estimators_
            ],
        }
    )

    buf = io.BytesIO()
    joblib.dump(model, buf)
    artifact_df = pd.DataFrame(
        {
            "model_version": [1],
            "n_estimators": [config.N_ESTIMATORS],
            "seed": [config.SEED],
            "feature_columns": [",".join(config.FEATURE_COLUMNS)],
            "model_blob_b64": [base64.b64encode(buf.getvalue()).decode("ascii")],
        }
    )

    client = get_bq_client()
    from google.cloud import bigquery

    dataset_ref = f"{config.GCP_PROJECT}.{config.BQ_DATASET}"
    client.create_dataset(dataset_ref, exists_ok=True)

    trees_ref = f"{dataset_ref}.{MODEL_TREES_TABLE}"
    client.load_table_from_dataframe(
        rules_df, trees_ref, job_config=bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE")
    ).result()
    print(f"Wrote {len(rules_df)} tree rule-dumps to {trees_ref}")

    artifact_ref = f"{dataset_ref}.{MODEL_ARTIFACT_TABLE}"
    client.load_table_from_dataframe(
        artifact_df,
        artifact_ref,
        job_config=bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE"),
    ).result()
    print(f"Wrote model artifact to {artifact_ref}")


def load_model():
    """Reconstruct the sklearn RandomForestClassifier from BigQuery."""
    client = get_bq_client()
    artifact_ref = f"{config.GCP_PROJECT}.{config.BQ_DATASET}.{MODEL_ARTIFACT_TABLE}"
    df = client.query(f"SELECT * FROM `{artifact_ref}` ORDER BY model_version DESC LIMIT 1").to_dataframe()
    if df.empty:
        raise RuntimeError(f"No model found in {artifact_ref} -- run save_model() first")

    blob = base64.b64decode(df.loc[0, "model_blob_b64"])
    model = joblib.load(io.BytesIO(blob))
    print(f"Loaded model_version={df.loc[0, 'model_version']} from {artifact_ref}")
    return model


if __name__ == "__main__":
    save_model()
