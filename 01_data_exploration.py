"""
Data Exploration — BirdCLEF 2026
Generates visualisations saved to results/
"""

import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import librosa
import librosa.display
import warnings
warnings.filterwarnings("ignore")

from config import DATA_DIR, RESULTS_DIR, SR, DURATION, N_MFCC, HOP_LENGTH, N_FFT, N_MELS, TOP_N_CLASSES

os.makedirs(RESULTS_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Load metadata
# ---------------------------------------------------------------------------
df = pd.read_csv(os.path.join(DATA_DIR, "train.csv"))
print(f"Total samples: {len(df)}")
print(f"Class breakdown:\n{df['class_name'].value_counts()}\n")

birds = df[df["class_name"] == "Aves"].copy()
print(f"Bird (Aves) samples: {len(birds)}")
print(f"Unique bird species: {birds['primary_label'].nunique()}")

# Top N species
top_species = birds["primary_label"].value_counts().head(TOP_N_CLASSES)
print(f"\nTop {TOP_N_CLASSES} species by sample count:\n{top_species}")

# ---------------------------------------------------------------------------
# Figure 1: Class distribution bar chart
# ---------------------------------------------------------------------------
fig, axes = plt.subplots(1, 2, figsize=(16, 5))

# All classes (Aves top 20)
top_species.plot(kind="barh", ax=axes[0], color="steelblue")
axes[0].set_xlabel("Number of samples")
axes[0].set_title(f"Top {TOP_N_CLASSES} Bird Species by Sample Count")
axes[0].invert_yaxis()

# Get common names for top species
taxa = pd.read_csv(os.path.join(DATA_DIR, "taxonomy.csv"))
top_df = top_species.reset_index()
top_df.columns = ["primary_label", "count"]
top_df = top_df.merge(taxa[["primary_label", "common_name"]], on="primary_label", how="left")
top_df["label"] = top_df["common_name"].fillna(top_df["primary_label"])
top_df.set_index("label")["count"].plot(kind="barh", ax=axes[1], color="coral")
axes[1].set_xlabel("Number of samples")
axes[1].set_title("Top Species with Common Names")
axes[1].invert_yaxis()

plt.tight_layout()
plt.savefig(os.path.join(RESULTS_DIR, "01_class_distribution.png"), dpi=150)
plt.close()
print("Saved: 01_class_distribution.png")

# ---------------------------------------------------------------------------
# Figure 2: All class types pie chart
# ---------------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(6, 6))
df["class_name"].value_counts().plot(kind="pie", ax=ax, autopct="%1.1f%%",
                                      startangle=140, colors=plt.cm.Set3.colors)
ax.set_ylabel("")
ax.set_title("Sample Distribution by Taxonomic Class")
plt.tight_layout()
plt.savefig(os.path.join(RESULTS_DIR, "02_taxonomy_pie.png"), dpi=150)
plt.close()
print("Saved: 02_taxonomy_pie.png")

# ---------------------------------------------------------------------------
# Figure 3: Waveform, Mel-spectrogram, MFCC for a sample file
# ---------------------------------------------------------------------------
sample_row = birds[birds["primary_label"] == top_species.index[0]].iloc[0]
audio_path = os.path.join(DATA_DIR, "train_audio", sample_row["filename"])

print(f"\nSample file: {audio_path}")
y, sr = librosa.load(audio_path, sr=SR, mono=True, duration=DURATION)
if len(y) < int(SR * DURATION):
    y = np.pad(y, (0, int(SR * DURATION) - len(y)))

fig = plt.figure(figsize=(14, 10))
gs = gridspec.GridSpec(3, 2, figure=fig)

# Waveform
ax1 = fig.add_subplot(gs[0, :])
librosa.display.waveshow(y, sr=sr, ax=ax1, color="steelblue")
ax1.set_title(f"Waveform — {sample_row.get('common_name', sample_row['primary_label'])}")
ax1.set_xlabel("Time (s)")

# Mel-spectrogram
ax2 = fig.add_subplot(gs[1, 0])
mel = librosa.feature.melspectrogram(y=y, sr=sr, n_mels=N_MELS,
                                      n_fft=N_FFT, hop_length=HOP_LENGTH)
log_mel = librosa.power_to_db(mel, ref=np.max)
img = librosa.display.specshow(log_mel, sr=sr, hop_length=HOP_LENGTH,
                                x_axis="time", y_axis="mel", ax=ax2)
fig.colorbar(img, ax=ax2, format="%+2.0f dB")
ax2.set_title("Mel-Spectrogram")

# STFT spectrogram
ax3 = fig.add_subplot(gs[1, 1])
D = librosa.amplitude_to_db(np.abs(librosa.stft(y, n_fft=N_FFT, hop_length=HOP_LENGTH)),
                              ref=np.max)
img2 = librosa.display.specshow(D, sr=sr, hop_length=HOP_LENGTH,
                                  x_axis="time", y_axis="log", ax=ax3)
fig.colorbar(img2, ax=ax3, format="%+2.0f dB")
ax3.set_title("STFT Spectrogram (log frequency)")

# MFCC
ax4 = fig.add_subplot(gs[2, 0])
mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=N_MFCC,
                              n_fft=N_FFT, hop_length=HOP_LENGTH)
img3 = librosa.display.specshow(mfcc, sr=sr, hop_length=HOP_LENGTH,
                                  x_axis="time", ax=ax4)
fig.colorbar(img3, ax=ax4)
ax4.set_title(f"MFCC ({N_MFCC} coefficients)")
ax4.set_ylabel("MFCC index")

# Chroma
ax5 = fig.add_subplot(gs[2, 1])
chroma = librosa.feature.chroma_stft(y=y, sr=sr, n_fft=N_FFT, hop_length=HOP_LENGTH)
img4 = librosa.display.specshow(chroma, sr=sr, hop_length=HOP_LENGTH,
                                  x_axis="time", y_axis="chroma", ax=ax5)
fig.colorbar(img4, ax=ax5)
ax5.set_title("Chroma Features")

plt.suptitle(f"Audio Analysis: {sample_row.get('common_name', sample_row['primary_label'])}",
             fontsize=14, y=1.01)
plt.tight_layout()
plt.savefig(os.path.join(RESULTS_DIR, "03_audio_analysis.png"), dpi=150, bbox_inches="tight")
plt.close()
print("Saved: 03_audio_analysis.png")

# ---------------------------------------------------------------------------
# Figure 4: Feature comparison across 4 different species
# ---------------------------------------------------------------------------
fig, axes = plt.subplots(4, 2, figsize=(14, 14))
sample_labels = top_species.index[:4].tolist()

for i, label in enumerate(sample_labels):
    row = birds[birds["primary_label"] == label].iloc[0]
    path = os.path.join(DATA_DIR, "train_audio", row["filename"])
    try:
        yy, _ = librosa.load(path, sr=SR, mono=True, duration=DURATION)
        if len(yy) < int(SR * DURATION):
            yy = np.pad(yy, (0, int(SR * DURATION) - len(yy)))

        mel_i = librosa.power_to_db(
            librosa.feature.melspectrogram(y=yy, sr=SR, n_mels=N_MELS,
                                           n_fft=N_FFT, hop_length=HOP_LENGTH),
            ref=np.max)
        mfcc_i = librosa.feature.mfcc(y=yy, sr=SR, n_mfcc=N_MFCC,
                                       n_fft=N_FFT, hop_length=HOP_LENGTH)
        common = taxa[taxa["primary_label"] == label]["common_name"].values
        title = common[0] if len(common) > 0 else label

        librosa.display.specshow(mel_i, sr=SR, hop_length=HOP_LENGTH,
                                  x_axis="time", y_axis="mel", ax=axes[i][0])
        axes[i][0].set_title(f"Mel-Spec: {title}", fontsize=9)

        librosa.display.specshow(mfcc_i, sr=SR, hop_length=HOP_LENGTH,
                                  x_axis="time", ax=axes[i][1])
        axes[i][1].set_title(f"MFCC: {title}", fontsize=9)
    except Exception as e:
        print(f"  Skipped {label}: {e}")

plt.suptitle("Mel-Spectrogram and MFCC Comparison Across Species", y=1.01)
plt.tight_layout()
plt.savefig(os.path.join(RESULTS_DIR, "04_species_comparison.png"), dpi=150, bbox_inches="tight")
plt.close()
print("Saved: 04_species_comparison.png")

# ---------------------------------------------------------------------------
# Figure 5: Pitch (F0) and energy profile
# ---------------------------------------------------------------------------
fig, axes = plt.subplots(3, 1, figsize=(12, 8))
times = librosa.times_like(mfcc, sr=SR, hop_length=HOP_LENGTH)

# Reuse last loaded yy
f0 = librosa.yin(yy, fmin=32, fmax=2048, sr=SR, hop_length=HOP_LENGTH)
rms = librosa.feature.rms(y=yy, hop_length=HOP_LENGTH)[0]
zcr = librosa.feature.zero_crossing_rate(yy, hop_length=HOP_LENGTH)[0]

t_f0 = librosa.times_like(f0, sr=SR, hop_length=HOP_LENGTH)
t_rms = librosa.times_like(rms, sr=SR, hop_length=HOP_LENGTH)

axes[0].plot(t_f0, f0, color="green", linewidth=0.8)
axes[0].set_ylabel("Frequency (Hz)")
axes[0].set_title(f"Pitch (F0) — {title}")
axes[0].set_xlim(0, DURATION)

axes[1].plot(t_rms, rms, color="darkorange", linewidth=0.8)
axes[1].set_ylabel("RMS Energy")
axes[1].set_title("Volume (RMS Energy)")
axes[1].set_xlim(0, DURATION)

axes[2].plot(t_rms[:len(zcr)], zcr, color="purple", linewidth=0.8)
axes[2].set_ylabel("Rate")
axes[2].set_xlabel("Time (s)")
axes[2].set_title("Zero Crossing Rate (Speech Rate Proxy)")
axes[2].set_xlim(0, DURATION)

plt.tight_layout()
plt.savefig(os.path.join(RESULTS_DIR, "05_pitch_energy_zcr.png"), dpi=150)
plt.close()
print("Saved: 05_pitch_energy_zcr.png")

print("\nData exploration complete. All plots saved to:", RESULTS_DIR)
