"""
PayNotu Scenario Classifier — Core Iskelet

Sliding window üzerinde rule-based davranış sınıflandırması yapar.
SPK kalibre eşikler ve relative anomaly (XU100 + sektör baseline) mantığı kullanır.

Bu dosya Etap 1.2a kapsamında iskelet halinde — rule-based labeling ve
conflict resolution Etap 1.2b'de eklenecek.

Mimari kararlar (anayasal):
- Fixed start-date growing window (segment indeksleri stabil)
- Rolling 1825-day statistical baseline (Z-score için)
- Config-driven pencere boyutları (system_config/scenario_classifier)
- Dynamic lookback (max rolling baseline + buffer)
- Continuous confidence decay (context_ratio = available / required)
- IPO regime ayrı state (MarketRegime enum)
- Kategori bias additive (multiplicative değil)
- "segment + lookback context" pattern (financial_engine slice-friendly çağrılır)
"""

# =============================================================================
# INTERVAL CONVENTION
# =============================================================================
# All intervals in this module are HALF-OPEN:
#
#     [start_index, end_index)
#
# Rules:
# - end_index is EXCLUSIVE
# - length = end_index - start_index
# - touching endpoints are NOT overlap
# - [10, 20) and [20, 30) are disjoint
# - [10, 20) and [19, 30) overlap by 1 unit ([19, 20))
#
# Pipeline contract — convention preserved through:
# scan_windows → LabeledWindow → ResolvedScenarioCandidate →
# FinalScenarioCandidate → ScenarioSegment
#
# DO NOT change to closed [start, end] semantics without auditing every
# interval operation in this module.
# =============================================================================

from __future__ import annotations

from datetime import date, datetime, timedelta
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, List, Optional, Tuple, Union
import logging
import pandas as pd
from pydantic import BaseModel, Field, ConfigDict

if TYPE_CHECKING:
    from motors.financial_engine import FinancialEngine

from models.scenario import (
    ScenarioBundle,
    ScenarioSegment,
    ScenarioType,
    AnomalyComponents,
)

_logger = logging.getLogger(__name__)


def _neutrality(fiyat: float, center: float = 0.55, width: float = 0.20) -> float:
    """
    Bir fiyat skorunun "nötr/yatay" karaktere ne kadar yakın olduğunu hesaplar.

    Accumulation ve consolidation kategorilerinde kullanılır — fiyat çok yüksek
    veya çok düşük olduğunda bu kategoriler anlamsızdır.

    Args:
        fiyat: AnomalyComponents.fiyat değeri (0.0-1.0)
        center: Nötr merkez (default 0.55 — hafif pozitif drift varsayımı,
                accumulation karakterine uygun)
        width: Sıfıra düşme genişliği (default 0.20)

    Returns:
        center'da 1.0, center ± width'te 0.0, dışında 0.0

    Example:
        _neutrality(0.55) → 1.0
        _neutrality(0.65) → 0.5
        _neutrality(0.35) → 0.0 (clamp)
        _neutrality(0.75) → 0.0 (clamp)
    """
    result = max(0.0, 1.0 - abs(fiyat - center) / width)
    # Floating point epsilon clamp — IEEE 754 kayan nokta hatalarını 0'a indir.
    # abs() ile iki yönlü koruma: defensive programming.
    # 1e-9 eşiği gerçek küçük değerleri (örn. 0.001) etkilemez, sadece
    # matematiksel olarak 0 olması gereken epsilon artıklarını temizler.
    if abs(result) < 1e-9:
        return 0.0
    return result


# ============================================================
# DISPLAY HELPERS — locale-independent, UI-safe
# ============================================================

DateLike = Union[str, "date", "datetime", "pd.Timestamp"]


def _to_iso_date(value: "DateLike | None") -> str:
    """
    Bir değeri ISO 8601 tarih formatına (YYYY-MM-DD) çevirir.

    Locale-independent, deterministic. Pipeline boyunca tarih
    string'lerinin tek formatta olmasını garanti eder.

    Kabul edilen tipler:
    - pandas.Timestamp → isoformat()[:10]
    - datetime.date / datetime.datetime → isoformat()[:10]
    - str (zaten ISO formatlı) → ilk 10 karakter (ISO 8601 varsayımı)
    - None / NaN / boş → ""

    String fallback notu:
        İlk 10 karakter ISO 8601 varsayar. Non-ISO format ("15/08/2024"
        gibi) sessiz truncation yapar. Şu an pipeline pandas Timestamp
        üretiyor, problem değil. External source bağlanırsa Etap 2'de
        ISO regex validation düşünülmeli.
    """
    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass

    if hasattr(value, "isoformat"):
        iso_str = value.isoformat()
        return iso_str[:10]

    if isinstance(value, str):
        return value[:10]

    return ""


def _to_display_percent(value: float) -> int:
    """
    [0.0, 1.0] aralığındaki değeri [0, 100] integer yüzdeye çevirir.
    Defensive clamp ile sınır taşmaları engellenir.

    Pydantic Field(ge=0, le=1) zaten model seviyesinde clamp uyguluyor.
    Bu helper UI display sırasında ek defensive depth sağlar.
    """
    return min(100, max(0, round(value * 100)))


# ============================================================
# MARKET REGIME
# ============================================================

class MarketRegime(str, Enum):
    """
    Hissenin classifier penceresinde bulunduğu rejim.

    NORMAL: Yeterli geçmiş veri var, baseline stabil, normal classification.
    IPO_DISCOVERY: IPO sonrası ilk N gün (config'ten okunur), fiyat keşfi var,
                   baseline yok, classifier düşük confidence ile çalışır.
    INSUFFICIENT_CONTEXT: Hisse yeni eklenmiş ya da veri eksik, lookback yetersiz,
                         confidence context_ratio ile decay edilir.
    """
    NORMAL = "normal"
    IPO_DISCOVERY = "ipo_discovery"
    INSUFFICIENT_CONTEXT = "insufficient_context"


# ============================================================
# SCENARIO THRESHOLD MODELLERİ
# ============================================================

class BaseScenarioThresholds(BaseModel):
    """
    Tüm scenario threshold modelleri için ortak base.

    İleride ortak alanlar (priority_override, confidence_weight, vb.) buraya
    eklenebilir. Şu an sadece frozen config ortaklığı sağlıyor.
    """
    model_config = ConfigDict(frozen=True)


class ManipulationThresholds(BaseScenarioThresholds):
    """
    Manipulation: abnormal coordinated instability.

    "Üç boyut birden aşırı" şartı: pump benzerliği, hacim patlaması,
    volatilite yükselişi aynı segment'te birleşmiş + fiyat yön belirgin.

    SPK uyumu için en konservatif kategori — false positive > false negative tercih.
    PROVISIONAL — Etap 1.4 kalibrasyonuyla güncellenecek.
    """
    pump_min: float = Field(default=0.85, ge=0.0, le=1.0)
    hacim_min: float = Field(default=0.75, ge=0.0, le=1.0)
    volatilite_min: float = Field(default=0.70, ge=0.0, le=1.0)
    fiyat_min: float = Field(default=0.65, ge=0.0, le=1.0)


class PumpThresholds(BaseScenarioThresholds):
    """
    Pump: klasik pump-and-dump'ın yükseliş fazı.

    Pump benzerliği yüksek + fiyat hareketi yüksek + (genelde) hacim destekli.
    Manipulation'dan farkı: üçü birden "aşırı" değil, ikisi belirgin.
    PROVISIONAL — Etap 1.4 kalibrasyonuyla güncellenecek.
    """
    pump_min: float = Field(default=0.60, ge=0.0, le=1.0)
    fiyat_min: float = Field(default=0.55, ge=0.0, le=1.0)
    hacim_min: float = Field(default=0.50, ge=0.0, le=1.0)
    volatilite_min_floor: float = Field(
        default=0.40, ge=0.0, le=1.0,
        description="Bu değerin altındaysa pump değil (sade trend olabilir)",
    )


class DistributionThresholds(BaseScenarioThresholds):
    """
    Distribution: dağıtım fazı — yüksek hacim, zayıflayan fiyat.
    Smart money çıkıyor, perakende alıyor.
    PROVISIONAL — Etap 1.4 kalibrasyonuyla güncellenecek.
    """
    hacim_min: float = Field(default=0.60, ge=0.0, le=1.0)
    fiyat_max: float = Field(default=0.30, ge=0.0, le=1.0)
    volatilite_min: float = Field(default=0.40, ge=0.0, le=1.0)
    pump_max: float = Field(
        default=0.40, ge=0.0, le=1.0,
        description="Pump-benzerliği yüksekse distribution değil, manipulation tarafına eğilim",
    )


class AccumulationThresholds(BaseScenarioThresholds):
    """
    Accumulation: birikim fazı — sessiz, kontrollü, hafif pozitif drift.
    Smart money giriyor.
    PROVISIONAL — Etap 1.4 kalibrasyonuyla güncellenecek.
    """
    fiyat_min: float = Field(default=0.45, ge=0.0, le=1.0)
    fiyat_max: float = Field(default=0.65, ge=0.0, le=1.0)
    hacim_min: float = Field(default=0.45, ge=0.0, le=1.0)
    volatilite_max: float = Field(default=0.35, ge=0.0, le=1.0)
    pump_max: float = Field(default=0.30, ge=0.0, le=1.0)
    neutrality_center: float = Field(default=0.55, ge=0.0, le=1.0)
    neutrality_width: float = Field(default=0.20, gt=0.0, le=1.0)


class BreakoutThresholds(BaseScenarioThresholds):
    """
    Breakout: sağlıklı yukarı kırılım — fiyat agresif yukarı, hacim destekli,
    pump-benzerliği DÜŞÜK (manipülatif değil).
    PROVISIONAL — Etap 1.4 kalibrasyonuyla güncellenecek.
    """
    fiyat_min: float = Field(default=0.65, ge=0.0, le=1.0)
    hacim_min: float = Field(default=0.40, ge=0.0, le=1.0)
    volatilite_min: float = Field(default=0.45, ge=0.0, le=1.0)
    pump_max: float = Field(
        default=0.65, ge=0.0, le=1.0,
        description="Bu üzeri pump kategorisine kayar",
    )


class ConsolidationThresholds(BaseScenarioThresholds):
    """
    Consolidation: sakin yatay seyir — düşük volatilite, orta hacim, yön belirsiz.

    Dead zone (hacim < dead_zone_max) HARİÇ — ölü hisseler etiketsiz kalır.
    PROVISIONAL — Etap 1.4 kalibrasyonuyla güncellenecek.
    """
    volatilite_max: float = Field(default=0.30, ge=0.0, le=1.0)
    hacim_min: float = Field(default=0.30, ge=0.0, le=1.0)
    hacim_max: float = Field(default=0.55, ge=0.0, le=1.0)
    fiyat_min: float = Field(default=0.35, ge=0.0, le=1.0)
    fiyat_max: float = Field(default=0.65, ge=0.0, le=1.0)
    dead_zone_max: float = Field(
        default=0.20, ge=0.0, le=1.0,
        description="Hacim bu değerin altındaysa hisse dead zone'da — consolidation değil, etiketsiz kalır",
    )
    neutrality_center: float = Field(default=0.50, ge=0.0, le=1.0)
    neutrality_width: float = Field(default=0.25, gt=0.0, le=1.0)


class RuleThresholds(BaseModel):
    """
    Tüm scenario threshold modellerinin aggregate'i.

    ClassifierConfig içine eklenir. İleride system_config/scenario_classifier_rules
    Firestore dökümanından okunabilir (Etap 1.2b-3'te entegrasyon).
    """
    model_config = ConfigDict(frozen=True)

    manipulation: ManipulationThresholds = Field(default_factory=ManipulationThresholds)
    pump: PumpThresholds = Field(default_factory=PumpThresholds)
    distribution: DistributionThresholds = Field(default_factory=DistributionThresholds)
    accumulation: AccumulationThresholds = Field(default_factory=AccumulationThresholds)
    breakout: BreakoutThresholds = Field(default_factory=BreakoutThresholds)
    consolidation: ConsolidationThresholds = Field(default_factory=ConsolidationThresholds)


# ============================================================
# CONFIG MODELI
# ============================================================

class ClassifierConfig(BaseModel):
    """
    Classifier'ın çalışma parametreleri. system_config/scenario_classifier
    dökümanından okunur. Default değerler PROVISIONAL — kalibrasyon adımıyla
    güncellenecek.
    """
    model_config = ConfigDict(frozen=True)

    # Sliding window boyutları (gün cinsinden). SMRVA gibi uzun pump'lar için 120 dahil.
    window_sizes: List[int] = Field(default_factory=lambda: [5, 15, 30, 60, 120])

    # IPO discovery rejimi süresi (gün).
    ipo_discovery_days: int = Field(default=30, ge=0)

    # IPO_DISCOVERY rejiminde segment confidence çarpanı (0.0-1.0).
    ipo_confidence_factor: float = Field(default=0.5, ge=0.0, le=1.0)

    # Kategori additive bias değerleri — PROVISIONAL, kalibrasyon ile güncellenecek.
    kategori_bias_aktif_pd: float = Field(default=0.15, ge=-1.0, le=1.0)
    kategori_bias_yeni_pd: float = Field(default=0.08, ge=-1.0, le=1.0)
    kategori_bias_gecmis_pd: float = Field(default=0.04, ge=-1.0, le=1.0)
    kategori_bias_temiz: float = Field(default=0.00, ge=-1.0, le=1.0)

    # Statistical baseline uzunluğu (rolling, financial_engine ile uyumlu).
    rolling_baseline_days: int = Field(
        default=1250, ge=100, le=5000,
        description=(
            "Z-score baseline için iş günü sayısı (5 takvim yılı ≈ "
            "1250 iş günü). 2021-01-01 milatından itibaren beklenen "
            "veri uzunluğuyla uyumlu."
        ),
    )

    # Lookback buffer (rolling_baseline'a eklenecek ek context).
    lookback_buffer_days: int = Field(default=10, ge=0)

    classifier_version: str = Field(default="0.2.0-rule-based")

    # Senaryo etiketleme kural eşikleri — PROVISIONAL, Etap 1.4'te kalibre edilecek
    rule_thresholds: RuleThresholds = Field(default_factory=RuleThresholds)

    # Structural engine confidence filtresi — bu altı eler (recall odaklı, düşük tutulur).
    structural_confidence_min: float = Field(
        default=0.30, ge=0.0, le=1.0,
        description="Structural engine threshold — bu altı eler. Düşük tutulur (recall odaklı).",
    )

    # Final UI confidence filtresi — bu altı kullanıcıya gösterilmez (precision odaklı).
    final_confidence_min: float = Field(
        default=0.55, ge=0.0, le=1.0,
        description="Final UI threshold — bu altı kullanıcıya gösterilmez. Yüksek tutulur (precision odaklı).",
    )

    # Split kalıntısı minimum gün sayısı — bu altına düşen parçalar discard edilir.
    minimum_segment_length: int = Field(
        default=3, ge=1,
        description="Split sonucu bu uzunluğun altına düşen parçalar discard edilir.",
    )

    # Aynı tip/priority segmentlerde merge tetikleme minimum overlap oranı.
    overlap_ratio_threshold: float = Field(
        default=0.25, ge=0.0, le=1.0,
        description="Aynı tip + priority segmentlerde merge için minimum overlap oranı.",
    )


# ============================================================
# CONTEXT BUNDLE — classifier'ın elindeki tüm girdi paketi
# ============================================================

class ClassifierContext(BaseModel):
    """
    Bir classify() çağrısı için gerekli tüm girdi paketi.
    OHLCV DataFrame'i Pydantic'e koyamayacağımız için pass-by-reference olarak
    ScenarioClassifier.classify() method'una ayrı geçilir, bu sadece metadata.
    """
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    ticker: str
    kategori: str  # TEMIZ / GECMIS_PD / YENI_PD / AKTIF_PD
    ipo_date: Optional[date]
    current_date: date
    regime: MarketRegime
    available_history_days: int
    required_lookback_days: int


# ============================================================
# WINDOW SCAN UNIT — bir sliding window kayıtı (henüz etiketlenmemiş)
# ============================================================

class WindowScan(BaseModel):
    """
    Bir sliding window'un ham verisi — henüz scenario etiketi atanmamış.
    Etap 1.2b'deki labeler bu WindowScan'leri ScenarioSegment'e dönüştürür.
    """
    model_config = ConfigDict(frozen=True)

    start_index: int = Field(..., ge=0)
    end_index: int = Field(..., ge=0)
    start_date: str   # ISO YYYY-MM-DD
    end_date: str
    window_size: int = Field(..., ge=1)
    # Relative metrics — XU100 ve sektör baseline'a göre normalize edilmiş alt skorlar
    relative_subscores: AnomalyComponents


# ============================================================
# LABELED WINDOW — labeling sonrası ara form
# ============================================================

class LabeledWindow(BaseModel):
    """
    Bir WindowScan'in rule-based labeler tarafından etiketlenmiş hali.

    Henüz ScenarioSegment değil — conflict resolution + finalize aşaması geçilmedi.
    Etap 1.2b-3'te conflict resolver bunları ScenarioSegment'e dönüştürecek.
    """
    model_config = ConfigDict(frozen=True)

    scan: WindowScan
    scenario_type: ScenarioType
    base_confidence: float = Field(
        ..., ge=0.0, le=1.0,
        description="Henüz kategori bias ve IPO decay uygulanmamış ham confidence",
    )


# ============================================================
# RESOLVED SCENARIO CANDIDATE — conflict resolution çıktısı
# ============================================================

class ResolvedScenarioCandidate(BaseModel):
    """
    Conflict resolution çıktısı — henüz final ScenarioSegment değil.

    Title/description template ve kategori bias Etap 1.2b-3b/3c'de uygulanacak.
    Tarihler PROVISIONAL: split operasyonlarında indeks→tarih dönüşümü için ohlcv_df
    erişimi Etap 1.2b-3c pipeline'ında eklenecek; şu an original tarihler taşınır.
    """
    model_config = ConfigDict(frozen=True)

    scenario_type: ScenarioType
    start_index: int = Field(..., ge=0)
    end_index: int = Field(..., ge=0)
    start_date: str   # ISO YYYY-MM-DD
    end_date: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    subscores: AnomalyComponents


# ============================================================
# FINAL SCENARIO CANDIDATE — confidence post-processing çıktısı
# ============================================================

class FinalScenarioCandidate(BaseModel):
    """
    Confidence post-processing sonrası, Etap 1.2b-3c presentation
    aşamasına geçecek model.

    ResolvedScenarioCandidate'tan farkları:
    - confidence → final_confidence (bias + decay uygulanmış)
    - base_confidence eklendi (audit: bias/decay öncesi orijinal)
    - applied_kategori_bias eklendi (audit: ne kadar bias eklendi)
    - applied_context_decay eklendi (audit: ne kadar decay uygulandı)

    Yapısal alanlar (start_index, end_index, dates, scenario_type,
    subscores) DEĞİŞMEDEN taşınır.

    PIPELINE CONTRACT:
    - Final filter (final_confidence < final_confidence_min) UYGULANMIŞ —
      bu modelde sadece geçenler bulunur
    - subscores aynen taşınır (rescaling DEĞİL)
    - geometry aynen taşınır (split/merge yok)
    """
    model_config = ConfigDict(frozen=True)

    scenario_type: ScenarioType
    start_index: int = Field(..., ge=0)
    end_index: int = Field(..., ge=0)
    start_date: str
    end_date: str

    # Confidence — post-processing sonrası nihai değer
    final_confidence: float = Field(
        ..., ge=0.0, le=1.0,
        description="Bias + decay uygulanmış, [0,1] clamp'li nihai confidence",
    )

    # Audit trail — explainability için
    base_confidence: float = Field(
        ..., ge=0.0, le=1.0,
        description="Bias/decay öncesi structural pipeline confidence",
    )
    applied_kategori_bias: float = Field(
        default=0.0,
        description="Eklenen kategori bias miktarı (additive, [-1,1] aralığında)",
    )
    applied_context_decay: float = Field(
        default=1.0, ge=0.0, le=1.0,
        description="Uygulanan context_ratio decay çarpanı (IPO veya INSUFFICIENT_CONTEXT için)",
    )

    # Subscores aynen taşınır
    subscores: AnomalyComponents


# ============================================================
# SCENARIO PRIORITY LOOKUP — conflict resolution için
# ============================================================

_SCENARIO_PRIORITY: dict[ScenarioType, int] = {
    ScenarioType.MANIPULATION: 6,
    ScenarioType.PUMP: 5,
    ScenarioType.DISTRIBUTION: 4,
    ScenarioType.BREAKOUT: 3,
    ScenarioType.ACCUMULATION: 2,
    ScenarioType.CONSOLIDATION: 1,
}


def _priority_of(scenario_type: ScenarioType) -> int:
    """ScenarioType için priority integer döner. Bilinmeyen tipler 0 alır."""
    return _SCENARIO_PRIORITY.get(scenario_type, 0)


# ============================================================
# PRESENTATION LAYER — template sabitler ve registry
# ============================================================

# Süre kategorisi eşikleri (gün cinsinden, half-open semantik)
# Sınır davranışı:
#   <7 gün         → "short"
#   7-29 gün       → "medium"
#   ≥30 gün        → "long"
# NOT: 30 günlük segment "long" kategorisine düşer — bu kasıtlı,
# 1 aylık+ süre kullanıcıya "uzun dönem" olarak gösterilir.
_DURATION_SHORT_MAX = 7    # segment_length < 7 → "short"
_DURATION_MEDIUM_MAX = 30  # 7 ≤ segment_length < 30 → "medium"; ≥30 → "long"

# _find_dominant_signal için deterministik tie-break sırası.
# Eşit subscore değerine sahip alanlar arasında düşük priority kazanır.
# Sıra: fiyat → hacim → volatilite → pump
_FIELD_PRIORITY: dict[str, int] = {
    "fiyat": 0,
    "hacim": 1,
    "volatilite": 2,
    "pump": 3,
}


@dataclass(frozen=True)
class TemplateVariants:
    """Bir scenario_type için süre kategorilerine göre title varyantları."""
    short: str   # <7 gün
    medium: str  # 7-29 gün
    long: str    # ≥30 gün


@dataclass(frozen=True)
class DominantSignalLabels:
    """Subscores alanlarına göre dominant signal etiketleri."""
    fiyat: str
    hacim: str
    volatilite: str
    pump: str


# =============================================================================
# TEMPLATE REGISTRY
# =============================================================================
# Tüm title varyantları ve dominant signal etiketleri burada.
# DİL POLİTİKASI: "Tespit", "Kesin", "Doğrulandı", "Pump-Dump", "Spekülatif"
# YASAK. Yumuşak terimler: "Şüphesi", "Riski", "Anomali", "Karakter",
# "Sinyali", "Ani Yükseliş".
#
# UI/Hukuki kontrat: Bu registry'deki string'ler doğrudan kullanıcıya gösterilir.
# Değişiklik yapılırken DİL POLİTİKASI yeniden kontrol edilmeli.
# =============================================================================

_TEMPLATE_REGISTRY: dict[ScenarioType, tuple[TemplateVariants, DominantSignalLabels]] = {
    ScenarioType.MANIPULATION: (
        TemplateVariants(
            short="Kısa Süreli Manipülasyon Şüphesi",
            medium="Manipülasyon Şüphesi",
            long="Uzun Dönem Manipülatif Hareket Şüphesi",
        ),
        DominantSignalLabels(
            fiyat="Fiyat Aşırılığıyla",
            hacim="Aşırı Hacimle",
            volatilite="Düzensiz Hareketle",
            pump="Ani Yükseliş Karakterinde",  # "Pump-Dump" YASAK — SPK terminolojisi
        ),
    ),
    ScenarioType.PUMP: (
        TemplateVariants(
            short="Ani Pump Hareketi",
            medium="Pump Fazı Şüphesi",
            long="Uzun Dönem Pump Karakteri",
        ),
        DominantSignalLabels(
            fiyat="Fiyat Yükselişiyle",
            hacim="Hacim Patlamasıyla",
            volatilite="Yüksek Volatiliteyle",
            pump="Ani Yükseliş Sinyaliyle",
        ),
    ),
    ScenarioType.DISTRIBUTION: (
        TemplateVariants(
            short="Hızlı Dağıtım Şüphesi",
            medium="Dağıtım Fazı Şüphesi",
            long="Uzun Dönem Dağıtım Hareketi",
        ),
        DominantSignalLabels(
            fiyat="Fiyat Düşüşüyle",
            hacim="Yüksek Hacimle",
            volatilite="Volatil Seyirle",
            pump="Dağıtım Sinyaliyle",
        ),
    ),
    ScenarioType.ACCUMULATION: (
        TemplateVariants(
            short="Kısa Birikim Sinyali",
            medium="Birikim Fazı",
            long="Uzun Dönem Birikim",
        ),
        DominantSignalLabels(
            fiyat="Yatay Fiyatla",
            hacim="Artan Hacimle",
            volatilite="Sakin Seyirle",
            pump="Birikim Sinyaliyle",  # defensive fallback — accumulation'da
                                        # pump dominant beklenmez ama defensive
                                        # olarak korunur
        ),
    ),
    ScenarioType.BREAKOUT: (
        TemplateVariants(
            short="Ani Yukarı Kırılım",
            medium="Yukarı Kırılım Hareketi",
            long="Uzun Dönem Yukarı Trend",
        ),
        DominantSignalLabels(
            fiyat="Güçlü Yükselişle",
            hacim="Hacim Desteğiyle",
            volatilite="Volatilite Genişlemesiyle",
            pump="Kırılım Sinyaliyle",  # defensive fallback — breakout'ta
                                        # pump dominant beklenmez ama defensive
                                        # olarak korunur
        ),
    ),
    ScenarioType.CONSOLIDATION: (
        TemplateVariants(
            short="Kısa Yatay Seyir",
            medium="Yatay Konsolidasyon",
            long="Uzun Dönem Sıkışık Bant",
        ),
        DominantSignalLabels(
            fiyat="Yatay Fiyatla",
            hacim="Dengeli Hacimle",
            volatilite="Düşük Volatiliteyle",
            pump="Sakin Seyirle",  # defensive fallback — consolidation'da
                                   # pump dominant beklenmez ama defensive
                                   # olarak korunur
        ),
    ),
    ScenarioType.IPO_PERIOD: (
        TemplateVariants(
            short="İlk Halka Arz",
            medium="İlk Halka Arz Dönemi",
            long="Hisse halka arz sonrası ilk dönemde — yeterli "
                 "geçmiş veri bulunmadığından istatistiksel anomali "
                 "analizi uygulanamadı.",
        ),
        DominantSignalLabels(
            fiyat="ipo_donemi",
            hacim="ipo_donemi",
            volatilite="ipo_donemi",
            pump="ipo_donemi",
        ),
    ),
}


# ============================================================
# CLASSIFIER ANA SINIFI
# ============================================================

class ScenarioClassifier:
    """
    Scenario classifier ana sınıfı.

    Etap 1.2a — bu sürüm: config loading, regime detection, window scanning.
    Etap 1.2b — gelecek sürüm: rule-based labeling, conflict resolution, templates.
    """

    def __init__(
        self,
        config: ClassifierConfig,
        financial_engine: "FinancialEngine",
    ):
        """
        Args:
            config: ClassifierConfig
            financial_engine: Slice-friendly subscore hesaplaması için FinancialEngine
                             instance. Etap 1.2.5'te eklenen refactor'la birlikte
                             _pump_benzerlik_skoru(lookback=), _hacim_patlamasi_skoru,
                             _volatilite_skoru, _fiyat_anomali_skoru fonksiyonları
                             segment-level çağrılarla kullanılır.
        """
        self._config = config
        self._engine = financial_engine

    @classmethod
    def from_firestore_config(
        cls,
        config_doc: dict | None,
        financial_engine: "FinancialEngine",
    ) -> "ScenarioClassifier":
        """
        system_config/scenario_classifier dökümanından config yükler.
        Döküman yoksa default ClassifierConfig kullanılır.
        """
        if not config_doc:
            return cls(ClassifierConfig(), financial_engine)
        return cls(ClassifierConfig(**config_doc), financial_engine)

    # --------------------------------------------------------
    # REGIME DETECTION
    # --------------------------------------------------------

    def detect_market_regime(
        self,
        ipo_date: Optional[date],
        current_date: date,
        available_history_days: int,
        required_lookback_days: int,
    ) -> MarketRegime:
        """
        Hissenin classifier penceresinde bulunduğu rejimi belirler.

        Sıralama (öncelik):
        1. IPO_DISCOVERY → ipo_date varsa ve current_date - ipo_date <= config.ipo_discovery_days
        2. INSUFFICIENT_CONTEXT → available_history < required_lookback
        3. NORMAL
        """
        if ipo_date is not None:
            days_since_ipo = (current_date - ipo_date).days
            if days_since_ipo <= self._config.ipo_discovery_days:
                return MarketRegime.IPO_DISCOVERY

        if available_history_days < required_lookback_days:
            return MarketRegime.INSUFFICIENT_CONTEXT

        return MarketRegime.NORMAL

    # --------------------------------------------------------
    # LOOKBACK HESABI
    # --------------------------------------------------------

    def compute_required_lookback(self) -> int:
        """
        Dinamik lookback: rolling_baseline + buffer.
        financial_engine'in en uzun rolling window'una göre boyutlanır.
        """
        return self._config.rolling_baseline_days + self._config.lookback_buffer_days

    # --------------------------------------------------------
    # WINDOW SCANNING
    # --------------------------------------------------------

    def scan_windows(
        self,
        ohlcv_df: pd.DataFrame,
        xu100_series: pd.Series,
        sector_baseline_df: Optional[pd.DataFrame],
        context: ClassifierContext,
    ) -> List[WindowScan]:
        """
        OHLCV serisi üzerinde config-driven sliding window taraması yapar.
        Her window için "segment + lookback context" pattern ile subscore üretir.

        Pattern:
            Her window [start_idx, end_idx] için:
              1. context_df = ohlcv_df[start_idx - lookback : end_idx]
              2. segment_df = ohlcv_df[start_idx : end_idx]
              3. Subscore: _compute_window_subscores ile hesaplanır
              4. WindowScan listesine eklenir

        Args:
            ohlcv_df: OHLCV DataFrame. Index DatetimeIndex veya integer, columns
                      en az: ["Close", "Volume"] (büyük harf, financial_engine uyumlu)
            xu100_series: pd.Series — DatetimeIndex, values=günlük getiriler (pct_change).
                          engine.xu100_returns ile eşdeğer.
            sector_baseline_df: Şimdilik None geçilecek (Etap 1.2b-3'te kullanılacak).
            context: ClassifierContext

        Returns:
            WindowScan listesi, kronolojik sıralı (start_index, window_size).
        """
        if context.regime == MarketRegime.IPO_DISCOVERY:
            # ⚠️ GEÇİCİ DAVRANIŞ — Etap 1.2b-1 kapsamında IPO rejiminde boş liste dönüyoruz.
            # KALICI ÇÖZÜM Etap 1.2b-3'te eklenecek:
            #   - IPO rejiminde de scan yapılacak
            #   - Üretilen segmentlere düşük confidence (config.ipo_confidence_factor) uygulanacak
            #   - context_ratio decay ile birleştirilecek
            # Etap 1.2b-3'e geçildiğinde bu erken-return kaldırılacak.
            return []

        scans: List[WindowScan] = []
        total_days = len(ohlcv_df)
        lookback = context.required_lookback_days
        # Etap 2.0 — sliding window tüm tarihsel veriyi tarar.
        # context_df adaptif: erken window'larda küçük, geç window'larda
        # tam lookback kadar büyür. Confidence decay _compute_context_decay
        # üzerinden context.available_history / required_lookback ile uygulanır.
        _MIN_CONTEXT = 60

        for window_size in self._config.window_sizes:
            step = max(1, window_size // 2)
            start_idx = _MIN_CONTEXT

            while start_idx + window_size <= total_days:
                end_idx = start_idx + window_size

                context_start = max(0, start_idx - lookback)
                context_df = ohlcv_df.iloc[context_start:end_idx]

                if len(context_df) < _MIN_CONTEXT:
                    start_idx += step
                    continue

                segment_df = ohlcv_df.iloc[start_idx:end_idx]

                subscores = self._compute_window_subscores(
                    context_df=context_df,
                    segment_df=segment_df,
                    xu100_series=xu100_series,
                    sector_baseline_df=sector_baseline_df,
                )

                if isinstance(segment_df.index, pd.DatetimeIndex):
                    start_date = _to_iso_date(segment_df.index[0])
                    end_date = _to_iso_date(segment_df.index[-1])
                elif "Date" in segment_df.columns:
                    start_date = _to_iso_date(segment_df["Date"].iloc[0])
                    end_date = _to_iso_date(segment_df["Date"].iloc[-1])
                else:
                    start_date = ""
                    end_date = ""

                scans.append(WindowScan(
                    start_index=start_idx,
                    end_index=end_idx,
                    start_date=start_date,
                    end_date=end_date,
                    window_size=window_size,
                    relative_subscores=subscores,
                ))

                start_idx += step

        scans.sort(key=lambda s: (s.start_index, s.window_size))
        return scans

    # --------------------------------------------------------
    # SUBSCORE HESAPLAMA
    # --------------------------------------------------------

    def _compute_window_subscores(
        self,
        context_df: pd.DataFrame,
        segment_df: pd.DataFrame,
        xu100_series: pd.Series,
        sector_baseline_df: Optional[pd.DataFrame],
    ) -> AnomalyComponents:
        """
        Bir window için fiyat/hacim/volatilite/pump alt skorları hesaplar.

        Strateji ("segment + lookback context"):
        - _spek_gunleri_tespit context_df üzerinde gerçek çalıştırılır
        - _fiyat_anomali_skoru: segment_df + spek array'inin son segment_len günü
        - _hacim/_volatilite: context_df + tam spek array (son-N mantığı uyumlu)
        - _pump: context_df üzerinde segment_len lookback

        Returns:
            AnomalyComponents (fiyat, hacim, volatilite, pump — hepsi 0.0-1.0)
        """
        # XU100 cache'ini güncelle — _spek_gunleri_tespit iç olarak kullanır
        self._engine._xu100_yukle()

        segment_len = len(segment_df)

        # spek_hard ve spek_extreme context_df üzerinde gerçek hesaplanır
        _, spek_hard, spek_extreme = self._engine._spek_gunleri_tespit(context_df, None)

        # 1. FİYAT — segment_df üzerinde, spek array son segment_len güne slice edilir
        fiyat_raw, _ = self._engine._fiyat_anomali_skoru(
            segment_df,
            spek_hard[-segment_len:],
            spek_extreme[-segment_len:],
        )
        fiyat_relative = self._normalize_against_xu100(
            score=fiyat_raw,
            segment_df=segment_df,
            xu100_series=xu100_series,
        )

        # 2. HACİM — context içinde son segment_len günü baseline 50g'ye karşı
        hacim_raw, _ = self._engine._hacim_patlamasi_skoru(
            context_df,
            spek_hard,
            baseline_window=50,
            recent_window=segment_len,
            baseline_offset=segment_len,
        )

        # 3. VOLATİLİTE — pencere boyutları segment uzunluğuna göre ayarlanır
        volatilite_raw, _ = self._engine._volatilite_skoru(
            context_df,
            spek_hard,
            long_window=max(60, segment_len * 2),
            mid_window=max(20, segment_len),
            short_window=max(10, segment_len // 2),
        )

        # 4. PUMP — segment uzunluğu lookback olarak
        pump_raw, _ = self._engine._pump_benzerlik_skoru(
            context_df,
            lookback=segment_len,
        )

        # financial_engine._*_skoru metodları [0.0, 10.0] ham aralığında döner.
        # /10.0 ile [0.0, 1.0] aralığına normalize et, defansif clamp ile taşmaları yakala.
        # fiyat_relative de _normalize_against_xu100'den ham aralıkta çıkar (score * factor).
        RAW_SCORE_MAX = 10.0  # financial_engine clip aralığı

        return AnomalyComponents(
            fiyat=float(min(1.0, max(0.0, fiyat_relative / RAW_SCORE_MAX))),
            hacim=float(min(1.0, max(0.0, hacim_raw / RAW_SCORE_MAX))),
            volatilite=float(min(1.0, max(0.0, volatilite_raw / RAW_SCORE_MAX))),
            pump=float(min(1.0, max(0.0, pump_raw / RAW_SCORE_MAX))),
        )

    # --------------------------------------------------------
    # XU100 RELATIVE NORMALIZE
    # --------------------------------------------------------

    def _normalize_against_xu100(
        self,
        score: float,
        segment_df: pd.DataFrame,
        xu100_series: pd.Series,
    ) -> float:
        """
        Bir segment skorunu XU100'ün aynı dönemdeki hareketine göre normalize eder.
        Marketwide rally'lerde false positive üretmemek için.

        Mantık:
        - Segment için geometrik getiri hesaplanır (Close pct_change kümülatif çarpımı)
        - XU100 için aynı tarih aralığındaki geometrik getiri hesaplanır
        - XU100 ne kadar açıklıyorsa skor o kadar azaltılır
        - LOWER BOUND: relative_factor en az 0.2, yani skor tamamen sıfırlanmaz
          (bireysel anomali sinyallerini korumak için)

        Anormal durumlarda (eksik veri, sıfıra bölme, tarih bulunamama) skor
        değişmeden döner — defensive try/except XU100 verisi yapısal belirsizliği için.
        """
        # PROVISIONAL — Etap 1.4 kalibrasyon adımında gerçek veriyle ayarlanacak
        RELATIVE_FACTOR_FLOOR = 0.2

        try:
            if len(segment_df) < 2 or xu100_series.empty:
                return score

            if "Close" not in segment_df.columns:
                return score

            # Segment tarih aralığını belirle
            if isinstance(segment_df.index, pd.DatetimeIndex):
                seg_start_date = segment_df.index[0]
                seg_end_date = segment_df.index[-1]
            elif "Date" in segment_df.columns:
                seg_start_date = segment_df["Date"].iloc[0]
                seg_end_date = segment_df["Date"].iloc[-1]
            else:
                return score

            # Segment geometrik getirisi
            seg_close_returns = segment_df["Close"].pct_change().dropna()
            if len(seg_close_returns) < 1:
                return score
            seg_period_return = float((1 + seg_close_returns).prod() - 1)

            if abs(seg_period_return) < 1e-6:
                return score

            # XU100'ün aynı dönemdeki geometrik getirisi
            seg_xu100 = xu100_series.loc[seg_start_date:seg_end_date].dropna()
            if len(seg_xu100) < 2:
                return score
            xu_period_return = float((1 + seg_xu100).prod() - 1)

            explained_ratio = max(0.0, min(1.0, xu_period_return / seg_period_return))
            relative_factor = max(RELATIVE_FACTOR_FLOOR, 1.0 - explained_ratio)

            return float(score * relative_factor)

        except Exception:
            # XU100 verisi yapısal belirsizliği — orijinal skoru koru
            return score

    # --------------------------------------------------------
    # CONFIDENCE FINALIZER
    # --------------------------------------------------------

    def _compute_kategori_bias(self, kategori: str) -> float:
        """
        Hissenin kategori (TEMIZ / GECMIS_PD / YENI_PD / AKTIF_PD)
        durumuna göre additive bias değerini döner.

        Bias değerleri ClassifierConfig'ten okunur:
        - AKTIF_PD: en yüksek bias (izleme listesinde aktif)
        - YENI_PD: orta-yüksek
        - GECMIS_PD: orta-düşük
        - TEMIZ: nötr (0.0)

        Bilinmeyen kategori için defansif: 0.0 (nötr)
        """
        config = self._config
        if kategori == "AKTIF_PD":
            return config.kategori_bias_aktif_pd
        elif kategori == "YENI_PD":
            return config.kategori_bias_yeni_pd
        elif kategori == "GECMIS_PD":
            return config.kategori_bias_gecmis_pd
        elif kategori == "TEMIZ":
            return config.kategori_bias_temiz
        else:
            return 0.0  # bilinmeyen kategori — defansif nötr

    def _compute_context_decay(self, context: ClassifierContext) -> float:
        """
        Hissenin market regime'ine göre confidence decay çarpanını döner.

        Regimes:
        - NORMAL: 1.0 (decay yok)
        - IPO_DISCOVERY: ipo_confidence_factor (config, default 0.5)
        - INSUFFICIENT_CONTEXT: context_ratio = available / required
          (continuous decay, sabit değil)

        Returns:
            [0.0, 1.0] aralığında çarpan
        """
        if context.regime == MarketRegime.NORMAL:
            return 1.0

        elif context.regime == MarketRegime.IPO_DISCOVERY:
            return self._config.ipo_confidence_factor

        elif context.regime == MarketRegime.INSUFFICIENT_CONTEXT:
            if context.required_lookback_days <= 0:
                return 1.0  # defansif — sıfıra bölünme yok
            raw_ratio = context.available_history_days / context.required_lookback_days
            # Sqrt decay — kısa veri için daha yumuşak (Etap 2.0 D-Y kararı)
            return float(min(1.0, max(0.0, raw_ratio ** 0.5)))

        else:
            return 1.0  # bilinmeyen regime — defansif, decay yok

    def _apply_post_processing(
        self,
        resolved_candidates: List[ResolvedScenarioCandidate],
        context: ClassifierContext,
    ) -> List[FinalScenarioCandidate]:
        """
        Confidence Finalizer ana method'u.

        Algoritma (her resolved candidate için):
          1. base_confidence = resolved.confidence (audit kayıt)
          2. kategori_bias  = _compute_kategori_bias(context.kategori)
          3. context_decay  = _compute_context_decay(context)
          4. final_confidence = (base_confidence + kategori_bias) * context_decay
             — additive bias ÖNCE, multiplicative decay SONRA
          5. clamp [0.0, 1.0]
          6. final_confidence_min altındaysa filter (listeden çıkar)

        Sıra:
          structural sıra korunur — resolved_candidates zaten deterministic
          sortlanmış; filter sonrası yeniden sıralama YAPILMAZ.

        PURE: Geometry, subscores, scenario_type DEĞİŞMEZ.
        """
        config = self._config

        # Döngü dışı sabit hesapla — her candidate için tekrar hesaplamaya gerek yok
        kategori_bias = self._compute_kategori_bias(context.kategori)
        context_decay = self._compute_context_decay(context)

        finalized: List[FinalScenarioCandidate] = []

        for cand in resolved_candidates:
            base_conf = cand.confidence

            # Adım 1-2: Additive bias + multiplicative decay
            final_conf = float(min(1.0, max(0.0, (base_conf + kategori_bias) * context_decay)))

            # Adım 3: Final threshold filter
            if final_conf < config.final_confidence_min:
                continue

            finalized.append(FinalScenarioCandidate(
                scenario_type=cand.scenario_type,
                start_index=cand.start_index,
                end_index=cand.end_index,
                start_date=cand.start_date,
                end_date=cand.end_date,
                final_confidence=final_conf,
                base_confidence=base_conf,
                applied_kategori_bias=kategori_bias,
                applied_context_decay=context_decay,
                subscores=cand.subscores,
            ))

        return finalized

    # --------------------------------------------------------
    # RULE-BASED LABELER
    # --------------------------------------------------------

    def _label_window(
        self,
        scan: WindowScan,
        context: ClassifierContext,
    ) -> Optional[LabeledWindow]:
        """
        Bir WindowScan'i rule-based olarak etiketler.

        Kurallar sırayla denenir (priority hierarchy — erken-return):
        1. manipulation (en şüpheli — konservatif)
        2. pump
        3. distribution
        4. breakout
        5. accumulation
        6. consolidation (default)

        Dead zone kontrolü: Eğer hacim < consolidation.dead_zone_max ise None döner
        (hisse ölü/inaktif, etiketsiz kalır).

        Returns:
            LabeledWindow veya None (dead zone / hiçbir kural tetiklenmediyse)
        """
        rules = self._config.rule_thresholds
        subs = scan.relative_subscores

        # DEAD ZONE KONTROLÜ — en başta
        if subs.hacim < rules.consolidation.dead_zone_max:
            return None

        # 1. MANIPULATION
        m = rules.manipulation
        if (subs.pump >= m.pump_min and
                subs.hacim >= m.hacim_min and
                subs.volatilite >= m.volatilite_min and
                subs.fiyat >= m.fiyat_min):
            confidence = min(subs.pump, subs.hacim, subs.volatilite)
            return LabeledWindow(
                scan=scan,
                scenario_type=ScenarioType.MANIPULATION,
                base_confidence=float(min(1.0, max(0.0, confidence))),
            )

        # 2. PUMP
        p = rules.pump
        if (subs.pump >= p.pump_min and
                subs.fiyat >= p.fiyat_min and
                subs.hacim >= p.hacim_min and
                subs.volatilite >= p.volatilite_min_floor):
            confidence = (subs.pump + subs.fiyat) / 2.0
            return LabeledWindow(
                scan=scan,
                scenario_type=ScenarioType.PUMP,
                base_confidence=float(min(1.0, max(0.0, confidence))),
            )

        # 3. DISTRIBUTION
        d = rules.distribution
        if (subs.hacim >= d.hacim_min and
                subs.fiyat <= d.fiyat_max and
                subs.volatilite >= d.volatilite_min and
                subs.pump <= d.pump_max):
            confidence = subs.hacim * (1.0 - subs.fiyat)
            return LabeledWindow(
                scan=scan,
                scenario_type=ScenarioType.DISTRIBUTION,
                base_confidence=float(min(1.0, max(0.0, confidence))),
            )

        # 4. BREAKOUT
        b = rules.breakout
        if (subs.fiyat >= b.fiyat_min and
                subs.hacim >= b.hacim_min and
                subs.volatilite >= b.volatilite_min and
                subs.pump <= b.pump_max):
            confidence = subs.fiyat * subs.hacim * (1.0 - subs.pump)
            return LabeledWindow(
                scan=scan,
                scenario_type=ScenarioType.BREAKOUT,
                base_confidence=float(min(1.0, max(0.0, confidence))),
            )

        # 5. ACCUMULATION
        a = rules.accumulation
        if (a.fiyat_min <= subs.fiyat <= a.fiyat_max and
                subs.hacim >= a.hacim_min and
                subs.volatilite <= a.volatilite_max and
                subs.pump <= a.pump_max):
            neut = _neutrality(
                subs.fiyat,
                center=a.neutrality_center,
                width=a.neutrality_width,
            )
            confidence = subs.hacim * (1.0 - subs.volatilite) * neut
            return LabeledWindow(
                scan=scan,
                scenario_type=ScenarioType.ACCUMULATION,
                base_confidence=float(min(1.0, max(0.0, confidence))),
            )

        # 6. CONSOLIDATION (default)
        c = rules.consolidation
        if (subs.volatilite <= c.volatilite_max and
                c.hacim_min <= subs.hacim <= c.hacim_max and
                c.fiyat_min <= subs.fiyat <= c.fiyat_max):
            neut = _neutrality(
                subs.fiyat,
                center=c.neutrality_center,
                width=c.neutrality_width,
            )
            confidence = (1.0 - subs.volatilite) * min(subs.hacim, neut)
            return LabeledWindow(
                scan=scan,
                scenario_type=ScenarioType.CONSOLIDATION,
                base_confidence=float(min(1.0, max(0.0, confidence))),
            )

        # Hiçbir kural tetiklenmediyse — etiketsiz
        return None

    # --------------------------------------------------------
    # CONFLICT RESOLUTION
    # --------------------------------------------------------

    def _resolve_conflicts(
        self,
        labeled_windows: List[Optional[LabeledWindow]],
        context: ClassifierContext,
    ) -> List[ResolvedScenarioCandidate]:
        """
        LabeledWindow listesini çakışma çözümünden geçirip ResolvedScenarioCandidate listesi üretir.

        Aşamalar:
          1. None ve structural_confidence_min altı elenir
          2. Aynı tip örtüşen pencereler merge edilir
          3. Farklı tip örtüşmeler priority hiyerarşisine göre çözülür

        STRUCTURAL PURE: context.kategori veya herhangi bir bias kullanılmaz —
        yalnızca geometrik operasyonlar ve priority değerleri.
        """
        valid: List[LabeledWindow] = [
            w for w in labeled_windows
            if w is not None and w.base_confidence >= self._config.structural_confidence_min
        ]

        if not valid:
            return []

        merged = self._merge_same_type_overlaps(valid, self._config.overlap_ratio_threshold)

        if not merged:
            return []

        resolved = self._resolve_cross_priority_overlaps(merged)

        # Deterministik final sıralama — pipeline çıktısının repeatability garantisi.
        # Tie-break sırası:
        # 1. start_index — kronolojik düzen
        # 2. -priority — yüksek priority önce (aynı başlangıçta)
        # 3. end_index — kısa segment önce (daha spesifik)
        # 4. scenario_type.value — refactor-safe lexical anchor
        # 5. -confidence — yüksek confidence son tie-break
        resolved.sort(key=lambda c: (
            c.start_index,
            -_priority_of(c.scenario_type),
            c.end_index,
            c.scenario_type.value,
            -c.confidence,
        ))
        return resolved

    def _merge_same_type_overlaps(
        self,
        windows: List[LabeledWindow],
        overlap_threshold: float,
    ) -> List[ResolvedScenarioCandidate]:
        """
        Aynı ScenarioType'taki örtüşen pencereleri cluster'lara ayırıp merge eder.

        Overlap oranı threshold'un üzerinde olan aynı-tip pencereler tek candidate'e merge edilir.
        BFS connected-component yaklaşımı kullanılır.

        Determinizm: type ve index sıralama `sorted()` ile yapılır.
        """
        groups: dict[ScenarioType, List[LabeledWindow]] = defaultdict(list)
        for w in windows:
            groups[w.scenario_type].append(w)

        candidates: List[ResolvedScenarioCandidate] = []

        for stype in sorted(groups.keys(), key=lambda t: t.value):
            group = sorted(groups[stype], key=lambda w: (w.scan.start_index, w.scan.end_index))
            n = len(group)
            visited = [False] * n

            for i in range(n):
                if visited[i]:
                    continue
                cluster: List[LabeledWindow] = [group[i]]
                visited[i] = True
                queue = [i]
                while queue:
                    curr = queue.pop(0)
                    for j in range(n):
                        if not visited[j]:
                            ratio = self._overlap_ratio(
                                group[curr].scan.start_index,
                                group[curr].scan.end_index,
                                group[j].scan.start_index,
                                group[j].scan.end_index,
                            )
                            if ratio >= overlap_threshold:
                                visited[j] = True
                                cluster.append(group[j])
                                queue.append(j)
                candidates.append(self._merge_cluster(cluster, stype))

        return candidates

    def _overlap_ratio(
        self,
        a_start: int,
        a_end: int,
        b_start: int,
        b_end: int,
    ) -> float:
        """Jaccard-like overlap: intersection / union. Aynı tip merge kararı için."""
        intersection = max(0, min(a_end, b_end) - max(a_start, b_start))
        if intersection == 0:
            return 0.0
        union = max(a_end, b_end) - min(a_start, b_start)
        if union <= 0:
            return 0.0
        return float(intersection / union)

    def _merge_cluster(
        self,
        cluster: List[LabeledWindow],
        scenario_type: ScenarioType,
    ) -> ResolvedScenarioCandidate:
        """
        Aynı tipte örtüşen LabeledWindow cluster'ını tek ResolvedScenarioCandidate'e indirger.

        - start/end indeks: cluster extremum
        - confidence: confidence-weighted ortalama
        - subscores: length-weighted ortalama per field (longer window daha temsil edici)
        - tarihler: extremum pencerelerden alınır
        """
        if len(cluster) == 1:
            w = cluster[0]
            return ResolvedScenarioCandidate(
                scenario_type=scenario_type,
                start_index=w.scan.start_index,
                end_index=w.scan.end_index,
                start_date=w.scan.start_date,
                end_date=w.scan.end_date,
                confidence=w.base_confidence,
                subscores=w.scan.relative_subscores,
            )

        # Confidence: confidence-weighted ortalama
        total_conf_weight = sum(w.base_confidence for w in cluster)
        if total_conf_weight < 1e-9:
            conf_weights = [1.0 / len(cluster)] * len(cluster)
        else:
            conf_weights = [w.base_confidence / total_conf_weight for w in cluster]

        # Subscores: length-weighted ortalama (uzun window daha temsil edici — pipeline contract)
        total_length = sum(w.scan.end_index - w.scan.start_index for w in cluster)
        if total_length <= 0:
            len_weights = [1.0 / len(cluster)] * len(cluster)
        else:
            len_weights = [
                (w.scan.end_index - w.scan.start_index) / total_length for w in cluster
            ]

        start_window = min(cluster, key=lambda w: w.scan.start_index)
        end_window = max(cluster, key=lambda w: w.scan.end_index)

        merged_subscores = AnomalyComponents(
            fiyat=float(min(1.0, max(0.0,
                sum(len_weights[i] * cluster[i].scan.relative_subscores.fiyat for i in range(len(cluster)))
            ))),
            hacim=float(min(1.0, max(0.0,
                sum(len_weights[i] * cluster[i].scan.relative_subscores.hacim for i in range(len(cluster)))
            ))),
            volatilite=float(min(1.0, max(0.0,
                sum(len_weights[i] * cluster[i].scan.relative_subscores.volatilite for i in range(len(cluster)))
            ))),
            pump=float(min(1.0, max(0.0,
                sum(len_weights[i] * cluster[i].scan.relative_subscores.pump for i in range(len(cluster)))
            ))),
        )

        return ResolvedScenarioCandidate(
            scenario_type=scenario_type,
            start_index=start_window.scan.start_index,
            end_index=end_window.scan.end_index,
            start_date=start_window.scan.start_date,
            end_date=end_window.scan.end_date,
            confidence=float(min(1.0, max(0.0,
                sum(conf_weights[i] * cluster[i].base_confidence for i in range(len(cluster)))
            ))),
            subscores=merged_subscores,
        )

    def _resolve_cross_priority_overlaps(
        self,
        candidates: List[ResolvedScenarioCandidate],
    ) -> List[ResolvedScenarioCandidate]:
        """
        Farklı tipte örtüşen ResolvedScenarioCandidate'leri priority hiyerarşisine göre çözer.

        BFS ile farklı-tip örtüşme cluster'larını bulur; her cluster'ı
        `_resolve_overlap_cluster`'a gönderir. Örtüşmeyen kandidatlar doğrudan geçer.

        Determinizm: priority desc, start_index asc sırasıyla işlenir.
        """
        if not candidates:
            return []

        n = len(candidates)
        adj: List[List[int]] = [[] for _ in range(n)]
        for i in range(n):
            for j in range(i + 1, n):
                if candidates[i].scenario_type != candidates[j].scenario_type:
                    if self._intervals_overlap(
                        candidates[i].start_index, candidates[i].end_index,
                        candidates[j].start_index, candidates[j].end_index,
                    ):
                        adj[i].append(j)
                        adj[j].append(i)

        # Deterministik BFS başlangıç sırası: priority desc, start_index asc
        visit_order = sorted(
            range(n),
            key=lambda i: (-_priority_of(candidates[i].scenario_type), candidates[i].start_index),
        )

        processed = [False] * n
        result: List[ResolvedScenarioCandidate] = []

        for start_i in visit_order:
            if processed[start_i]:
                continue
            cluster_indices: List[int] = []
            in_queue = [False] * n
            in_queue[start_i] = True
            queue = [start_i]
            while queue:
                curr = queue.pop(0)
                cluster_indices.append(curr)
                processed[curr] = True
                for nb in sorted(adj[curr]):  # sorted → determinizm
                    if not in_queue[nb]:
                        in_queue[nb] = True
                        queue.append(nb)

            cluster = [candidates[i] for i in cluster_indices]
            if len(cluster) == 1:
                result.append(cluster[0])
            else:
                result.extend(self._resolve_overlap_cluster(cluster))

        return result

    def _intervals_overlap(
        self,
        a_start: int,
        a_end: int,
        b_start: int,
        b_end: int,
    ) -> bool:
        """
        Half-open interval overlap check: touching endpoints are NOT overlap.

        [a_start, a_end) ∩ [b_start, b_end) için:
            [10, 20) ile [20, 30) → False (touching, disjoint)
            [10, 20) ile [19, 30) → True  (1 unit overlap)

        Bu modüldeki tüm interval'lar half-open convention kullanır.
        """
        return min(a_end, b_end) > max(a_start, b_start)

    # TODO(Etap 2 / calibration findings): Multi-pass overlap resolution.
    #
    # Mevcut algoritma "winner-takes-local-overlap" yapar; "globally
    # conflict-free segmentation" GARANTİSİ vermez. Single-pass cluster
    # resolution sırasında, winner'a göre split edilen remainder'lar
    # birbiriyle yeni overlap'ler oluşturabilir.
    #
    # Edge case örneği:
    #   Cluster: A manipulation [10,30) + B pump [25,45) + C distribution [40,60)
    #   Pass:
    #     - A winner (en yüksek priority)
    #     - B split against A → B_remainder [30,45)
    #     - C, A ile çakışmıyor → [40,60) intact
    #   Sonuç: A [10,30), B_remainder [30,45), C [40,60)
    #
    #   PROBLEM: B_remainder [30,45) ve C [40,60) HALA OVERLAP halinde
    #   ([40,45) bölgesinde 5 unit). Cross-priority resolve sonrası bu durum
    #   dokunulmaz — cluster zaten "resolved" sayılıyor.
    #
    # Çözüm seçenekleri (Etap 1.4 calibration sonrası değerlendirilecek):
    #   - Fixed-point iteration (resolve sonrası tekrar overlap kontrolü)
    #   - Recursive cluster (remainder'lardan yeni cluster üret)
    #   - Pre-emptive merge (cross-priority pass öncesi remainder kontrolü)
    def _resolve_overlap_cluster(
        self,
        cluster: List[ResolvedScenarioCandidate],
    ) -> List[ResolvedScenarioCandidate]:
        """
        Farklı tipte birbiriyle örtüşen kandidat cluster'ını çözer.

        Winner: en yüksek priority; beraberlik durumunda confidence desc, sonra
        start_index asc (erken başlayan) — tam determinizm.

        Diğer tüm kandidatlar winner'a karşı split edilir; minimum_segment_length
        altına düşen parçalar discard edilir.

        STRUCTURAL PURE: yalnızca geometrik operasyonlar, kategori bias yok.
        """
        # Winner seçim tie-break sırası (max kazanır olduğu için pozitif/negatif yönler tersine):
        # 1. priority (yüksek kazanır)
        # 2. confidence (yüksek kazanır)
        # 3. specificity (kısa segment = daha spesifik bilgi, kazanır)
        # 4. -start_index (erken başlayan kazanır)
        # 5. scenario_type.value (lexical son anchor)
        winner = max(
            cluster,
            key=lambda c: (
                _priority_of(c.scenario_type),
                c.confidence,
                -(c.end_index - c.start_index),
                -c.start_index,
                c.scenario_type.value,
            ),
        )

        result: List[ResolvedScenarioCandidate] = [winner]

        for candidate in cluster:
            if candidate is winner:
                continue
            result.extend(self._split_against(target=candidate, cutter=winner))

        return result

    def _split_against(
        self,
        target: ResolvedScenarioCandidate,
        cutter: ResolvedScenarioCandidate,
    ) -> List[ResolvedScenarioCandidate]:
        """
        target'ı cutter'ın aralığından keser; kalan fragment(lar)ı döner.

        Durum analizi:
          Sol fragment: [target.start, cutter.start - 1]
          Sağ fragment: [cutter.end + 1, target.end]

        minimum_segment_length kontrolü her fragment için uygulanır.
        Hiçbiri geçemezse boş liste döner (target tamamen örtülmüş).

        PIPELINE CONTRACT — Structural Pure / Split Confidence & Subscores Preservation:
        ---------------------------------------------------------------------------------
        Split remainders, original'ın confidence DEĞERİNİ ve subscores DEĞERLERİNİ
        AYNEN korur.

        Bu kasıtlı bir mimari karardır:
        - Structural engine PURE prensibi (anayasal): structural pipeline
          yalnızca geometry / overlap / priority ile ilgilenir.
        - Confidence rescaling ("küçük parçaların confidence'ı düşmeli" gibi)
          bir semantic weighting'tir → Etap 1.2b-3b (Confidence Finalizer)
          sorumluluğundadır.
        - Subscores rescaling ("küçük parçaların subscores'u yeniden hesaplansın")
          da semantic weighting'tir → bu modülün kapsamı DIŞI (Etap 2 calibration
          findings değerlendirmesine bırakılmıştır).
        - Bu izolasyon, "hangi segment yaşayacak" (structural) ile
          "segment'in güveni/subscores'u ne olacak" (scoring) kararlarını ayrı tutar.

        Bir gün split remainder'larının çok küçük olduğunda confidence veya subscores
        decay edilmesi gerektiği görülürse, bu kod değil 1.2b-3b'deki Confidence
        Finalizer güncellenmelidir.
        """
        t_start, t_end = target.start_index, target.end_index
        c_start, c_end = cutter.start_index, cutter.end_index

        # OVERLAP GUARD — target ile cutter direkt overlap etmiyorsa target intact döner.
        # Half-open semantic: [t_start, t_end) ∩ [c_start, c_end) boş ise no-op.
        # Transitif cluster bağlantısı _split_against'i tetikleyebilir ama burada
        # geometric overlap kontrolü cluster topolojisinden bağımsız olmalı.
        if not self._intervals_overlap(t_start, t_end, c_start, c_end):
            return [target]

        # cutter target'ı tamamen kaplıyor — fragment kalmaz
        if c_start <= t_start and c_end >= t_end:
            return []

        results: List[ResolvedScenarioCandidate] = []
        min_len = self._config.minimum_segment_length

        # Half-open: cutter [c_start, c_end) → sol kalan [t_start, c_start), sağ kalan [c_end, t_end)
        # left_end = c_start (exclusive), right_start = c_end (first uncovered index)
        left_end = c_start
        if left_end > t_start and (left_end - t_start) >= min_len:
            results.append(self._build_split_remainder(target, t_start, left_end))

        right_start = c_end
        if right_start < t_end and (t_end - right_start) >= min_len:
            results.append(self._build_split_remainder(target, right_start, t_end))

        return results

    def _build_split_remainder(
        self,
        original: ResolvedScenarioCandidate,
        new_start: int,
        new_end: int,
    ) -> ResolvedScenarioCandidate:
        """
        Bir split fragment'inden yeni ResolvedScenarioCandidate üretir.

        Tarihler PROVISIONAL: OHLCV erişimi olmadan indeks→tarih dönüşümü yapılamaz.
        original.start_date / end_date taşınır — Etap 1.2b-3c'de classify() pipeline'ından
        ohlcv_df geçirilince kesin tarihlerle replace edilecek.

        Confidence ve subscores AYNEN taşınır — bkz. _split_against pipeline contract.
        """
        return ResolvedScenarioCandidate(
            scenario_type=original.scenario_type,
            start_index=new_start,
            end_index=new_end,
            start_date=original.start_date,
            end_date=original.end_date,
            confidence=original.confidence,
            subscores=original.subscores,
        )

    # --------------------------------------------------------
    # PRESENTATION LAYER
    # --------------------------------------------------------

    def _classify_duration_category(self, segment_length: int) -> str:
        """
        Segment uzunluğunu (gün) süre kategorisine atar.

        Half-open semantic:
            segment_length < 7    → "short"
            7 ≤ length < 30       → "medium"
            length ≥ 30           → "long"
        """
        if segment_length < _DURATION_SHORT_MAX:
            return "short"
        elif segment_length < _DURATION_MEDIUM_MAX:
            return "medium"
        else:
            return "long"

    def _find_dominant_signal(self, subscores: AnomalyComponents) -> str:
        """
        Subscores içinde en yüksek değerli alanın adını döner.

        Deterministic tie-break: Eşit subscore değerinde _FIELD_PRIORITY
        sırası kullanılır (fiyat < hacim < volatilite < pump).
        Tuple-based key: (value, -priority) — value max, eşitlikte düşük
        priority kazanır.
        """
        candidates = [
            ("fiyat", subscores.fiyat),
            ("hacim", subscores.hacim),
            ("volatilite", subscores.volatilite),
            ("pump", subscores.pump),
        ]
        dominant_name, _ = max(
            candidates,
            key=lambda x: (x[1], -_FIELD_PRIORITY[x[0]])
        )
        return dominant_name

    def _build_title(
        self,
        scenario_type: ScenarioType,
        segment_length: int,
        subscores: AnomalyComponents,
    ) -> str:
        """
        Registry-based title üretimi.

        Format: "{duration_variant} ({dominant_label})"
        Örnek: "Manipülasyon Şüphesi (Aşırı Hacimle)"
        """
        variants, dominant_labels = _TEMPLATE_REGISTRY[scenario_type]
        duration_cat = self._classify_duration_category(segment_length)

        if duration_cat == "short":
            duration_variant = variants.short
        elif duration_cat == "medium":
            duration_variant = variants.medium
        else:
            duration_variant = variants.long

        dominant = self._find_dominant_signal(subscores)
        if dominant == "fiyat":
            dominant_label = dominant_labels.fiyat
        elif dominant == "hacim":
            dominant_label = dominant_labels.hacim
        elif dominant == "volatilite":
            dominant_label = dominant_labels.volatilite
        else:
            dominant_label = dominant_labels.pump

        return f"{duration_variant} ({dominant_label})"

    def _build_description(
        self,
        segment_length: int,
        subscores: AnomalyComponents,
        start_date: str,
        end_date: str,
    ) -> str:
        """
        Sayısal explainability içeren açıklama üretimi.

        Format:
            "{N} gün sürdü. Hacim %{H}, fiyat anomalisi %{F},
            volatilite %{V}, pump benzerliği %{P}. {start} ile {end} arası."

        HALF-OPEN SEMANTIC NOTU:
        segment_length = end_index - start_index (half-open hesabı).
        UI'da calendar-day farkıyla birebir örtüşmeyebilir.
        Pipeline boyunca half-open convention korunur — "+1" ekleme YASAK.
        """
        fiyat_pct = _to_display_percent(subscores.fiyat)
        hacim_pct = _to_display_percent(subscores.hacim)
        vol_pct = _to_display_percent(subscores.volatilite)
        pump_pct = _to_display_percent(subscores.pump)

        return (
            f"{segment_length} gün sürdü. "
            f"Hacim %{hacim_pct}, fiyat anomalisi %{fiyat_pct}, "
            f"volatilite %{vol_pct}, pump benzerliği %{pump_pct}. "
            f"{start_date} ile {end_date} arası."
        )

    def _build_scenario_segment(
        self,
        final_cand: FinalScenarioCandidate,
    ) -> ScenarioSegment:
        """
        FinalScenarioCandidate'ı ScenarioSegment'e dönüştürür.
        Title ve description registry-based üretilir.

        Audit trail alanları (base_confidence, applied_*) ScenarioSegment'e
        GEÇMEZ — yalnızca final pipeline aşamasında debug için kalmıştır.
        """
        raw_length = final_cand.end_index - final_cand.start_index

        # Defensive guard — scanner veya conflict_resolver'da olası bir
        # bug zero-length segment üretirse UI'da "0 gün sürdü" çıkmasın.
        if raw_length <= 0:
            _logger.warning(
                "Zero-length segment detected: scenario_type=%s, "
                "start_index=%d, end_index=%d. Coercing display_length=1.",
                final_cand.scenario_type.value,
                final_cand.start_index,
                final_cand.end_index,
            )
        display_length = max(raw_length, 1)

        title = self._build_title(
            scenario_type=final_cand.scenario_type,
            segment_length=display_length,
            subscores=final_cand.subscores,
        )
        description = self._build_description(
            segment_length=display_length,
            subscores=final_cand.subscores,
            start_date=final_cand.start_date,
            end_date=final_cand.end_date,
        )

        return ScenarioSegment(
            type=final_cand.scenario_type,
            start_index=final_cand.start_index,  # orijinal değer
            end_index=final_cand.end_index,       # orijinal değer
            start_date=final_cand.start_date,
            end_date=final_cand.end_date,
            title=title,
            description=description,
            confidence=final_cand.final_confidence,
            subscores=final_cand.subscores,
        )

    def _build_ipo_period_segment(
        self,
        ohlcv_df: pd.DataFrame,
        context: ClassifierContext,
    ) -> ScenarioSegment:
        """
        IPO discovery rejiminde tüm veri aralığını tek segment olarak işaretler.
        """
        total_days = len(ohlcv_df)

        if isinstance(ohlcv_df.index, pd.DatetimeIndex):
            start_date = _to_iso_date(ohlcv_df.index[0])
            end_date = _to_iso_date(ohlcv_df.index[-1])
        else:
            start_date = ""
            end_date = ""

        variants, _ = _TEMPLATE_REGISTRY[ScenarioType.IPO_PERIOD]
        description = (
            f"Hisse son {total_days} iş günüdür işlemde. "
            f"İstatistiksel baseline için yeterli geçmiş veri "
            f"bulunmadığından klasik anomali analizi uygulanmadı."
        )

        return ScenarioSegment(
            type=ScenarioType.IPO_PERIOD,
            start_index=0,
            end_index=total_days,
            start_date=start_date,
            end_date=end_date,
            title=variants.medium,
            description=description,
            confidence=1.0,
            subscores=AnomalyComponents(
                fiyat=0.0, hacim=0.0, volatilite=0.0, pump=0.0,
            ),
        )

    def _build_scenario_bundle(
        self,
        segments: List[ScenarioSegment],
        total_window_days: int,
    ) -> ScenarioBundle:
        """
        ScenarioSegment listesini final ScenarioBundle'a paketler.
        Firestore'a doğrudan yazılabilir model döner.
        """
        return ScenarioBundle(
            segments=segments,
            total_window_days=total_window_days,
            classifier_version=self._config.classifier_version,
        )

    # --------------------------------------------------------
    # ANA classify()
    # --------------------------------------------------------

    def classify(
        self,
        ohlcv_df: pd.DataFrame,
        xu100_series: pd.Series,
        sector_baseline_df: Optional[pd.DataFrame],
        ticker: str,
        kategori: str,
        ipo_date: Optional[date],
        current_date: date,
    ) -> ScenarioBundle:
        """
        Scenario classifier ana entry point — FULL PIPELINE.

        Pipeline:
          1. Market regime detection
          2. Window scanning (raw subscores)
          3. Rule-based labeling
          4. Structural conflict resolution
          5. Confidence finalization
          6. Presentation layer (title/description templates)
          7. ScenarioBundle assembly

        Returns:
            ScenarioBundle — Firestore'a yazılabilir, deterministic,
            SPK uyumlu segment listesi.
        """
        required_lookback = self.compute_required_lookback()
        available_history = len(ohlcv_df)

        regime = self.detect_market_regime(
            ipo_date=ipo_date,
            current_date=current_date,
            available_history_days=available_history,
            required_lookback_days=required_lookback,
        )

        context = ClassifierContext(
            ticker=ticker,
            kategori=kategori,
            ipo_date=ipo_date,
            current_date=current_date,
            regime=regime,
            available_history_days=available_history,
            required_lookback_days=required_lookback,
        )

        # Etap 2.0 — IPO_DISCOVERY rejiminde IPO_PERIOD segment üret
        if regime == MarketRegime.IPO_DISCOVERY:
            ipo_segment = self._build_ipo_period_segment(
                ohlcv_df=ohlcv_df, context=context,
            )
            return self._build_scenario_bundle(
                segments=[ipo_segment],
                total_window_days=available_history,
            )

        # Aşama 1: Window scanning
        window_scans = self.scan_windows(
            ohlcv_df=ohlcv_df,
            xu100_series=xu100_series,
            sector_baseline_df=sector_baseline_df,
            context=context,
        )

        # Aşama 2: Rule-based labeling
        labeled: List[LabeledWindow] = []
        for scan in window_scans:
            lw = self._label_window(scan, context)
            if lw is not None:
                labeled.append(lw)

        # Aşama 3: Structural conflict resolution
        resolved = self._resolve_conflicts(labeled, context)

        # Aşama 4: Confidence finalization
        finalized = self._apply_post_processing(resolved, context)

        # Aşama 5: Presentation layer
        segments = [self._build_scenario_segment(f) for f in finalized]

        # Aşama 6: Bundle assembly
        return self._build_scenario_bundle(
            segments=segments,
            total_window_days=available_history,
        )
