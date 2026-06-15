"""
Traditional ML — KNN, SVM, Random Forest
Loads pre-extracted features, trains with 5-fold stratified CV,
evaluates on held-out test set, saves models and plots.
"""

import os
import pickle
import json
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.model_selection import StratifiedKFold, GridSearchCV, train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.neighbors import KNeighborsClassifier
from sklearn.svm import SVC
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (accuracy_score, classification_report,
                              confusion_matrix, f1_score)

from config import FEATURES_DIR, MODELS_DIR, RESULTS_DIR, RANDOM_STATE, TEST_SIZE, MAX_SAMPLES_ML

os.makedirs(MODELS_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Load features
# ---------------------------------------------------------------------------
X = np.load(os.path.join(FEATURES_DIR, "X_ml.npy"))
y = np.load(os.path.join(FEATURES_DIR, "y.npy"))
label_names = np.load(os.path.join(FEATURES_DIR, "label_names.npy"))
with open(os.path.join(FEATURES_DIR, "class_info.json")) as f:
    class_info = json.load(f)

# Cap per-class samples for traditional ML to keep training fast
from collections import Counter
counts = Counter(y)
keep_idx = []
rng = np.random.default_rng(RANDOM_STATE)
for cls, cnt in counts.items():
    idx = np.where(y == cls)[0]
    n = min(cnt, MAX_SAMPLES_ML)
    keep_idx.extend(rng.choice(idx, size=n, replace=False).tolist())
keep_idx = sorted(keep_idx)
X = X[keep_idx]
y = y[keep_idx]
print(f"Using {len(y)} samples for traditional ML ({len(label_names)} classes)")

# Train / test split (stratified)
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=TEST_SIZE, stratify=y, random_state=RANDOM_STATE)
print(f"Train: {len(y_train)}  Test: {len(y_test)}")

# Short display names for plots
short_names = [class_info.get(sp, sp)[:12] for sp in label_names]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=RANDOM_STATE)

def evaluate_and_save(name, model, X_tr, y_tr, X_te, y_te):
    """Fit, CV score, test score, save model + confusion matrix."""
    print(f"\n{'='*50}")
    print(f"Model: {name}")

    # 5-fold CV on training set
    from sklearn.model_selection import cross_val_score
    cv_scores = cross_val_score(model, X_tr, y_tr, cv=cv,
                                 scoring="accuracy", n_jobs=-1)
    print(f"  5-fold CV accuracy: {cv_scores.mean():.4f} ± {cv_scores.std():.4f}")

    # Fit on full training set
    model.fit(X_tr, y_tr)
    y_pred = model.predict(X_te)

    acc = accuracy_score(y_te, y_pred)
    f1 = f1_score(y_te, y_pred, average="macro")
    print(f"  Test accuracy: {acc:.4f}   Macro F1: {f1:.4f}")
    print(classification_report(y_te, y_pred,
                                  target_names=label_names, zero_division=0))

    # Confusion matrix
    cm = confusion_matrix(y_te, y_pred)
    fig, ax = plt.subplots(figsize=(12, 10))
    sns.heatmap(cm, annot=True, fmt="d", cmap="Blues",
                xticklabels=short_names, yticklabels=short_names,
                ax=ax, linewidths=0.3)
    ax.set_xlabel("Predicted")
    ax.set_ylabel("True")
    ax.set_title(f"{name} — Confusion Matrix (Test Set)\nAcc={acc:.3f}  F1={f1:.3f}")
    plt.xticks(rotation=45, ha="right", fontsize=7)
    plt.yticks(rotation=0, fontsize=7)
    plt.tight_layout()
    fname = f"cm_{name.lower().replace(' ', '_')}.png"
    plt.savefig(os.path.join(RESULTS_DIR, fname), dpi=150)
    plt.close()

    # Save model
    model_path = os.path.join(MODELS_DIR, f"{name.lower().replace(' ', '_')}.pkl")
    with open(model_path, "wb") as f:
        pickle.dump(model, f)
    print(f"  Saved: {model_path}")

    return {"model": name, "cv_mean": cv_scores.mean(), "cv_std": cv_scores.std(),
            "test_acc": acc, "macro_f1": f1}


# ---------------------------------------------------------------------------
# K-Nearest Neighbours
# ---------------------------------------------------------------------------
knn_pipe = Pipeline([
    ("scaler", StandardScaler()),
    ("knn", KNeighborsClassifier(n_neighbors=5, metric="euclidean", n_jobs=-1))
])

# Quick grid search for k
param_grid_knn = {"knn__n_neighbors": [3, 5, 7, 11, 15]}
gs_knn = GridSearchCV(knn_pipe, param_grid_knn, cv=cv, scoring="accuracy",
                       n_jobs=-1, verbose=0)
gs_knn.fit(X_train, y_train)
print(f"KNN best k = {gs_knn.best_params_['knn__n_neighbors']}, "
      f"CV acc = {gs_knn.best_score_:.4f}")
best_knn = gs_knn.best_estimator_
r_knn = evaluate_and_save("KNN", best_knn, X_train, y_train, X_test, y_test)

# ---------------------------------------------------------------------------
# Support Vector Machine
# ---------------------------------------------------------------------------
svm_pipe = Pipeline([
    ("scaler", StandardScaler()),
    ("svm", SVC(kernel="rbf", C=10, gamma="scale",
                decision_function_shape="ovr", random_state=RANDOM_STATE))
])
r_svm = evaluate_and_save("SVM", svm_pipe, X_train, y_train, X_test, y_test)

# ---------------------------------------------------------------------------
# Random Forest
# ---------------------------------------------------------------------------
rf = RandomForestClassifier(n_estimators=200, max_depth=None,
                             min_samples_split=2, n_jobs=-1,
                             random_state=RANDOM_STATE)
r_rf = evaluate_and_save("Random Forest", rf, X_train, y_train, X_test, y_test)

# ---------------------------------------------------------------------------
# Summary comparison plot
# ---------------------------------------------------------------------------
results = [r_knn, r_svm, r_rf]
res_df = pd.DataFrame(results).set_index("model")
print("\n=== Summary ===")
print(res_df.to_string())

fig, ax = plt.subplots(figsize=(8, 5))
x = np.arange(len(res_df))
w = 0.3
ax.bar(x - w, res_df["cv_mean"], w, label="CV Accuracy", color="steelblue",
       yerr=res_df["cv_std"], capsize=4)
ax.bar(x, res_df["test_acc"], w, label="Test Accuracy", color="coral")
ax.bar(x + w, res_df["macro_f1"], w, label="Macro F1", color="seagreen")
ax.set_xticks(x)
ax.set_xticklabels(res_df.index)
ax.set_ylim(0, 1.05)
ax.set_ylabel("Score")
ax.set_title("Traditional ML Model Comparison")
ax.legend()
plt.tight_layout()
plt.savefig(os.path.join(RESULTS_DIR, "ml_comparison.png"), dpi=150)
plt.close()
print("\nSaved: ml_comparison.png")

# Save numerical results
res_df.to_csv(os.path.join(RESULTS_DIR, "ml_results.csv"))
print("Saved: ml_results.csv")

# ---------------------------------------------------------------------------
# Feature importance from Random Forest
# ---------------------------------------------------------------------------
importances = rf.feature_importances_
top_k = 20
top_idx = np.argsort(importances)[-top_k:][::-1]

# Build feature names
feat_names = []
prefixes = (
    [f"MFCC_{i}_mean" for i in range(40)] + [f"MFCC_{i}_std" for i in range(40)] +
    [f"dMFCC_{i}_mean" for i in range(40)] + [f"dMFCC_{i}_std" for i in range(40)] +
    [f"ddMFCC_{i}_mean" for i in range(40)] + [f"ddMFCC_{i}_std" for i in range(40)] +
    [f"Chroma_{i}_mean" for i in range(12)] + [f"Chroma_{i}_std" for i in range(12)] +
    ["SpCentroid_mean", "SpCentroid_std", "SpBandwidth_mean", "SpBandwidth_std",
     "SpRolloff_mean", "SpRolloff_std", "SpFlatness_mean", "SpFlatness_std",
     "ZCR_mean", "ZCR_std", "RMS_mean", "RMS_std",
     "Pitch_mean", "Pitch_std"]
)
feat_names = prefixes

fig, ax = plt.subplots(figsize=(10, 6))
ax.barh(range(top_k), importances[top_idx][::-1], color="mediumpurple")
ax.set_yticks(range(top_k))
ax.set_yticklabels([feat_names[i] if i < len(feat_names) else f"feat_{i}"
                    for i in top_idx[::-1]], fontsize=8)
ax.set_xlabel("Importance")
ax.set_title(f"Top {top_k} Feature Importances (Random Forest)")
plt.tight_layout()
plt.savefig(os.path.join(RESULTS_DIR, "rf_feature_importance.png"), dpi=150)
plt.close()
print("Saved: rf_feature_importance.png")
