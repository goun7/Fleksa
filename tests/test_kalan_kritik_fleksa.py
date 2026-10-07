"""Kalan EN KRİTİK Fleksa test açıkları — sadece YENI dosya.

Kapsam (mevcut testleri DEĞİŞTİRMEZ):

  1. workload.gpu_flexibility.GpuFlexibilityProfiler.demand_pressure (33L,
     tam test-dışı) — dinamik GPU cap'in kalbi olan talep-basıncı indeksi.
     compute_flexibility_profile dolaylı olarak kullanıyordu ama formül
     hiç doğrudan test edilmiyordu.
  2. workload.power_cap.GpuPowerCapSimulator.calculate_efficiency — tek bir
     happy-path testi vardı; kıstlama (clamp), bilinmeyen-model varsayılanı,
     tüm GPU modelleri ve perf/Watt matematiği test-dışı.
  3. cli.main.solve_cmd'ın test-dışı dalları — --gpu-flex=dynamic (talek
     tabanlı profil), benchmark padding (kayıt < saat), --dynamic-gpu-cap
     ve geçersiz solver parametresi (SystemExit(1)).

Tüm testler saf fonksiyon mantığını test eder; dış ağ/ NVML çağrısı YOK.
"""
from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from fleksa.cli.main import main
from fleksa.core.constants import (
    GPU_CAP_CEILING,
    GPU_CAP_HARD_FLOOR,
    GPU_FLEX_BACKLOG_SATURATION_FLOPS,
    GPU_FLEX_ELASTICITY_EXPONENT,
    GPU_FLEX_MAX_NONCRITICAL_SHARE,
)
from fleksa.workload.gpu_flexibility import (
    GpuDemandSignals,
    GpuFlexibilityProfiler,
)
from fleksa.workload.power_cap import GpuPowerCapSimulator


# =====================================================================
# 1) demand_pressure — talep-basıncı indeksi
# =====================================================================

def _signals(backlog, noncrit, sla):
    """Tek saatlik sinyal demeti."""
    return GpuDemandSignals(
        queue_backlog_flops=[backlog],
        noncritical_share=[noncrit],
        sla_pressure=[sla],
    )


@pytest.fixture()
def profiler() -> GpuFlexibilityProfiler:
    return GpuFlexibilityProfiler()


def test_demand_pressure_idle_cluster_residuel_floor(profiler) -> None:
    """Boş kuyruk (backlog=0) → backlog_term=0 → basınç 0.05 rezid zemin."""
    p = profiler.demand_pressure(_signals(0.0, 0.5, 0.0))
    assert p == pytest.approx([0.05])


def test_demand_pressure_tam_doygun_kritik_tavan(profiler) -> None:
    """Maks kuyruk + sıfır önelenebilir + max SLA → basınç 1.0 (tavan)."""
    p = profiler.demand_pressure(_signals(1e12, 0.0, 1.0))
    assert p == pytest.approx([1.0])


def test_demand_pressure_yarim_doygunma_noktasi(profiler) -> None:
    """backlog == backlog_saturation_flops → backlog_term tam 0.5.

    Michaelis-Menten tarzı doygunma: yarım-doyma noktası sabitidir.
    noncrit=0, sla=0 → basınç = 0.05 + 0.95*0.5 = 0.525.
    """
    p = profiler.demand_pressure(
        _signals(GPU_FLEX_BACKLOG_SATURATION_FLOPS, 0.0, 0.0))
    assert p == pytest.approx([0.525])


def test_demand_pressure_onelenebilir_is_basinci_dusurur(profiler) -> None:
    """Önelenebilir payı maksimumda → absorbable_term=0.85 → basınç düşer.

    backlog doygun, sla=0, noncrit >= max_noncritical_share (0.80):
    basınç = 0.05 + 0.95 * (1 * 0.15) = 0.1925.
    """
    p = profiler.demand_pressure(_signals(1e12, GPU_FLEX_MAX_NONCRITICAL_SHARE, 0.0))
    assert p == pytest.approx([0.1925])
    # max_noncritical_share'in üstü clip'lenir — aynı sonuç
    p2 = profiler.demand_pressure(_signals(1e12, 1.0, 0.0))
    assert p2 == pytest.approx([0.1925])


def test_demand_pressure_onelenebilir_arttikca_basinc_duser(profiler) -> None:
    """noncritical_share arttıkça basınç monoton azalır (absorbable term)."""
    pressures = [
        profiler.demand_pressure(_signals(1e6, nc, 0.3))[0]
        for nc in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
    ]
    assert pressures == sorted(pressures, reverse=True)
    assert pressures[0] > pressures[-1]


def test_demand_pressure_backlog_arttikca_basinc_yukselir(profiler) -> None:
    """Kuyruk derinleştikçe basınç monoton artar (doyma'ya kadar)."""
    pressures = [
        profiler.demand_pressure(_signals(b, 0.5, 0.2))[0]
        for b in (0.0, 1e4, 1e5, 5e5, 1e7, 1e12)
    ]
    assert pressures == sorted(pressures)
    assert pressures[-1] > pressures[0]


def test_demand_pressure_sla_deadline_basinci_sikistirir(profiler) -> None:
    """SLA baskısı arttıkça basınç monoton artar (1+sla_term)."""
    pressures = [
        profiler.demand_pressure(_signals(1e6, 0.4, s))[0]
        for s in (0.0, 0.25, 0.5, 0.75, 1.0)
    ]
    assert pressures == sorted(pressures)
    assert pressures[-1] > pressures[0]


def test_demand_pressure_aralik_ve_uzunluk(profiler) -> None:
    """Tüm basınç değerleri [0.05, 1.0] aralığında; uzunluk giriş ile aynı."""
    sig = GpuDemandSignals(
        queue_backlog_flops=[0.0, 1e3, 5e5, 1e12],
        noncritical_share=[0.9, 0.5, 0.2, 0.0],
        sla_pressure=[0.0, 0.3, 0.6, 1.0],
    )
    p = profiler.demand_pressure(sig)
    assert len(p) == 4
    assert all(0.05 - 1e-12 <= v <= 1.0 + 1e-12 for v in p)


def test_demand_pressure_karisik_sinyaller_degerleri(profiler) -> None:
    """Bilinen bir karışık durumda formül elle doğrulanır."""
    # backlog=1e6 → term = 1e6/1.5e6 = 2/3; noncrit=0.4 → absorbable=0.5
    # → absorbable_term=0.425; sla=0.5
    # raw = (2/3) * 0.575 * 1.5 = 0.575; pressure = 0.05+0.95*0.575
    p = profiler.demand_pressure(_signals(1e6, 0.4, 0.5))[0]
    expected = 0.05 + 0.95 * ((1e6 / 1.5e6) * (1.0 - 0.85 * 0.5) * 1.5)
    assert p == pytest.approx(expected)


def test_demand_pressure_slack_formuluyse_es_noktasi(profiler) -> None:
    """Elastikiyet üssü sadece compute_flexibility_profile'da kullanılır;

    demand_pressure doğrudan döndürülür — formül elastikiyet'den bağımsızdır.
    """
    p1 = GpuFlexibilityProfiler(elasticity_exponent=0.5)
    p2 = GpuFlexibilityProfiler(elasticity_exponent=2.0)
    sig = _signals(1e6, 0.4, 0.5)
    assert p1.demand_pressure(sig) == p2.demand_pressure(sig)


# =====================================================================
# 2) calculate_efficiency — güç kıstlama verimliliği
# =====================================================================

def test_efficiency_h100_orta_cap_matematigi() -> None:
    """H100_SXM5 @450W: cap_fraction=9/14; thr_loss=(1-9/14)*0.35."""
    r = GpuPowerCapSimulator.calculate_efficiency("H100_SXM5", 450.0)
    assert r["model_name"] == "H100_SXM5"
    assert r["nominal_w"] == 700.0
    assert r["applied_w"] == 450.0
    cap = 450.0 / 700.0
    assert r["power_reduction_pct"] == pytest.approx((1 - cap) * 100, abs=0.01)
    assert r["throughput_loss_pct"] == pytest.approx((1 - cap) * 0.35 * 100, abs=0.01)
    # bellek-bağımlı çekirdek: verim kaybı güç tasarrufundan ÇOK daha küçük
    assert r["throughput_loss_pct"] < r["power_reduction_pct"]
    assert r["relative_throughput"] == pytest.approx(1 - r["throughput_loss_pct"] / 100, abs=1e-4)
    assert r["efficiency_gain_pct"] > 0


def test_efficiency_nominalde_sifir_kazanc() -> None:
    """Nominal TDP'de kıstlama yok → tüm kazançlar 0."""
    r = GpuPowerCapSimulator.calculate_efficiency("H100_SXM5", 700.0)
    assert r["applied_w"] == 700.0
    assert r["power_reduction_pct"] == 0.0
    assert r["throughput_loss_pct"] == 0.0
    assert r["relative_throughput"] == 1.0
    assert r["efficiency_gain_pct"] == 0.0


def test_efficiency_nominal_ustu_kisitlanir() -> None:
    """Nominal'in üstündeki hedef → nominal'e kıstlanır (kazanç 0)."""
    r = GpuPowerCapSimulator.calculate_efficiency("H100_SXM5", 99999.0)
    assert r["applied_w"] == 700.0
    assert r["power_reduction_pct"] == 0.0
    assert r["efficiency_gain_pct"] == 0.0


def test_efficiency_min_alti_kisitlanir() -> None:
    """Minimum TDP'nin altı → min'e kıstlanır, daha aşağı inilmez."""
    r = GpuPowerCapSimulator.calculate_efficiency("H100_SXM5", 100.0)
    assert r["applied_w"] == 350.0
    assert r["power_reduction_pct"] == 50.0
    assert r["throughput_loss_pct"] == pytest.approx(17.5, abs=0.01)
    assert r["relative_throughput"] == pytest.approx(0.825, abs=1e-4)


def test_efficiency_bilinmeyen_model_h100_varsayilani() -> None:
    """Bilinmeyen GPU → H100_SXM5 spec'ine düşer (fail-safe varsayılan)."""
    r = GpuPowerCapSimulator.calculate_efficiency("UNKNOWN_GPU_XYZ", 450.0)
    ref = GpuPowerCapSimulator.calculate_efficiency("H100_SXM5", 450.0)
    # model_name dışında tüm değerler H100 ile aynı
    assert r["model_name"] == "UNKNOWN_GPU_XYZ"
    for k in ("nominal_w", "applied_w", "power_reduction_pct",
              "throughput_loss_pct", "relative_throughput", "efficiency_gain_pct"):
        assert r[k] == ref[k]


@pytest.mark.parametrize("model, nominal, min_w, alpha", [
    ("H100_SXM5", 700.0, 350.0, 0.35),
    ("H100_PCIE", 350.0, 200.0, 0.32),
    ("H200_SXM5", 700.0, 350.0, 0.33),
    ("B200_NVL", 1000.0, 500.0, 0.36),
])
def test_efficiency_tum_gpu_modelleri_spec_ile_uyumlu(model, nominal, min_w, alpha) -> None:
    """Her GPU modeli için spec'ten türeyen kıstlama aralığı ve alpha."""
    r = GpuPowerCapSimulator.calculate_efficiency(model, nominal * 0.75)
    assert r["nominal_w"] == nominal
    assert r["applied_w"] == nominal * 0.75
    cap = 0.75
    assert r["throughput_loss_pct"] == pytest.approx((1 - cap) * alpha * 100, abs=0.01)
    assert r["efficiency_gain_pct"] > 0
    # min'in altı kıstlanır
    r2 = GpuPowerCapSimulator.calculate_efficiency(model, min_w * 0.5)
    assert r2["applied_w"] == min_w


def test_efficiency_kazanc_perf_per_watt_turevi() -> None:
    """efficiency_gain = (relative_throughput/cap_fraction - 1) * 100."""
    r = GpuPowerCapSimulator.calculate_efficiency("B200_NVL", 750.0)
    cap = 750.0 / 1000.0
    expected_gain = ((1 - (1 - cap) * 0.36) / cap - 1.0) * 100.0
    assert r["efficiency_gain_pct"] == pytest.approx(expected_gain, abs=0.01)


def test_efficiency_dusuk_cap_daha_yuksek_kazanc() -> None:
    """Daha düşük cap → daha yüksek perf/Watt kazancı (monoton artar)."""
    gains = [
        GpuPowerCapSimulator.calculate_efficiency("H100_SXM5", w)["efficiency_gain_pct"]
        for w in (700.0, 600.0, 500.0, 400.0, 350.0)
    ]
    # güç azaldıkça kazanç monoton artar
    assert gains == sorted(gains)
    assert gains[0] == 0.0
    assert gains[-1] > gains[0]


# =====================================================================
# 3) solve_cmd'ın test-dışı dalları
# =====================================================================

def test_solve_gpu_flex_dynamic_modu() -> None:
    """--gpu-flex=dynamic → DYNAMIC_DEMAND_BASED modu, cap'ler zemine bağlı."""
    res = CliRunner().invoke(
        main, ["solve", "--hours", "8", "--gpu-flex", "dynamic", "--json-output"])
    assert res.exit_code == 0
    d = json.loads(res.output)
    assert d["status"] == "OPTIMAL"
    assert d["gpu_flexibility_mode"] == "DYNAMIC_DEMAND_BASED"
    assert len(d["gpu_power_cap_pct"]) == 8
    # dinamik profil hard_floor ile ceiling arasında
    assert all(GPU_CAP_HARD_FLOOR - 1e-9 <= c <= GPU_CAP_CEILING + 1e-9
               for c in d["gpu_power_cap_pct"])


def test_solve_gpu_flex_dynamic_json_govdesi_tamdir() -> None:
    """--json-output → status/maliyet/tasarruf/cap/SoC alanları eksiksiz."""
    res = CliRunner().invoke(
        main, ["solve", "--hours", "6", "--gpu-flex", "dynamic", "--json-output"])
    assert res.exit_code == 0
    d = json.loads(res.output)
    for key in ("status", "projected_cost_try", "expected_savings_try",
                "p_ch_kw", "p_dis_kw", "p_grid_kw", "gpu_power_cap_pct",
                "soc_trajectory_kwh", "gpu_flexibility_mode"):
        assert key in d


def test_solve_benchmark_kaydi_saatten_azsa_pad_yapar(tmp_path) -> None:
    """Benchmark kayıtları saatten azsa son değerle doldurulur (pad dalı)."""
    bench = tmp_path / "short.json"
    bench.write_text(json.dumps({"records": [{"ptf": 2500}, {"ptf": 3000}]}),
                     encoding="utf-8")
    res = CliRunner().invoke(
        main, ["solve", "--hours", "6", "--benchmark-file", str(bench),
               "--json-output"])
    assert res.exit_code == 0
    d = json.loads(res.output)
    assert d["status"] == "OPTIMAL"
    assert len(d["gpu_power_cap_pct"]) == 6


def test_solve_benchmark_hatali_json_yedek_fiyata_duser(tmp_path) -> None:
    """Bozuk benchmark JSON → sabit 2.5 TRY/kWh yedeği (except dalı)."""
    bench = tmp_path / "bad.json"
    bench.write_text("{ this is not json ", encoding="utf-8")
    res = CliRunner().invoke(
        main, ["solve", "--hours", "4", "--benchmark-file", str(bench),
               "--json-output"])
    assert res.exit_code == 0
    assert json.loads(res.output)["status"] == "OPTIMAL"


def test_solve_benchmark_bos_kayitlar_yedek_fiyata_duser(tmp_path) -> None:
    """Boş records listesi → ptf boşken 2.5 yedeği (len(ptf)==0 dalı)."""
    bench = tmp_path / "empty.json"
    bench.write_text(json.dumps({"records": []}), encoding="utf-8")
    res = CliRunner().invoke(
        main, ["solve", "--hours", "3", "--benchmark-file", str(bench),
               "--json-output"])
    assert res.exit_code == 0
    assert json.loads(res.output)["status"] == "OPTIMAL"


def test_solve_dynamic_gpu_cap_acik_deger_kullanilir() -> None:
    """--dynamic-gpu-cap açık skaler → çözücüde o değer uygulanır."""
    res = CliRunner().invoke(
        main, ["solve", "--hours", "4", "--dynamic-gpu-cap", "0.77",
               "--json-output"])
    assert res.exit_code == 0
    d = json.loads(res.output)
    assert d["gpu_power_cap_pct"][0] == pytest.approx(0.77)


def test_solve_gecersiz_cap_araligi_hata_ile_cikar() -> None:
    """gpu_cap_min > gpu_cap_max → 'Solver parameter error' + SystemExit(1)."""
    res = CliRunner().invoke(
        main, ["solve", "--hours", "4", "--gpu-cap-min", "0.9",
               "--gpu-cap-max", "0.1"])
    assert res.exit_code == 1
    assert "Solver parameter error" in (res.output or "")


def test_solve_gelismis_rapor_sablonu_metni() -> None:
    """İnsan-okur rapor çıktısı: status/maliyet/tasarruf/dispatch satırları."""
    res = CliRunner().invoke(
        main, ["solve", "--hours", "12", "--battery-soc", "150", "--gpu-flex",
               "dynamic"])
    assert res.exit_code == 0
    out = res.output
    assert "Optimization Status: OPTIMAL" in out
    assert "Expected Savings" in out
    assert "GPU Flexibility" in out
    assert "Dispatch Setpoints" in out
