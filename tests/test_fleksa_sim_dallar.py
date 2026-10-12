r"""76-Fleksa cli.main._simulate_gpu_demand + _ipmvp_audit_scenario dal-kesen testleri (LEED).

Kural-1: mevcut dosyalara DOKUNULMADI, SADECE bu yeni dosya eklendi.
Kural-4: saf in-memory ( DETERMINISTIK numpy; DIS-AG/meter/gercek-grid
CAGRILMAZ; sabit-tohum uretim).

ORTAM-ANATOMI:
- _simulate_gpu_demand(hours, peak_queue): ( backlog, noncrit, sla) listeleri
- _ipmvp_audit_scenario(history_days): IPMVP Option B M&V sahne-sozlugu
"""
import sys

import numpy as np
import pytest

sys.path.insert(0, ".")
sys.path.insert(0, "src")
from fleksa.cli.main import _ipmvp_audit_scenario, _simulate_gpu_demand  # noqa: E402


# == _simulate_gpu_demand: temel =====================================================================

def test_gpu_uc_liste_donar():
    """ORTAM: ( backlog, noncrit, sla) 3-liste."""
    b, n, s = _simulate_gpu_demand(24, 100.0)
    assert isinstance(b, list) and isinstance(n, list) and isinstance(s, list)


def test_gpu_uzunluk_hours():
    """ORTAM: her-liste 'hours' uzunlugunda."""
    for hrs in [1, 6, 24, 48, 100]:
        b, n, s = _simulate_gpu_demand(hrs, 100.0)
        assert len(b) == len(n) == len(s) == hrs


def test_gpu_sifir_saat():
    """ORTAM: hours=0 -> uc-bos-liste."""
    assert _simulate_gpu_demand(0, 100.0) == ([], [], [])


def test_gpu_degerler_float():
    """ORTAM: backlog/noncrit float64, sla float ( np.clip)."""
    b, n, s = _simulate_gpu_demand(24, 100.0)
    assert isinstance(b[0], (float, np.floating))
    assert isinstance(n[0], (float, np.floating))
    assert isinstance(s[0], (float, np.floating))


# == gunluk-dongu =====================================================================================

def test_gpu_peak_saat14():
    """ORTAM-OGRENDI: business-hours hump — 14:00'te ( h=14) cos=1 ->
    backlog MAKS; DOSYA-YORUMU '04:00' YANLIS — gercek-min h=02."""
    b, _, _ = _simulate_gpu_demand(24, 100.0)
    assert b[14] == max(b)
    assert b[14] == pytest.approx(100.0, abs=0.01)


def test_gpu_min_saat02():
    """ORTAM-OGRENDI: cos=-1 ( h-14 = -12 -> h=02) -> backlog MIN ( 0.15
    floor). DOSYA-YORUMU '0.15 at 04:00' YANLIS — gercek-min 02:00."""
    b, _, _ = _simulate_gpu_demand(24, 100.0)
    assert b[2] == min(b)
    assert b[2] == pytest.approx(15.0, abs=0.01)


def test_gpu_015_085_araligi():
    """ORTAM-OGRENDI: backlog = peak*( 0.15 + 0.85*day) — [0.15,1.0]*
    peak; 04:00 15.0, 14:00 100.0 ( peak=100)."""
    b, _, _ = _simulate_gpu_demand(24, 100.0)
    for v in b:
        assert 14.99 <= v <= 100.01


def test_gpu_noncrit_ters():
    """ORTAM-OGRENDI: noncrit = 0.85 - 0.55*day — business-peak'te
    KRITIK-pay artar ( noncrit DUS: 14:00 0.30); gece noncrit 0.85."""
    _, n, _ = _simulate_gpu_demand(24, 100.0)
    assert n[14] == pytest.approx(0.30, abs=0.01)  # day=1 -> 0.30
    assert n[2] == pytest.approx(0.85, abs=0.01)   # day=0 -> 0.85


def test_gpu_noncrit_aralik():
    _, n, _ = _simulate_gpu_demand(24, 100.0)
    assert min(n) == pytest.approx(0.30, abs=0.01)
    assert max(n) == pytest.approx(0.85, abs=0.01)


def test_gpu_sla_clip_aralik():
    """ORTAM-OGRENDI: sla = clip( 0.35*day + 0.10*( h>=20), 0, 1) —
    [0, 0.45] araliginda; 20:00+ sonrasinda +0.10 bonus."""
    _, _, s = _simulate_gpu_demand(24, 100.0)
    for v in s:
        assert 0.0 <= v <= 1.0
    assert max(s) <= 0.46


def test_gpu_sla_gece_bonus():
    """ORTAM: h>=20 -> +0.10 ( 21:00 > 19:00 deger, ayni-day)."""
    _, _, s = _simulate_gpu_demand(24, 100.0)
    day19 = 0.35 * (np.cos((19 - 14.0) / 24.0 * 2.0 * np.pi) * 0.5 + 0.5)
    day21 = 0.35 * (np.cos((21 - 14.0) / 24.0 * 2.0 * np.pi) * 0.5 + 0.5)
    assert s[21] == pytest.approx(float(np.clip(day21 + 0.10, 0, 1)), abs=1e-9)
    assert s[19] == pytest.approx(float(np.clip(day19, 0, 1)), abs=1e-9)


@pytest.mark.parametrize("h,bek", [(0, 20.6939), (2, 15.0), (14, 100.0),
                                   (23, 27.448)])
def test_gpu_backlog_tablo(h, bek):
    """ORTAM: gunluk-dongu degerleri ( 24h, peak=100)."""
    b, _, _ = _simulate_gpu_demand(24, 100.0)
    assert b[h] == pytest.approx(bek, abs=0.05)


def test_gpu_peak_lineer():
    """ORTAM: backlog peak_queue ile DOGRU-ORANTILI."""
    b1, _, _ = _simulate_gpu_demand(24, 100.0)
    b2, _, _ = _simulate_gpu_demand(24, 50.0)
    for i in range(24):
        assert b2[i] == pytest.approx(b1[i] / 2, abs=0.01)


def test_gpu_noncrit_peak_bagimsiz():
    """ORTAM-OGRENDI: noncrit/sla peak_queue'dan BAĞIMSIZ ( sadece
    gunluk-dongu)."""
    _, n1, s1 = _simulate_gpu_demand(24, 100.0)
    _, n2, s2 = _simulate_gpu_demand(24, 500.0)
    assert n1 == n2
    assert s1 == s2


def test_gpu_sifir_peak():
    """ORTAM: peak_queue=0 -> backlog hep 0."""
    b, _, _ = _simulate_gpu_demand(24, 0.0)
    assert all(v == 0.0 for v in b)


def test_gpu_stabil():
    """ORTAM: ayni-girdi ayni-cikti ( DETERMINISTIK)."""
    a = _simulate_gpu_demand(24, 100.0)
    b = _simulate_gpu_demand(24, 100.0)
    assert a[0] == b[0] and a[1] == b[1] and a[2] == b[2]


def test_gpu_48s_iki_gun():
    """ORTAM: 48 saat = 2-gunluk dongu ( b[0]==b[24])."""
    b, _, _ = _simulate_gpu_demand(48, 100.0)
    assert b[0] == pytest.approx(b[24], abs=1e-9)


# == _ipmvp_audit_scenario: temel ====================================================================

def test_ipmvp_donut_sozluk():
    """ORTAM: 11-anahtarli sozluk."""
    scn = _ipmvp_audit_scenario(5)
    assert isinstance(scn, dict)
    assert sorted(scn.keys()) == ["actual", "adjusted_baseline", "ashrae",
                                  "audit_merkle_root", "baseline",
                                  "event_hours", "event_start_hour",
                                  "history", "pre_event_actual_2h_kw",
                                  "ptf", "savings"]


@pytest.mark.parametrize("gun", [3, 5, 10, 30])
def test_ipmvp_history_gunler(gun):
    """ORTAM: history_days gun-sayisi kadar 24-saatlik satir."""
    scn = _ipmvp_audit_scenario(gun)
    assert len(scn["history"]) == gun
    assert all(len(d) == 24 for d in scn["history"])


@pytest.mark.parametrize("gun", [0, 1, 2])
def test_ipmvp_az_gun_hatasi(gun):
    """ORTAM-OGRENDI: history < 3 gun -> ValueError ( 'At least 3
    historical days required' — 10-in-10-baseline istatistik-gereksinimi)."""
    with pytest.raises(ValueError, match="At least 3"):
        _ipmvp_audit_scenario(gun)


def test_ipmvp_event_saatleri():
    """ORTAM-OGRENDI: event SAATLERI 17-20 ( 4-saat; DR-peak-shave)."""
    scn = _ipmvp_audit_scenario(5)
    assert scn["event_hours"] == [17, 18, 19, 20]
    assert scn["event_start_hour"] == 17


def test_ipmvp_actual_kisilma():
    """ORTAM-OGRENDI: event-saatlerinde actual 100 kW KISILDI ( 17:00
    305->205, 18:00 290->190, 19:00 275->175, 20:00 250->150)."""
    scn = _ipmvp_audit_scenario(5)
    a = scn["actual"]
    assert a[17] == pytest.approx(205.0, abs=0.01)
    assert a[18] == pytest.approx(190.0, abs=0.01)
    assert a[19] == pytest.approx(175.0, abs=0.01)
    assert a[20] == pytest.approx(150.0, abs=0.01)


def test_ipmvp_actual_event_disi_dokunulmaz():
    """ORTAM: event-disi saatler base-curve ile ayni."""
    scn = _ipmvp_audit_scenario(5)
    a = scn["actual"]
    for h in [0, 8, 15, 16, 21, 23]:
        assert a[h] != pytest.approx(a[h] - 100)


def test_ipmvp_pre_event_2h():
    """ORTAM: event-oncesi 2-saat ( 15:00, 16:00) actual degerleri."""
    scn = _ipmvp_audit_scenario(5)
    pre = scn["pre_event_actual_2h_kw"]
    assert len(pre) == 2
    assert pre[0] == pytest.approx(scn["actual"][15], abs=1e-9)
    assert pre[1] == pytest.approx(scn["actual"][16], abs=1e-9)


def test_ipmvp_ptf_sabit():
    """ORTAM: PTF tarife 3.80 TL/kWh ( 24-saat sabit)."""
    scn = _ipmvp_audit_scenario(5)
    assert len(scn["ptf"]) == 24
    assert all(v == pytest.approx(3.80, abs=1e-9) for v in scn["ptf"])


def test_ipmvp_baseline_24_saat():
    """ORTAM: adjusted_baseline 24-saat."""
    scn = _ipmvp_audit_scenario(5)
    assert len(scn["baseline"]) == 24
    assert len(scn["adjusted_baseline"]) == 24


# == savings =========================================================================================

def test_ipmvp_savings_anahtarlar():
    """ORTAM: savings 4-anahtarli ( IPMVP Option B)."""
    scn = _ipmvp_audit_scenario(5)
    sv = scn["savings"]
    assert sorted(sv.keys()) == ["net_curtailed_kwh",
                                 "net_financial_savings_try",
                                 "total_actual_kwh", "total_baseline_kwh"]


def test_ipmvp_actual_720_sabit():
    """ORTAM-OGRENDI: actual event-4-saat ( 205+190+175+150=720) —
    history_days'den BAGIMSIZ ( sabit base-curve)."""
    scn = _ipmvp_audit_scenario(5)
    a = scn["actual"]
    assert sum(a[h] for h in scn["event_hours"]) == pytest.approx(
        scn["savings"]["total_actual_kwh"], abs=0.01)
    a10 = _ipmvp_audit_scenario(10)["actual"]
    assert np.array_equal(a, a10)


def test_ipmvp_finansal_savings():
    """ORTAM-OGRENDI: finansal-tasarruf = kisilan-kWh * PTF (
    399.21 kWh * 3.80 TL = 1517.0 TL)."""
    scn = _ipmvp_audit_scenario(5)
    sv = scn["savings"]
    assert sv["net_financial_savings_try"] == pytest.approx(
        sv["net_curtailed_kwh"] * 3.80, abs=0.1)


def test_ipmvp_net_curtailed_konsistans():
    """ORTAM: net_curtailed = baseline - actual."""
    scn = _ipmvp_audit_scenario(5)
    sv = scn["savings"]
    assert sv["net_curtailed_kwh"] == pytest.approx(
        sv["total_baseline_kwh"] - sv["total_actual_kwh"], abs=0.01)


# == ashrae ==========================================================================================

def test_ipmvp_ashrae_anahtarlar():
    """ORTAM: ASHRAE Guideline-14 uyum-anahtarlari."""
    scn = _ipmvp_audit_scenario(5)
    ash = scn["ashrae"]
    assert sorted(ash.keys()) == ["compliance_grade", "cv_rmse_compliant",
                                  "cv_rmse_pct", "cv_rmse_threshold_pct",
                                  "is_ashrae_compliant", "nmbe_compliant",
                                  "nmbe_pct", "nmbe_threshold_pct"]


def test_ipmvp_ashrae_baslangic():
    """ORTAM-OGRENDI: actual[:17]/baseline[:17] ( event-oncesi 17 saat
    ile karsilastirma)."""
    scn = _ipmvp_audit_scenario(5)
    ash = scn["ashrae"]
    assert ash["cv_rmse_threshold_pct"] == 20.0
    assert ash["nmbe_threshold_pct"] == 5.0
    assert ash["is_ashrae_compliant"] is True
    assert ash["compliance_grade"] == "GRADE_A_CERTIFIED"


def test_ipmvp_ashrae_compliant_true():
    scn = _ipmvp_audit_scenario(10)
    assert scn["ashrae"]["is_ashrae_compliant"] is True


# == merkle + determinism ============================================================================

def test_ipmvp_merkle_root():
    """ORTAM: audit-ledger Merkle-koku ( hex-string)."""
    scn = _ipmvp_audit_scenario(5)
    root = scn["audit_merkle_root"]
    assert isinstance(root, str)
    assert len(root) == 64
    assert all(c in "0123456789abcdef" for c in root)
    assert root != _ipmvp_audit_scenario(10)["audit_merkle_root"]


def test_ipmvp_deterministik():
    """ORTAM-OGRENDI: SABIT-TOHUM ( rng default_rng(123)) + sabit-curves
    -> ayni-girdi BYTE-AYNI cikti ( audit/audit-verify/tamga-anchor
    replay-bozulmaz)."""
    a = _ipmvp_audit_scenario(5)
    b = _ipmvp_audit_scenario(5)
    assert a["audit_merkle_root"] == b["audit_merkle_root"]
    assert np.array_equal(a["history"], b["history"])
    assert a["savings"] == b["savings"]


def test_ipmvp_merkle_history_bagli():
    """ORTAM-OGRENDI: merkle-koku history_days'e BAGLI — baseline ( dolayisiyla
    savings) history-noise'undan ETKILENIR ( her-gun farkli; TOHUM-sabittir
    ama tohum-un ciktilari days'le degisir)."""
    r3 = _ipmvp_audit_scenario(3)["audit_merkle_root"]
    r5 = _ipmvp_audit_scenario(5)["audit_merkle_root"]
    r10 = _ipmvp_audit_scenario(10)["audit_merkle_root"]
    assert len({r3, r5, r10}) == 3  # uc-FARKLI


def test_ipmvp_history_degisince_baseline_degisir():
    """ORTAM: history_days degisince baseline degisir ( ama savings
    sabit — yukaridaki merkle-tespiti)."""
    b5 = _ipmvp_audit_scenario(5)["baseline"]
    b10 = _ipmvp_audit_scenario(10)["baseline"]
    assert not np.allclose(b5, b10)


def test_ipmvp_actual_sabit():
    """ORTAM: actual base-curve'dan — history_days'den BAGIMSIZ."""
    a5 = _ipmvp_audit_scenario(5)["actual"]
    a10 = _ipmvp_audit_scenario(10)["actual"]
    assert np.array_equal(a5, a10)


def test_ipmvp_base_curve_24():
    """ORTAM: base-curve 24-saat ( sabit; history'ye +8 std noise)."""
    scn = _ipmvp_audit_scenario(5)
    assert len(scn["history"][0]) == 24
    # base 180-350 araliginda
    for d in scn["history"]:
        assert all(140.0 < v < 400.0 for v in d)


# == karakterizasyon ==================================================================================

def test_gpu_amaci():
    r"""ORTAM-OGRENDI (DOCSTACK): GPU talep-sinyalleri sentetik-gercekci;
    gunluk-dongu ( diurnal: cos(( h-14)/24*2pi)) — 14:00 peak ( jobs
    08:00-18:00), 02:00 drain; backlog = peak*( 0.15+0.85*day) [0.15,1.0]*
    peak; noncrit = 0.85-0.55*day ( business-peak'te kritik-pay artar);
    sla = clip( 0.35*day+0.10*( h>=20), 0,1) — deadline-pressure hump'in
    kuyrugunda; noncrit/sla peak_queue'dan BAGIMSIZ; 155,410-GPU trace
    ( arXiv:2609.05406) inter-hour degiskenligini yansitir. DOSYA-
    YORUMU '0.15 at 04:00' YANLIS — gercek-min 02:00 ( cos=-1 h-14=-12)."""
    b, n, s = _simulate_gpu_demand(24, 100.0)
    assert b[14] == max(b) and b[2] == min(b)
    assert n[14] == pytest.approx(0.30, abs=0.01)
    assert all(0.0 <= v <= 1.0 for v in s)


def test_ipmvp_amaci():
    r"""ORTAM-OGRENDI (DOCSTACK): IPMVP Option B M&V sahne; SABIT-TOHUM
    ( default_rng(123)) + sabit-curves -> audit/audit-verify/tamga-anchor
    byte-ayni replay; event 17-20 ( 4-saat DR-peak-shave 100 kW);
    PTF 3.80 TL/kWh; savings 4-metrik; ASHRAE Guideline-14 ( CVRMSE<%20,
    NMBE<%5) GRADE_A_CERTIFIED; merkle-koku savings'e BAGLI ( history-days
    degisince DEGISIR — savings baseline'in history-noise'undan etkilenir)."""
    scn = _ipmvp_audit_scenario(5)
    assert scn["event_hours"] == [17, 18, 19, 20]
    assert scn["ashrae"]["compliance_grade"] == "GRADE_A_CERTIFIED"
    assert _ipmvp_audit_scenario(5)["audit_merkle_root"] != \
        _ipmvp_audit_scenario(10)["audit_merkle_root"]
