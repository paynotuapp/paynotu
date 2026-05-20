"""
SPK Calibration loader and matcher.

Loads pump-dump fingerprint from motor_config.json (Pipeline 2 — production)
and reference ticker list from esikler_final.json (Pipeline 1 — validation).

Provides:
- SPKCalibration.load_from_files(motor_path, esikler_path)
- PumpDumpFingerprint.match(metrics) -> similarity 0..1
- extract_pump_dump_metrics(ohlcv_window) -> dict
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field


class PumpDumpFingerprint(BaseModel):
    """5-dimensional pump-dump fingerprint with p10/p90 ranges."""
    model_config = {"frozen": True}

    pump_duration_mean: float
    pump_duration_std: float
    pump_duration_p10: float
    pump_duration_p90: float

    volume_surge_mean: float
    volume_surge_std: float
    volume_surge_p10: float
    volume_surge_p90: float

    pump_rate_mean: float
    pump_rate_std: float
    pump_rate_p10: float
    pump_rate_p90: float

    dump_rate_mean: float
    dump_rate_std: float
    dump_rate_p10: float
    dump_rate_p90: float

    post_peak_volume_mean: float
    post_peak_volume_std: float
    post_peak_volume_p10: float
    post_peak_volume_p90: float

    n_cases: int

    def match(self, metrics: dict) -> float:
        """
        Compute pump-dump similarity (0..1) with mean-centered match.

        For each dimension:
        - Value at mean: m = 1.0 (perfect match)
        - Value at p10/p90 boundary: m = 0.5 (weak signal)
        - Value outside [p10, p90]: gaussian decay with std (unchanged)

        Strict discrimination: blue-chip-like patterns (volume_surge≈1,
        pump_rate≈0.01) only score in [0.50, 0.75] range, while true
        pump-dump patterns (near-mean on multiple dimensions) score >0.85.
        """
        dimensions = [
            ('pump_duration', metrics.get('pump_duration', 0)),
            ('volume_surge', metrics.get('volume_surge', 0)),
            ('pump_rate', metrics.get('pump_rate', 0)),
            ('dump_rate', metrics.get('dump_rate', 0)),
            ('post_peak_volume', metrics.get('post_peak_volume', 0)),
        ]

        matches = []
        for name, value in dimensions:
            p10 = getattr(self, f'{name}_p10')
            p90 = getattr(self, f'{name}_p90')
            mean = getattr(self, f'{name}_mean')
            std = getattr(self, f'{name}_std')

            if p10 <= value <= p90:
                # Range içi: mean'e yakınlık ile [0.5, 1.0]
                # Asimetrik aralık olabilir (mean p10/p90'a eşit uzaklıkta değil)
                half_range = max(p90 - mean, mean - p10, 1e-9)
                distance = abs(value - mean)
                # Lineer interpolasyon: mean=1.0, kenar=0.5
                m = 1.0 - (distance / half_range) * 0.5
                m = max(0.5, min(1.0, m))
            else:
                # Range dışı: gaussian decay (eskisi gibi)
                if std > 1e-9:
                    z = abs(value - mean) / std
                    m = math.exp(-0.5 * z * z)
                else:
                    m = 0.0

            matches.append(m)

        return float(np.mean(matches))


class SPKCalibration(BaseModel):
    """SPK calibration data: thresholds + fingerprint + reference tickers."""
    model_config = {"frozen": True, "arbitrary_types_allowed": True}

    # Pipeline 2 — motor_config.json (production)
    hacim_spike_threshold: float
    mahalanobis_threshold: float
    gini_threshold: float
    daily_price_threshold: float
    calibrated_from_n_decisions: int
    calibration_date: str
    pump_dump_fingerprint: PumpDumpFingerprint

    # Pipeline 1 — esikler_final.json (validation)
    pump_gt2_tickers: list[str] = Field(default_factory=list)
    pump_gt2_count: int = 0

    @classmethod
    def load_from_files(
        cls,
        motor_config_path: str | Path,
        esikler_path: str | Path,
    ) -> "SPKCalibration":
        """Load calibration from both pipelines."""
        motor_path = Path(motor_config_path)
        esikler_p = Path(esikler_path)

        with motor_path.open(encoding="utf-8") as f:
            motor_data = json.load(f)

        fingerprint = PumpDumpFingerprint(**motor_data["pump_dump_fingerprint"])

        # Pipeline 1 (optional)
        pump_gt2_tickers = []
        pump_gt2_count = 0
        if esikler_p.exists():
            with esikler_p.open(encoding="utf-8") as f:
                esikler_data = json.load(f)
            pump_gt2_tickers = list(esikler_data.get("pump_gt2_tickerlar", []))
            pump_gt2_count = int(esikler_data.get("meta", {}).get("pump_gt2_sayisi", 0))

        return cls(
            hacim_spike_threshold=motor_data["hacim_spike_esigi"],
            mahalanobis_threshold=motor_data["mahalanobis_esigi"],
            gini_threshold=motor_data["gini_esigi"],
            daily_price_threshold=motor_data["gunluk_fiyat_esigi"],
            calibrated_from_n_decisions=motor_data["calibrated_from_n_decisions"],
            calibration_date=motor_data["calibration_date"],
            pump_dump_fingerprint=fingerprint,
            pump_gt2_tickers=pump_gt2_tickers,
            pump_gt2_count=pump_gt2_count,
        )


def extract_pump_dump_metrics(ohlcv_window: pd.DataFrame) -> dict:
    """
    Extract 5-dimensional pump-dump metrics from an OHLCV window.

    Returns dict with keys:
    - pump_duration: max ardisik yukselis gun sayisi (streak)
    - volume_surge: pump doneminde ort hacim / pre-pump donem
    - pump_rate: pump doneminde gunluk ortalama getiri
    - dump_rate: tepe sonrasi gunluk ortalama getiri
    - post_peak_volume: tepe sonrasi hacim / pump donemi hacim

    Window must have: Close, Volume columns. Min 10 bars required.
    """
    if ohlcv_window is None or len(ohlcv_window) < 10:
        return {
            'pump_duration': 0.0,
            'volume_surge': 1.0,
            'pump_rate': 0.0,
            'dump_rate': 0.0,
            'post_peak_volume': 1.0,
        }

    close = ohlcv_window['Close'].values
    volume = ohlcv_window['Volume'].values
    n = len(close)

    # Find peak (highest close in window)
    peak_idx = int(np.argmax(close))

    # Pump duration: max ardisik yukari gun streak peak'e kadar
    daily_returns = np.diff(close) / close[:-1]
    pump_streak = 0
    max_streak = 0
    for i in range(peak_idx):
        if daily_returns[i] > 0:
            pump_streak += 1
            max_streak = max(max_streak, pump_streak)
        else:
            pump_streak = 0
    pump_duration = float(max_streak)

    # Pump phase: 0 -> peak_idx
    pump_phase = close[:peak_idx + 1] if peak_idx > 0 else close[:1]
    pump_volumes = volume[:peak_idx + 1] if peak_idx > 0 else volume[:1]

    # Dump phase: peak_idx -> end
    dump_phase = close[peak_idx:] if peak_idx < n - 1 else close[-1:]
    dump_volumes = volume[peak_idx:] if peak_idx < n - 1 else volume[-1:]

    # Volume surge: pump phase ort / pre-pump (ilk 1/4)
    pre_pump_len = max(1, n // 4)
    pre_pump_vol = float(np.mean(volume[:pre_pump_len]))
    pump_vol = float(np.mean(pump_volumes)) if len(pump_volumes) > 0 else pre_pump_vol
    volume_surge = pump_vol / pre_pump_vol if pre_pump_vol > 1e-9 else 1.0

    # Pump rate: pump phase gunluk ortalama getiri
    if peak_idx > 0:
        pump_returns = np.diff(pump_phase) / pump_phase[:-1]
        pump_rate = float(np.mean(pump_returns)) if len(pump_returns) > 0 else 0.0
    else:
        pump_rate = 0.0

    # Dump rate: dump phase gunluk ortalama getiri
    if peak_idx < n - 1:
        dump_returns = np.diff(dump_phase) / dump_phase[:-1]
        dump_rate = float(np.mean(dump_returns)) if len(dump_returns) > 0 else 0.0
    else:
        dump_rate = 0.0

    # Post-peak volume: dump phase ort / pump phase ort
    dump_vol_mean = float(np.mean(dump_volumes)) if len(dump_volumes) > 0 else pump_vol
    post_peak_volume = dump_vol_mean / pump_vol if pump_vol > 1e-9 else 1.0

    return {
        'pump_duration': float(pump_duration),
        'volume_surge': float(volume_surge),
        'pump_rate': float(pump_rate),
        'dump_rate': float(dump_rate),
        'post_peak_volume': float(post_peak_volume),
    }


def tier_from_similarity(similarity: float) -> int:
    """
    Map similarity score to Tier:
    - Tier 1: >= 0.70 (guclu match)
    - Tier 2: >= 0.50 (orta match)
    - Tier 3: >= 0.30 (zayif match)
    - Tier 0: < 0.30 (etiketsiz)
    """
    if similarity >= 0.70:
        return 1
    elif similarity >= 0.50:
        return 2
    elif similarity >= 0.30:
        return 3
    else:
        return 0
