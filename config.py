import os

BASE_DIR = r"D:\NNU\语音识别技术\大作业"
DATA_DIR = os.path.join(BASE_DIR, "birdclef-2026")
FEATURES_DIR = os.path.join(BASE_DIR, "features")
MODELS_DIR = os.path.join(BASE_DIR, "models")
RESULTS_DIR = os.path.join(BASE_DIR, "results")

# Audio
SR = 22050
DURATION = 5.0
N_SAMPLES = int(SR * DURATION)  # 110250

# Feature extraction
N_MFCC = 40
N_MELS = 128
HOP_LENGTH = 512
N_FFT = 2048
N_CHROMA = 12

# Mel-spectrogram time frames for 5-second clip
SPEC_FRAMES = 1 + (N_SAMPLES - N_FFT) // HOP_LENGTH  # ~212

# Dataset subset — adjust to trade speed vs. coverage
TOP_N_CLASSES = 20
MAX_SAMPLES_ML = 50      # per class for traditional ML
MAX_SAMPLES_DL = 100     # per class for deep learning

RANDOM_STATE = 42
TEST_SIZE = 0.2
VAL_SIZE = 0.1

# Training
BATCH_SIZE = 32
EPOCHS_CNN = 30
EPOCHS_LSTM = 25
LR = 1e-3
PATIENCE = 7             # early stopping
