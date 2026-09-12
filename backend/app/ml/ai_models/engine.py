"""
MODULE 6: AI MODEL ENGINE
============================
Deep learning models for discovering latent market structures:

1. Temporal Autoencoder    — compress market sequences into latent space
2. Temporal Transformer    — self-attention over market history
3. LSTM Sequence Model     — learn temporal dependencies
4. Temporal CNN (TCN)      — dilated causal convolutions

All models are trained to reconstruct/predict the detrended series
and expose their latent representations for the Analog Engine.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── Import torch lazily to avoid startup overhead ─────────────────────────────

def _get_device():
    try:
        import torch
        if torch.cuda.is_available():
            return torch.device("cuda")
    except ImportError:
        pass
    return "cpu"


# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ModelConfig:
    model_type: str = "autoencoder"      # autoencoder | transformer | lstm | tcn
    input_dim: int = 1
    seq_len: int = 64
    latent_dim: int = 32
    hidden_dim: int = 128
    n_heads: int = 8
    n_layers: int = 4
    dropout: float = 0.1
    batch_size: int = 64
    learning_rate: float = 1e-3
    weight_decay: float = 1e-4
    n_epochs: int = 100
    patience: int = 15               # Early stopping patience
    device: str = "auto"
    artifacts_dir: str = "/app/artifacts/models"


@dataclass
class TrainingResult:
    model_type: str
    train_losses: List[float]
    val_losses: List[float]
    best_epoch: int
    best_val_loss: float
    training_time_seconds: float
    model_path: str
    config: ModelConfig


@dataclass
class InferenceResult:
    embeddings: np.ndarray              # (n_windows, latent_dim)
    reconstructions: np.ndarray         # (n_windows, seq_len)
    reconstruction_errors: np.ndarray   # (n_windows,)
    anomaly_scores: np.ndarray          # Normalized 0–1
    timestamps: List[str]


# ─────────────────────────────────────────────────────────────────────────────
# PYTORCH MODELS
# ─────────────────────────────────────────────────────────────────────────────

class TemporalAutoencoder:
    """1D Convolutional Autoencoder for market sequences."""

    def _build(self, cfg: ModelConfig):
        import torch.nn as nn

        class _Model(nn.Module):
            def __init__(self, cfg):
                super().__init__()
                # Encoder
                self.encoder = nn.Sequential(
                    nn.Conv1d(cfg.input_dim, 32, kernel_size=3, padding=1),
                    nn.GELU(),
                    nn.Conv1d(32, 64, kernel_size=3, padding=1, stride=2),
                    nn.GELU(),
                    nn.Conv1d(64, 128, kernel_size=3, padding=1, stride=2),
                    nn.GELU(),
                    nn.Flatten(),
                    nn.Linear(128 * (cfg.seq_len // 4), cfg.latent_dim),
                )
                # Decoder
                self.fc_decode = nn.Linear(cfg.latent_dim, 128 * (cfg.seq_len // 4))
                self.decoder = nn.Sequential(
                    nn.Unflatten(1, (128, cfg.seq_len // 4)),
                    nn.ConvTranspose1d(128, 64, kernel_size=3, padding=1, stride=2, output_padding=1),
                    nn.GELU(),
                    nn.ConvTranspose1d(64, 32, kernel_size=3, padding=1, stride=2, output_padding=1),
                    nn.GELU(),
                    nn.ConvTranspose1d(32, cfg.input_dim, kernel_size=3, padding=1),
                )

            def encode(self, x):
                return self.encoder(x)

            def decode(self, z):
                return self.decoder(self.fc_decode(z))

            def forward(self, x):
                z = self.encode(x)
                return self.decode(z), z

        return _Model(cfg)


class TemporalTransformerModel:
    """Transformer encoder for market sequence embedding."""

    def _build(self, cfg: ModelConfig):
        import torch.nn as nn
        import math

        class _Model(nn.Module):
            def __init__(self, cfg):
                super().__init__()
                d_model = cfg.hidden_dim
                self.input_proj = nn.Linear(cfg.input_dim, d_model)
                self.pos_encoding = nn.Parameter(
                    torch.zeros(1, cfg.seq_len, d_model)
                )
                encoder_layer = nn.TransformerEncoderLayer(
                    d_model=d_model,
                    nhead=cfg.n_heads,
                    dim_feedforward=d_model * 4,
                    dropout=cfg.dropout,
                    batch_first=True,
                    activation="gelu",
                )
                self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=cfg.n_layers)
                self.to_latent = nn.Linear(d_model, cfg.latent_dim)
                self.from_latent = nn.Linear(cfg.latent_dim, d_model)
                self.output_proj = nn.Linear(d_model, cfg.input_dim)
                self.norm = nn.LayerNorm(d_model)

            def encode(self, x):
                # x: (B, C, T) → (B, T, C)
                x = x.permute(0, 2, 1)
                h = self.input_proj(x) + self.pos_encoding[:, :x.size(1), :]
                h = self.transformer(h)
                h = self.norm(h)
                z = self.to_latent(h.mean(dim=1))
                return z

            def forward(self, x):
                x_in = x.permute(0, 2, 1)
                h = self.input_proj(x_in) + self.pos_encoding[:, :x_in.size(1), :]
                h = self.transformer(h)
                h = self.norm(h)
                z = self.to_latent(h.mean(dim=1))
                # Reconstruct
                h_dec = self.from_latent(z).unsqueeze(1).expand(-1, x_in.size(1), -1)
                out = self.output_proj(h_dec).permute(0, 2, 1)
                return out, z

        import torch
        return _Model(cfg)


class LSTMModel:
    """Bidirectional LSTM autoencoder."""

    def _build(self, cfg: ModelConfig):
        import torch.nn as nn

        class _Model(nn.Module):
            def __init__(self, cfg):
                super().__init__()
                self.encoder_lstm = nn.LSTM(
                    cfg.input_dim, cfg.hidden_dim, num_layers=cfg.n_layers,
                    batch_first=True, dropout=cfg.dropout, bidirectional=True,
                )
                self.to_latent = nn.Linear(cfg.hidden_dim * 2, cfg.latent_dim)
                self.from_latent = nn.Linear(cfg.latent_dim, cfg.hidden_dim)
                self.decoder_lstm = nn.LSTM(
                    cfg.hidden_dim, cfg.input_dim, num_layers=2,
                    batch_first=True,
                )

            def encode(self, x):
                x = x.permute(0, 2, 1)  # (B, T, C)
                out, (h, _) = self.encoder_lstm(x)
                # Concat last hidden from both directions
                h_cat = torch.cat([h[-2], h[-1]], dim=-1)
                z = self.to_latent(h_cat)
                return z

            def forward(self, x):
                x_in = x.permute(0, 2, 1)
                out, (h, _) = self.encoder_lstm(x_in)
                h_cat = torch.cat([h[-2], h[-1]], dim=-1)
                z = self.to_latent(h_cat)
                # Decode: repeat z across time steps
                dec_input = self.from_latent(z).unsqueeze(1).expand(-1, x_in.size(1), -1)
                dec_out, _ = self.decoder_lstm(dec_input)
                return dec_out.permute(0, 2, 1), z

        import torch
        return _Model(cfg)


class TCNModel:
    """Temporal Convolutional Network with dilated causal convolutions."""

    def _build(self, cfg: ModelConfig):
        import torch.nn as nn

        class _CausalConv(nn.Module):
            def __init__(self, in_ch, out_ch, kernel, dilation):
                super().__init__()
                self.padding = (kernel - 1) * dilation
                self.conv = nn.Conv1d(in_ch, out_ch, kernel, dilation=dilation, padding=self.padding)
                self.norm = nn.BatchNorm1d(out_ch)
                self.act = nn.GELU()

            def forward(self, x):
                out = self.conv(x)
                out = out[:, :, :-self.padding] if self.padding > 0 else out
                return self.act(self.norm(out))

        class _Model(nn.Module):
            def __init__(self, cfg):
                super().__init__()
                channels = [32, 64, 128, cfg.hidden_dim]
                layers = []
                in_ch = cfg.input_dim
                for i, ch in enumerate(channels):
                    layers.append(_CausalConv(in_ch, ch, kernel=3, dilation=2**i))
                    in_ch = ch
                self.encoder = nn.Sequential(*layers)
                self.to_latent = nn.Sequential(
                    nn.AdaptiveAvgPool1d(1),
                    nn.Flatten(),
                    nn.Linear(cfg.hidden_dim, cfg.latent_dim),
                )
                self.decoder = nn.Sequential(
                    nn.Linear(cfg.latent_dim, cfg.hidden_dim * cfg.seq_len),
                    nn.Unflatten(1, (cfg.hidden_dim, cfg.seq_len)),
                    nn.Conv1d(cfg.hidden_dim, 64, 3, padding=1),
                    nn.GELU(),
                    nn.Conv1d(64, cfg.input_dim, 3, padding=1),
                )

            def encode(self, x):
                h = self.encoder(x)
                return self.to_latent(h)

            def forward(self, x):
                h = self.encoder(x)
                z = self.to_latent(h)
                out = self.decoder(z)
                return out, z

        return _Model(cfg)


# ─────────────────────────────────────────────────────────────────────────────
# AI MODEL ENGINE
# ─────────────────────────────────────────────────────────────────────────────

class AIModelEngine:
    """
    Trains and runs inference on deep learning models to discover
    latent market structures.
    """

    MODEL_BUILDERS = {
        "autoencoder": TemporalAutoencoder,
        "transformer": TemporalTransformerModel,
        "lstm": LSTMModel,
        "tcn": TCNModel,
    }

    def __init__(self, config: Optional[ModelConfig] = None):
        self.config = config or ModelConfig()
        if self.config.device == "auto":
            device = _get_device()
            self.config.device = str(device)
        self._device = None

    @property
    def device(self):
        if self._device is None:
            import torch
            self._device = torch.device(self.config.device)
        return self._device

    def train(
        self,
        series: pd.Series,
        model_id: str = "default",
    ) -> TrainingResult:
        """
        Train the configured model on the market series.

        Args:
            series: Preprocessed (normalized) series.
            model_id: Identifier for saving model artifacts.

        Returns:
            TrainingResult with training curves and saved path.
        """
        import torch
        import torch.nn as nn
        from torch.utils.data import DataLoader, TensorDataset

        cfg = self.config
        values = series.dropna().values.astype(np.float32)

        # ── Build windowed dataset ────────────────────────────────────
        X = self._build_windows(values, cfg.seq_len, cfg.input_dim)
        if len(X) < 10:
            raise ValueError("Insufficient data for model training")

        # Train/val split
        split = int(len(X) * 0.85)
        X_train = torch.tensor(X[:split], dtype=torch.float32)
        X_val = torch.tensor(X[split:], dtype=torch.float32)

        train_loader = DataLoader(
            TensorDataset(X_train, X_train),
            batch_size=cfg.batch_size, shuffle=True, drop_last=True, num_workers=0,
        )
        val_loader = DataLoader(
            TensorDataset(X_val, X_val),
            batch_size=cfg.batch_size, shuffle=False, num_workers=0,
        )

        # ── Build model ───────────────────────────────────────────────
        builder_cls = self.MODEL_BUILDERS.get(cfg.model_type, TemporalAutoencoder)
        builder = builder_cls()
        model = builder._build(cfg).to(self.device)
        optimizer = torch.optim.AdamW(model.parameters(), lr=cfg.learning_rate, weight_decay=cfg.weight_decay)
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=cfg.n_epochs)
        criterion = nn.MSELoss()

        # ── Training loop ─────────────────────────────────────────────
        train_losses, val_losses = [], []
        best_val_loss = float("inf")
        best_epoch = 0
        patience_counter = 0
        start_time = time.time()

        model_path = os.path.join(cfg.artifacts_dir, f"{model_id}_{cfg.model_type}.pt")
        os.makedirs(cfg.artifacts_dir, exist_ok=True)

        for epoch in range(cfg.n_epochs):
            # Train
            model.train()
            epoch_loss = 0.0
            for xb, yb in train_loader:
                xb, yb = xb.to(self.device), yb.to(self.device)
                optimizer.zero_grad()
                out, z = model(xb)
                loss = criterion(out, yb)
                loss.backward()
                nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
                epoch_loss += loss.item()
            train_losses.append(epoch_loss / len(train_loader))

            # Validate
            model.eval()
            val_loss = 0.0
            with torch.no_grad():
                for xb, yb in val_loader:
                    xb, yb = xb.to(self.device), yb.to(self.device)
                    out, _ = model(xb)
                    val_loss += criterion(out, yb).item()
            val_losses.append(val_loss / len(val_loader))
            scheduler.step()

            if val_losses[-1] < best_val_loss:
                best_val_loss = val_losses[-1]
                best_epoch = epoch
                patience_counter = 0
                torch.save({"model_state": model.state_dict(), "config": cfg.__dict__}, model_path)
            else:
                patience_counter += 1
                if patience_counter >= cfg.patience:
                    logger.info(f"Early stopping at epoch {epoch}")
                    break

            if epoch % 10 == 0:
                logger.info(f"[{cfg.model_type}] Epoch {epoch}: train={train_losses[-1]:.6f}, val={val_losses[-1]:.6f}")

        training_time = time.time() - start_time

        return TrainingResult(
            model_type=cfg.model_type,
            train_losses=train_losses,
            val_losses=val_losses,
            best_epoch=best_epoch,
            best_val_loss=float(best_val_loss),
            training_time_seconds=training_time,
            model_path=model_path,
            config=cfg,
        )

    def infer(
        self,
        series: pd.Series,
        model_path: str,
    ) -> InferenceResult:
        """Run inference: produce embeddings + anomaly scores."""
        import torch

        cfg = self.config
        values = series.dropna().values.astype(np.float32)
        dates = series.dropna().index

        X = self._build_windows(values, cfg.seq_len, cfg.input_dim)
        if len(X) == 0:
            raise ValueError("No valid windows for inference")

        # Load model
        checkpoint = torch.load(model_path, map_location=self.device)
        builder_cls = self.MODEL_BUILDERS.get(cfg.model_type, TemporalAutoencoder)
        model = builder_cls()._build(cfg).to(self.device)
        model.load_state_dict(checkpoint["model_state"])
        model.eval()

        Xt = torch.tensor(X, dtype=torch.float32).to(self.device)
        embeddings_list, recon_list, error_list = [], [], []

        batch_size = 128
        with torch.no_grad():
            for i in range(0, len(Xt), batch_size):
                xb = Xt[i: i + batch_size]
                out, z = model(xb)
                embeddings_list.append(z.cpu().numpy())
                recon_list.append(out.cpu().numpy())
                err = ((xb - out) ** 2).mean(dim=(1, 2)).cpu().numpy()
                error_list.append(err)

        embeddings = np.concatenate(embeddings_list)
        reconstructions = np.concatenate(recon_list)
        errors = np.concatenate(error_list)
        errors_norm = (errors - errors.min()) / (errors.max() - errors.min() + 1e-10)

        # Map timestamps to windows
        n_windows = len(X)
        step = max(1, (len(values) - cfg.seq_len) // n_windows)
        ts_indices = [min(i * step + cfg.seq_len - 1, len(dates) - 1) for i in range(n_windows)]
        timestamps = [str(dates[i]) for i in ts_indices]

        return InferenceResult(
            embeddings=embeddings,
            reconstructions=reconstructions[:, 0, :],   # First channel
            reconstruction_errors=errors,
            anomaly_scores=errors_norm,
            timestamps=timestamps,
        )

    # ── Utilities ─────────────────────────────────────────────────────────────

    def _build_windows(
        self, values: np.ndarray, seq_len: int, n_features: int
    ) -> np.ndarray:
        """Build overlapping windows: (n_windows, n_features, seq_len)."""
        n = len(values)
        if n < seq_len:
            return np.array([])

        step = max(1, seq_len // 4)
        windows = []
        for i in range(0, n - seq_len, step):
            w = values[i: i + seq_len]
            if np.isnan(w).any():
                continue
            # Normalize window
            std = w.std()
            if std < 1e-8:
                continue
            w_norm = (w - w.mean()) / std
            windows.append(w_norm)

        if not windows:
            return np.array([])

        arr = np.array(windows)  # (n_windows, seq_len)
        # Add feature dim: (n_windows, 1, seq_len) or (n_windows, n_features, seq_len)
        return arr[:, np.newaxis, :]
