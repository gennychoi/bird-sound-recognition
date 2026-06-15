"""
Gradio UI — Bird Sound Recognition
Upload a .ogg/.wav/.mp3 file and get predictions from all trained models.
Run: python 06_ui.py
"""

import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"   # fix PyTorch + sklearn OpenMP conflict
import static_ffmpeg
static_ffmpeg.add_paths()                      # make ffmpeg/ffprobe available for Gradio
import json
import pickle
import tempfile
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use("Agg")
import librosa
import librosa.display
import torch
import torch.nn as nn
import gradio as gr

from config import (FEATURES_DIR, MODELS_DIR, SR, DURATION, N_MFCC,
                    HOP_LENGTH, N_FFT, N_MELS, SPEC_FRAMES)
from utils import load_audio, extract_features, get_mel_spectrogram, get_mfcc_sequence

# ---------------------------------------------------------------------------
# Load metadata
# ---------------------------------------------------------------------------
label_names = np.load(os.path.join(FEATURES_DIR, "label_names.npy"))
with open(os.path.join(FEATURES_DIR, "class_info.json")) as f:
    class_info = json.load(f)
n_classes = len(label_names)
DEVICE = torch.device("cpu")

# ---------------------------------------------------------------------------
# Load traditional ML models
# ---------------------------------------------------------------------------
def _load_pkl(name):
    path = os.path.join(MODELS_DIR, f"{name}.pkl")
    if os.path.exists(path):
        with open(path, "rb") as f:
            return pickle.load(f)
    return None

knn_model = _load_pkl("knn")
svm_model = _load_pkl("svm")
rf_model  = _load_pkl("random_forest")

# ---------------------------------------------------------------------------
# Load CNN
# ---------------------------------------------------------------------------
class BirdCNN(nn.Module):
    def __init__(self, n_classes):
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(1, 32, 3, padding=1), nn.BatchNorm2d(32), nn.ReLU(),
            nn.Conv2d(32, 32, 3, padding=1), nn.BatchNorm2d(32), nn.ReLU(),
            nn.MaxPool2d(2, 2), nn.Dropout2d(0.1),
            nn.Conv2d(32, 64, 3, padding=1), nn.BatchNorm2d(64), nn.ReLU(),
            nn.Conv2d(64, 64, 3, padding=1), nn.BatchNorm2d(64), nn.ReLU(),
            nn.MaxPool2d(2, 2), nn.Dropout2d(0.1),
            nn.Conv2d(64, 128, 3, padding=1), nn.BatchNorm2d(128), nn.ReLU(),
            nn.Conv2d(128, 128, 3, padding=1), nn.BatchNorm2d(128), nn.ReLU(),
            nn.MaxPool2d(2, 2), nn.Dropout2d(0.2),
            nn.Conv2d(128, 256, 3, padding=1), nn.BatchNorm2d(256), nn.ReLU(),
            nn.AdaptiveAvgPool2d((4, 4)),
        )
        self.classifier = nn.Sequential(
            nn.Flatten(),
            nn.Linear(256 * 4 * 4, 512), nn.ReLU(), nn.Dropout(0.5),
            nn.Linear(512, 256), nn.ReLU(), nn.Dropout(0.3),
            nn.Linear(256, n_classes),
        )

    def forward(self, x):
        return self.classifier(self.features(x))


class BirdLSTM(nn.Module):
    def __init__(self, input_size, hidden_size, num_layers, n_classes, dropout=0.3):
        super().__init__()
        self.lstm = nn.LSTM(input_size, hidden_size, num_layers=num_layers,
                             batch_first=True, bidirectional=True,
                             dropout=dropout if num_layers > 1 else 0.0)
        feat_dim = hidden_size * 2
        self.attention = nn.Linear(feat_dim, 1)
        self.classifier = nn.Sequential(
            nn.Linear(feat_dim, 256), nn.ReLU(), nn.Dropout(0.4),
            nn.Linear(256, 128), nn.ReLU(), nn.Dropout(0.3),
            nn.Linear(128, n_classes),
        )

    def forward(self, x):
        out, _ = self.lstm(x)
        attn_w = torch.softmax(self.attention(out), dim=1)
        context = (attn_w * out).sum(dim=1)
        return self.classifier(context)


def _load_torch(cls, path, **kwargs):
    if not os.path.exists(path):
        return None
    m = cls(**kwargs)
    m.load_state_dict(torch.load(path, map_location=DEVICE))
    m.eval()
    return m

cnn_model = _load_torch(BirdCNN, os.path.join(MODELS_DIR, "cnn_best.pt"),
                         n_classes=n_classes)
lstm_model = _load_torch(BirdLSTM, os.path.join(MODELS_DIR, "lstm_best.pt"),
                          input_size=N_MFCC, hidden_size=128, num_layers=2,
                          n_classes=n_classes, dropout=0.3)

print("Models loaded:", {
    "KNN": knn_model is not None,
    "SVM": svm_model is not None,
    "RF":  rf_model is not None,
    "CNN": cnn_model is not None,
    "LSTM": lstm_model is not None,
})


# ---------------------------------------------------------------------------
# Prediction helpers
# ---------------------------------------------------------------------------
def top5_str(probs):
    idx = np.argsort(probs)[::-1][:5]
    lines = []
    for rank, i in enumerate(idx, 1):
        sp = label_names[i]
        name = class_info.get(sp, sp)
        lines.append(f"{rank}. {name} ({sp}) — {probs[i]*100:.1f}%")
    return "\n".join(lines)


def predict_ml(model, feat_vec):
    if model is None:
        return "Model not trained yet."
    try:
        proba = model.predict_proba(feat_vec.reshape(1, -1))[0]
    except AttributeError:
        # SVC 未开启 probability=True，改用 decision_function softmax 近似
        scores = model.decision_function(feat_vec.reshape(1, -1))[0]
        scores = scores - scores.max()
        proba = np.exp(scores) / np.exp(scores).sum()
    return top5_str(proba)


def predict_torch(model, tensor_input):
    if model is None:
        return "Model not trained yet."
    with torch.no_grad():
        logits = model(tensor_input.unsqueeze(0))
        probs = torch.softmax(logits, dim=1).cpu().numpy()[0]
    return top5_str(probs)


# ---------------------------------------------------------------------------
# Visualisation helper
# ---------------------------------------------------------------------------
def make_vis_figure(y, sr):
    fig, axes = plt.subplots(3, 1, figsize=(10, 8))

    # Waveform
    librosa.display.waveshow(y, sr=sr, ax=axes[0], color="steelblue")
    axes[0].set_title("Waveform")
    axes[0].set_xlabel("Time (s)")

    # Mel-spectrogram
    mel = librosa.feature.melspectrogram(y=y, sr=sr, n_mels=N_MELS,
                                          n_fft=N_FFT, hop_length=HOP_LENGTH)
    log_mel = librosa.power_to_db(mel, ref=np.max)
    img = librosa.display.specshow(log_mel, sr=sr, hop_length=HOP_LENGTH,
                                    x_axis="time", y_axis="mel", ax=axes[1])
    fig.colorbar(img, ax=axes[1], format="%+2.0f dB")
    axes[1].set_title("Log Mel-Spectrogram")

    # MFCC：per-coeff z-score + 发散型色图，与模型输入预处理一致
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=N_MFCC,
                                  n_fft=N_FFT, hop_length=HOP_LENGTH)
    mfcc_norm = (mfcc - mfcc.mean(axis=1, keepdims=True)) / \
                (mfcc.std(axis=1, keepdims=True) + 1e-8)
    img2 = librosa.display.specshow(mfcc_norm, sr=sr, hop_length=HOP_LENGTH,
                                     x_axis="time", ax=axes[2],
                                     cmap="RdBu_r", vmin=-3, vmax=3)
    fig.colorbar(img2, ax=axes[2], label="z-score")
    axes[2].set_title("MFCC (per-coeff z-score)")
    axes[2].set_ylabel("Coefficient")

    plt.tight_layout()
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    plt.savefig(tmp.name, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return tmp.name


# ---------------------------------------------------------------------------
# Main inference function
# ---------------------------------------------------------------------------
def recognize_bird(audio_path):
    if audio_path is None:
        return (None, "Please upload an audio file.",
                "—", "—", "—", "—", "—")

    try:
        y = load_audio(audio_path)
    except Exception as e:
        return (None, f"Error loading audio: {e}", "—", "—", "—", "—", "—")

    # Feature extraction
    feat_ml   = extract_features(y)
    mel_spec  = get_mel_spectrogram(y)               # (1, 128, T)
    mfcc_seq  = get_mfcc_sequence(y)                 # (T, N_MFCC)

    mel_t  = torch.tensor(mel_spec, dtype=torch.float32)
    mfcc_t = torch.tensor(mfcc_seq, dtype=torch.float32)

    # Feature summary text
    f0 = librosa.yin(y, fmin=32, fmax=2048, sr=SR, hop_length=HOP_LENGTH)
    rms = librosa.feature.rms(y=y, hop_length=HOP_LENGTH)[0]
    zcr = librosa.feature.zero_crossing_rate(y, hop_length=HOP_LENGTH)[0]
    f0_voiced = f0[f0 > 0]
    pitch_str = f"{f0_voiced.mean():.1f} Hz" if len(f0_voiced) > 0 else "N/A"
    feat_summary = (
        f"Duration: {len(y)/SR:.1f}s\n"
        f"Avg Pitch (F0): {pitch_str}\n"
        f"Avg Volume (RMS): {rms.mean():.4f}\n"
        f"Avg ZCR: {zcr.mean():.4f}\n"
        f"MFCC[0] mean: {feat_ml[0]:.2f}\n"
        f"MFCC[1] mean: {feat_ml[1]:.2f}"
    )

    vis_path = make_vis_figure(y, SR)

    r_knn  = predict_ml(knn_model, feat_ml)
    r_svm  = predict_ml(svm_model, feat_ml)
    r_rf   = predict_ml(rf_model, feat_ml)
    r_cnn  = predict_torch(cnn_model, mel_t)
    r_lstm = predict_torch(lstm_model, mfcc_t)

    return vis_path, feat_summary, r_knn, r_svm, r_rf, r_cnn, r_lstm


# ---------------------------------------------------------------------------
# Gradio interface
# ---------------------------------------------------------------------------
with gr.Blocks(title="Bird Sound Recognition", theme=gr.themes.Soft()) as demo:
    gr.Markdown("# 🐦 基于声音的鸟类识别系统\n"
                "Upload a bird sound recording (.ogg / .wav / .mp3) to identify the species.\n\n"
                f"Recognises **{n_classes} species** from BirdCLEF 2026.")

    with gr.Row():
        audio_in = gr.Audio(type="filepath", label="Upload Bird Sound")
        btn = gr.Button("Identify Bird", variant="primary")

    vis_out = gr.Image(label="Audio Visualisation (Waveform / Mel-Spec / MFCC)")
    feat_out = gr.Textbox(label="Extracted Audio Features", lines=6)

    gr.Markdown("### Top-5 Predictions per Model")
    with gr.Row():
        knn_out  = gr.Textbox(label="KNN",  lines=6)
        svm_out  = gr.Textbox(label="SVM",  lines=6)
        rf_out   = gr.Textbox(label="Random Forest", lines=6)
    with gr.Row():
        cnn_out  = gr.Textbox(label="CNN (Mel-Spectrogram)", lines=6)
        lstm_out = gr.Textbox(label="BiLSTM (MFCC Sequence)", lines=6)

    btn.click(fn=recognize_bird, inputs=[audio_in],
              outputs=[vis_out, feat_out, knn_out, svm_out, rf_out, cnn_out, lstm_out])

    gr.Markdown(
        "**Supported species** (top 20 Aves from BirdCLEF 2026):\n" +
        " · ".join(f"{v} ({k})" for k, v in list(class_info.items())[:20])
    )

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0",
                share=False, inbrowser=False, show_api=False, show_error=True)
