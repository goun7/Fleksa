"""
test_tamga_anchor_cmd_dal.py — Dal-kesen testler: tamga_anchor_cmd, es_number, yukle

Hedeflenen test-disi fonksiyonlar (src/fleksa):
  * cli/main.py:586 tamga_anchor_cmd        (57L) — zincir: Tamga hash-zinciri sabitleme CLI
  * audit/tamga_anchor.py:128 es_number      (31L) — kanonik: RFC 8785 §3.2.2.2 sayı serileştirme
  * audit/tamga_anchor.py:373 yukle          (30L) — güvenlik: fail-closed zincir yükleyici

KURAL: SADECE YENI DOSYA; mevcut testleri/kodu DEĞİŞTIRMEZ. Harici çağrı
yok (ağ/DNS/hiber dal-kesilir); fonksiyonların kendi mantığı test edilir.
"""

import json

import pytest
from click.testing import CliRunner

from fleksa.audit.tamga_anchor import (
    TAMGA_GENESIS_H,
    BozukTamgaZinciriError,
    OlcumTamgaSabitleyici,
    TamgaLedger,
    es_number,
    jcs,
    olcum_kanit_uret,
)
from fleksa.cli.main import main


# ---------------------------------------------------------------------------
# 1. es_number — RFC 8785 §3.2.2.2 (ECMAScript Number.prototype.toString)
# ---------------------------------------------------------------------------
class TestEsNumber:
    """Kanonik serileştirme — TamgaProtocol ile bayt-uyumlu olma kritik."""

    def test_es_number_tamsayi_trailing_sifir_atar(self):
        # 1.0 → "1" (ECMAScript trailing-zero kuralı)
        assert es_number(1.0) == "1"

    def test_es_number_sifir_negatif_sifir(self):
        # 0 ve -0.0 ikisi de "0" (ECMAScript "0" basar)
        assert es_number(0.0) == "0"
        assert es_number(-0.0) == "0"

    def test_es_number_kucuk_ussu_notasyon(self):
        # 2.93e-07 → "2.93e-7" (§3.2.2.2 üs kısaltma)
        assert es_number(2.93e-07) == "2.93e-7"

    def test_es_number_buyuk_tamsayi_gecis(self):
        # 1e16 → "10000000000000000" (k <= n <= 21 → sabit-gösterim)
        assert es_number(1e16) == "10000000000000000"

    def test_es_number_cok_buyuk_ussu(self):
        # 1e21 → "1e+21" (n > 21 → üssü gösterim)
        assert es_number(1e21) == "1e+21"

    def test_es_number_negatif_deger(self):
        assert es_number(-1.5) == "-1.5"
        assert es_number(-0.0001) == "-0.0001"

    def test_es_number_kesirli_orta_aralik(self):
        # 0 < n <= 21 → s[:n] + "." + s[n:]
        assert es_number(12.5) == "12.5"
        assert es_number(3.14) == "3.14"

    def test_es_number_nan_reddeder(self):
        # I-JSON altkümesi (RFC 7493): NaN reddedilir
        with pytest.raises(ValueError, match="ijson_number_not_finite"):
            es_number(float("nan"))

    def test_es_number_infinity_reddeder(self):
        with pytest.raises(ValueError, match="ijson_number_not_finite"):
            es_number(float("inf"))
        with pytest.raises(ValueError, match="ijson_number_not_finite"):
            es_number(float("-inf"))

    def test_es_number_jcs_ile_tutarli(self):
        # es_number float'lar için jcs çıktısı bire-bayt aynı olmalı
        for deger in [1.0, 0.0, -0.0, 2.93e-07, 1e16, 1e21, 3.14, -1.5]:
            assert jcs(deger) == es_number(deger).encode("utf-8")


# ---------------------------------------------------------------------------
# 2. TamgaLedger.yukle — fail-closed zincir yeniden-kurma
# ---------------------------------------------------------------------------
def _dogru_zincir(n: int = 3) -> list:
    """Doğru seq/prev/h içeren geçerli bir Tamga zinciri üret."""
    led = TamgaLedger()
    for i in range(n):
        led.append({"tip": "olcum_kanit", "saat": i, "deger": float(i)})
    return led.disa_aktar()


class TestTamgaLedgerYukle:
    """Güvenlik-kritik: bozuk zincir belleğe HİÇ girmez."""

    def test_yukle_gecerli_zinciri_almali(self):
        kayitlar = _dogru_zincir(3)
        led = TamgaLedger()
        led.yukle(kayitlar)
        assert len(led) == 3
        assert led.verify() is True

    def test_yukle_bos_liste(self):
        led = TamgaLedger()
        led.yukle([])
        assert len(led) == 0
        assert led.verify() is True

    def test_yukle_jsonl_roundtrip(self, tmp_path):
        kayitlar = _dogru_zincir(4)
        led = TamgaLedger()
        led.yukle(kayitlar)
        yol = led.jsonl_yaz(tmp_path / "tamga.jsonl")

        led2 = TamgaLedger()
        led2.jsonl_oku(yol)
        assert len(led2) == 4
        assert led2.verify() is True
        # bayt-düzeyi aynı olmalı (disa_aktar kopyası)
        assert led2.disa_aktar() == kayitlar

    def test_yukle_bozuk_seq_reddeder(self):
        kayitlar = _dogru_zincir(3)
        kayitlar[1]["seq"] = 99
        led = TamgaLedger()
        with pytest.raises(BozukTamgaZinciriError, match="seq-sırası bozuk"):
            led.yukle(kayitlar)
        # fail-closed: BOZUK kayıt (seq=99) belleğe alınmamış olmalı
        assert all(rec["seq"] != 99 for rec in led.entries)

    def test_yukle_eksik_alan_reddeder(self):
        kayitlar = _dogru_zincir(2)
        del kayitlar[1]["h"]
        led = TamgaLedger()
        with pytest.raises(BozukTamgaZinciriError):
            led.yukle(kayitlar)
        # bozuk kayıt (h'siz) alınmamış
        assert all("h" in rec for rec in led.entries)

    def test_yukle_tip_eksik_alan_reddeder(self):
        kayitlar = _dogru_zincir(2)
        kayitlar[0]["prev"] = 1234  # str değil
        led = TamgaLedger()
        with pytest.raises(BozukTamgaZinciriError):
            led.yukle(kayitlar)
        # tip-yanlış ilk kayıt dahi alınmamış
        assert len(led) == 0

    def test_yukle_bozuk_prev_reddeder(self):
        kayitlar = _dogru_zincir(3)
        kayitlar[2]["prev"] = "a" * 64  # yanlış prev
        led = TamgaLedger()
        with pytest.raises(BozukTamgaZinciriError, match="prev-bağlantısı bozuk"):
            led.yukle(kayitlar)
        # bozuk kayıt (yanlış prev'li seq-3) alınmamış
        assert all(rec["seq"] != 3 for rec in led.entries)

    def test_yukle_bozuk_hash_reddeder(self):
        kayitlar = _dogru_zincir(3)
        kayitlar[1]["h"] = "b" * 64  # kurcalanmış hash
        led = TamgaLedger()
        with pytest.raises(BozukTamgaZinciriError, match="h-doğrulaması başarısız"):
            led.yukle(kayitlar)
        # kurcalanmış hash'li kayıt alınmamış
        assert all(rec["h"] != "b" * 64 for rec in led.entries)

    def test_yukle_kurcalanan_kayit_verify_false(self):
        # yukle tüm kayıtları alır ama verify() kurcalamayı yakalar
        kayitlar = _dogru_zincir(3)
        led = TamgaLedger()
        led.yukle(kayitlar)
        assert led.verify() is True
        led.entries[1]["payload"] = {"KURCALANDI": True}
        assert led.verify() is False

    def test_yukle_genesis_prev_kontrol(self):
        # İlk kaydın prev'i TAMGA_GENESIS_H olmalı
        kayitlar = _dogru_zincir(2)
        kayitlar[0]["prev"] = "1" * 64
        led = TamgaLedger()
        with pytest.raises(BozukTamgaZinciriError, match="prev-bağlantısı bozuk"):
            led.yukle(kayitlar)

    def test_yukle_append_uzerine_zinciri_devam_ettirir(self):
        led = TamgaLedger()
        led.append({"x": 1.0})
        kalan = _dogru_zincir(0)
        # elle seq=2 ile devam ekle
        led2 = TamgaLedger()
        led2.append({"x": 1.0})
        rec2 = {"x": 2.0, "seq": 2, "prev": led2.entries[-1]["h"], "h": ""}
        govde = {k: v for k, v in rec2.items()}
        rec2["h"] = TamgaLedger._hashla(2, rec2["prev"], govde)
        led2.yukle([rec2])
        assert len(led2) == 2
        assert led2.verify() is True

    def test_genesis_sabit(self):
        # sabit: ilk kayıt 64×'0' genesis
        led = TamgaLedger()
        led.append({"a": 1})
        assert led.entries[0]["prev"] == TAMGA_GENESIS_H
        assert len(TAMGA_GENESIS_H) == 64
        assert set(TAMGA_GENESIS_H) == {"0"}


# ---------------------------------------------------------------------------
# 3. tamga_anchor_cmd — CLI: Tamga hash-zincirine sabitleme
# ---------------------------------------------------------------------------
class TestTamgaAnchorCmd:
    """zincir: `fleksa tamga-anchor` komutu (dal kesme: filesystem tmp_path)."""

    def test_tamga_anchor_cmd_prose_cikti(self):
        runner = CliRunner()
        result = runner.invoke(main, ["tamga-anchor", "--history-days", "3"])
        assert result.exit_code == 0
        assert "anchored to the Tamga hash chain" in result.output
        assert "Anchor verified:    YES" in result.output

    def test_tamga_anchor_cmd_json_output(self):
        runner = CliRunner()
        result = runner.invoke(
            main, ["tamga-anchor", "--history-days", "3", "--json-output"]
        )
        assert result.exit_code == 0
        veri = json.loads(result.output)
        assert veri["tamga_format"] == "tamga-sim/1"
        assert veri["dogrulandi"] is True
        assert veri["kaynak"] == "76-Fleksa/audit-ledger"
        # her event-hour + 1 savings girdisi sabitlenmiş olmalı
        assert veri["olcum_sayisi"] >= 1
        # 64-hex Merkle kökü
        assert len(veri["merkle_kok"]) == 64
        int(veri["merkle_kok"], 16)  # geçerli hex
        assert veri["audit_merkle_root"]  # audit claim bağlantısı taşınıyor

    def test_tamga_anchor_cmd_ledger_jsonl_yazar(self, tmp_path):
        ledger = tmp_path / "anchor.jsonl"
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "tamga-anchor",
                "--history-days",
                "3",
                "--ledger",
                str(ledger),
                "--json-output",
            ],
        )
        assert result.exit_code == 0
        veri = json.loads(result.output)
        assert veri["ledger_jsonl"] == str(ledger)
        # JSONL satırları ayrıştırılabilir ve kendi-kendine doğrulanabilir
        satirlar = [s for s in ledger.read_text(encoding="utf-8").splitlines() if s]
        assert len(satirlar) == veri["olcum_sayisi"]
        kayitlar = [json.loads(s) for s in satirlar]
        # tamga-sim/1 gramer: seq/prev/h her kayıtta
        for n, rec in enumerate(kayitlar, start=1):
            assert rec["seq"] == n
            assert "prev" in rec and "h" in rec
        # tamga zinciri bağımsız yeniden-doğrulanabilir
        kontrol = TamgaLedger()
        kontrol.yukle(kayitlar)
        assert kontrol.verify() is True

    def test_tamga_anchor_cmd_facility_id_kaydedilir(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["tamga-anchor", "--history-days", "3", "--facility-id", "tr-test-42"],
        )
        assert result.exit_code == 0
        # facility_id ölçüm-kanıtı payload'ına yansımali — ledger ile doğrula
        ledger = tmp_path / "fac.jsonl"
        r2 = runner.invoke(
            main,
            [
                "tamga-anchor",
                "--history-days",
                "3",
                "--facility-id",
                "tr-test-42",
                "--ledger",
                str(ledger),
            ],
        )
        assert r2.exit_code == 0
        import json as _json
        kayitlar = [_json.loads(s) for s in ledger.read_text(encoding="utf-8").splitlines() if s]
        tesisler = {rec["payload"].get("tesis") for rec in kayitlar if "payload" in rec}
        assert "tr-test-42" in tesisler

    def test_tamga_anchor_cmd_deterministik_ayni_merkle(self):
        # Aynı history-days → aynı Merkle kökü (tekrar-oynatılabilir kanıt)
        r1 = CliRunner().invoke(
            main, ["tamga-anchor", "--history-days", "3", "--json-output"]
        )
        r2 = CliRunner().invoke(
            main, ["tamga-anchor", "--history-days", "3", "--json-output"]
        )
        assert r1.exit_code == 0 and r2.exit_code == 0
        assert json.loads(r1.output)["merkle_kok"] == json.loads(r2.output)["merkle_kok"]


# ---------------------------------------------------------------------------
# 4. entegrasyon: olcum_kanit_uret + sabitle + dogrula (zincir tutarlılık)
# ---------------------------------------------------------------------------
class TestOlcumKanitAnchorTutarlilik:
    def test_sabitle_dogrula_ve_ozet(self):
        sab = OlcumTamgaSabitleyici()
        for h in range(3):
            sab.sabitle(
                olcum_kanit_uret(
                    tesis_id="tr-ist-eqx-02",
                    olay="DR_PEAK_SHAVE",
                    saat=h,
                    baseline_kw=200.0 + h,
                    actual_kw=150.0 + h,
                    tarif_try_kwh=3.5,
                )
            )
        assert sab.dogrula() is True
        oz = sab.ozet()
        assert oz["sabitlenen_olcum"] == 3
        assert oz["tamga_format"] == "tamga-sim/1"
        assert oz["dogru"] is True
        assert len(oz["merkle_kok"]) == 64

    def test_sabitle_kurcalama_yakalanir(self):
        # Tamga zincirinde bir payload değiştirilirse dogrula False döner
        sab = OlcumTamgaSabitleyici()
        for h in range(2):
            sab.sabitle(
                olcum_kanit_uret(
                    tesis_id="tr-x",
                    olay="DR_PEAK_SHAVE",
                    saat=h,
                    baseline_kw=200.0,
                    actual_kw=150.0,
                    tarif_try_kwh=3.5,
                )
            )
        assert sab.dogrula() is True
        sab.tamga.entries[0]["payload"]["actual_kw"] = 999.0
        assert sab.dogrula() is False
