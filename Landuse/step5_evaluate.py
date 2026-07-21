"""Step 5: evaluate the trained model on the held-out test split."""

import os

import joblib
import matplotlib.pyplot as plt
import pandas as pd
from sklearn.metrics import (
    ConfusionMatrixDisplay,
    accuracy_score,
    cohen_kappa_score,
    confusion_matrix,
)

import config
from step3_split import load_features


def main():
    model_path = os.path.join(config.OUTPUT_DIR, "rf_model.joblib")
    model = joblib.load(model_path)

    df = load_features()
    test_df = df[df["split"] == "test"]
    X_test = test_df[config.FEATURE_COLUMNS]
    y_test = test_df["class_code"]

    y_pred = model.predict(X_test)

    class_codes = sorted(config.CLASSES.keys())
    class_names = [config.CLASSES[c][1] for c in class_codes]

    cm = confusion_matrix(y_test, y_pred, labels=class_codes)
    acc = accuracy_score(y_test, y_pred)
    kappa = cohen_kappa_score(y_test, y_pred)

    print("Confusion matrix (rows=actual, cols=predicted):")
    print(pd.DataFrame(cm, index=class_names, columns=class_names))
    print(f"\nOverall Accuracy: {acc:.4f}")
    print(f"Kappa: {kappa:.4f}")

    importances = pd.Series(model.feature_importances_, index=config.FEATURE_COLUMNS)
    importances = importances.sort_values(ascending=False)
    print("\nVariable Importance:")
    print(importances)

    os.makedirs(config.OUTPUT_DIR, exist_ok=True)

    disp = ConfusionMatrixDisplay(confusion_matrix=cm, display_labels=class_names)
    disp.plot(cmap="Blues")
    plt.title(f"Confusion Matrix (Accuracy={acc:.3f}, Kappa={kappa:.3f})")
    cm_path = os.path.join(config.OUTPUT_DIR, "confusion_matrix.png")
    plt.savefig(cm_path, bbox_inches="tight")
    print(f"\nConfusion matrix plot saved to {cm_path}")

    importances_path = os.path.join(config.OUTPUT_DIR, "variable_importance.csv")
    importances.to_csv(importances_path, header=["importance"])
    print(f"Variable importance saved to {importances_path}")


if __name__ == "__main__":
    main()
