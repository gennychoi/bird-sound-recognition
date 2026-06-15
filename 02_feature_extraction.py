"""
Feature Extraction — BirdCLEF 2026
Extracts and saves three representations:
  features/X_ml.npy       — statistical feature vector (for traditional ML)
  features/X_mel.npy      — log-mel spectrogram (for CNN)
  features/X_mfcc_seq.npy — MFCC time-series (for LSTM)
  features/y.npy          — integer labels
  features/label_names.npy — string labels (species codes)
  features/label_encoder.pkl
"""

import os
import pickle
import json
import numpy as np
import pandas as pd
from tqdm import tqdm
from sklearn.preprocessing import LabelEncoder

from config import (DATA_DIR, FEATURES_DIR, TOP_N_CLASSES,
                    MAX_SAMPLES_ML, MAX_SAMPLES_DL, RANDOM_STATE)
from utils import load_audio, extract_features, get_mel_spectrogram, get_mfcc_sequence

os.makedirs(FEATURES_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Build file list
# ---------------------------------------------------------------------------
df = pd.read_csv(os.path.join(DATA_DIR, "train.csv"))
taxa = pd.read_csv(os.path.join(DATA_DIR, "taxonomy.csv"))
name_map = taxa.set_index("primary_label")["common_name"].to_dict()

birds = df[df["class_name"] == "Aves"].copy()
top_species = birds["primary_label"].value_counts().head(TOP_N_CLASSES).index.tolist()
birds = birds[birds["primary_label"].isin(top_species)].copy()
print(f"Using {len(top_species)} species, {len(birds)} total samples before capping")

# Reproducible per-class sampling
rng = np.random.default_rng(RANDOM_STATE)
selected_rows = []
for sp in top_species:
    sp_rows = birds[birds["primary_label"] == sp]
    n = min(len(sp_rows), MAX_SAMPLES_DL)
    idx = rng.choice(len(sp_rows), size=n, replace=False)
    selected_rows.append(sp_rows.iloc[idx])

selected = pd.concat(selected_rows).reset_index(drop=True)
print(f"Selected {len(selected)} samples across {len(top_species)} species")

# ---------------------------------------------------------------------------
# Label encoding
# ---------------------------------------------------------------------------
le = LabelEncoder()
le.fit(top_species)
with open(os.path.join(FEATURES_DIR, "label_encoder.pkl"), "wb") as f:
    pickle.dump(le, f)

# Save human-readable class info
class_info = {sp: name_map.get(sp, sp) for sp in top_species}
with open(os.path.join(FEATURES_DIR, "class_info.json"), "w") as f:
    json.dump(class_info, f, indent=2)
print("Saved label encoder and class info")

# ---------------------------------------------------------------------------
# Extract features
# ---------------------------------------------------------------------------
X_ml, X_mel, X_mfcc, y_all = [], [], [], []
failed = 0

for _, row in tqdm(selected.iterrows(), total=len(selected), desc="Extracting features"):
    fpath = os.path.join(DATA_DIR, "train_audio", row["filename"])
    label = le.transform([row["primary_label"]])[0]
    try:
        audio = load_audio(fpath)
        X_ml.append(extract_features(audio))
        X_mel.append(get_mel_spectrogram(audio))
        X_mfcc.append(get_mfcc_sequence(audio))
        y_all.append(label)
    except Exception as e:
        failed += 1

print(f"\nExtracted {len(y_all)} samples ({failed} failed)")

X_ml = np.array(X_ml, dtype=np.float32)
X_mel = np.array(X_mel, dtype=np.float32)
X_mfcc = np.array(X_mfcc, dtype=np.float32)
y_all = np.array(y_all, dtype=np.int64)

print(f"X_ml shape:   {X_ml.shape}")
print(f"X_mel shape:  {X_mel.shape}")
print(f"X_mfcc shape: {X_mfcc.shape}")
print(f"y shape:      {y_all.shape}")

np.save(os.path.join(FEATURES_DIR, "X_ml.npy"), X_ml)
np.save(os.path.join(FEATURES_DIR, "X_mel.npy"), X_mel)
np.save(os.path.join(FEATURES_DIR, "X_mfcc_seq.npy"), X_mfcc)
np.save(os.path.join(FEATURES_DIR, "y.npy"), y_all)
np.save(os.path.join(FEATURES_DIR, "label_names.npy"),
        np.array(le.classes_, dtype=str))

print("\nAll features saved to:", FEATURES_DIR)

# Quick sanity check
print("\nPer-class sample counts:")
for i, sp in enumerate(le.classes_):
    cnt = int((y_all == i).sum())
    print(f"  {sp:12s} ({name_map.get(sp, '?')[:30]:<30s}): {cnt}")
