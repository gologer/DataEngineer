"""Step 4: train the Random Forest classifier on the training split."""

import os

import joblib
from sklearn.ensemble import RandomForestClassifier

import config
from step3_split import load_features


def main():
    df = load_features()
    if "split" not in df.columns:
        raise RuntimeError("No `split` column found -- run step3_split.py first")

    train_df = df[df["split"] == "train"]
    X_train = train_df[config.FEATURE_COLUMNS]
    y_train = train_df["class_code"]

    model = RandomForestClassifier(n_estimators=config.N_ESTIMATORS, random_state=config.SEED)
    model.fit(X_train, y_train)
    print(f"Trained RandomForestClassifier on {len(train_df)} points, "
          f"{config.N_ESTIMATORS} trees")

    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    model_path = os.path.join(config.OUTPUT_DIR, "rf_model.joblib")
    joblib.dump(model, model_path)
    print(f"Model saved to {model_path}")


if __name__ == "__main__":
    main()
