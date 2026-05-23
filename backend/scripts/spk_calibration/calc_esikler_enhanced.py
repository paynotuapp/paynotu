"""
Enhanced fingerprint distribution calculator (Etap 2.3a).

Reads vakalar.csv (SPK kararlari) and computes 12-dimensional
enhanced pump-dump fingerprint reference distribution.

Pipeline 1 (5 dims) + Pipeline 2 (5 dims) + Relative (2 dims) = 12 boyut.

Output: backend/spk_belgeleri/esikler_enhanced.json
  Each dimension: mean, std, p10, p25, p50, p75, p90

Usage:
    cd backend/scripts/spk_calibration
    python calc_esikler_enhanced.py
"""
import io
import sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import csv
import json
import warnings
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import borsapy as bp

warnings.filterwarnings("ignore")

# ─── Konfigürasyon ──────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
SPK_BELGELERI_DIR = SCRIPT_DIR.parent.parent / "spk_belgeleri"
VAKALAR_V3_CSV = SPK_BELGELERI_DIR / "vakalar_v3.csv"
OUTPUT_JSON = SPK_BELGELERI_DIR / "esikler_enhanced.json"

XU100_SYMBOL = "XU100"
MIN_BARS = 10                   # Minimum bar sayısı — altındaki vakalar atlanır


# ─── Metric helpers ─────────────────────────────────────────────────────────

def compute_rsi(closes: pd.Series, period: int = 14) -> pd.Series:
    delta = closes.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def compute_gini(values: np.ndarray) -> float:
    values = np.abs(values[~np.isnan(values)])
    if len(values) < 2 or values.sum() == 0:
        return 0.0
    sorted_v = np.sort(values)
    n = len(sorted_v)
    idx = np.arange(1, n + 1)
    return float((2 * np.sum(idx * sorted_v)) / (n * np.sum(sorted_v)) - (n + 1) / n)


def compute_streak_max(returns: np.ndarray) -> int:
    streak = max_streak = 0
    for r in returns:
        if r > 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    return max_streak


# ─── 12-boyutlu metrik çıkarıcı ─────────────────────────────────────────────

def extract_12_metrics(ohlcv: pd.DataFrame, xu100: pd.DataFrame) -> dict | None:
    """
    OHLCV + XU100 same-period window'tan 12 boyutlu metrik çıkar.
    Returns None if insufficient data.
    """
    # Index intersect (ortak tarihler)
    common_idx = ohlcv.index.intersection(xu100.index)
    if len(common_idx) < MIN_BARS:
        return None

    ohlcv = ohlcv.loc[common_idx].copy()
    xu100 = xu100.loc[common_idx].copy()

    close = ohlcv["Close"].values.astype(float)
    volume = ohlcv["Volume"].values.astype(float)
    xu100_close = xu100["Close"].values.astype(float)
    n = len(close)

    if np.any(np.isnan(close)) or np.any(np.isnan(xu100_close)):
        close = np.nan_to_num(close, nan=close[~np.isnan(close)].mean() if np.any(~np.isnan(close)) else 1.0)
        xu100_close = np.nan_to_num(xu100_close, nan=xu100_close[~np.isnan(xu100_close)].mean() if np.any(~np.isnan(xu100_close)) else 1.0)

    peak_idx = int(np.argmax(close))
    daily_returns = np.diff(close) / np.maximum(close[:-1], 1e-9)

    # ─── PIPELINE 2 — 5 boyut ────────────────────────────────────────────────
    pump_streak = max_streak_pre = 0
    for i in range(peak_idx):
        if daily_returns[i] > 0:
            pump_streak += 1
            max_streak_pre = max(max_streak_pre, pump_streak)
        else:
            pump_streak = 0
    pump_duration = float(max_streak_pre)

    pre_pump_len = max(1, n // 4)
    pre_pump_vol = float(np.mean(volume[:pre_pump_len])) if pre_pump_len > 0 else 1.0
    pump_volumes = volume[:peak_idx + 1] if peak_idx > 0 else volume[:1]
    pump_vol = float(np.mean(pump_volumes)) if len(pump_volumes) > 0 else pre_pump_vol
    volume_surge = pump_vol / pre_pump_vol if pre_pump_vol > 1e-9 else 1.0

    if peak_idx > 0:
        pump_ph = close[:peak_idx + 1]
        pr = np.diff(pump_ph) / np.maximum(pump_ph[:-1], 1e-9)
        pump_rate = float(np.mean(pr)) if len(pr) > 0 else 0.0
    else:
        pump_rate = 0.0

    if peak_idx < n - 1:
        dump_ph = close[peak_idx:]
        dr = np.diff(dump_ph) / np.maximum(dump_ph[:-1], 1e-9)
        dump_rate = float(np.mean(dr)) if len(dr) > 0 else 0.0
    else:
        dump_rate = 0.0

    dump_vol = float(np.mean(volume[peak_idx:])) if peak_idx < n - 1 and len(volume[peak_idx:]) > 0 else pump_vol
    post_peak_volume = dump_vol / pump_vol if pump_vol > 1e-9 else 1.0

    # ─── PIPELINE 1 — 5 boyut ────────────────────────────────────────────────
    close_s = pd.Series(close)
    rsi_vals = compute_rsi(close_s, period=14).dropna().values
    rsi_max = float(np.max(rsi_vals)) if len(rsi_vals) > 0 else 50.0

    if len(daily_returns) > 1:
        mu = float(np.mean(daily_returns))
        sd = float(np.std(daily_returns, ddof=1))
        zscore_max = float(np.max(np.abs((daily_returns - mu) / sd))) if sd > 1e-9 else 0.0
    else:
        zscore_max = 0.0

    close_start = float(close[0])
    close_peak = float(close[peak_idx])
    pump_orani = close_peak / close_start if close_start > 1e-9 else 1.0

    streak_max_full = float(compute_streak_max(daily_returns))

    gini_hacim = compute_gini(volume)

    # ─── RELATIVE — 2 boyut ──────────────────────────────────────────────────
    if peak_idx > 0:
        stock_pump_ret = (close[peak_idx] - close[0]) / max(close[0], 1e-9)
        xu100_pump_ret = (xu100_close[peak_idx] - xu100_close[0]) / max(xu100_close[0], 1e-9)
        excess_pump_return = float(stock_pump_ret - xu100_pump_ret)
    else:
        excess_pump_return = 0.0

    if peak_idx < n - 1:
        stock_dump = (close[-1] - close[peak_idx]) / max(close[peak_idx], 1e-9)
        xu100_dump = (xu100_close[-1] - xu100_close[peak_idx]) / max(xu100_close[peak_idx], 1e-9)
        excess_dump_severity = float(stock_dump - xu100_dump)
    else:
        excess_dump_severity = 0.0

    return {
        "pump_duration": pump_duration,
        "volume_surge": volume_surge,
        "pump_rate": pump_rate,
        "dump_rate": dump_rate,
        "post_peak_volume": post_peak_volume,
        "rsi_max": rsi_max,
        "zscore_max": zscore_max,
        "pump_orani": pump_orani,
        "streak_max": streak_max_full,
        "gini_hacim": gini_hacim,
        "excess_pump_return": excess_pump_return,
        "excess_dump_severity": excess_dump_severity,
    }


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("Etap 2.3a — Enhanced Reference Distribution")
    print("=" * 70)

    # 1. vakalar_v3.csv yükle — zaten genişletilmiş, tek ticker per satır
    print(f"\n→ Vakalar yükleniyor: {VAKALAR_V3_CSV}")
    cases = []
    with VAKALAR_V3_CSV.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ticker = row.get("ticker", "").strip()
            bas = row.get("baslangic", "").strip()
            bit = row.get("bitis", "").strip()
            src = row.get("source", "").strip()
            if not ticker or not bas or not bit:
                continue
            cases.append({"ticker": ticker, "baslangic": bas, "bitis": bit, "source": src})

    print(f"  Vaka-ticker toplam: {len(cases)}")

    # 2. XU100 indir — tüm tarih aralığını kapsayacak şekilde
    all_bas = [datetime.strptime(c["baslangic"], "%Y-%m-%d") for c in cases]
    all_bit = [datetime.strptime(c["bitis"], "%Y-%m-%d") for c in cases]
    xu100_start = (min(all_bas) - timedelta(days=30)).strftime("%Y-%m-%d")
    xu100_end = (max(all_bit) + timedelta(days=30)).strftime("%Y-%m-%d")

    print(f"\n→ XU100 ({XU100_SYMBOL}) indiriliyor: {xu100_start} → {xu100_end}")
    xu100_full = bp.Ticker(XU100_SYMBOL).history(start=xu100_start, end=xu100_end)
    if isinstance(xu100_full.columns, pd.MultiIndex):
        xu100_full.columns = xu100_full.columns.get_level_values(0)
    xu100_full.index = pd.to_datetime(xu100_full.index).normalize().tz_localize(None)
    print(f"  XU100 satir: {len(xu100_full)}")

    if len(xu100_full) < 100:
        print("  ✗ XU100 verisi yetersiz — durduruluyor")
        return

    # 3. Her vaka için indir + metrik hesapla
    print(f"\n→ {len(cases)} vaka-ticker islem gorüyor...\n")
    all_metrics: list[dict] = []
    failures: list[tuple[str, str, str]] = []

    for i, case in enumerate(cases, 1):
        ticker = case["ticker"]
        bas_str = case["baslangic"]
        bit_str = case["bitis"]
        src = case.get("source", "")
        bas_dt = datetime.strptime(bas_str, "%Y-%m-%d")
        bit_dt = datetime.strptime(bit_str, "%Y-%m-%d")

        # Pencere çok kısa mı?
        if (bit_dt - bas_dt).days < MIN_BARS:
            reason = f"pencere_kisa ({(bit_dt-bas_dt).days}g)"
            print(f"  [{i:>2}/{len(cases)}] {ticker:>8} SKIP {reason}")
            failures.append((ticker, bas_str, reason))
            continue

        bas_fetch = (bas_dt - timedelta(days=5)).strftime("%Y-%m-%d")
        bit_fetch = (bit_dt + timedelta(days=5)).strftime("%Y-%m-%d")

        print(f"  [{i:>3}/{len(cases)}] {ticker:>8} ({src:>11}) {bas_str} -> {bit_str}", end=" ")
        try:
            df = bp.Ticker(ticker).history(start=bas_fetch, end=bit_fetch)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            if df is None or df.empty or len(df) < MIN_BARS:
                print(f"NO_DATA ({len(df) if df is not None else 0})")
                failures.append((ticker, bas_str, "no_data"))
                continue

            # Index normalize
            df.index = pd.to_datetime(df.index).normalize().tz_localize(None)

            # XU100 aynı pencere
            xu100_win = xu100_full.loc[df.index.min():df.index.max()].copy()
            if len(xu100_win) < MIN_BARS:
                print(f"NO_XU100 ({len(xu100_win)})")
                failures.append((ticker, bas_str, "no_xu100"))
                continue

            metrics = extract_12_metrics(df, xu100_win)
            if metrics is None:
                print("INSUF_INTERSECT")
                failures.append((ticker, bas_str, "insufficient_intersection"))
                continue

            metrics["_ticker"] = ticker
            metrics["_baslangic"] = bas_str
            metrics["_bitis"] = bit_str
            metrics["_source"] = src
            all_metrics.append(metrics)
            print(f"OK ({len(df)} bar)")

        except Exception as exc:
            msg = str(exc)[:50]
            print(f"ERROR {type(exc).__name__}: {msg}")
            failures.append((ticker, bas_str, msg))

    # 4. Sonuç özeti
    print(f"\n→ Basarili: {len(all_metrics)}  Basarisiz: {len(failures)}")
    if failures:
        print("  Basarisizlar:")
        for t, d, r in failures:
            print(f"    {t} ({d}): {r}")

    if len(all_metrics) < 20:
        print("\n✗ Yetersiz başarılı vaka (<20) — durduruluyor")
        return

    # 5. Dağılım istatistikleri
    print(f"\n→ Dagılım hesaplanıyor...")

    DIMENSIONS = [
        "pump_duration", "volume_surge", "pump_rate", "dump_rate", "post_peak_volume",
        "rsi_max", "zscore_max", "pump_orani", "streak_max", "gini_hacim",
        "excess_pump_return", "excess_dump_severity",
    ]

    distribution: dict[str, dict] = {}
    for dim in DIMENSIONS:
        vals = np.array([m[dim] for m in all_metrics], dtype=float)
        vals = vals[~np.isnan(vals)]
        distribution[dim] = {
            "mean": float(np.mean(vals)),
            "std": float(np.std(vals, ddof=1)) if len(vals) > 1 else 0.0,
            "p10": float(np.percentile(vals, 10)),
            "p25": float(np.percentile(vals, 25)),
            "p50": float(np.percentile(vals, 50)),
            "p75": float(np.percentile(vals, 75)),
            "p90": float(np.percentile(vals, 90)),
            "min": float(np.min(vals)),
            "max": float(np.max(vals)),
            "n": int(len(vals)),
        }

    # 6. JSON çıktısı
    output = {
        "meta": {
            "version": "2.4-borsapy-v3",
            "calibration_date": datetime.now().strftime("%Y-%m-%d"),
            "n_cases": len(all_metrics),
            "n_total_vakalar": len(cases),
            "n_failures": len(failures),
            "data_source": "vakalar_v3.csv (3 sources) + borsapy + XU100",
            "source_distribution": dict(Counter(m["_source"] for m in all_metrics)),
            "dimensions": DIMENSIONS,
            "description": (
                "12-dimensional enhanced pump-dump fingerprint. "
                "Pipeline 2 (5 dims: pump_duration/volume_surge/pump_rate/"
                "dump_rate/post_peak_volume) + "
                "Pipeline 1 (5 dims: rsi_max/zscore_max/pump_orani/"
                "streak_max/gini_hacim) + "
                "Relative (2 dims: excess_pump_return/excess_dump_severity)."
            ),
        },
        "distributions": distribution,
        "tickers_included": sorted({m["_ticker"] for m in all_metrics}),
        "failures": [
            {"ticker": t, "baslangic": d, "reason": r} for t, d, r in failures
        ],
    }

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_JSON.open("w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n✓ Yazıldı: {OUTPUT_JSON}")

    print(f"\n=== Dağılım Özeti (12 boyut × {len(all_metrics)} vaka) ===")
    for dim in DIMENSIONS:
        d = distribution[dim]
        print(f"  {dim:>22}: "
              f"mean={d['mean']:>9.4f}  "
              f"p10={d['p10']:>9.4f}  "
              f"p50={d['p50']:>9.4f}  "
              f"p90={d['p90']:>9.4f}")

    print(f"\n=== Yeni RELATIVE metriklerin özeti ===")
    ep = distribution["excess_pump_return"]
    ed = distribution["excess_dump_severity"]
    print(f"  excess_pump_return:   p50={ep['p50']:.4f} ({ep['p50']*100:.1f}%) "
          f"p10={ep['p10']:.4f}  p90={ep['p90']:.4f}")
    print(f"  excess_dump_severity: p50={ed['p50']:.4f} ({ed['p50']*100:.1f}%) "
          f"p10={ed['p10']:.4f}  p90={ed['p90']:.4f}")
    if ep["p50"] > 0:
        print(f"  → SPK vakaları XU100'ü p50=%{ep['p50']*100:.0f} beat ediyor (beklenen: pozitif)")
    else:
        print(f"  ⚠ excess_pump_return p50 negatif — veri/tarih problemi olabilir")


if __name__ == "__main__":
    main()
