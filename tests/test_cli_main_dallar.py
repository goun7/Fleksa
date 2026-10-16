"""Dal-kesen (branch-cutting) testler — :mod:`fleksa.cli.main` (779 satır).

Xunit tarzı: her public komut/fonksiyon için başarı + başarısızlık + sınır
dalları ``class TestX`` içinde kesilir. Dallar docstring'lerde listelenir ve
``Test`` ile biten metot adlarına yansır.

Kapsam (public API):
  - ``main`` (click group) — ``version``, ``solve``, ``verify-policy``,
    ``monte-carlo``, ``audit``, ``audit-verify``, ``tamga-anchor``, ``canary``,
    ``arbitrage-gate``, ``openadr``, ``modbus``, ``credential``, ``benchmark``,
    ``ui``
  - yardımcılar: ``_simulate_gpu_demand``, ``_ipmvp_audit_scenario``

Saf in-memory'dir: ``click.testing.CliRunner`` alt-process AÇMAZ; dosya
yazma/okuma yalnızca ``tmp_path`` altında; ``ui`` komutu gerçek sunucu
başlatmaz (``run_server`` monkeypatch ile stub'lanır).
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest
from click.testing import CliRunner

from fleksa.cli.main import (
    _ipmvp_audit_scenario,
    _simulate_gpu_demand,
    main,
)

# ``fleksa.cli.__init__`` grup ``main``'i yeniden ihraç ettiğü için
# ``import fleksa.cli.main as X`` Group döndürür; gerçek modülü sys.modules
# üzerinden alırız (``--benchmark`` monkeypatch'i için).
_CLI_MOD = sys.modules["fleksa.cli.main"]

# ``tests`` bir paket olduğundan kardeş test modülünden imza-yardımcısı alınır
# (mevcut ``tests/test_cli.py`` ile aynı yol; düzenleme YOK).
from tests.test_policy_verifier import create_signed_policy_yaml

RUNNER = CliRunner()


# --------------------------------------------------------------------- yardımcılar


def _imzali_politika(tmp_path: Path, priv_hex: str) -> Path:
    """Geçerli imzalı flex-policy YAML'i ``tmp_path`` altına yazar."""
    yol = tmp_path / "politika.yaml"
    yol.write_text(create_signed_policy_yaml(priv_hex), encoding="utf-8")
    return yol


def _rapor_yaz(tmp_path: Path, payload: dict) -> Path:
    yol = tmp_path / "rapor.json"
    yol.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return yol


def _haneli_rapor(tmp_path: Path) -> dict:
    """``audit --report`` ile üretilen ham rapor yükünü döner."""
    yol = tmp_path / "rapor.json"
    RUNNER.invoke(main, ["audit", "--history-days", "5", "--report", str(yol)])
    return json.loads(yol.read_text(encoding="utf-8"))


# ===================================================================== version


class TestVersionCmd:
    """``version`` — başarı dalı (diğer dallar: group dispatch, no-args help)."""

    def test_version_bilgisi(self):
        """Başarı: çıkış motor adını ve sürümünü içerir."""
        res = RUNNER.invoke(main, ["version"])
        assert res.exit_code == 0
        assert "Fleksa Engine" in res.output

    def test_help_dallari(self):
        """Sınır: ``--help`` tüm alt-komutları listeler (exit 0, gösterir)."""
        res = RUNNER.invoke(main, ["--help"])
        assert res.exit_code == 0
        for alt in ("solve", "audit", "tamga-anchor", "monte-carlo", "canary"):
            assert alt in res.output


# ===================================================================== solve


class TestSolveCmd:
    """``solve`` dalları: GPU-flex seçimi, dinamik kap, hata yolu,
    benchmark işleme (dolgu/boş/bozuk), JSON/prose çıkış, saat sınırı."""

    def test_varsayilan_basarili(self):
        """Başarı: varsayılan parametrelerle OPTIMAL."""
        res = RUNNER.invoke(main, ["solve", "--hours", "12", "--battery-soc", "150"])
        assert res.exit_code == 0
        assert "Optimization Status: OPTIMAL" in res.output
        assert "Expected Savings" in res.output

    def test_json_cikisi(self):
        """Başarı: ``--json-output`` makine-okunur JSON verir."""
        res = RUNNER.invoke(main, ["solve", "--hours", "6", "--json-output"])
        assert res.exit_code == 0
        veri = json.loads(res.output)
        assert veri["status"] == "OPTIMAL"
        assert veri["expected_savings_try"] > 0.0
        assert "soc_trajectory_kwh" in veri

    @pytest.mark.parametrize("mod", ["dynamic", "fixed"])
    def test_gpu_flex_secenegi(self, mod: str):
        """Başarı dalı ×2: ``--gpu-flex dynamic|fixed`` profileyici seçer."""
        res = RUNNER.invoke(main, ["solve", "--hours", "6", "--gpu-flex", mod])
        assert res.exit_code == 0
        assert "OPTIMAL" in res.output
        if mod == "dynamic":
            assert "GPU Flexibility: DYNAMIC_DEMAND_BASED" in res.output

    @pytest.mark.parametrize("kap", [0.36, 0.50, 0.94])
    def test_dinamik_gpu_kap_aralikta(self, kap: float):
        """Başarı dalı ×3: ``--dynamic-gpu-cap`` [0.35, 0.95] içinde."""
        res = RUNNER.invoke(main, ["solve", "--hours", "6", "--dynamic-gpu-cap", str(kap)])
        assert res.exit_code == 0
        assert "OPTIMAL" in res.output

    def test_dinamik_gpu_kap_aralik_disi(self):
        """Başarısızlık dalı: ``--dynamic-gpu-cap 0.99`` → SystemExit(1) + mesaj."""
        res = RUNNER.invoke(main, ["solve", "--hours", "4", "--dynamic-gpu-cap", "0.99"])
        assert res.exit_code == 1
        assert "Solver parameter error" in res.output
        assert "0.99" in res.output

    def test_gpu_kap_min_buyuktur_max(self):
        """Başarısızlık dalı: min > max → SystemExit(1) + doğrulama mesajı."""
        res = RUNNER.invoke(main, ["solve", "--hours", "4",
                                   "--gpu-cap-min", "0.9", "--gpu-cap-max", "0.4"])
        assert res.exit_code == 1
        assert "Solver parameter error" in res.output

    def test_benchmark_dosyasi_dolgu_yapar(self, tmp_path):
        """Sınır: benchmark kayıtları saatten azsa son değerle doldurulur."""
        yol = tmp_path / "bench.json"
        json.dump({"records": [{"ptf": 2100, "smf": 2000},
                               {"ptf": 2200, "smf": 2100}]},
                  open(yol, "w"))
        res = RUNNER.invoke(main, ["solve", "--hours", "8",
                                   "--benchmark-file", str(yol), "--json-output"])
        assert res.exit_code == 0
        assert json.loads(res.output)["status"] == "OPTIMAL"

    def test_benchmark_bos_kayitlar(self, tmp_path):
        """Sınır: ``records: []`` → 2.5 TRY/MWh'lik öntanımlı dolgu kullanılır."""
        yol = tmp_path / "bos.json"
        json.dump({"records": []}, open(yol, "w"))
        res = RUNNER.invoke(main, ["solve", "--hours", "4",
                                   "--benchmark-file", str(yol), "--json-output"])
        assert res.exit_code == 0
        assert json.loads(res.output)["status"] == "OPTIMAL"

    def test_benchmark_bozuk_json_dusser(self, tmp_path):
        """Başarısızlık dalı: ayrıştırma hatası → öntanımlı profile düşer
        (graceful degradation; command yine de çözer)."""
        yol = tmp_path / "bozuk.json"
        yol.write_text("{not valid json", encoding="utf-8")
        res = RUNNER.invoke(main, ["solve", "--hours", "4",
                                   "--benchmark-file", str(yol), "--json-output"])
        assert res.exit_code == 0
        assert json.loads(res.output)["status"] == "OPTIMAL"

    def test_benchmark_olmayan_dosya(self):
        """Başarısızlık dalı: ``click.Path(exists=True)`` rc=2 ile reddeder."""
        res = RUNNER.invoke(main, ["solve", "--benchmark-file", "/yok/bench.json"])
        assert res.exit_code == 2

    @pytest.mark.parametrize("saat", [1, 12, 23, 24])
    def test_saat_sinirlari_basarili(self, saat: int):
        """Sınır dalı ×4: 1 ≤ hours ≤ 24 öntanımlı profile ile çözer."""
        res = RUNNER.invoke(main, ["solve", "--hours", str(saat), "--json-output"])
        assert res.exit_code == 0
        assert json.loads(res.output)["status"] == "OPTIMAL"

    def test_saat_24_fazlasi_cokmeli_bulgu(self):
        """BULGU-2 (DÜZELTILDI — FL-FLEKSA-1, 2026-10-14):

        Oneski (gerçek bug): ``solve_cmd`` ``--hours > 24`` için
        yakalanamayan ``IndexError`` ile çöker::

            IndexError: index 24 is out of bounds for axis 0 with size 24

        Kök neden: ``pv_gen`` öntanımlı profili 24 elemanlı sabit liste ve
        ``[:hours]`` dilimi 24'ü geçemez; ``base_load``/``temp`` hours-dolu,
        ``ptf`` pad'li — yalnızca ``pv_gen`` 24-saatte kilitli kalıyordu.

        FIX: ``pv_list = _pv[:hours]`` + son-değerle-doldurma (ptf pad-deseni
        ile aynı). 48 saatlik "receding horizon" artık çalışır; hours<=24'te
        davranış değişmez. xfail KALDIRILDI (düzeltme kanıtlandı).
        """

        res = RUNNER.invoke(main, ["solve", "--hours", "48", "--json-output"])
        assert res.exit_code == 0
        assert "OPTIMAL" in res.output
        assert res.exception is None


# ===================================================== _simulate_gpu_demand


class TestSimulateGpuDemand:
    """``_simulate_gpu_demand(hours, peak_queue)`` — şekil, diurnal dalga,
    oran aralıkları ve SLA klip dalları."""

    def test_sekilleri_ve_uzunluk(self):
        """Başarı: backlog/noncrit/sla her biri ``hours`` uzunluğundadır."""
        backlog, noncrit, sla = _simulate_gpu_demand(24, 750_000.0)
        assert len(backlog) == 24 and len(noncrit) == 24 and len(sla) == 24
        # saf Python listeleridir (JSON serileştirmesi için)
        assert isinstance(backlog, list) and isinstance(noncrit, list)
        assert isinstance(sla, list)

    @pytest.mark.parametrize("saat, pahalilik", [(2, 0.15), (14, 1.0)])
    def test_diurnal_dalga_sinirlari(self, saat: int, pahalilik: float):
        """Sınır dalı ×2: gece 02:00 backlog oranı 0.15 (minimum), 14:00 ise
        1.0 (zirve) — öntanımlı zamanlama fonksiyonunun uç değerleri."""
        backlog, _, _ = _simulate_gpu_demand(24, 750_000.0)
        assert backlog[saat] / 750_000.0 == pytest.approx(pahalilik)

    def test_backlog_doygunluk_dali(self):
        """Sınır: kuyruk gün ortasında ``peak_queue`` değerine doygunlaşır."""
        backlog, _, _ = _simulate_gpu_demand(24, 750_000.0)
        assert backlog[14] == 750_000.0
        assert backlog[23] < backlog[14]

    def test_noncrit_sla_araliklarinda(self):
        """Başarı: noncrit [0.30, 0.85], sla [0.0, 0.35] aralığındadır."""
        _, noncrit, sla = _simulate_gpu_demand(24, 750_000.0)
        assert min(noncrit) == pytest.approx(0.30, abs=1e-9)
        assert max(noncrit) == pytest.approx(0.85, abs=1e-9)
        assert min(sla) == pytest.approx(0.0, abs=1e-9)
        assert max(sla) == pytest.approx(0.35, abs=1e-9)

    def test_bosluk_kuyrugu_sifir_dali(self):
        """Sınır: ``peak_queue=0.0`` → backlog tüm gün sıfır.

        Gözlem: SLA payı kuyruk büyüklüğünden bağımsızdır (zamanlama
        fonksiyonu ile [0.0, 0.35] aralığında kalır) — yani sıfır kuyruk
        bile SLA için sıfır olmayan bir pay bırakabilir.
        """
        backlog, noncrit, sla = _simulate_gpu_demand(24, 0.0)
        assert all(v == 0.0 for v in backlog)
        assert 0.0 <= min(sla) and max(sla) <= 0.35
        assert max(sla) > 0.0
        assert min(noncrit) == pytest.approx(0.30, abs=1e-9)

    def test_tek_saat_siniri(self):
        """Sınır: ``hours=1`` → skaler değil, uzunluğu 1 olan diziler."""
        backlog, noncrit, sla = _simulate_gpu_demand(1, 100_000.0)
        assert len(backlog) == 1 and len(noncrit) == 1 and len(sla) == 1
        assert 0.0 <= backlog[0] <= 100_000.0

    def test_determinizma(self):
        """Başarı: saf fonksiyon — aynı girdi ikinci çağrıda birebir aynı."""
        a = _simulate_gpu_demand(12, 500_000.0)
        b = _simulate_gpu_demand(12, 500_000.0)
        assert all(np.allclose(x, y) for x, y in zip(a, b))


# ============================================================= verify-policy


class TestVerifyPolicyCmd:
    """``verify-policy`` dalları: imza atlama ile geçerlilik,
    ayrıştırma hatası, olmayan dosya (click exists)."""

    def test_gecerli_politika(self, tmp_path, ed25519_keypair):
        """Başarı: imzalı politika ``--skip-signature`` ile geçerlidir."""
        yol = _imzali_politika(tmp_path, ed25519_keypair["private_hex"])
        res = RUNNER.invoke(main, ["verify-policy", str(yol), "--skip-signature"])
        assert res.exit_code == 0
        assert "is valid and all safety guards passed" in res.output

    def test_bozuk_yaml_basarisiz(self, tmp_path):
        """Başarısızlık dalı: geçersiz YAML → SystemExit(1) + mesaj."""
        yol = tmp_path / "kot.yaml"
        yol.write_text("invalid_yaml: [", encoding="utf-8")
        res = RUNNER.invoke(main, ["verify-policy", str(yol)])
        assert res.exit_code != 0
        assert "Verification failed" in res.output

    def test_olmayan_dosya_reddedilir(self):
        """Başarısızlık dalı: ``click.Path(exists=True)`` rc=2 verir."""
        res = RUNNER.invoke(main, ["verify-policy", "/yok/politika.yaml"])
        assert res.exit_code == 2


# ============================================================= monte-carlo


class TestMonteCarloCmd:
    """``monte-carlo`` dalları: metrikler, seed determinizması,
    tek-çalıştırma sınırı."""

    def test_metrikler_basarili(self):
        """Başarı: P50/P90/CVaR ve kayıp olasılığı raporlanır."""
        res = RUNNER.invoke(main, ["monte-carlo", "--runs", "100"])
        assert res.exit_code == 0
        assert "Simulation Complete" in res.output
        assert "P50 (Median)" in res.output
        assert "Loss Probability" in res.output

    def test_ayni_seed_deterministik(self):
        """Başarı dalı: aynı ``--seed`` birebir aynı çıktıyı verir."""
        a = RUNNER.invoke(main, ["monte-carlo", "--runs", "50", "--seed", "7"])
        b = RUNNER.invoke(main, ["monte-carlo", "--runs", "50", "--seed", "7"])
        assert a.output == b.output

    def test_farkli_seed_farkli(self):
        """Başarı dalı: farklı seed farklı örnekleme (yasadışı-sync kontrolü)."""
        a = RUNNER.invoke(main, ["monte-carlo", "--runs", "50", "--seed", "7"])
        b = RUNNER.invoke(main, ["monte-carlo", "--runs", "50", "--seed", "99"])
        assert a.output != b.output

    def test_tek_calistirma_siniri(self):
        """Sınır: ``--runs 1`` dahi tam rapor üretir (bölme-sıfır dalı yok)."""
        res = RUNNER.invoke(main, ["monte-carlo", "--runs", "1"])
        assert res.exit_code == 0
        assert "P50 (Median)" in res.output


# ================================================== _ipmvp_audit_scenario


class TestIpmvpAuditScenario:
    """``_ipmvp_audit_scenario(history_days)`` — yapı, determinizma, gün
    sayısı sınırı."""

    def test_anahtar_yapisi(self):
        """Başarı: senaryo IPMVP için tüm gerekli anahtarları taşır."""
        scn = _ipmvp_audit_scenario(5)
        for anahtar in ("actual", "adjusted_baseline", "ashrae", "audit_merkle_root",
                        "baseline", "event_hours", "history", "ptf", "savings"):
            assert anahtar in scn

    def test_sabit_olay_pencereli(self):
        """Sınır: olay saatleri her zaman [17, 18, 19, 20]'dir."""
        scn = _ipmvp_audit_scenario(3)
        assert scn["event_hours"] == [17, 18, 19, 20]

    def test_tasarruf_alt_anahtarlari(self):
        """Başarı: ``savings`` dört IPMVP alt-iddiasını taşır."""
        scn = _ipmvp_audit_scenario(5)
        assert set(scn["savings"]) >= {"net_curtailed_kwh", "net_financial_savings_try",
                                       "total_actual_kwh", "total_baseline_kwh"}
        # net tasarruf, gerçekleştirilen − baz hatası (negatif olamaz)
        assert scn["savings"]["net_curtailed_kwh"] > 0.0

    @pytest.mark.parametrize("gun", [3, 5, 14])
    def test_gecmis_gun_sayisi_siniri(self, gun: int):
        """Sınır dalı ×3: ``history_days`` kadar geçmiş gün, her biri 24 saat."""
        scn = _ipmvp_audit_scenario(gun)
        assert len(scn["history"]) == gun
        for gun_serisi in scn["history"]:
            assert len(gun_serisi) == 24

    def test_minimum_gecmis_gun_altinda_deger(self):
        """Başarısızlık dalı: ``history_days=2`` → ValueError (baseline motoru
        en az 3 gün ister); ``--hours``/``--history-days`` alt sınırı = 3.

        Gözlem: değer CLI katmanında doğrulanmaz; traceback (rc=1) olarak
        yansır — temiz bir doğrulama mesajı yerine.
        """
        with pytest.raises(ValueError, match="At least 3 historical days"):
            _ipmvp_audit_scenario(2)

    def test_determinizma(self):
        """Başarı: saf fonksiyon — iki çağrı birebir aynı (numpy dizileri
        dahil)."""
        a = _ipmvp_audit_scenario(5)
        b = _ipmvp_audit_scenario(5)
        assert set(a) == set(b)
        assert json.dumps(a["savings"], sort_keys=True) == json.dumps(b["savings"], sort_keys=True)
        assert a["audit_merkle_root"] == b["audit_merkle_root"]
        assert a["event_hours"] == b["event_hours"]
        for anahtar in ("actual", "adjusted_baseline", "baseline", "ptf", "history"):
            assert np.allclose(np.asarray(a[anahtar]), np.asarray(b[anahtar]))

    def test_merkle_kok_tutarlisi(self):
        """Başarı: ``audit_merkle_root`` deterministik 64-hex SHA-256'dır."""
        scn = _ipmvp_audit_scenario(5)
        assert isinstance(scn["audit_merkle_root"], str)
        assert len(scn["audit_merkle_root"]) == 64
        assert all(c in "0123456789abcdef" for c in scn["audit_merkle_root"])


# ===================================================================== audit


class TestAuditCmd:
    """``audit`` dalları: prose çıktı, ``--report`` yazımı, rapor yapısı."""

    def test_prose_cikisi(self):
        """Başarı: IPMVP Option B başlığı + ASHRAE CV(RMSE) raporu."""
        res = RUNNER.invoke(main, ["audit", "--history-days", "4"])
        assert res.exit_code == 0
        assert "IPMVP Option B Audit Results:" in res.output
        assert "ASHRAE 14 CV(RMSE)" in res.output

    def test_rapor_dosyasi_yazilir(self, tmp_path):
        """Başarı: ``--report`` diske yazar ve onaylar."""
        res = RUNNER.invoke(main, ["audit", "--history-days", "5"])
        yol = tmp_path / "rapor.json"
        res = RUNNER.invoke(main, ["audit", "--history-days", "5",
                                   "--report", str(yol)])
        assert res.exit_code == 0
        assert "Verifiable report written" in res.output
        assert yol.exists()

    def test_rapor_yapisi(self, tmp_path):
        """Başarı: rapor ipmvp-report şemasının tüm üst-anahatarlarını taşır."""
        payload = _haneli_rapor(tmp_path)
        assert set(payload) == {"assumptions", "claims", "generated_by",
                                "inputs", "method", "report_version"}
        assert payload["report_version"] == 1
        assert "IPMVP" in payload["method"]
        assert set(payload["claims"]) == {"ashrae", "merkle_root",
                                          "out_of_window_curtailed_kwh", "savings"}

    def test_rapor_girdi_kaydedilir(self, tmp_path):
        """Başarı: ``inputs`` bağımsız yeniden-hesaplamayı sağlar (veri
        bütünlüğü için kanıt)."""
        payload = _haneli_rapor(tmp_path)
        inp = payload["inputs"]
        assert len(inp["actual_meter_kw"]) == 24
        assert len(inp["ptf_tariff_try_kwh"]) == 24
        assert inp["event_hours"] == [17, 18, 19, 20]
        assert len(inp["history_days"]) == 5

    def test_pencere_disi_aciklama(self, tmp_path):
        """Başarı: ``out_of_window_curtailed_kwh`` materiality disclosure'u
        mevcuttur (sayısal 0 olabilir ama ANAHTAR her zaman vardır)."""
        payload = _haneli_rapor(tmp_path)
        assert "out_of_window_curtailed_kwh" in payload["claims"]
        assert isinstance(payload["claims"]["out_of_window_curtailed_kwh"], float)

    def test_minimum_altinda_gecmis_gun_rc2(self, tmp_path):
        """DUZELTILDI BULGU-2 — ``audit`` kolu: ``--history-days 2`` → rc=2 +
        okunur mesaj; sahte "Computing IPMVP" banner'ı YOK ve rapor dosyası
        OLUŞMAZ (yarım-denetim-deligi bırakmaz).

        ESKİ davranış: motorun ``ValueError``'ı yakalanmadan ham traceback
        olarak dökülüyordu (rc=1).
        """
        yol = tmp_path / "rapor.json"
        res = RUNNER.invoke(main, ["audit", "--history-days", "2", "--report", str(yol)])
        assert res.exit_code == 2
        assert "Invalid --history-days=2" in res.output
        assert "Computing IPMVP" not in res.output
        assert not yol.exists()


# ============================================================== audit-verify


class TestAuditVerifyCmd:
    """``audit-verify`` dalları: geçerli → PASSED; tahriz → FAILED (rc=1);
    eksik girdi → rc=2; şema (hours_per_day / method / version / negatif
    tariff) denetimleri.

    NOT: ``history_days``/``event_hours`` uzunluk-uymuşuzluğunda
    ``recomputed`` değerinin bir LİSTE olması ``float(list)`` TypeError'ına
    yol açar — bu DAVRANIŞ ``tests/test_audit_verify_branches.py`` içinde
    zaten "uygulama-notu" olarak belgelenmiştir (fail-closed: rc=1,
    PASSED yok). Burada benzer davranışı tekrarlamayıp örtüşmemesi için
    yalnızca temiz ✗ satırı üreten ek şema dalları kesilir.
    """

    def test_gecerli_rapor_gecer(self, tmp_path):
        """Başarı: elle üretilmiş rapor bağımsız yeniden-hesaplamayla eşleşir."""
        yol = _rapor_yaz(tmp_path, _haneli_rapor(tmp_path))
        res = RUNNER.invoke(main, ["audit-verify", str(yol)])
        assert res.exit_code == 0
        assert "VERIFICATION PASSED" in res.output

    def test_tasarruf_tahrizi_basarisiz(self, tmp_path):
        """Başarısızlık dalı: ``net_curtailed_kwh`` tahrizi → rc=1 + FAILED."""
        payload = copy.deepcopy(_haneli_rapor(tmp_path))
        payload["claims"]["savings"]["net_curtailed_kwh"] = 999.0
        res = RUNNER.invoke(main, ["audit-verify", str(_rapor_yaz(tmp_path, payload))])
        assert res.exit_code == 1
        assert "VERIFICATION FAILED" in res.output
        assert "net_curtailed_kwh" in res.output

    def test_merkle_kok_tahrizi_basarisiz(self, tmp_path):
        """Başarısızlık dalı: ``merkle_root`` tahrizi → rc=1 + FAILED."""
        payload = copy.deepcopy(_haneli_rapor(tmp_path))
        payload["claims"]["merkle_root"] = "a" * 64
        res = RUNNER.invoke(main, ["audit-verify", str(_rapor_yaz(tmp_path, payload))])
        assert res.exit_code == 1
        assert "merkle_root" in res.output

    def test_girdi_eksik_cikis_2(self, tmp_path):
        """Başarısızlık dalı: zorunlu girdi eksik → SystemExit(2) (tahriz
        değil, format hatası)."""
        payload = copy.deepcopy(_haneli_rapor(tmp_path))
        payload["inputs"].pop("event_hours")
        res = RUNNER.invoke(main, ["audit-verify", str(_rapor_yaz(tmp_path, payload))])
        assert res.exit_code == 2
        assert "missing required inputs" in res.output

    def test_ucden_az_gecmis_gun_rc2(self, tmp_path):
        """DUZELTILDI BULGU-2 (`audit-verify` kolu): 3'ten az geçmiş günü olan
        rapor → rc=2 + okunur mesaj; eskiden baseline motorunun yakalanmayan
        ``ValueError``'ı ham traceback olarak dökülüyordu (rc=1).

        Kanıt (motor sözleşmesi değişmedi): ``_ipmvp_audit_scenario(2)`` hâlâ
        ``ValueError`` fırlatır — yani red baseline motorundan GELİYORDU ve CLI
        sınırı onu kullanıcı-adına çeviriyor.
        """
        payload = copy.deepcopy(_haneli_rapor(tmp_path))
        payload["inputs"]["history_days"] = payload["inputs"]["history_days"][:2]
        res = RUNNER.invoke(main, ["audit-verify", str(_rapor_yaz(tmp_path, payload))])
        assert res.exit_code == 2
        assert "at least 3 are required" in res.output
        assert "VERIFICATION PASSED" not in res.output
        with pytest.raises(ValueError):
            _ipmvp_audit_scenario(2)

    def test_olmayan_rapor_cikis_2(self):
        """Başarısızlık dalı: ``click.Path(exists=True)`` rc=2 verir."""
        res = RUNNER.invoke(main, ["audit-verify", "/yok/rapor.json"])
        assert res.exit_code == 2

    def test_saat_basi_gun_uyumsuz(self, tmp_path):
        """Şema dalı: ``hours_per_day`` 24 yerine 20 → ``actual_meter_kw`` 24
        saatlik geldiği için structural denetim ``actual_meter_kw_length``
        eklenir ve tahriz reddedilir.

        NOT: Aynı zammanda ``history_days_all_24h`` denetimi de ateşlenir ve
        onun yeniden-hesaplanan değeri bir LİSTEDİR; bu, bilinen
        ``float(list)`` TypeError davranışıdır ve
        ``tests/test_audit_verify_branches.py``'de "uygulama-notu" olarak
        belgelendiği için burada tekrar derinlemesine kesilmez. Bu test
        yalnızca güvenlik özelliğini (fail-closed: rc=1, PASSED YOK) doğrular.
        """
        payload = copy.deepcopy(_haneli_rapor(tmp_path))
        payload["inputs"]["hours_per_day"] = 20
        res = RUNNER.invoke(main, ["audit-verify", str(_rapor_yaz(tmp_path, payload))])
        assert res.exit_code == 1
        assert "VERIFICATION PASSED" not in res.output

    def test_nmbe_threshold_tahrizi(self, tmp_path):
        """Şema dalı: ``nmbe_threshold_pct`` tahrizi → temiz ✗ satırı + rc=1."""
        payload = copy.deepcopy(_haneli_rapor(tmp_path))
        payload["claims"]["ashrae"]["nmbe_threshold_pct"] = 0.01
        res = RUNNER.invoke(main, ["audit-verify", str(_rapor_yaz(tmp_path, payload))])
        assert res.exit_code == 1
        assert "nmbe_threshold" in res.output
        assert "VERIFICATION FAILED" in res.output

    def test_metot_imzasi_ipmvp_degil(self, tmp_path):
        """Şema dalı: ``method`` içinde 'IPMVP' yok → imza ✗ + rc=1."""
        payload = copy.deepcopy(_haneli_rapor(tmp_path))
        payload["method"] = "baska yontem"
        res = RUNNER.invoke(main, ["audit-verify", str(_rapor_yaz(tmp_path, payload))])
        assert res.exit_code == 1
        assert "method_signature" in res.output

    def test_rapor_surumu_geri_cekme(self, tmp_path):
        """Şema dalı: ``report_version != 1`` → ✗ + rc=1."""
        payload = copy.deepcopy(_haneli_rapor(tmp_path))
        payload["report_version"] = 2
        res = RUNNER.invoke(main, ["audit-verify", str(_rapor_yaz(tmp_path, payload))])
        assert res.exit_code == 1
        assert "report_version" in res.output

    def test_negatif_tarif_yeniden_hesaplamayla_yakalanir(self, tmp_path):
        """Şema dalı: negatif tarif → ``tariff_non_negative`` ✗; ayrıca
        yeniden-hesaplanan tasarruf negatife döner (claim mismatch)."""
        payload = copy.deepcopy(_haneli_rapor(tmp_path))
        payload["inputs"]["ptf_tariff_try_kwh"] = [-1.0] * 24
        res = RUNNER.invoke(main, ["audit-verify", str(_rapor_yaz(tmp_path, payload))])
        assert res.exit_code == 1
        assert "tariff_non_negative" in res.output
        assert "VERIFICATION PASSED" not in res.output


# ============================================================= tamga-anchor


class TestTamgaAnchorCmd:
    """``tamga-anchor`` dalları: prose, JSON çıkışı, ``--ledger`` JSONL
    (fail-closed geri-yüklemeyle doğrulanır)."""

    def test_prose_cikisi(self):
        """Başarı: zincir başı, doğrulama YES ve katman özetleri."""
        res = RUNNER.invoke(main, ["tamga-anchor", "--history-days", "5"])
        assert res.exit_code == 0
        assert "Tamga chain head" in res.output
        assert "Anchor verified:    YES" in res.output

    def test_json_cikisi(self):
        """Başarı: JSON çıkışı tamga-sim/1 meta anahtarlarını taşır."""
        res = RUNNER.invoke(main, ["tamga-anchor", "--json-output"])
        assert res.exit_code == 0
        veri = json.loads(res.output)
        for anahtar in ("audit_merkle_root", "dogrulandi", "kaynak", "merkle_kok",
                        "olcum_sayisi", "tamga_format", "tamga_tip"):
            assert anahtar in veri
        assert veri["dogrulandi"] is True
        assert veri["olcum_sayisi"] > 0

    def test_ledger_jsonl_yazilir_ve_dogrulanir(self, tmp_path):
        """Başarı: ``--ledger`` JSONL yazar ve satır sayısı ölçüm sayısına
        eşittir; geri-yükleme fail-closed doğrulamasıyla zinciri kabul eder.
        """
        yol = tmp_path / "ledger.jsonl"
        res = RUNNER.invoke(main, ["tamga-anchor", "--history-days", "5",
                                   "--ledger", str(yol)])
        assert res.exit_code == 0
        assert yol.exists()

        # bağımsız geri-yükleme: her kayıt seq/prev/h ile doğrulanmalıdır
        from fleksa.audit.tamga_anchor import TamgaLedger
        geri = TamgaLedger()
        geri.jsonl_oku(yol)
        assert len(geri) == 5
        assert geri.verify() is True
        # tip() zincir baş-hash'idir (64-hex), format dizesi değil
        assert isinstance(geri.tip(), str) and len(geri.tip()) == 64

    def test_determinizma(self):
        """Başarı: aynı girdi aynı Merkle kökünü üretir (sabitleme
        tekrar-oynatılabilir)."""
        a = RUNNER.invoke(main, ["tamga-anchor", "--json-output"])
        b = RUNNER.invoke(main, ["tamga-anchor", "--json-output"])
        assert json.loads(a.output)["merkle_kok"] == json.loads(b.output)["merkle_kok"]

    def test_minimum_gecmis_gun(self):
        """Sınır: ``--history-days 3`` dahi tam 5 kayıt (4 olay saati + 1
        tasarruf çapası) sabitler — ölçüm sayısı history_days'e bağlı değildir.
        """
        res = RUNNER.invoke(main, ["tamga-anchor", "--history-days", "3", "--json-output"])
        assert res.exit_code == 0
        assert json.loads(res.output)["olcum_sayisi"] == 5

    def test_minimum_altinda_gecmis_gun_coker(self):
        """DUZELTILDI BULGU-2 — başarısızlık dalı: ``--history-days 2`` → rc=2 +
        okunur doğrulama mesajı; sahte "hesaplanıyor" banner'ı YOK.

        ESKİ davranış (pin'lenen hata): değer CLI katmanında doğrulanmazdı,
        baseline motorunun ``ValueError``'sı ham traceback olarak kullanıcıya
        dökülüyordu (rc=1 + ``res.exception is ValueError``). Artık CLI sınırı
        girdi-hatasını adıyla söyler ve tahriz-format convention'ıyla rc=2 ile
        fail-closed çıkar (``audit-verify``'in "eksik girdi" rc=2'siyle aynı).
        Motor sözleşmesi DEĞİŞMEDİ: ``_ipmvp_audit_scenario(2)`` hâlâ
        ``ValueError`` fırlatır (aşağıdaki ``TestIpmvpAuditScenario`` pini).
        """
        res = RUNNER.invoke(main, ["tamga-anchor", "--history-days", "2", "--json-output"])
        assert res.exit_code == 2
        assert isinstance(res.exception, SystemExit)
        assert "Invalid --history-days=2" in res.output
        # fail-closed sırası: geçersiz girdi için ilerleme-banner'ı basılmaz
        assert "Computing IPMVP" not in res.output
        assert "merkle_kok" not in res.output


# ===================================================================== canary


class TestCanaryCmd:
    """``canary`` dalları: triangulation consensus başarısı / başarısızlığı."""

    def test_consensus_basarili(self):
        """Başarı: üç kaynak yakın değerde → quorum doğrulanır."""
        res = RUNNER.invoke(main, ["canary", "--epias", "2500", "--teias", "2480",
                                   "--regional", "2450"])
        assert res.exit_code == 0
        assert "Triangulation Canary Quorum Verified" in res.output

    def test_consensus_reddedilir(self):
        """Başarısızlık dalı: kaynaklar dağılırsa → SystemExit(1) + mesaj."""
        res = RUNNER.invoke(main, ["canary", "--epias", "1000", "--teias", "5000",
                                   "--regional", "9000"])
        assert res.exit_code != 0
        assert "Canary consensus rejected" in res.output


# ============================================================ arbitrage-gate


class TestArbitrageGateCmd:
    """``arbitrage-gate`` dalları: Theorem 1 değerlendirmesi,
    kârlı / kârsız kararlar."""

    def test_karli_arbitraj(self):
        """Başarı: deşarj fiyatı şarj fiyatının 5 katı → PROFITABLE."""
        res = RUNNER.invoke(main, ["arbitrage-gate", "--charge", "1.0",
                                   "--discharge", "5.0"])
        assert res.exit_code == 0
        assert "Theorem 1 Arbitrage Gate Evaluation" in res.output
        assert "PROFITABLE_ARBITRAGE" in res.output

    def test_karsiz_arbitraj(self):
        """Başarısızlık dalı: eşit fiyatlar → NO arbitrage karar satırı."""
        res = RUNNER.invoke(main, ["arbitrage-gate", "--charge", "4.0",
                                   "--discharge", "4.1"])
        assert res.exit_code == 0
        assert "Verdict" in res.output
        assert "PROFITABLE_ARBITRAGE" not in res.output


# ===================================================================== openadr


class TestOpenadrCmd:
    """``openadr`` dalları: OADR event üretimi ve opt-in kararı."""

    def test_opt_in_event(self):
        """Başarı: 120 kW kesinti %70 SOC ile OPT_IN OadrCreatedOptEvent."""
        res = RUNNER.invoke(main, ["openadr", "--curtail-kw", "120", "--soc-pct", "70"])
        assert res.exit_code == 0
        assert "OadrCreatedOptEvent" in res.output
        assert "OPT_IN" in res.output

    @pytest.mark.parametrize("kesinti,soc", [(120.0, 70.0), (0.0, 70.0), (120.0, 5.0)])
    def test_karar_dallari(self, kesinti: float, soc: float):
        """Başarı dalı ×3: her kesiti/SOC birleşiminde iyi biçimli bir event
        üretilir (``opt_type`` her zaman raporlanır; bu ASIL durumlarda
        OPT_IN'dir)."""
        res = RUNNER.invoke(main, ["openadr", "--curtail-kw", str(kesinti),
                                   "--soc-pct", str(soc)])
        assert res.exit_code == 0
        # çıkış bir "✓ OpenADR VEN Response:" başlığı + JSON gövdesinden oluşur
        veri = json.loads(res.output[res.output.index("{"):])
        assert veri["opt_type"] == "OPT_IN"
        assert veri["response_type"] == "OadrCreatedOptEvent"
        assert "OadrCreatedOptEvent" in res.output


# ===================================================================== modbus


class TestModbusCmd:
    """``modbus`` dalları: SunSpec register üretimi + ADU frame."""

    def test_register_uretimi(self):
        """Başarı: ADU frame'i ve modbus modeli üretilir."""
        res = RUNNER.invoke(main, ["modbus", "--power-pct", "75", "--mode", "CHARGE",
                                   "--setpoint-kw", "150"])
        assert res.exit_code == 0
        assert "SunSpec Modbus TCP Generation" in res.output
        assert "ADU Frame" in res.output

    def test_guc_yuzdesi_sinirlari(self):
        """Sınır: ``--power-pct`` 0 ile 100 arasında klemplenir (alt/üst)."""
        alt = RUNNER.invoke(main, ["modbus", "--power-pct", "-50", "--mode", "CHARGE",
                                   "--setpoint-kw", "10"])
        ust = RUNNER.invoke(main, ["modbus", "--power-pct", "250", "--mode", "DISCHARGE",
                                   "--setpoint-kw", "10"])
        assert alt.exit_code == 0 and ust.exit_code == 0
        assert "ADU Frame" in alt.output and "ADU Frame" in ust.output

    @pytest.mark.parametrize("mod", ["CHARGE", "DISCHARGE", "AUTO", "DISABLED"])
    def test_mod_dallari(self, mod: str):
        """Başarı dalı ×4: her geçerli çalışma modu bir ADU frame üretir."""
        res = RUNNER.invoke(main, ["modbus", "--power-pct", "50", "--mode", mod,
                                   "--setpoint-kw", "100"])
        assert res.exit_code == 0
        assert "ADU Frame" in res.output

    def test_gecersiz_mod_reddedilir(self):
        """Başarısızlık dalı: ``--mode IDLE`` → click.Choice rc=2 ile reddeder."""
        res = RUNNER.invoke(main, ["modbus", "--power-pct", "50", "--mode", "IDLE",
                                   "--setpoint-kw", "100"])
        assert res.exit_code == 2
        assert "not one of" in res.output


# ================================================================ credential


class TestCredentialCmd:
    """``credential`` dalları: Ed25519 anahtar üretimi, VC imzası,
    kriptografik doğrulama (öntanımlı + FLEKSA_FACILITY_KEY env)."""

    def test_varsayilan_anahtar_pass(self):
        """Başarı: öntanımlı anahtarla VC üretilir ve doğrulanır."""
        res = RUNNER.invoke(main, ["credential", "--facility-id", "test-facility-01",
                                   "--curtailed-kwh", "300"])
        assert res.exit_code == 0
        assert "VerifiableCredential" in res.output
        assert "Cryptographic Verification: PASS" in res.output

    def test_env_anahtari_pass(self, monkeypatch):
        """Başarı: ``FLEKSA_FACILITY_KEY`` env ile anahtar döner (okuma dalı)."""
        monkeypatch.setenv("FLEKSA_FACILITY_KEY", "ab" * 32)
        res = RUNNER.invoke(main, ["credential", "--facility-id", "tr-ist-eqx-02",
                                   "--curtailed-kwh", "100"])
        assert res.exit_code == 0
        assert "Cryptographic Verification: PASS" in res.output

    def test_gecerli_kimlik_yapisi(self):
        """Başarı: VC ``id`` ve ``proof`` (imza) alanlarını taşır."""
        res = RUNNER.invoke(main, ["credential", "--curtailed-kwh", "50"])
        assert res.exit_code == 0
        assert '"id"' in res.output
        assert '"proof"' in res.output


# ================================================================ benchmark


class TestBenchmarkCmd:
    """``benchmark`` dalları: veri seti var/yok. Ortak yardımcı modül
    sabitini ``monkeypatch`` ile değiştirerek sınır dalları kesilir."""

    def test_veri_seti_ozeti(self):
        """Başarı: öntanımlı EPIAŞ veri seti özetlenir."""
        res = RUNNER.invoke(main, ["benchmark"])
        assert res.exit_code == 0
        assert "EPIAŞ Benchmark Dataset" in res.output

    def test_veri_seti_yok_bulgu(self, monkeypatch):
        """DUZELTILDI BULGU-3: ``benchmark`` veri seti yoksa artık rc=1.

        ESKİ davranış (pin'lenen hata): ``✗ Benchmark file not found.`` yazıp
        ``return`` ediyordu → **exit code 0**. ``fleksa benchmark && sonraki-adim``
        zincirleri bozuk/eksik veri setini sessizce "başarı" sayıyordu
        (fail-open). Artık modülün diğer hata yollarıyla aynı idiyom: ✗ + rc=1.
        """
        from fleksa.cli import main as mod
        monkeypatch.setattr(_CLI_MOD, "DEFAULT_BENCHMARK_PATH",
                            Path("/tmp/fleksa_bench_yok_2026.json"))
        res = RUNNER.invoke(main, ["benchmark"])
        assert res.exit_code == 1
        assert "Benchmark file not found." in res.output

    def test_veri_seti_var_rc0(self, monkeypatch, tmp_path):
        """BULGU-3 regresyon sınırı: aynı komut VERİ SETİ VARKE hâlâ rc=0 ve
        özet basar — düzeltme yalnızca yok-dalını sertleştirir.
        """
        bench = tmp_path / "bench.json"
        bench.write_text(json.dumps({"records": [
            {"ptf": 2000000, "smf": 2100000, "day": "2026-01-01"},
            {"ptf": 2400000, "smf": 2500000, "day": "2026-01-02"},
        ]}), encoding="utf-8")
        monkeypatch.setattr(_CLI_MOD, "DEFAULT_BENCHMARK_PATH", bench)
        res = RUNNER.invoke(main, ["benchmark"])
        assert res.exit_code == 0
        assert "EPIAŞ Benchmark Dataset" in res.output


# ===================================================================== ui


class TestUiCmd:
    """``ui`` dalları: cockpit sunucusu argümanları (gerçek sunucu
    AÇILMAZ — ``run_server`` monkeypatch ile stub'lanır, saf in-memory)."""

    def test_sunucu_argumanlari(self, monkeypatch):
        """Başarı: ``--port``/``--host`` run_server'a iletilir."""
        from fleksa.server import app as server_mod
        cagri: dict = {}

        def _sahte_run_server(port: int, bind_address: str) -> None:
            cagri["port"] = port
            cagri["host"] = bind_address

        monkeypatch.setattr(server_mod, "run_server", _sahte_run_server)
        res = RUNNER.invoke(main, ["ui", "--port", "8099", "--host", "0.0.0.0"])
        assert res.exit_code == 0
        assert "Starting Fleksa Cockpit" in res.output
        assert cagri == {"port": 8099, "host": "0.0.0.0"}

    def test_ontanimli_argumanlar(self, monkeypatch):
        """Sınır: port/host verilmezse öntanımlılar iletilir."""
        from fleksa.server import app as server_mod
        cagri: dict = {}

        monkeypatch.setattr(
            server_mod, "run_server",
            lambda port, bind_address: cagru_ekle(cagri, port, bind_address),
        )
        res = RUNNER.invoke(main, ["ui"])
        assert res.exit_code == 0
        assert "port" in cagri and "host" in cagri


def cagru_ekle(cagri: dict, port: int, bind_address: str) -> None:
    """``test_ontanimli_argumanlar`` için lambda-safe yardımcı."""
    cagri["port"] = port
    cagri["host"] = bind_address


# ------------------------------------------------------------------ genel tarama


class TestGroupDallari:
    """``main`` click group'unun kendine özgü dalları."""

    def test_bilinmeyen_komut(self):
        """Başarısızlık dalı: bilinmeyen komut rc=2 + UsageError mesajı."""
        res = RUNNER.invoke(main, ["bilmemne-komut"])
        assert res.exit_code == 2
        assert "No such command" in res.output

    def test_argumansiz_yardim(self):
        """Sınır: argümansız çağrı kullanım/yardım metnini gösterir (rc=2)."""
        res = RUNNER.invoke(main, [])
        assert res.exit_code == 2
        assert "Commands:" in res.output
        assert "solve" in res.output

    def test_tum_komutlar_bulunur(self):
        """Başarı: group 14 alt-komutu kaydetmiştir (kayıt/dağıtım dalı)."""
        isimler = set(main.commands)
        beklenen = {"version", "solve", "verify-policy", "monte-carlo", "audit",
                    "audit-verify", "tamga-anchor", "canary", "arbitrage-gate",
                    "openadr", "modbus", "credential", "benchmark", "ui"}
        assert beklenen <= isimler
        assert len(isimler) == 14


# Modül düzeyinde pytest'in CliRunner'ı alt-process kullanmaz; tmp_path ve
# monkeypatch ile dosya/çevre etkileşimi test sonunda otomatık temizlenir.
if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-o", "addopts=", "-q"]))
