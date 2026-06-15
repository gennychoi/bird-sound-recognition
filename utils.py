"""
Audio loading and feature extraction utilities.
All feature extraction functions operate on a fixed-length (5-second) mono waveform.
"""

import numpy as np
import librosa
import warnings
warnings.filterwarnings("ignore")

from config import SR, DURATION, N_SAMPLES, N_MFCC, N_MELS, HOP_LENGTH, N_FFT, N_CHROMA, SPEC_FRAMES


# ---------------------------------------------------------------------------
# Audio I/O
# ---------------------------------------------------------------------------

def load_audio(filepath: str, sr: int = SR, duration: float = DURATION) -> np.ndarray:
    """Load audio, convert to mono, pad/trim to fixed length."""
    try:
        y, _ = librosa.load(filepath, sr=sr, mono=True, duration=duration)
    except Exception as e:
        raise RuntimeError(f"Cannot load {filepath}: {e}")

    target = int(sr * duration)
    if len(y) < target:
        y = np.pad(y, (0, target - len(y)))
    else:
        y = y[:target]
    return y


# ---------------------------------------------------------------------------
# Feature extraction for traditional ML  (statistical summary → 1-D vector)
# ---------------------------------------------------------------------------

def extract_features(y: np.ndarray, sr: int = SR) -> np.ndarray:
    """
    Extract a 1-D feature vector for traditional ML.
    Features (all summarised as mean + std per coefficient):
      MFCC (40×2), Δ-MFCC (40×2), ΔΔ-MFCC (40×2),
      Chroma (12×2), Spectral centroid (2), Bandwidth (2),
      Rolloff (2), Flatness (2), ZCR (2), RMS (2), Pitch (2)
    Total: 278 dimensions.
    """
    feats = []

    # MFCCs and deltas
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=N_MFCC,
                                  n_fft=N_FFT, hop_length=HOP_LENGTH)
    delta1 = librosa.feature.delta(mfcc)
    delta2 = librosa.feature.delta(mfcc, order=2)
    for mat in (mfcc, delta1, delta2):
        feats.extend(mat.mean(axis=1))
        feats.extend(mat.std(axis=1))

    # Chroma
    chroma = librosa.feature.chroma_stft(y=y, sr=sr, n_chroma=N_CHROMA,
                                          n_fft=N_FFT, hop_length=HOP_LENGTH)
    feats.extend(chroma.mean(axis=1))
    feats.extend(chroma.std(axis=1))

    # Spectral shape features (each is 1×T → mean+std)
    for fn in (librosa.feature.spectral_centroid,
               librosa.feature.spectral_bandwidth,
               librosa.feature.spectral_rolloff):
        val = fn(y=y, sr=sr, n_fft=N_FFT, hop_length=HOP_LENGTH)
        feats.append(float(val.mean()))
        feats.append(float(val.std()))
    flat = librosa.feature.spectral_flatness(y=y, n_fft=N_FFT, hop_length=HOP_LENGTH)
    feats.append(float(flat.mean()))
    feats.append(float(flat.std()))

    # ZCR
    zcr = librosa.feature.zero_crossing_rate(y, hop_length=HOP_LENGTH)
    feats.append(float(zcr.mean()))
    feats.append(float(zcr.std()))

    # RMS energy (volume)
    rms = librosa.feature.rms(y=y, hop_length=HOP_LENGTH)
    feats.append(float(rms.mean()))
    feats.append(float(rms.std()))

    # Pitch (fundamental frequency) via YIN
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        f0 = librosa.yin(y, fmin=32, fmax=2048, sr=sr, hop_length=HOP_LENGTH)
    f0_voiced = f0[f0 > 0]
    feats.append(float(f0_voiced.mean()) if len(f0_voiced) > 0 else 0.0)
    feats.append(float(f0_voiced.std()) if len(f0_voiced) > 0 else 0.0)

    return np.array(feats, dtype=np.float32)


# ---------------------------------------------------------------------------
# Mel-spectrogram for CNN  → shape (1, N_MELS, SPEC_FRAMES)
# ---------------------------------------------------------------------------

def get_mel_spectrogram(y: np.ndarray, sr: int = SR) -> np.ndarray:
    """Return log-mel spectrogram, shape (1, N_MELS, SPEC_FRAMES)."""
    mel = librosa.feature.melspectrogram(y=y, sr=sr, n_mels=N_MELS,
                                          n_fft=N_FFT, hop_length=HOP_LENGTH)
    log_mel = librosa.power_to_db(mel, ref=np.max)

    # Ensure fixed width
    if log_mel.shape[1] < SPEC_FRAMES:
        log_mel = np.pad(log_mel, ((0, 0), (0, SPEC_FRAMES - log_mel.shape[1])),
                         mode="constant", constant_values=log_mel.min())
    else:
        log_mel = log_mel[:, :SPEC_FRAMES]

    # Normalise to [0, 1]
    lo, hi = log_mel.min(), log_mel.max()
    if hi > lo:
        log_mel = (log_mel - lo) / (hi - lo)
    return log_mel[np.newaxis, :, :].astype(np.float32)  # (1, 128, SPEC_FRAMES)


# ---------------------------------------------------------------------------
# MFCC sequence for LSTM  → shape (SPEC_FRAMES, N_MFCC)
# ---------------------------------------------------------------------------

def get_mfcc_sequence(y: np.ndarray, sr: int = SR) -> np.ndarray:
    """Return MFCC time-series, shape (SPEC_FRAMES, N_MFCC)."""
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=N_MFCC,
                                  n_fft=N_FFT, hop_length=HOP_LENGTH)
    if mfcc.shape[1] < SPEC_FRAMES:
        mfcc = np.pad(mfcc, ((0, 0), (0, SPEC_FRAMES - mfcc.shape[1])))
    else:
        mfcc = mfcc[:, :SPEC_FRAMES]

    # Normalise each coefficient independently
    mean = mfcc.mean(axis=1, keepdims=True)
    std = mfcc.std(axis=1, keepdims=True) + 1e-8
    mfcc = (mfcc - mean) / std

    return mfcc.T.astype(np.float32)  # (SPEC_FRAMES, N_MFCC)
