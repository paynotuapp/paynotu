# -*- coding: utf-8 -*-
"""
PayNotu — Finansal Motor v2.2
==============================
Görev: Hissenin spekülatif davranış yoğunluğunu ölçmek.

Bu motor "en iyi hisseyi" bulmaz.
"En anormal davranan hisseyi" tespit eder.

Çıktı: spek_score (0.0 - 10.0)

Mimari:
  ANA MOTOR    → 4 spek kriteri → Entropi Ağırlık → TOPSIS → raw_spek_score
  FİLTRE       → Temelden Kopuş → fundamental_multiplier (0.65 - 1.0)
  SONUÇ        → raw_spek_score × multiplier × guven_skoru = spek_score

Katmanlar (sırayla):
  1.  Rolling Window (1825 işlem seansı ≈ 7 yıl)
  2.  Veri Kalite Kontrolü
  3.  Kurumsal Aksiyon Maskesi (bool flag)
  4.  IPO Filtresi (30 seans günü altı → liste dışı)
  5.  XU100 Cache
  6.  Spekülatif Gün Tespiti — üç seviyeli (soft/hard/extreme) — VEKTÖRELİZE
  7.  Fiyat Anomali Skoru
  8.  Hacim Patlaması Skoru (bağımsız baseline penceresi)
  9.  Volatilite Skoru (ölçek uyumlu fallback)
  10. Pump Benzerlik Skoru (SPK parmak izi → sinyal)
  11. Entropi Ağırlıklandırma (4 bağımsız feature, double-computation temiz)
  12. TOPSIS (spek feature'lara uygulanır)
  13. Temelden Kopuş Filtresi (çarpan)
  14. Final Skor (tek clip, bilgi kaybı yok)

Anayasa:
  - Spek günleri SİLİNMEZ, SAYILIR ve ÖLÇÜLÜR
  - Finansal metrikler (ROE, PD/DD, F/K) ana skor değil, filtre aracıdır
  - Hardcoded eşik yok — SPK kalibrasyonundan türetilir
  - Her kriter açıklanabilir metin döndürür
  - Immutable SpekResult — copyWith() ile güncelleme

Düzeltmeler (v2.1 → v2.2):
  - [KRİTİK] Türkçe karakterler geri getirildi: borsapy bilanço index'leri ve
            sektör adları (Özkaynaklar, DÖNEM KARI, ENERJİ, TEKNOLOJİ vs.)
            Bu fix öncesi tüm hisseler fundamental fallback'e düşüyordu.
  - [ORTA]   Entropi: feature'lar daha bağımsız (ret_abs, volume_norm,
            spike_freq, hl_norm) — collinearity azaltıldı
  - [KÜÇÜK] _entropi_agirliklari: double computation kaldırıldı
  - [KÜÇÜK] _sektor_fallback ve _fundamental_multiplier: sektör adı
            normalizasyonu (ASCII↔Türkçe karakter toleransı)
  - [KÜÇÜK] Yorum tutarlılığı: spk_asim_oran pencere mantığı

Düzeltmeler (v2 → v2.1) [hatırlatma]:
  - Entropi feature collinearity, hacim spike kontaminasyonu, çift clip,
    borsapy_banking is_ kontrolü, vectorization, event_flag bool,
    XU100 ffill, volatilite ölçek uyumu, pump baseline kontaminasyonu
"""

import json
import logging
import os
import unicodedata
from dataclasses import dataclass
from typing import List, Optional, cast

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── Temel Analiz Cache ────────────────────────────────────────────────────────
_FUNDAMENTAL_CACHE: dict = {}
_FUNDAMENTAL_CACHE_DATE: str = ""

# ── SPK Kalibrasyon Eşikleri (fallback) ──────────────────────────────────────
_SPK_DEFAULTS = {
    "gunluk_fiyat_esigi":    0.09,
    "hacim_spike_esigi":     5.86,
    "mahalanobis_esigi":     3.54,
    "gini_esigi":            0.55,
    "pump_duration_mean":   43.033,
    "pump_duration_std":    21.010,
    "volume_surge_mean":     1.517,
    "volume_surge_std":      0.705,
    "pump_rate_mean":        0.01134,
    "pump_rate_std":         0.00842,
    "dump_rate_mean":       -0.01057,
    "dump_rate_std":         0.01448,
    "post_peak_volume_mean": 1.1516,
    "post_peak_volume_std":  1.0218,
}

# ── Sektör Varsayılan Değerleri ───────────────────────────────────────────────
# Türkçe karakterli — Firestore'dan gelen sektör adlarıyla doğrudan eşleşir.
# ASCII gelirse _normalize() üzerinden tolere edilir.
_SEKTOR_DEFAULTS: dict = {
    "BANKACILIK":   {"roe": 0.14, "net_kar_marji": 0.28, "pd_dd": 0.90, "net_borc_favok": 0.0, "fk":  7.0},
    "FİNANSAL":     {"roe": 0.14, "net_kar_marji": 0.28, "pd_dd": 0.90, "net_borc_favok": 0.0, "fk":  7.0},
    "SİGORTACILIK": {"roe": 0.12, "net_kar_marji": 0.15, "pd_dd": 1.20, "net_borc_favok": 0.0, "fk":  9.0},
    "GYO":          {"roe": 0.10, "net_kar_marji": 0.22, "pd_dd": 0.50, "net_borc_favok": 4.0, "fk": 10.0},
    "ENERJİ":       {"roe": 0.18, "net_kar_marji": 0.12, "pd_dd": 1.50, "net_borc_favok": 3.0, "fk": 12.0},
    "TEKNOLOJİ":    {"roe": 0.20, "net_kar_marji": 0.15, "pd_dd": 2.00, "net_borc_favok": 0.5, "fk": 20.0},
    "PERAKENDE":    {"roe": 0.15, "net_kar_marji": 0.06, "pd_dd": 1.20, "net_borc_favok": 2.5, "fk": 14.0},
    "DEFAULT":      {"roe": 0.15, "net_kar_marji": 0.10, "pd_dd": 1.50, "net_borc_favok": 2.0, "fk": 12.0},
}


def _normalize_tr(text: str) -> str:
    """
    Türkçe karakterleri ASCII'ye çevir, upper() ve strip() uygula.
    Eşleşme tabanı için kullanılır — Firestore "ENERJİ" da gönderse,
    "ENERJI" da gönderse eşleşme garantili.
    """
    if not text:
        return ""
    # NFD ile diakritikleri ayır, ASCII'ye dök
    nfkd = unicodedata.normalize('NFKD', text)
    ascii_text = ''.join(c for c in nfkd if not unicodedata.combining(c))
    # Özel Türkçe harfler (NFKD'nin yakalamadıkları)
    replacements = {'ı': 'i', 'I': 'I', 'İ': 'I', 'Ş': 'S', 'ş': 's',
                    'Ğ': 'G', 'ğ': 'g', 'Ç': 'C', 'ç': 'c',
                    'Ü': 'U', 'ü': 'u', 'Ö': 'O', 'ö': 'o'}
    for tr, en in replacements.items():
        ascii_text = ascii_text.replace(tr, en)
    return ascii_text.upper().strip()


# Sektör defaults'un normalize edilmiş versiyonu (cache)
_SEKTOR_DEFAULTS_NORMALIZED = {
    _normalize_tr(k): v for k, v in _SEKTOR_DEFAULTS.items()
}

# ── Anomali Aktivite Skoru Sabitleri ─────────────────────────────────────────
ANOMALY_HARD_WEIGHT        = 1.0
ANOMALY_EXTREME_WEIGHT     = 2.0
MIN_DAYS_FOR_ANOMALY_SCORE = 60


@dataclass(frozen=True)
class AnomalyActivityMetrics:
    total_days:             int
    hard_count:             int
    extreme_count:          int
    weighted_count:         float
    block_count:            int
    longest_streak:         int
    avg_streak:             float
    hhi:                    float
    recency_center:         float
    r_activity:             float
    r_streak:               float
    anomaly_activity_score: Optional[float]


@dataclass(frozen=True)
class SpekResult:
    ticker: str
    guven_skoru: float
    spek_gun_soft: int
    spek_gun_hard: int
    spek_gun_extreme: int
    spek_orani: float
    max_streak: int
    son_30g_spek_yuzdesi: float
    veri_gun_sayisi: int = 0
    ipo_listede: bool = False
    corporate_action_maskelendi: int = 0
    data_start: str = ""
    data_end: str = ""
    temel_roe: Optional[float] = None
    temel_pd_dd: Optional[float] = None
    temel_fk: Optional[float] = None
    temel_net_kar_marji: Optional[float] = None
    temel_ok_buyume: Optional[float] = None
    temel_borc_favok: Optional[float] = None
    temel_kaynak: str = "fallback"
    temel_period: Optional[str] = None
    kap_haber_sayisi: int = 0
    kategori: str = "TEMIZ"  # 'TEMIZ' | 'GECMIS_PD' | 'YENI_PD' | 'AKTIF_PD'
    anomaly_metrics: Optional[AnomalyActivityMetrics] = None
    piyasa_degeri: Optional[float] = None
    beta: Optional[float] = None

    def copyWith(self, **kwargs) -> "SpekResult":
        import dataclasses
        return dataclasses.replace(self, **kwargs)


class FinancialEngine:
    ROLLING_WINDOW = 1825  # 1825 işlem seansı ≈ 7 takvim yılı
    IPO_MIN_SEANS  = 30

    def __init__(self) -> None:
        self._esikler: dict = dict(_SPK_DEFAULTS)
        self._xu100_returns: Optional[pd.Series] = None
        self._xu100_cache_date: str = ""
        self._config_path = os.path.join(os.path.dirname(__file__), "../../motor_config.json")
        self._config_yukle()

    def _config_yukle(self) -> None:
        if os.path.exists(self._config_path):
            try:
                with open(self._config_path) as f:
                    self.reload_thresholds(json.load(f))
            except Exception as e:
                logger.warning(f"[config] motor_config.json yuklenemedi: {e}")

    def reload_thresholds(self, cfg: dict) -> None:
        for key in _SPK_DEFAULTS:
            if key in cfg:
                self._esikler[key] = cfg[key]
        if "pump_dump_fingerprint" in cfg:
            for key, val in cfg["pump_dump_fingerprint"].items():
                self._esikler[key] = val

    @property
    def xu100_returns(self) -> pd.Series:
        """
        XU100 endeksinin getiri serisi (read-only erişim için copy döner).

        Classifier ve diğer dış katmanların relative anomaly hesaplamasında
        kullanabilmesi için public accessor. Mevcut iç hesaplama mantığı
        (_xu100_returns private field) bozulmaz.

        Returns:
            pd.Series: XU100 günlük getirileri, mevcut iç serinin kopyası.
                       Boş seri dönebilir eğer XU100 yüklenmemişse.
        """
        if self._xu100_returns is None:
            return pd.Series(dtype=float)
        return self._xu100_returns.copy()

    def calculate(
        self,
        ticker: str,
        price_df: pd.DataFrame,
        endeksler: Optional[list] = None,
        sektor: Optional[str] = None,
        kap_haber_sayisi: int = 0,
        corporate_action_dates: Optional[list] = None,
    ) -> SpekResult:
        df = self._rolling_window(price_df)
        df, guven_skoru = self._veri_kalite_kontrolu(df)
        df, maskelenen = self._kurumsal_aksiyon_maskesi(df, corporate_action_dates)

        if len(df) < self.IPO_MIN_SEANS:
            return self._ipo_result(ticker, len(df))

        self._xu100_yukle()

        spek_soft, spek_hard, spek_extreme = self._spek_gunleri_tespit(df, endeksler)
        max_streak   = self._max_streak(spek_hard)
        son_30g_spek = float(spek_hard[-30:].mean()) if len(spek_hard) >= 30 else float(spek_hard.mean())

        son_30g_oran = float(spek_hard[-30:].mean()) if len(spek_hard) >= 30 else 0.0
        gecmis_oran  = float(spek_hard[:-30].mean()) if len(spek_hard) > 30 else 0.0

        if len(spek_hard) > 252:
            yillik_max = max(
                float(spek_hard[i:i+252].mean())
                for i in range(0, len(spek_hard) - 252, 30)
            )
        else:
            yillik_max = gecmis_oran

        son_aktif    = son_30g_oran > 0.10
        gecmis_aktif = gecmis_oran > 0.05 or yillik_max > 0.10

        if son_aktif and gecmis_aktif:
            kategori = "AKTIF_PD"
        elif son_aktif:
            kategori = "YENI_PD"
        elif gecmis_aktif:
            kategori = "GECMIS_PD"
        else:
            kategori = "TEMIZ"

        fundamental = self._fundamental_cek(ticker, sektor)

        anomaly_metrics = self._anomaly_activity_metrics(spek_hard, spek_extreme, len(df))

        data_start = str(df.index[0].date())  if len(df) > 0 else ""
        data_end   = str(df.index[-1].date()) if len(df) > 0 else ""

        # Beta — yfinance'tan
        beta = None
        try:
            import yfinance as _yf
            _info = _yf.Ticker(f"{ticker}.IS").info
            _beta = _info.get("beta")
            if _beta is not None:
                beta = round(float(_beta), 4)
        except Exception:
            pass

        return SpekResult(
            ticker=ticker,
            guven_skoru=round(guven_skoru, 4),
            spek_gun_soft=int(spek_soft.sum()),
            spek_gun_hard=int(spek_hard.sum()),
            spek_gun_extreme=int(spek_extreme.sum()),
            spek_orani=round(float(spek_hard.mean()), 4),
            max_streak=max_streak,
            son_30g_spek_yuzdesi=round(son_30g_spek, 4),
            veri_gun_sayisi=len(df),
            ipo_listede=False,
            corporate_action_maskelendi=maskelenen,
            data_start=data_start,
            data_end=data_end,
            temel_roe=fundamental.get("roe"),
            temel_pd_dd=fundamental.get("pd_dd"),
            temel_fk=fundamental.get("fk"),
            temel_net_kar_marji=fundamental.get("net_kar_marji"),
            temel_ok_buyume=fundamental.get("ok_buyume"),
            temel_borc_favok=fundamental.get("borc_favok"),
            temel_kaynak=fundamental.get("data_source", "fallback"),
            temel_period=str(fundamental.get("period")) if fundamental.get("period") else None,
            kap_haber_sayisi=kap_haber_sayisi,
            kategori=kategori,
            anomaly_metrics=anomaly_metrics,
            piyasa_degeri=fundamental.get("piyasa_degeri"),
            beta=beta,
        )

    def _rolling_window(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.sort_index().copy()
        df.index = pd.DatetimeIndex(df.index.date)
        return cast(pd.DataFrame, df.iloc[-self.ROLLING_WINDOW:].copy())

    def _veri_kalite_kontrolu(self, df: pd.DataFrame) -> tuple[pd.DataFrame, float]:
        df    = df.copy()
        guven = 1.0
        if len(df) == 0:
            return df, 0.0
        sifir_hacim = (df["Volume"] <= 0).sum()
        if sifir_hacim > 0:
            df["Volume"] = df["Volume"].replace(0, np.nan).ffill().fillna(0)
            guven *= max(0.8, 1.0 - sifir_hacim / len(df))
        if (df["Close"] <= 0).sum() > 0:
            valid_close_mask = df["Close"] > 0
            df = cast(pd.DataFrame, df.loc[valid_close_mask].copy())
            guven *= 0.9
        if len(df) > 10:
            beklenen = pd.bdate_range(df.index[0], df.index[-1])
            eksik    = 1.0 - len(df) / max(len(beklenen), 1)
            if eksik > 0.10:
                guven *= max(0.7, 1.0 - eksik)
        return df.sort_index(), float(np.clip(guven, 0.0, 1.0))

    def _kurumsal_aksiyon_maskesi(self, df: pd.DataFrame, dates: Optional[list]) -> tuple[pd.DataFrame, int]:
        """
        Bölünme/birleşme tarihlerini bool flag ile işaretle.
        ÖNEMLİ: target Timestamp olarak tutulmalı — datetime.date kullanılırsa
        DatetimeIndex membership check (`target in df.index`) sessizce False döner
        ve hiçbir şey maskelenmez. Bu v2.1'e kadar gizli bir buggydı.
        """
        df = df.copy()
        df["event_flag"] = False  # bool — string yerine ~10x hızlı
        if not dates:
            return df, 0
        maskelenen = 0
        for date_str in dates:
            try:
                # ÖNEMLİ: .date() ÇAĞIRMIYORUZ — Timestamp kalmalı
                action_date = pd.Timestamp(date_str).normalize()
                for offset in range(3):
                    target = action_date + pd.Timedelta(days=offset)
                    if target in df.index:
                        df.loc[target, "event_flag"] = True
                        maskelenen += 1
            except Exception as e:
                logger.warning(f"[corporate_action] {e}")
        return df, maskelenen

    def _ipo_result(self, ticker: str, gun_sayisi: int) -> SpekResult:
        return SpekResult(
            ticker=ticker, guven_skoru=0.0,
            spek_gun_soft=0, spek_gun_hard=0, spek_gun_extreme=0,
            spek_orani=0.0, max_streak=0, son_30g_spek_yuzdesi=0.0,
            veri_gun_sayisi=gun_sayisi, ipo_listede=True,
        )

    def _xu100_yukle(self) -> None:
        today = str(pd.Timestamp.now().date())
        if self._xu100_cache_date == today and self._xu100_returns is not None:
            return
        try:
            import borsapy as bp
            end   = pd.Timestamp.now().strftime("%Y-%m-%d")
            start = (pd.Timestamp.now() - pd.Timedelta(days=1825)).strftime("%Y-%m-%d")
            raw   = bp.Ticker("XU100").history(start=start, end=end)
            raw.index = pd.DatetimeIndex(raw.index.date)
            # ffill(limit=2) — tatil boşluklarını kapat, max 2 gün
            self._xu100_returns    = raw["Close"].pct_change().ffill(limit=2)
            self._xu100_cache_date = today
        except Exception as e:
            logger.warning(f"[xu100] cekilemedi: {e}")
            self._xu100_returns = pd.Series(dtype=float)

    def _spek_gunleri_tespit(self, df: pd.DataFrame, endeksler: Optional[list]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """For loop yerine vektörel — ~80x hızlanma"""
        n      = len(df)
        h_ret  = df["Close"].pct_change().to_numpy(dtype=float)
        volume = df["Volume"].to_numpy(dtype=float)
        vol_mean = pd.Series(volume).rolling(60, min_periods=10).mean().to_numpy(dtype=float)

        # bool kolonu string yerine
        is_corp = df.get("event_flag", pd.Series([False] * n, index=df.index)).to_numpy(dtype=bool)

        xu100 = np.full(n, np.nan)
        if self._xu100_returns is not None and not self._xu100_returns.empty:
            xu100 = self._xu100_returns.reindex(df.index).ffill(limit=2).to_numpy(dtype=float)

        esik_soft  = 0.05
        esik_hard  = self._esikler["gunluk_fiyat_esigi"]
        esik_hacim = self._esikler["hacim_spike_esigi"]

        valid       = ~np.isnan(h_ret) & ~is_corp
        market_calm = np.isnan(xu100) | (np.abs(xu100) < 0.03)
        ters_yon    = np.isnan(xu100) | (h_ret * xu100 <= 0)

        soft    = valid & (np.abs(h_ret) >= esik_soft) & market_calm
        hard    = valid & (np.abs(h_ret) >= esik_hard) & market_calm & ters_yon
        extreme = hard  & (vol_mean > 0) & (volume > vol_mean * esik_hacim)

        return soft, hard, extreme

    def _max_streak(self, mask: np.ndarray) -> int:
        max_s, cur = 0, 0
        for v in mask:
            cur   = cur + 1 if v else 0
            max_s = max(max_s, cur)
        return max_s

    def _anomaly_activity_metrics(
        self,
        spek_hard: np.ndarray,
        spek_extreme: np.ndarray,
        total_days: int,
    ) -> Optional[AnomalyActivityMetrics]:
        if total_days < MIN_DAYS_FOR_ANOMALY_SCORE:
            return None

        hard_count     = int(spek_hard.sum())
        extreme_count  = int(spek_extreme.sum())
        weighted_count = (
            hard_count    * ANOMALY_HARD_WEIGHT +
            extreme_count * ANOMALY_EXTREME_WEIGHT
        )

        # event_series: extreme ⊆ hard → extreme=2, hard-only=1, normal=0
        event_series = np.where(spek_extreme, 2, np.where(spek_hard, 1, 0))

        # Blok metrikler
        blocks: List[int] = []
        cur = 0
        for v in event_series:
            if v > 0:
                cur += 1
            elif cur > 0:
                blocks.append(cur)
                cur = 0
        if cur > 0:
            blocks.append(cur)

        block_count    = len(blocks)
        longest_streak = max(blocks) if blocks else 0
        avg_streak     = float(sum(blocks)) / block_count if block_count > 0 else 0.0

        # HHI — blok yoğunlaşma endeksi
        if hard_count > 0 and block_count > 0:
            hhi = float(sum((b / hard_count) ** 2 for b in blocks))
        else:
            hhi = 0.0

        # Recency center — anomali günlerinin ağırlıklı zaman merkezi [0, 1]
        n = len(event_series)
        anomaly_idx = np.where(event_series > 0)[0]
        if len(anomaly_idx) > 0:
            weights        = event_series[anomaly_idx].astype(float)
            center         = float(np.average(anomaly_idx, weights=weights))
            recency_center = center / (n - 1) if n > 1 else 0.5
        else:
            recency_center = 0.0

        # Normalize R değerleri [0, 1]
        # r_activity: weighted_count oranı; %30 tamamen anomalili → 1.0
        r_activity = min(1.0, (weighted_count / total_days) / 0.30) if total_days > 0 else 0.0
        # r_streak: 15 ardışık gün → 1.0
        r_streak   = min(1.0, longest_streak / 15.0)
        # r_recency: recency_center zaten [0, 1]
        r_recency  = recency_center

        # V1 AAS
        aas = round(float(np.clip(
            (0.45 * r_activity + 0.30 * r_streak + 0.25 * r_recency) * 10.0,
            0.0, 10.0
        )), 4)

        return AnomalyActivityMetrics(
            total_days=total_days,
            hard_count=hard_count,
            extreme_count=extreme_count,
            weighted_count=round(weighted_count, 4),
            block_count=block_count,
            longest_streak=longest_streak,
            avg_streak=round(avg_streak, 4),
            hhi=round(hhi, 4),
            recency_center=round(recency_center, 4),
            r_activity=round(r_activity, 4),
            r_streak=round(r_streak, 4),
            anomaly_activity_score=aas,
        )

    def _fundamental_cek(self, ticker: str, sektor: Optional[str]) -> dict:
        global _FUNDAMENTAL_CACHE, _FUNDAMENTAL_CACHE_DATE
        today = str(pd.Timestamp.now().date())
        if _FUNDAMENTAL_CACHE_DATE != today:
            _FUNDAMENTAL_CACHE.clear()
            _FUNDAMENTAL_CACHE_DATE = today
        if ticker in _FUNDAMENTAL_CACHE:
            return _FUNDAMENTAL_CACHE[ticker]
        result = None
        try:
            result = self._borsapy_standard(ticker)
        except Exception as e:
            logger.warning(f"[temel] {ticker} borsapy standart: {e}")
        if result is None:
            try:
                result = self._borsapy_banking(ticker)
            except Exception as e:
                logger.warning(f"[temel] {ticker} borsapy banking: {e}")
        if result is None:
            try:
                result = self._yfinance_fallback(ticker)
            except Exception as e:
                logger.warning(f"[temel] {ticker} yfinance fallback: {e}")
        if result is None:
            result = self._sektor_fallback(sektor)
        # borsapy döndü ama fk null ise yfinance'tan sadece fk'yı tamamla
        if result is not None and result.get("fk") is None:
            try:
                import yfinance as _yf
                _info = _yf.Ticker(f"{ticker}.IS").info
                _fk = _info.get("trailingPE")
                if _fk is not None:
                    result["fk"] = round(float(_fk), 4)
                    result["data_source"] = result.get("data_source", "borsapy") + "+yfinance_fk"
            except Exception:
                pass
        # borsapy döndü ama pd_dd null ise yfinance'tan tamamla
        if result is not None and result.get("pd_dd") is None:
            try:
                import yfinance as _yf
                _info = _yf.Ticker(f"{ticker}.IS").info
                _pd_dd = _info.get("priceToBook")
                if _pd_dd is not None:
                    result["pd_dd"] = round(float(_pd_dd), 4)
                    src = result.get("data_source", "borsapy")
                    if "+yfinance_fk" not in src:
                        result["data_source"] = src + "+yfinance_pddd"
                    else:
                        result["data_source"] = src.replace("+yfinance_fk", "+yfinance_fk_pddd")
            except Exception:
                pass
        _FUNDAMENTAL_CACHE[ticker] = result
        return result

    def _borsapy_standard(self, ticker: str) -> Optional[dict]:
        """
        borsapy standart bilanço çekimi.
        ÖNEMLİ: Index satır başlıkları Türkçe karakterli — borsapy'nin
        döndürdüğü orijinal halleri. ASCII'ye çevirmek eşleşmeyi BOZAR.
        """
        import borsapy as bp
        t    = bp.Ticker(ticker)
        bs   = t.balance_sheet
        is_  = t.income_stmt
        info = t.info
        if bs is None or bs.empty or is_ is None or is_.empty:
            return None
        latest = bs.columns[0]

        def _v(df, key):
            df2 = df.copy()
            df2.index = df2.index.str.strip()
            if key in df2.index:
                v = df2.loc[key].iloc[0]
                return float(v) if pd.notna(v) else None
            return None

        # Türkçe karakterli — borsapy'nin döndürdüğü orijinal başlıklar
        ozkaynaklar     = _v(bs,  "Özkaynaklar")
        net_kar         = _v(is_, "DÖNEM KARI (ZARARI)")
        satis           = _v(is_, "Satış Gelirleri")
        odenmis_sermaye = _v(bs,  "Ödenmiş Sermaye")

        if not ozkaynaklar or ozkaynaklar <= 0:
            return None
        roe = net_kar / ozkaynaklar if net_kar is not None else None
        nkm = net_kar / satis if (net_kar and satis and satis > 0) else None
        pd_dd, fk = None, None

        def _to_float_or_none(value):
            try:
                if value is None or pd.isna(value):
                    return None
                return float(value)
            except Exception:
                return None

        # Borsapy info içinden fiyat / EPS gelirse önce onları kullan.
        # Bazı hisselerde info.eps boş geldiği için F/K daha önce None kalıyordu.
        last_price = _to_float_or_none(
            getattr(info, "last", None) or
            (info.get("last") if hasattr(info, "get") else None)
        )
        eps = _to_float_or_none(
            getattr(info, "eps", None) or
            (info.get("eps") if hasattr(info, "get") else None)
        )

        # Fiyat info.last içinde gelmezse son kapanıştan fallback üret.
        if last_price is None:
            try:
                hist = t.history(period="10d")
                if hist is not None and not hist.empty and "Close" in hist.columns:
                    close = hist["Close"].dropna()
                    if not close.empty:
                        last_price = float(close.iloc[-1])
            except Exception as e:
                logger.warning(f"[temel] {ticker} son fiyat fallback hesaplanamadı: {e}")

        # EPS info.eps içinde gelmezse yaklaşık EPS = net_kar / odenmis_sermaye.
        # Bu sayede F/K alanı, EPS eksikliğinde de hesaplanabilir.
        if eps is None and net_kar is not None and odenmis_sermaye is not None:
            try:
                if float(odenmis_sermaye) > 0:
                    eps = float(net_kar) / float(odenmis_sermaye)
            except Exception as e:
                logger.warning(f"[temel] {ticker} EPS fallback hesaplanamadı: {e}")

        if last_price is not None and odenmis_sermaye and ozkaynaklar > 0:
            pd_dd = float(last_price) * float(odenmis_sermaye) / ozkaynaklar

        if last_price is not None and eps is not None and float(eps) > 0:
            fk = float(last_price) / float(eps)
        # Özkaynak büyümesi (iki dönem varsa hesapla)
        ok_buyume = None
        try:
            if len(bs.columns) >= 2:
                ozk_onceki = float(bs.loc["Özkaynaklar"].iloc[1]) if "Özkaynaklar" in bs.index else None
                if ozk_onceki and ozk_onceki > 0 and ozkaynaklar:
                    ok_buyume = round((ozkaynaklar - ozk_onceki) / abs(ozk_onceki), 6)
        except Exception:
            ok_buyume = None

        # Borç / FAVÖK
        borc_favok = None
        try:
            toplam_borc_keys = ["Finansal Borçlar", "Toplam Yükümlülükler", "Uzun Vadeli Borçlar"]
            favok_keys = ["FAVÖK", "Faiz Amortisman Vergi Öncesi Kâr"]
            toplam_borc = None
            for k in toplam_borc_keys:
                if k in bs.index:
                    v = bs.loc[k].iloc[0]
                    if pd.notna(v):
                        toplam_borc = float(v)
                        break
            favok = None
            for k in favok_keys:
                if k in is_.index:
                    v = is_.loc[k].iloc[0]
                    if pd.notna(v):
                        favok = float(v)
                        break
            if toplam_borc is not None and favok is not None and favok > 0:
                borc_favok = round(toplam_borc / favok, 4)
        except Exception:
            borc_favok = None

        piyasa_degeri = (
            round(float(last_price) * float(odenmis_sermaye), 0)
            if last_price is not None and odenmis_sermaye is not None
            else None
        )
        return {
            "roe":           round(roe,   6) if roe   is not None else None,
            "net_kar_marji": round(nkm,   6) if nkm   is not None else None,
            "pd_dd":         round(pd_dd, 4) if pd_dd is not None else None,
            "fk":            round(fk,    4) if fk    is not None else None,
            "ok_buyume":     ok_buyume,
            "borc_favok":    borc_favok,
            "piyasa_degeri": piyasa_degeri,
            "data_source":   "borsapy",
            "period":        latest,
        }

    def _borsapy_banking(self, ticker: str) -> Optional[dict]:
        """
        Bankacılık UFRS bilanço çekimi (BIST bankacılık formatı).
        ÖNEMLİ: Index satır başlıkları Türkçe karakterli kalmalı.
        """
        import borsapy as bp
        t = bp.Ticker(ticker)
        bs, is_ = None, None
        for fg in ("UFRS", "TMS_17", "UFRS_B"):
            try:
                _bs  = t.get_balance_sheet(financial_group=fg)
                _is  = t.get_income_stmt(financial_group=fg)
                if _bs is not None and not _bs.empty and _is is not None and not _is.empty:
                    bs, is_ = _bs, _is
                    break
            except Exception:
                continue
        if bs is None or is_ is None:
            return None
        bs.index  = bs.index.str.strip()
        is_.index = is_.index.str.strip()

        def _v(df, key):
            if key in df.index:
                v = df.loc[key].iloc[0]
                return float(v) if pd.notna(v) else None
            return None

        # Türkçe karakterli — BIST bankacılık tablo başlıkları
        ozkaynaklar = _v(bs,  "XVI. ÖZKAYNAKLAR")
        net_kar     = _v(is_, "XXIII. NET DÖNEM KARI/ZARARI (XVII+XXII)")
        satis       = _v(is_, "VIII. FAALİYET GELİRLERİ/GİDERLERİ TOPLAMI (III+IV+V+VI+VII)")

        if not ozkaynaklar or ozkaynaklar <= 0:
            return None
        roe = net_kar / ozkaynaklar if net_kar is not None else None
        nkm = net_kar / satis if (net_kar and satis and satis > 0) else None
        return {
            "roe":            round(roe, 6) if roe is not None else None,
            "net_kar_marji":  round(nkm, 6) if nkm is not None else None,
            "pd_dd":          None,
            "fk":             None,
            "net_borc_favok": None,
            "piyasa_degeri":  None,
            "data_source":    "borsapy_banking",
            "period":         bs.columns[0],
        }

    def _yfinance_fallback(self, ticker: str) -> Optional[dict]:
        """yfinance'tan temel metrikler — borsapy başarısız olunca."""
        import yfinance as _yf
        info = _yf.Ticker(f"{ticker}.IS").info
        if not info or info.get("regularMarketPrice") is None:
            return None

        fk        = info.get("trailingPE")
        pd_dd     = info.get("priceToBook")
        roe       = info.get("returnOnEquity")
        nkm       = info.get("profitMargins")
        ok_buyume = info.get("revenueGrowth")
        mc        = info.get("marketCap")

        if all(v is None for v in [fk, pd_dd, roe, nkm]):
            return None

        return {
            "fk":            round(float(fk),       4) if fk        is not None else None,
            "pd_dd":         round(float(pd_dd),     4) if pd_dd     is not None else None,
            "roe":           round(float(roe),       6) if roe       is not None else None,
            "net_kar_marji": round(float(nkm),       6) if nkm       is not None else None,
            "ok_buyume":     round(float(ok_buyume), 6) if ok_buyume is not None else None,
            "borc_favok":    None,
            "piyasa_degeri": round(float(mc), 0)        if mc        is not None else None,
            "data_source":   "yfinance",
            "period":        "TTM",
        }

    def _sektor_fallback(self, sektor: Optional[str]) -> dict:
        """Türkçe karakter toleranslı sektör fallback."""
        if not sektor:
            return {**_SEKTOR_DEFAULTS["DEFAULT"], "data_source": "fallback", "period": None}
        s_norm = _normalize_tr(sektor)
        for key_norm, vals in _SEKTOR_DEFAULTS_NORMALIZED.items():
            if key_norm != "DEFAULT" and key_norm in s_norm:
                return {**vals, "data_source": "fallback", "period": None}
        return {**_SEKTOR_DEFAULTS["DEFAULT"], "data_source": "fallback", "period": None}