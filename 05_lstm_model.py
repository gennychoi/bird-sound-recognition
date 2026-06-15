"""
Bidirectional LSTM on MFCC sequences — BirdCLEF 2026
Input shape: (batch, SPEC_FRAMES, N_MFCC)
"""

import os
import json
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, confusion_matrix, f1_score

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader, WeightedRandomSampler

from config import (FEATURES_DIR, MODELS_DIR, RESULTS_DIR,
                    RANDOM_STATE, TEST_SIZE, VAL_SIZE,
                    BATCH_SIZE, EPOCHS_LSTM, LR, PATIENCE, N_MFCC, SPEC_FRAMES)

os.makedirs(MODELS_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)
torch.manual_seed(RANDOM_STATE)
np.random.seed(RANDOM_STATE)

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Using device: {DEVICE}")

# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------
class MFCCDataset(Dataset):
    def __init__(self, X, y):
        self.X = torch.tensor(X, dtype=torch.float32)  # (N, T, n_mfcc)
        self.y = torch.tensor(y, dtype=torch.long)

    def __len__(self):
        return len(self.y)

    def __getitem__(self, idx):
        return self.X[idx], self.y[idx]


# ---------------------------------------------------------------------------
# Bidirectional LSTM model
# ---------------------------------------------------------------------------
class BirdLSTM(nn.Module):
    def __init__(self, input_size: int, hidden_size: int,
                 num_layers: int, n_classes: int, dropout: float = 0.3):
        super().__init__()
        self.lstm = nn.LSTM(input_size, hidden_size, num_layers=num_layers,
                             batch_first=True, bidirectional=True,
                             dropout=dropout if num_layers > 1 else 0.0)
        feat_dim = hidden_size * 2  # bidirectional

        # Attention pooling
        self.attention = nn.Linear(feat_dim, 1)

        self.classifier = nn.Sequential(
            nn.Linear(feat_dim, 256), nn.ReLU(), nn.Dropout(0.4),
            nn.Linear(256, 128), nn.ReLU(), nn.Dropout(0.3),
            nn.Linear(128, n_classes),
        )

    def forward(self, x):
        # x: (batch, T, input_size)
        out, _ = self.lstm(x)               # (batch, T, 2*hidden)
        # Attention over time steps
        attn_w = torch.softmax(self.attention(out), dim=1)  # (batch, T, 1)
        context = (attn_w * out).sum(dim=1)                  # (batch, 2*hidden)
        return self.classifier(context)


# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
X = np.load(os.path.join(FEATURES_DIR, "X_mfcc_seq.npy"))   # (N, T, N_MFCC)
y = np.load(os.path.join(FEATURES_DIR, "y.npy"))
label_names = np.load(os.path.join(FEATURES_DIR, "label_names.npy"))
with open(os.path.join(FEATURES_DIR, "class_info.json")) as f:
    class_info = json.load(f)
n_classes = len(label_names)

print(f"X shape: {X.shape}  y shape: {y.shape}  n_classes: {n_classes}")

# Train / val / test split
X_tmp, X_test, y_tmp, y_test = train_test_split(
    X, y, test_size=TEST_SIZE, stratify=y, random_state=RANDOM_STATE)
val_frac = VAL_SIZE / (1 - TEST_SIZE)
X_train, X_val, y_train, y_val = train_test_split(
    X_tmp, y_tmp, test_size=val_frac, stratify=y_tmp, random_state=RANDOM_STATE)
print(f"Train: {len(y_train)}  Val: {len(y_val)}  Test: {len(y_test)}")

class_counts = np.bincount(y_train, minlength=n_classes)
weights = 1.0 / class_counts[y_train]
sampler = WeightedRandomSampler(weights, len(y_train), replacement=True)

train_dl = DataLoader(MFCCDataset(X_train, y_train), batch_size=BATCH_SIZE,
                       sampler=sampler)
val_dl = DataLoader(MFCCDataset(X_val, y_val), batch_size=BATCH_SIZE, shuffle=False)
test_dl = DataLoader(MFCCDataset(X_test, y_test), batch_size=BATCH_SIZE, shuffle=False)

# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------
model = BirdLSTM(input_size=N_MFCC, hidden_size=128, num_layers=2,
                  n_classes=n_classes, dropout=0.3).to(DEVICE)
print(f"\nModel parameters: {sum(p.numel() for p in model.parameters()):,}")

criterion = nn.CrossEntropyLoss()
optimizer = optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-4)
scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, patience=3,
                                                   factor=0.5, verbose=True)

def run_epoch(loader, training=True):
    model.train() if training else model.eval()
    total_loss, correct, n = 0, 0, 0
    ctx = torch.enable_grad() if training else torch.no_grad()
    with ctx:
        for X_b, y_b in loader:
            X_b, y_b = X_b.to(DEVICE), y_b.to(DEVICE)
            if training:
                optimizer.zero_grad()
            out = model(X_b)
            loss = criterion(out, y_b)
            if training:
                loss.backward()
                nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
            total_loss += loss.item() * len(y_b)
            correct += (out.argmax(1) == y_b).sum().item()
            n += len(y_b)
    return total_loss / n, correct / n

best_val_acc, patience_cnt = 0.0, 0
train_losses, val_losses, train_accs, val_accs = [], [], [], []

print(f"\nTraining BiLSTM for up to {EPOCHS_LSTM} epochs…")
for epoch in range(1, EPOCHS_LSTM + 1):
    tr_loss, tr_acc = run_epoch(train_dl, training=True)
    val_loss, val_acc = run_epoch(val_dl, training=False)
    scheduler.step(val_loss)

    train_losses.append(tr_loss); val_losses.append(val_loss)
    train_accs.append(tr_acc); val_accs.append(val_acc)

    print(f"  Epoch {epoch:3d}/{EPOCHS_LSTM} | "
          f"Train loss {tr_loss:.4f} acc {tr_acc:.4f} | "
          f"Val loss {val_loss:.4f} acc {val_acc:.4f}")

    if val_acc > best_val_acc:
        best_val_acc = val_acc
        patience_cnt = 0
        torch.save(model.state_dict(),
                   os.path.join(MODELS_DIR, "lstm_best.pt"))
    else:
        patience_cnt += 1
        if patience_cnt >= PATIENCE:
            print(f"  Early stopping at epoch {epoch}")
            break

model.load_state_dict(torch.load(os.path.join(MODELS_DIR, "lstm_best.pt"),
                                  map_location=DEVICE))

# ---------------------------------------------------------------------------
# Training curves
# ---------------------------------------------------------------------------
ep = range(1, len(train_losses) + 1)
fig, axes = plt.subplots(1, 2, figsize=(12, 4))
axes[0].plot(ep, train_losses, label="Train"); axes[0].plot(ep, val_losses, label="Val")
axes[0].set(title="BiLSTM Loss", xlabel="Epoch", ylabel="Loss"); axes[0].legend()
axes[1].plot(ep, train_accs, label="Train"); axes[1].plot(ep, val_accs, label="Val")
axes[1].set(title="BiLSTM Accuracy", xlabel="Epoch", ylabel="Accuracy"); axes[1].legend()
plt.tight_layout()
plt.savefig(os.path.join(RESULTS_DIR, "lstm_training_curves.png"), dpi=150)
plt.close()

# ---------------------------------------------------------------------------
# Test evaluation
# ---------------------------------------------------------------------------
model.eval()
all_preds, all_true = [], []
with torch.no_grad():
    for X_b, y_b in test_dl:
        preds = model(X_b.to(DEVICE)).argmax(1).cpu().numpy()
        all_preds.extend(preds); all_true.extend(y_b.numpy())

all_preds = np.array(all_preds); all_true = np.array(all_true)
test_acc = (all_preds == all_true).mean()
test_f1 = f1_score(all_true, all_preds, average="macro")
print(f"\nBiLSTM Test accuracy: {test_acc:.4f}   Macro F1: {test_f1:.4f}")
print(classification_report(all_true, all_preds,
                              target_names=label_names, zero_division=0))

short_names = [class_info.get(sp, sp)[:12] for sp in label_names]
cm = confusion_matrix(all_true, all_preds)
fig, ax = plt.subplots(figsize=(13, 11))
sns.heatmap(cm, annot=True, fmt="d", cmap="Greens",
            xticklabels=short_names, yticklabels=short_names, ax=ax, linewidths=0.3)
ax.set(xlabel="Predicted", ylabel="True",
       title=f"BiLSTM Confusion Matrix — Test Acc={test_acc:.3f}  F1={test_f1:.3f}")
plt.xticks(rotation=45, ha="right", fontsize=7)
plt.yticks(fontsize=7)
plt.tight_layout()
plt.savefig(os.path.join(RESULTS_DIR, "lstm_confusion_matrix.png"), dpi=150)
plt.close()
print("Saved BiLSTM results to", RESULTS_DIR)
