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
from typing import ClassVar, Optional

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

    # Etap 2.3 — Enhanced 12-dim fingerprint (opsiyonel)
    enhanced_fingerprint: Optional["EnhancedPumpDumpFingerprint"] = None

    @classmethod
    def load_from_files(
        cls,
        motor_config_path: str | Path,
        esikler_path: str | Path,
        enhanced_path: Optional[str | Path] = None,
    ) -> "SPKCalibration":
        """Load calibration from both pipelines.

        enhanced_path: Optional. If provided and exists, loads
        EnhancedPumpDumpFingerprint from esikler_enhanced.json.
        """
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

        # Etap 2.3 — Enhanced fingerprint (optional)
        enhanced_fp: Optional["EnhancedPumpDumpFingerprint"] = None
        if enhanced_path is not None:
            enh_p = Path(enhanced_path)
            if enh_p.exists():
                with enh_p.open(encoding="utf-8") as f:
                    enh_data = json.load(f)
                dists = enh_data.get("distributions", {})
                meta = enh_data.get("meta", {})
                enhanced_fp = EnhancedPumpDumpFingerprint(
                    pump_duration=dists["pump_duration"],
                    volume_surge=dists["volume_surge"],
                    pump_rate=dists["pump_rate"],
                    dump_rate=dists["dump_rate"],
                    post_peak_volume=dists["post_peak_volume"],
                    rsi_max=dists["rsi_max"],
                    zscore_max=dists["zscore_max"],
                    pump_orani=dists["pump_orani"],
                    streak_max=dists["streak_max"],
                    gini_hacim=dists["gini_hacim"],
                    excess_pump_return=dists["excess_pump_return"],
                    excess_dump_severity=dists["excess_dump_severity"],
                    n_cases=int(meta.get("n_cases", 0)),
                    calibration_date=str(meta.get("calibration_date", "")),
                )

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
            enhanced_fingerprint=enhanced_fp,
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


# ════════════════════════════════════════════════════════════════════════════
# ETAP 2.3 — ENHANCED FINGERPRINT (12-dimensional)
# ════════════════════════════════════════════════════════════════════════════

class EnhancedPumpDumpFingerprint(BaseModel):
    """
    12-dimensional enhanced pump-dump fingerprint.

    Pipeline 2 (motor_config) dims: pump_duration, volume_surge,
        pump_rate, dump_rate, post_peak_volume
    Pipeline 1 (esikler) dims: rsi_max, zscore_max, pump_orani,
        streak_max, gini_hacim
    Relative dims (new): excess_pump_return, excess_dump_severity

    Each dim stores the full distribution dict (mean, std, p10, p25,
    p50, p75, p90, min, max). Same mean-centered matching logic as
    PumpDumpFingerprint.match().
    """
    model_config = {"frozen": True}

    # Relative & discriminative dimensions: higher weight
    DIMENSION_WEIGHTS: ClassVar[dict] = {
        # 1. En kritik ayrıştırıcı — göreli aşırılık (3.0)
        "excess_pump_return":    3.0,
        "excess_dump_severity":  3.0,
        # 2. Aşırı alım + mutlak sıçrama (1.8-2.0)
        "rsi_max":               2.0,
        "zscore_max":            1.8,
        "pump_orani":            1.8,
        # 3. Yapısal şekil metrikleri (1.0)
        "pump_duration":         1.0,
        "streak_max":            1.0,
        "pump_rate":             1.0,
        "dump_rate":             1.0,
        # 4. Hacim metrikleri — blue-chip gürültüsü düşük tutulur (0.5-0.6)
        "gini_hacim":            0.6,
        "volume_surge":          0.5,
        "post_peak_volume":      0.5,
    }
    # Toplam: 17.2

    # Direction-aware matching sınıfları (Etap 2.5c)
    DIRECTIONAL_HIGH: ClassVar[set] = {
        "excess_pump_return",
        "rsi_max",
        "zscore_max",
        "pump_orani",
        "pump_rate",
        "volume_surge",
        "streak_max",
    }
    DIRECTIONAL_LOW: ClassVar[set] = {
        "excess_dump_severity",
        "dump_rate",
    }
    SYMMETRIC_DIMS: ClassVar[set] = {
        "pump_duration",
        "post_peak_volume",
        "gini_hacim",
    }

    # Pipeline 2 dimensions
    pump_duration: dict
    volume_surge: dict
    pump_rate: dict
    dump_rate: dict
    post_peak_volume: dict

    # Pipeline 1 dimensions
    rsi_max: dict
    zscore_max: dict
    pump_orani: dict
    streak_max: dict
    gini_hacim: dict

    # Relative (new)
    excess_pump_return: dict
    excess_dump_severity: dict

    # Meta
    n_cases: int
    calibration_date: str

    def match(self, metrics: dict) -> float:
        """
        Direction-aware weighted similarity (Etap 2.5c).

        - DIRECTIONAL_HIGH dims: value >= p90 → 1.0, linear scaling down
        - DIRECTIONAL_LOW  dims: value <= p10 → 1.0, linear scaling down
        - SYMMETRIC        dims: mean-centered gaussian (existing logic)
        """
        matches_by_dim = {}
        for dim, weight in self.DIMENSION_WEIGHTS.items():
            value = float(metrics.get(dim, 0.0))
            stats = getattr(self, dim)
            p10  = float(stats["p10"])
            p90  = float(stats["p90"])
            mean = float(stats["mean"])
            std  = float(stats["std"])

            if dim in self.DIRECTIONAL_HIGH:
                m = self._match_high(value, p10, p90, mean, std)
            elif dim in self.DIRECTIONAL_LOW:
                m = self._match_low(value, p10, p90, mean, std)
            else:
                m = self._match_symmetric(value, p10, p90, mean, std)

            matches_by_dim[dim] = m

        total_weight = sum(self.DIMENSION_WEIGHTS.values())
        weighted_sum = sum(
            self.DIMENSION_WEIGHTS[dim] * m
            for dim, m in matches_by_dim.items()
        )
        return float(weighted_sum / total_weight) if total_weight > 0 else 0.0

    @staticmethod
    def _match_high(value, p10, p90, mean, std):
        """Higher = more pump-like. p90 ve üstü → 1.0."""
        if value >= p90:
            return 1.0
        elif value >= mean:
            return 0.7 + (value - mean) / max(p90 - mean, 1e-9) * 0.3
        elif value >= p10:
            return 0.4 + (value - p10) / max(mean - p10, 1e-9) * 0.3
        else:
            if std > 1e-9:
                z = (p10 - value) / std
                return 0.4 * math.exp(-0.5 * z * z)
            return 0.0

    @staticmethod
    def _match_low(value, p10, p90, mean, std):
        """Lower (more negative) = more dump-like. p10 ve altı → 1.0."""
        if value <= p10:
            return 1.0
        elif value <= mean:
            return 0.7 + (mean - value) / max(mean - p10, 1e-9) * 0.3
        elif value <= p90:
            return 0.4 + (p90 - value) / max(p90 - mean, 1e-9) * 0.3
        else:
            if std > 1e-9:
                z = (value - p90) / std
                return 0.4 * math.exp(-0.5 * z * z)
            return 0.0

    @staticmethod
    def _match_symmetric(value, p10, p90, mean, std):
        """Mean-centered (mevcut logic — değişmez)."""
        if p10 <= value <= p90:
            half_range = max(p90 - mean, mean - p10, 1e-9)
            m = 1.0 - (abs(value - mean) / half_range) * 0.5
            return max(0.5, min(1.0, m))
        else:
            if std > 1e-9:
                z = abs(value - mean) / std
                return math.exp(-0.5 * z * z)
            return 0.0


# ─── Metric helpers (calc_esikler_enhanced ile AYNEN tutarlı) ────────────────

def _compute_rsi(closes: pd.Series, period: int = 14) -> pd.Series:
    """RSI (14-day) — calc_esikler_enhanced ile aynı."""
    delta = closes.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _compute_gini(values: np.ndarray) -> float:
    """Gini coefficient — calc_esikler_enhanced ile aynı."""
    values = np.abs(values[~np.isnan(values)])
    if len(values) < 2 or values.sum() == 0:
        return 0.0
    sorted_v = np.sort(values)
    n = len(sorted_v)
    idx = np.arange(1, n + 1)
    return float(
        (2 * np.sum(idx * sorted_v)) / (n * np.sum(sorted_v)) - (n + 1) / n
    )


def _compute_streak_max(returns: np.ndarray) -> int:
    """Max consecutive positive days — calc_esikler_enhanced ile aynı."""
    streak = 0
    max_s = 0
    for r in returns:
        if r > 0:
            streak += 1
            max_s = max(max_s, streak)
        else:
            streak = 0
    return max_s


def extract_enhanced_metrics(
    ohlcv_window: pd.DataFrame,
    xu100_window: Optional[pd.DataFrame] = None,
) -> dict:
    """
    Extract 12-dimensional enhanced metrics from OHLCV + XU100 window.

    Same metric formulas as calc_esikler_enhanced.py (guaranteed parity).
    If xu100_window is None or empty, excess_* dims default to 0.

    Window must have: Close, Volume columns. Min 10 bars required.
    """
    # Pipeline 2 base (5 dim) — reuse existing function
    base = extract_pump_dump_metrics(ohlcv_window)

    if ohlcv_window is None or len(ohlcv_window) < 10:
        return {
            **base,
            "rsi_max": 50.0,
            "zscore_max": 0.0,
            "pump_orani": 1.0,
            "streak_max": 0.0,
            "gini_hacim": 0.0,
            "excess_pump_return": 0.0,
            "excess_dump_severity": 0.0,
        }

    close = ohlcv_window["Close"].values.astype(float)
    volume = ohlcv_window["Volume"].values.astype(float)
    n = len(close)

    peak_idx = int(np.argmax(close))
    daily_returns = np.diff(close) / np.maximum(close[:-1], 1e-9)

    # Pipeline 1: rsi_max
    rsi_vals = _compute_rsi(pd.Series(close), period=14).dropna().values
    rsi_max = float(np.max(rsi_vals)) if len(rsi_vals) > 0 else 50.0

    # Pipeline 1: zscore_max
    if len(daily_returns) > 1:
        mu = float(np.mean(daily_returns))
        sd = float(np.std(daily_returns, ddof=1))
        zscore_max = float(np.max(np.abs((daily_returns - mu) / sd))) if sd > 1e-9 else 0.0
    else:
        zscore_max = 0.0

    # Pipeline 1: pump_orani
    close_start = float(close[0])
    close_peak = float(close[peak_idx])
    pump_orani = close_peak / close_start if close_start > 1e-9 else 1.0

    # Pipeline 1: streak_max (pencere içi tam max)
    streak_max_full = float(_compute_streak_max(daily_returns))

    # Pipeline 1: gini_hacim
    gini_hacim = _compute_gini(volume)

    # Relative: excess_pump_return, excess_dump_severity
    excess_pump_return = 0.0
    excess_dump_severity = 0.0

    if xu100_window is not None and len(xu100_window) >= 10:
        try:
            common_idx = ohlcv_window.index.intersection(xu100_window.index)
            if len(common_idx) >= 10:
                xu100_aln = xu100_window.loc[common_idx]
                ohlcv_aln = ohlcv_window.loc[common_idx]

                xu100_close = xu100_aln["Close"].values.astype(float)
                close_aln = ohlcv_aln["Close"].values.astype(float)
                peak_aln = int(np.argmax(close_aln))

                if peak_aln > 0:
                    stock_pump = (close_aln[peak_aln] - close_aln[0]) / max(close_aln[0], 1e-9)
                    xu100_pump = (xu100_close[peak_aln] - xu100_close[0]) / max(xu100_close[0], 1e-9)
                    excess_pump_return = float(stock_pump - xu100_pump)

                if peak_aln < len(close_aln) - 1:
                    stock_dump = (close_aln[-1] - close_aln[peak_aln]) / max(close_aln[peak_aln], 1e-9)
                    xu100_dump = (xu100_close[-1] - xu100_close[peak_aln]) / max(xu100_close[peak_aln], 1e-9)
                    excess_dump_severity = float(stock_dump - xu100_dump)
        except Exception:
            pass  # Sessiz fallback — excess metrikleri 0 kalır

    return {
        **base,
        "rsi_max": rsi_max,
        "zscore_max": zscore_max,
        "pump_orani": pump_orani,
        "streak_max": streak_max_full,
        "gini_hacim": gini_hacim,
        "excess_pump_return": excess_pump_return,
        "excess_dump_severity": excess_dump_severity,
    }
