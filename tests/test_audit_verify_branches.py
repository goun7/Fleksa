"""
El-yapımı minimal raporlarla audit-verify dal kapsamı (tests/test_audit_verify_branches.py).

tests/test_audit_verify.py, `fleksa audit` ile üretilmiş raporlar üzerinden
uçtan-uca testler kapsar. BU dosya, KENDİ ürettiğimiz minimal girdilerden
el-yapımı raporlar kurarak `audit_verify_cmd`'nin tests/test_audit_verify.py
tarafından dokunulmayan DALLARINI güvenceye alır:

  - el-yapımı rapor (gerçek IpmvpBaselineEngine + CryptographicSavingsLedger
    ile hesaplanmış claim'ler) bağımsız yeniden-hesaplamayı geçer
  - hours_per_day != 24 (12 saatlik günler) dalı
  - structural: history_days uzunluk uyumsuzluğu, ptf uzunluk uyumsuzluğu,
    event_hours aralık-dışı (negatif saat), method imzası IPMVP değil
  - ashrae: nmbe_threshold tahrizi, is_ashrae_compliant bool tahrızı,
    compliance_grade dizge tahrızı, eksik ashrae anahtarları
  - savings: eksik claim anahtarı (nan-karşılaştırma dalı)
  - pre_event_actual_2h_kw: açık değer + varsayılan (actual[start-2:start]) dalı
  - event_start_hour varsayılan (min(event_hours)) dalı
  - out_of_window: nonzero dürüst-açıklama geçer, açıklama yoksa başarısız
  - merkle_root: eksik claim ("" varsayılan) başarısız
  - olmayan rapor dosyası → click exists=True → çıkış 2
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from fleksa.audit.baseline import IpmvpBaselineEngine  # noqa: E402
from fleksa.audit.ledger import CryptographicSavingsLedger  # noqa: E402

_METHOD = "IPMVP Option B / EVO 10001-1:2022 10-in-10 + same-day adjustment"


# ------------------------------------------------------------------ yardımcılar

def _curve(n=24, base=200.0, slope=0.5, mid=12):
    return [round(base + (h - mid) * slope, 6) for h in range(n)]


def _inputs(**over):
    """24 saatlik, tamamen deterministik minimal girdi seti."""
    curve = _curve()
    inp = {
        "history_days": [curve[:] for _ in range(3)],
        "actual_meter_kw": list(curve),
        "ptf_tariff_try_kwh": [round(2.0 + 0.1 * h, 6) for h in range(24)],
        "event_hours": [17, 18, 19, 20],
        "event_start_hour": 17,
        "pre_event_actual_2h_kw": [curve[15], curve[16]],
    }
    inp.update(over)
    return inp


def _claims(inp):
    """audit_verify_cmd'nin kendisinin yaptığı yeniden-hesaplamayı birebir
    taklit eder — böylece el-yapımı raporlar GEÇERli, tahrize uğramış
    raporlar BAŞARISIZ olmalıdır."""
    history = [list(d) for d in inp["history_days"]]
    actual = inp["actual_meter_kw"]
    ptf = inp["ptf_tariff_try_kwh"]
    event_hours = list(inp["event_hours"])
    event_start_hour = int(inp.get("event_start_hour", min(event_hours)))
    pre_event = inp.get(
        "pre_event_actual_2h_kw",
        list(actual[max(0, event_start_hour - 2):event_start_hour]),
    )

    baseline = IpmvpBaselineEngine.calculate_10_in_10_baseline(history)
    adjusted = IpmvpBaselineEngine.apply_same_day_adjustment(
        baseline_hourly_kw=baseline,
        pre_event_actual_2h_kw=pre_event,
        event_start_hour=event_start_hour,
    )
    savings = IpmvpBaselineEngine.compute_event_savings(
        adjusted_baseline_kw=adjusted,
        actual_meter_kw=actual,
        ptf_tariff_try_kwh=ptf,
        event_hours=event_hours,
    )
    ashrae = IpmvpBaselineEngine.evaluate_ashrae_compliance(
        actual=actual[:event_start_hour],
        baseline=adjusted[:event_start_hour],
    )
    ledger = CryptographicSavingsLedger()
    ledger.append_entry({"event": "DR_PEAK_SHAVE", "savings": savings})

    out_of_window = round(float(sum(
        max(0.0, float(adjusted[h]) - float(actual[h]))
        for h in range(len(actual)) if h not in event_hours
    )), 6)

    return {
        "savings": savings,
        "ashrae": ashrae,
        "merkle_root": ledger.compute_merkle_root(),
        "out_of_window_curtailed_kwh": out_of_window,
    }


def _write_report(tmp_path, *, inputs=None, claims=None, method=_METHOD,
                  report_version=1, name="report.json"):
    inp = inputs if inputs is not None else _inputs()
    cl = claims if claims is not None else _claims(inp)
    payload = {
        "report_version": report_version,
        "generated_by": "el-yapimi-test",
        "method": method,
        "inputs": inp,
        "claims": cl,
        "assumptions": {},
    }
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _run_cli(*args):
    """fleksa audit-verify'i aynı süreç modelinde (test_audit_verify.py ile
    aynı kanonik komut) çalıştırır."""
    return subprocess.run(
        [sys.executable, "-m", "fleksa", *args],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        env={"PYTHONPATH": str(ROOT / "src"), "PATH": "/usr/bin:/bin"},
    )


def _verify(path):
    return _run_cli("audit-verify", str(path))


# ------------------------------------------------------------------ başarı yolu

def test_elyapimi_rapor_dogrulanir(tmp_path):
    """Minimal el-yapımı girdilerden hesaplanan claim'ler bağımsız
    yeniden-hesaplamayla birebir eşleşmeli."""
    report = _write_report(tmp_path)
    res = _verify(report)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "VERIFICATION PASSED" in res.stdout


def test_elyapimi_rapor_12_saatlik_gun(tmp_path):
    """hours_per_day != 24: bütün diziler 12 uzunlukta, olay saatleri 0-12'de."""
    curve = _curve(n=12, mid=6)
    inp = {
        "history_days": [curve[:] for _ in range(3)],
        "actual_meter_kw": list(curve),
        "ptf_tariff_try_kwh": [round(2.0 + 0.1 * h, 6) for h in range(12)],
        "event_hours": [5, 6, 7],
        "event_start_hour": 5,
        "pre_event_actual_2h_kw": [curve[3], curve[4]],
        "hours_per_day": 12,
    }
    report = _write_report(tmp_path, inputs=inp)
    res = _verify(report)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "VERIFICATION PASSED" in res.stdout


def test_pre_event_acik_deger_dogrulanir(tmp_path):
    """Olay-öncesi 2 saat açıkça verilirse (±%20 kelepçe içinde ratio != 1)
    ayarlanmış referans değişir; doğru claim yine doğrulanır."""
    inp = _inputs(pre_event_actual_2h_kw=[190.0, 190.0])
    report = _write_report(tmp_path, inputs=inp)
    res = _verify(report)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "VERIFICATION PASSED" in res.stdout


def test_pre_event_varsayilan_dogrulanir(tmp_path):
    """pre_event_actual_2h_kw verilmezse actual[start-2:start] kullanılır."""
    inp = _inputs()
    del inp["pre_event_actual_2h_kw"]
    report = _write_report(tmp_path, inputs=inp)
    res = _verify(report)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "VERIFICATION PASSED" in res.stdout


def test_event_start_hour_varsayilan_dogrulanir(tmp_path):
    """event_start_hour verilmezse min(event_hours) kullanılır."""
    inp = _inputs()
    del inp["event_start_hour"]
    report = _write_report(tmp_path, inputs=inp)
    res = _verify(report)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "VERIFICATION PASSED" in res.stdout


def test_out_of_window_sifirdan_fazla_duzdur(tmp_path):
    """Olay penceresi dışında da kısıntı varsa dürüstçe açıklanmalı ve
    açıklanan değer doğrulanmalı."""
    curve = _curve()
    actual = list(curve)
    actual[5] = 150.0  # olay dışı saatte referansın altına düş
    inp = _inputs(actual_meter_kw=actual)
    cl = _claims(inp)
    assert cl["out_of_window_curtailed_kwh"] > 0.0
    report = _write_report(tmp_path, inputs=inp, claims=cl)
    res = _verify(report)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "VERIFICATION PASSED" in res.stdout


def test_kismi_ashrae_claimleri_dogrulanir(tmp_path):
    """claims.ashrae sadece bazı anahtarları taşıyabilir; eksik anahtarlar
    denetim listesine eklenmez (if key in claimed_ashrae dalı)."""
    inp = _inputs()
    cl = _claims(inp)
    cl["ashrae"] = {"cv_rmse_pct": cl["ashrae"]["cv_rmse_pct"],
                    "is_ashrae_compliant": cl["ashrae"]["is_ashrae_compliant"]}
    report = _write_report(tmp_path, inputs=inp, claims=cl)
    res = _verify(report)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "VERIFICATION PASSED" in res.stdout


# ------------------------------------------------------------------ structural

def test_history_days_uzunluk_uyumsuz(tmp_path):
    """Bir tarih günü 24 yerine 25 saatli → structural denetim devreye girer.

    Uygulama-notu: ``history_days_all_24h`` denetiminin yeniden-hesaplanan
    değeri bir LİSTEDİR; mevcut çıktı çevrimi ``float(list)`` üzerinde
    TypeError ile sonlanır. Önemli olan güvenlik-özelliğidir: uzunluğu
    uyuşmayan bir rapor ASLA doğrulanmamalıdır (çıkış 1, PASSED yok).
    """
    inp = _inputs()
    inp["history_days"] = [d + [0.0] for d in inp["history_days"]]
    report = _write_report(tmp_path, inputs=inp)
    res = _verify(report)
    assert res.returncode == 1
    assert "VERIFICATION PASSED" not in res.stdout


def test_ptf_uzunluk_uyumsuz(tmp_path):
    """Tarif 24 yerine 23 saatli → structural denetim."""
    inp = _inputs()
    inp["ptf_tariff_try_kwh"] = inp["ptf_tariff_try_kwh"][:23]
    report = _write_report(tmp_path, inputs=inp)
    res = _verify(report)
    assert res.returncode == 1
    assert "ptf_length" in res.stdout


def test_event_hours_aralik_disi_negatif(tmp_path):
    """Negatif olay sahi range(0, 24) dışındadır → structural denetim.

    Uygulama-notu: ``event_hours_in_range`` denetiminin yeniden-hesaplanan
    değeri bir LİSTEDİR; mevcut çıktı çevrimi ``float(list)`` üzerinde
    TypeError ile sonlanır. Güvenlik-özelliği: aralık-dışı olay saatli bir
    rapor ASLA doğrulanmamalıdır (çıkış 1, PASSED yok).
    """
    inp = _inputs(event_hours=[-1, 17, 18, 19, 20])
    report = _write_report(tmp_path, inputs=inp)
    res = _verify(report)
    assert res.returncode == 1
    assert "VERIFICATION PASSED" not in res.stdout


def test_method_imzasi_ipmvp_degil(tmp_path):
    """method alanında 'IPMVP' yok → rapor şema-imzası reddedilir."""
    report = _write_report(tmp_path, method="foobar M&V method")
    res = _verify(report)
    assert res.returncode == 1
    assert "method_signature" in res.stdout


# ------------------------------------------------------------------ claim tahrizi

def test_nmbe_threshold_tahrizi(tmp_path):
    inp = _inputs()
    cl = _claims(inp)
    cl["ashrae"]["nmbe_threshold_pct"] = 0.01
    report = _write_report(tmp_path, inputs=inp, claims=cl)
    res = _verify(report)
    assert res.returncode == 1
    assert "nmbe_threshold" in res.stdout


def test_ashrae_uyumlu_bool_tahrizi(tmp_path):
    """Model aslında uygun değil (öncesi saatler %50 sapma) ama claim
    is_ashrae_compliant=True → bool karşılaştırma reddeder."""
    curve = _curve()
    actual = [round(v * 1.5, 6) if h < 17 else v for h, v in enumerate(curve)]
    actual = [150.0 if h in (17, 18, 19, 20) else v for h, v in enumerate(actual)]
    inp = _inputs(actual_meter_kw=actual)
    cl = _claims(inp)
    assert cl["ashrae"]["is_ashrae_compliant"] is False
    cl["ashrae"]["is_ashrae_compliant"] = True
    report = _write_report(tmp_path, inputs=inp, claims=cl)
    res = _verify(report)
    assert res.returncode == 1
    assert "is_ashrae_compliant" in res.stdout


def test_compliance_grade_dizge_tahrizi(tmp_path):
    curve = _curve()
    actual = [round(v * 1.5, 6) if h < 17 else v for h, v in enumerate(curve)]
    actual = [150.0 if h in (17, 18, 19, 20) else v for h, v in enumerate(actual)]
    inp = _inputs(actual_meter_kw=actual)
    cl = _claims(inp)
    assert cl["ashrae"]["compliance_grade"] == "NON_COMPLIANT_MODEL"
    cl["ashrae"]["compliance_grade"] = "GRADE_A_CERTIFIED"
    report = _write_report(tmp_path, inputs=inp, claims=cl)
    res = _verify(report)
    assert res.returncode == 1
    assert "compliance_grade" in res.stdout


def test_savings_claim_anahtari_eksik(tmp_path):
    """Eksik savings anahtarı nan ile karşılaştırılır → asla geçemez."""
    inp = _inputs()
    cl = _claims(inp)
    del cl["savings"]["net_curtailed_kwh"]
    report = _write_report(tmp_path, inputs=inp, claims=cl)
    res = _verify(report)
    assert res.returncode == 1
    assert "savings.net_curtailed_kwh" in res.stdout


def test_merkle_root_claim_eksik(tmp_path):
    """merkle_root yoksa "" varsayılanı gerçek kökle eşleşmez."""
    inp = _inputs()
    cl = _claims(inp)
    del cl["merkle_root"]
    report = _write_report(tmp_path, inputs=inp, claims=cl)
    res = _verify(report)
    assert res.returncode == 1
    assert "merkle_root" in res.stdout


def test_out_of_window_aciklama_eksik(tmp_path):
    """Olay dışı kısıntı var ama açıklanmamış → varsayılan 0.0 çelişir."""
    curve = _curve()
    actual = list(curve)
    actual[5] = 150.0
    inp = _inputs(actual_meter_kw=actual)
    cl = _claims(inp)
    del cl["out_of_window_curtailed_kwh"]
    report = _write_report(tmp_path, inputs=inp, claims=cl)
    res = _verify(report)
    assert res.returncode == 1
    assert "out_of_window" in res.stdout


# ------------------------------------------------------------------ girdi hatası

def test_olmayan_rapor_cikis_2(tmp_path):
    res = _verify(tmp_path / "yok.json")
    assert res.returncode == 2
