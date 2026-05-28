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
from dataclasses import dataclass, field
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
    spek_score: float
    topsis_raw: float
    guven_skoru: float
    fiyat_anomali_skoru: float
    hacim_patlamasi_skoru: float
    volatilite_skoru: float
    pump_benzerlik_skoru: float
    fiyat_anomali_aciklama: str
    hacim_patlamasi_aciklama: str
    volatilite_aciklama: str
    pump_benzerlik_aciklama: str
    fundamental_multiplier: float
    fundamental_aciklama: str
    spek_gun_soft: int
    spek_gun_hard: int
    spek_gun_extreme: int
    spek_orani: float
    max_streak: int
    son_30g_spek_yuzdesi: float
    hacim_spike_kati: float
    entropi_agirliklari: dict = field(default_factory=dict)
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
    haber_carpani: float = 1.0
    kategori: str = "TEMIZ"  # 'TEMIZ' | 'GECMIS_PD' | 'YENI_PD' | 'AKTIF_PD'
    anomaly_metrics: Optional[AnomalyActivityMetrics] = None

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

        fiyat_skoru,      fiyat_aciklama      = self._fiyat_anomali_skoru(df, spek_hard, spek_extreme)
        hacim_skoru,      hacim_aciklama      = self._hacim_patlamasi_skoru(df, spek_hard)
        volatilite_skoru, volatilite_aciklama = self._volatilite_skoru(df, spek_hard)
        pump_skoru,       pump_aciklama       = self._pump_benzerlik_skoru(df)
        hacim_spike_kati                      = self._hacim_spike_kati(df)

        agirliklar, entropi_dict = self._entropi_agirliklari(df)
        kriter_vektoru  = np.array([fiyat_skoru, hacim_skoru, volatilite_skoru, pump_skoru])
        topsis_raw      = self._topsis(kriter_vektoru, agirliklar)
        topsis_score_10 = topsis_raw * 10.0

        fundamental = self._fundamental_cek(ticker, sektor)
        multiplier, fund_aciklama = self._fundamental_multiplier(fundamental, sektor)

        # Haber bombardımanı çarpanı — bağımsız sinyal, multiplicative
        # 20+ ODA bildirimi olan hisseye %30 prim
        haber_carpani = 1.0 + min(kap_haber_sayisi / 20.0, 1.0) * 0.3

        # Final skor — tek clip, bilgi kaybı yok
        final_score = float(np.clip(
            topsis_score_10 * multiplier * guven_skoru * haber_carpani,
            0.0, 10.0
        ))

        anomaly_metrics = self._anomaly_activity_metrics(spek_hard, spek_extreme, len(df))

        data_start = str(df.index[0].date())  if len(df) > 0 else ""
        data_end   = str(df.index[-1].date()) if len(df) > 0 else ""

        return SpekResult(
            ticker=ticker,
            spek_score=round(final_score, 4),
            topsis_raw=round(topsis_raw, 4),
            guven_skoru=round(guven_skoru, 4),
            fiyat_anomali_skoru=round(fiyat_skoru, 4),
            hacim_patlamasi_skoru=round(hacim_skoru, 4),
            volatilite_skoru=round(volatilite_skoru, 4),
            pump_benzerlik_skoru=round(pump_skoru, 4),
            fiyat_anomali_aciklama=fiyat_aciklama,
            hacim_patlamasi_aciklama=hacim_aciklama,
            volatilite_aciklama=volatilite_aciklama,
            pump_benzerlik_aciklama=pump_aciklama,
            fundamental_multiplier=round(multiplier, 4),
            fundamental_aciklama=fund_aciklama,
            spek_gun_soft=int(spek_soft.sum()),
            spek_gun_hard=int(spek_hard.sum()),
            spek_gun_extreme=int(spek_extreme.sum()),
            spek_orani=round(float(spek_hard.mean()), 4),
            max_streak=max_streak,
            son_30g_spek_yuzdesi=round(son_30g_spek, 4),
            hacim_spike_kati=round(hacim_spike_kati, 3),
            entropi_agirliklari=entropi_dict,
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
            haber_carpani=round(haber_carpani, 4),
            kategori=kategori,
            anomaly_metrics=anomaly_metrics,
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
            ticker=ticker, spek_score=0.0, topsis_raw=0.0, guven_skoru=0.0,
            fiyat_anomali_skoru=0.0, hacim_patlamasi_skoru=0.0,
            volatilite_skoru=0.0, pump_benzerlik_skoru=0.0,
            fiyat_anomali_aciklama="IPO: Yetersiz veri",
            hacim_patlamasi_aciklama="IPO: Yetersiz veri",
            volatilite_aciklama="IPO: Yetersiz veri",
            pump_benzerlik_aciklama="IPO: Yetersiz veri",
            fundamental_multiplier=1.0,
            fundamental_aciklama="IPO: Piyasa keşif süreci devam ediyor",
            spek_gun_soft=0, spek_gun_hard=0, spek_gun_extreme=0,
            spek_orani=0.0, max_streak=0, son_30g_spek_yuzdesi=0.0,
            hacim_spike_kati=1.0, veri_gun_sayisi=gun_sayisi, ipo_listede=True,
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

    def _fiyat_anomali_skoru(
        self,
        df: pd.DataFrame,
        spek_hard: np.ndarray,
        spek_extreme: np.ndarray,
    ) -> tuple[float, str]:
        close = df["Close"].to_numpy(dtype=float)
        h_ret = np.concatenate([[0.0], np.diff(close) / (close[:-1] + 1e-10)])
        spek_oran       = spek_hard.mean()
        son30_spek      = spek_hard[-30:].mean() if len(spek_hard) >= 30 else spek_oran
        extreme_oran    = spek_extreme.mean()
        spek_g          = np.abs(h_ret[spek_hard])
        ort_spek_getiri = spek_g.mean() if len(spek_g) > 0 else 0.0
        if "High" in df.columns and "Low" in df.columns:
            hl     = (df["High"].to_numpy(dtype=float) - df["Low"].to_numpy(dtype=float)) / (close + 1e-10)
            spek_hl   = hl[spek_hard].mean()  if spek_hard.any()  else hl.mean()
            normal_hl = hl[~spek_hard].mean() if (~spek_hard).any() else hl.mean()
            hl_amp = spek_hl / (normal_hl + 1e-10)
        else:
            hl_amp = 1.0
        raw = (
            spek_oran    * 3.0 + son30_spek   * 2.5 + extreme_oran * 2.0 +
            min(ort_spek_getiri / 0.15, 1.0) * 1.5 + min((hl_amp - 1.0) / 3.0, 1.0) * 1.0
        )
        return float(np.clip(raw, 0.0, 10.0)), (
            f"Hard spek: {int(spek_hard.sum())} gun (%{spek_oran*100:.1f}), "
            f"Extreme: {int(spek_extreme.sum())} gun, Son 30g: %{son30_spek*100:.1f}"
        )

    def _hacim_patlamasi_skoru(
        self,
        df: pd.DataFrame,
        spek_hard: np.ndarray,
        baseline_window: int = 50,
        recent_window: int = 10,
        baseline_offset: int = 10,
    ) -> tuple[float, str]:
        volume = df["Volume"].replace(0, np.nan).ffill().fillna(0).to_numpy(dtype=float)
        if len(volume) < 20:
            return 0.0, "Yetersiz veri"

        # Bağımsız baseline — son baseline_offset gün dışarıda (kontaminasyon engellendi)
        if len(volume) >= baseline_offset + baseline_window:
            baseline = np.mean(volume[-(baseline_offset + baseline_window):-baseline_offset])
        elif len(volume) > baseline_offset:
            baseline = np.mean(volume[:-baseline_offset])
        else:
            baseline = np.mean(volume)
        son_10g    = np.mean(volume[-recent_window:])
        spike_kati = son_10g / (baseline + 1e-10)

        if len(volume) >= 35:
            onceki_ort = np.mean(volume[-35:-5])
            onceki_std = np.std(volume[-35:-5])
            son_5g     = np.mean(volume[-5:])
            sessiz_patlama = son_5g / (onceki_ort + 1e-10) if onceki_std < onceki_ort * 0.3 else 1.0
        else:
            sessiz_patlama = 1.0

        # spk_asim_oran: Son 60g penceresinde, baseline (son 10g hariç) eşiğini aşan gün sayısı
        # Pencere ve baseline asimetrisi kasıtlı — son 10g'nin "baseline'a göre patlama" sıklığını ölçer
        pencere_vol   = volume[-60:] if len(volume) >= 60 else volume
        spk_asim_oran = np.sum(pencere_vol > baseline * self._esikler["hacim_spike_esigi"]) / len(pencere_vol)

        if spek_hard.any() and (~spek_hard).any():
            hacim_amp = np.mean(volume[spek_hard]) / (np.mean(volume[~spek_hard]) + 1e-10)
        else:
            hacim_amp = 1.0

        raw = (
            min(spike_kati / self._esikler["hacim_spike_esigi"], 1.0) * 3.5 +
            min((sessiz_patlama - 1.0) / 4.0, 1.0) * 2.5 +
            min(spk_asim_oran / 0.10, 1.0) * 2.0 +
            min((hacim_amp - 1.0) / 3.0, 1.0) * 2.0
        )
        return float(np.clip(raw, 0.0, 10.0)), (
            f"Anlik spike: {spike_kati:.1f}x (esik {self._esikler['hacim_spike_esigi']}x), "
            f"SPK esik asimi: %{spk_asim_oran*100:.1f}"
        )

    def _hacim_spike_kati(self, df: pd.DataFrame) -> float:
        volume = df["Volume"].replace(0, np.nan).ffill().fillna(0).to_numpy(dtype=float)
        if len(volume) < 10:
            return 1.0
        baseline = np.mean(volume[-60:-10]) if len(volume) >= 60 else (np.mean(volume[:-10]) if len(volume) > 10 else np.mean(volume))
        return float(np.mean(volume[-10:]) / (baseline + 1e-10))

    def _volatilite_skoru(
        self,
        df: pd.DataFrame,
        spek_hard: np.ndarray,
        long_window: int = 60,
        mid_window: int = 20,
        short_window: int = 10,
    ) -> tuple[float, str]:
        close = df["Close"].to_numpy(dtype=float)
        ret   = pd.Series(close).pct_change().fillna(0).to_numpy(dtype=float)
        if "High" in df.columns and "Low" in df.columns:
            hl_spread = np.mean((df["High"].to_numpy(dtype=float) - df["Low"].to_numpy(dtype=float)) / (close + 1e-10))
        else:
            hl_spread = np.std(ret) * 2.5  # Ölçek uyumu
        std_20g = np.std(ret[-mid_window:]) if len(ret) >= mid_window else np.std(ret)
        if len(ret) >= long_window:
            ani_artis = (np.std(ret[-short_window:]) if len(ret) >= short_window else std_20g) / (np.std(ret[-long_window:]) + 1e-10)
        else:
            ani_artis = 1.0
        if spek_hard.any() and (~spek_hard).any():
            vol_amp = np.std(ret[spek_hard]) / (np.std(ret[~spek_hard]) + 1e-10)
        else:
            vol_amp = 1.0
        raw = (
            min(hl_spread / 0.06, 1.0) * 3.0 + min(std_20g / 0.04, 1.0) * 2.5 +
            min((ani_artis - 1.0) / 2.0, 1.0) * 2.5 + min((vol_amp - 1.0) / 3.0, 1.0) * 2.0
        )
        return float(np.clip(raw, 0.0, 10.0)), (
            f"HL spread: %{hl_spread*100:.2f}, 20g std: %{std_20g*100:.2f}, Ani artis: {ani_artis:.2f}x"
        )

    def _pump_benzerlik_skoru(self, df: pd.DataFrame, lookback: int = 180) -> tuple[float, str]:
        window = df.iloc[-lookback:].copy() if len(df) >= lookback else df.copy()
        if len(window) < 30:
            return 0.0, "Yetersiz veri"
        close  = window["Close"].to_numpy(dtype=float)
        volume = window["Volume"].replace(0, np.nan).ffill().to_numpy(dtype=float)
        peak_loc   = int(close.argmax())
        pump_start = max(0, peak_loc - 60)

        # pump_start <= 5 → baseline kirli, erken return
        if peak_loc < 5 or pump_start <= 5:
            return 0.0, "Zirve basta — P&D pattern yok"

        pump_close = close[pump_start:peak_loc + 1]
        dump_close = close[peak_loc:min(len(close), peak_loc + 61)]
        if len(pump_close) < 5 or len(dump_close) < 3:
            return 0.0, "Yetersiz pencere"
        if close[pump_start] > 0 and (close[peak_loc] / close[pump_start]) < 2.0:
            return 0.0, "Pump buyuklugu yetersiz (2x alti)"

        baseline_vol = float(np.nanmean(volume[:pump_start]))
        pump_vol     = float(np.nanmean(volume[pump_start:peak_loc + 1]))
        dump_vol     = float(np.nanmean(volume[peak_loc:peak_loc + 61]))
        pump_rets    = np.diff(pump_close) / (pump_close[:-1] + 1e-10)
        dump_rets    = np.diff(dump_close) / (dump_close[:-1] + 1e-10)

        candidates = [
            (len(pump_close),                    self._esikler["pump_duration_mean"],    self._esikler["pump_duration_std"]),
            (pump_vol / (baseline_vol + 1e-10),  self._esikler["volume_surge_mean"],     self._esikler["volume_surge_std"]),
            (float(np.mean(pump_rets)) if len(pump_rets) > 0 else 0.0, self._esikler["pump_rate_mean"], self._esikler["pump_rate_std"]),
            (float(np.mean(dump_rets)) if len(dump_rets) > 0 else 0.0, self._esikler["dump_rate_mean"], self._esikler["dump_rate_std"]),
            (dump_vol / (pump_vol + 1e-10),      self._esikler["post_peak_volume_mean"], self._esikler["post_peak_volume_std"]),
        ]
        sims = [
            float(np.exp(-0.5 * ((v - m) / s) ** 2)) if s > 1e-9 else (1.0 if abs(v - m) < 1e-6 else 0.0)
            for v, m, s in candidates
        ]
        benzerlik    = float(np.mean(sims))
        volume_surge = pump_vol / (baseline_vol + 1e-10)
        return float(np.clip(benzerlik * 10.0, 0.0, 10.0)), (
            f"P&D benzerlik: %{benzerlik*100:.1f}, Pump suresi: {len(pump_close)}g, Hacim surge: {volume_surge:.1f}x"
        )

    def _entropi_agirliklari(self, df: pd.DataFrame) -> tuple[np.ndarray, dict]:
        """
        Shannon entropi ağırlıklandırması.
        4 bağımsız feature kullanılır:
          - ret_abs       : mutlak günlük getiri (fiyat anomali proxy)
          - volume_norm   : ortalamaya göre normalize hacim (hacim proxy)
          - spike_freq    : rolling hacim eşiği aşım rate'i (volatilite/hacim spike proxy)
          - hl_norm       : std-normalize edilmiş intraday range (pump intensity proxy)

        Bu 4 feature farklı transformasyonlardan geldikleri için
        Shannon diversity'leri farklı çıkar — entropi ağırlıkları
        anlamlı bilgi katkısını yansıtır.
        """
        w      = min(60, len(df))
        if w < 5:
            # Çok az veri — eşit ağırlık
            equal = np.full(4, 0.25)
            return equal, {"fiyat_anomali": 0.25, "hacim_patlamasi": 0.25,
                           "volatilite": 0.25, "pump_benzerlik": 0.25}

        close  = df["Close"].to_numpy(dtype=float)[-w:]
        volume = df["Volume"].replace(0, np.nan).ffill().fillna(0).to_numpy(dtype=float)[-w:]

        # Feature 1: mutlak getiri
        ret_abs = np.abs(np.concatenate([[0.0], np.diff(close) / (close[:-1] + 1e-10)]))

        # Feature 2: normalize hacim
        vol_mean_w  = np.mean(volume) + 1e-10
        volume_norm = volume / vol_mean_w

        # Feature 3: rolling spike frekansı (rank-bağımsız transformasyon)
        # Son 60g içinde, her gün için "hacim son 20g ortalamasının N katı mı?" binary signal
        if w >= 20:
            roll_mean = pd.Series(volume).rolling(20, min_periods=5).mean().fillna(vol_mean_w).to_numpy()
            spike_freq = (volume > roll_mean * 2.0).astype(float)
        else:
            spike_freq = (volume > vol_mean_w * 2.0).astype(float)

        # Feature 4: std-normalize edilmiş intraday range (pump intensity)
        ret_std = np.std(ret_abs) + 1e-10
        if "High" in df.columns and "Low" in df.columns:
            hl = (df["High"].to_numpy(dtype=float)[-w:] - df["Low"].to_numpy(dtype=float)[-w:]) / (close + 1e-10)
            hl_norm = hl / (np.mean(hl) + 1e-10)
        else:
            hl_norm = ret_abs / ret_std

        features = np.column_stack([ret_abs, volume_norm, spike_freq, hl_norm])

        # Shannon entropi — temiz hesaplama (double computation kaldırıldı)
        eps      = 1e-10
        abs_f    = np.abs(features)
        col_sums = abs_f.sum(axis=0)
        col_sums = np.where(col_sums == 0, eps, col_sums)
        p        = abs_f / col_sums
        p        = np.where(p == 0, eps, p)

        n         = features.shape[0]
        entropy   = -np.sum(p * np.log(p), axis=0) / np.log(n + eps)
        diversity = 1 - entropy
        d_sum     = diversity.sum()
        weights   = diversity / d_sum if d_sum > 0 else np.full(4, 0.25)

        return weights, {
            "fiyat_anomali":   round(float(weights[0]), 4),
            "hacim_patlamasi": round(float(weights[1]), 4),
            "volatilite":      round(float(weights[2]), 4),
            "pump_benzerlik":  round(float(weights[3]), 4),
        }

    def _topsis(self, kriter_vektoru: np.ndarray, agirliklar: np.ndarray) -> float:
        v        = kriter_vektoru / 10.0
        weighted = v * agirliklar
        d_iyi    = np.sqrt(np.sum((weighted - agirliklar) ** 2))
        d_kotu   = np.sqrt(np.sum(weighted ** 2))
        total    = d_iyi + d_kotu
        return 0.0 if total < 1e-10 else float(d_kotu / total)

    def _sektor_ref(self, sektor: Optional[str]) -> dict:
        """Türkçe karakter toleranslı sektör eşleşmesi."""
        if not sektor:
            return _SEKTOR_DEFAULTS["DEFAULT"]
        s_norm = _normalize_tr(sektor)
        for key_norm, vals in _SEKTOR_DEFAULTS_NORMALIZED.items():
            if key_norm != "DEFAULT" and key_norm in s_norm:
                return vals
        return _SEKTOR_DEFAULTS["DEFAULT"]

    def _fundamental_multiplier(self, fundamental: dict, sektor: Optional[str]) -> tuple[float, str]:
        sektor_ref = self._sektor_ref(sektor)
        roe   = fundamental.get("roe")
        pd_dd = fundamental.get("pd_dd")
        fk    = fundamental.get("fk")
        nkm   = fundamental.get("net_kar_marji")
        guclu = 0
        zayif = 0
        if roe is not None:
            if roe > sektor_ref["roe"] * 1.5:  guclu += 2
            elif roe > sektor_ref["roe"]:       guclu += 1
            elif roe < 0:                       zayif += 2
            else:                               zayif += 1
        if pd_dd is not None:
            if pd_dd > sektor_ref["pd_dd"] * 2.0:   zayif += 2
            elif pd_dd > sektor_ref["pd_dd"] * 1.3: zayif += 1
            elif pd_dd < sektor_ref["pd_dd"] * 0.7: guclu += 1
        if fk is not None and sektor_ref.get("fk", 0) > 0:
            if fk > sektor_ref["fk"] * 2.5:   zayif += 2
            elif fk > sektor_ref["fk"] * 1.5: zayif += 1
            elif fk < sektor_ref["fk"] * 0.5: guclu += 1
        if nkm is not None:
            if nkm < 0:                                    zayif += 1
            elif nkm > sektor_ref["net_kar_marji"] * 1.5: guclu += 1
        net = guclu - zayif
        if net >= 3:    return 0.65, f"Güçlü fundamental (net={net}): Hareketin bir kısmı açıklanabilir"
        elif net == 2:  return 0.72, f"Orta-güçlü fundamental (net={net}): Kısmi temel destek"
        elif net == 1:  return 0.80, f"Hafif fundamental destek (net={net})"
        elif net == 0:  return 0.90, "Nötr fundamental: Hareket açıklanamıyor"
        elif net == -1: return 0.95, f"Zayıf fundamental (net={net}): Temel desteklenmiyor"
        else:           return 1.00, f"Çok zayıf fundamental (net={net}): Hareket tamamen spekülatif"

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
            result = self._sektor_fallback(sektor)
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

        return {
            "roe":           round(roe,   6) if roe   is not None else None,
            "net_kar_marji": round(nkm,   6) if nkm   is not None else None,
            "pd_dd":         round(pd_dd, 4) if pd_dd is not None else None,
            "fk":            round(fk,    4) if fk    is not None else None,
            "ok_buyume":     ok_buyume,
            "borc_favok":    borc_favok,
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
        for fg in ("UFRS_B", "UFRS", "TMS_17"):
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
            "data_source":    "borsapy_banking",
            "period":         bs.columns[0],
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