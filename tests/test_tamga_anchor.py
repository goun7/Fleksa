"""
Tamga anchor tests — Fleksa energy measurement proofs on the Tamga hash chain.

Covers the bridge module ``fleksa.audit.tamga_anchor``:

* the Tamga ledger model (genesis / 1-based seq / ``sha256(prev ‖ jcs(rec))``),
* the RFC 8785 JCS canonicalization (cross-language digest determinism),
* measurement-proof anchoring with Merkle cross-anchor integrity,
* tamper detection on both chains,
* JSONL round-trip (fail-closed reload),
* byte-level parity against TamgaProtocol's OWN verifier (``tamga_runner`` /
  ``tamga_canon``) when that sibling tree is present on this machine.
"""

import hashlib
import importlib
import json
import sys
from pathlib import Path

import pytest

from fleksa.audit.ledger import CryptographicSavingsLedger
from fleksa.audit.tamga_anchor import (
    BozukTamgaZinciriError,
    KAYIT_TIPI,
    TAMGA_GENESIS_H,
    OlcumTamgaSabitleyici,
    TamgaLedger,
    jcs,
    jcs_str,
    olcum_kanit_uret,
    sabitle_olcumler,
)

# Sibling open-source protocol tree on this host — used for the external
# (independent-verifier) parity tests. Absent → those tests skip cleanly.
TAMGA_REPO = Path("/home/gokun/projects/05_acik_kaynak/TamgaProtocol")


def _tamga_modul(name: str):
    """Import a module from the sibling TamgaProtocol tree, or skip the test."""
    if not TAMGA_REPO.is_dir():
        pytest.skip(f"TamgaProtocol not found at {TAMGA_REPO}")
    if str(TAMGA_REPO) not in sys.path:
        sys.path.insert(0, str(TAMGA_REPO))
    try:
        return importlib.import_module(name)
    except Exception as exc:  # nacl/dependency absent → skip, never fail
        pytest.skip(f"{name} import edilemedi: {exc}")


def _onar_zincir(ledger: TamgaLedger) -> None:
    """Recompute seq/prev/h so the Tamga chain is internally valid again.

    Test helper for the cross-anchor test: it lets us build a chain that
    Tamga's own rule accepts, but whose *Merkle claims* no longer match the
    recomputed Fleksa Merkle root — proving the cross-anchor layer is not
    subsumed by the hash-chain layer.
    """
    kayitlar = ledger.disa_aktar()
    ledger.entries.clear()
    for rec in kayitlar:
        govde = {k: v for k, v in rec.items() if k not in ("h", "seq", "prev")}
        ledger.append(govde)


# ---------------------------------------------------------------------------
# 1. Tamga ledger model — genesis, 1-based seq, hash rule
# ---------------------------------------------------------------------------
def test_tamga_genesis_ve_seq_kurali():
    """Genesis is 64×'0', seq is 1-based, and h follows Tamga's exact rule."""
    assert TAMGA_GENESIS_H == "0" * 64

    ledger = TamgaLedger()
    assert len(ledger) == 0
    assert ledger.tip() is None
    assert ledger.verify() is True  # empty chain: no claims, no break

    rec1 = ledger.append({"olcum": "h17", "kw": 100.0})
    assert rec1["seq"] == 1
    assert rec1["prev"] == TAMGA_GENESIS_H
    # Tamga D5 kuralı, elle yeniden hesapla:
    govde1 = {"olcum": "h17", "kw": 100.0, "seq": 1, "prev": TAMGA_GENESIS_H}
    assert rec1["h"] == hashlib.sha256(
        (TAMGA_GENESIS_H + jcs_str(govde1)).encode("utf-8")
    ).hexdigest()
    assert len(rec1["h"]) == 64

    rec2 = ledger.append({"olcum": "h18", "kw": 95.5})
    assert rec2["seq"] == 2
    assert rec2["prev"] == rec1["h"]
    govde2 = {"olcum": "h18", "kw": 95.5, "seq": 2, "prev": rec1["h"]}
    assert rec2["h"] == hashlib.sha256(
        (rec1["h"] + jcs_str(govde2)).encode("utf-8")
    ).hexdigest()

    assert ledger.tip() == rec2["h"]
    assert ledger.verify() is True

    # seq/prev/h provided by the caller are overwritten (append-only promise)
    rec3 = ledger.append({"seq": 99, "prev": "deadbeef", "h": "00", "x": 1})
    assert rec3["seq"] == 3
    assert rec3["prev"] == rec2["h"]
    assert rec3["h"] != "00"
    assert ledger.verify() is True


def test_tamga_verify_kirik_zincir_yakalar():
    """A broken seq/prev/hash must fail verify() (fail-open değil)."""
    ledger = TamgaLedger()
    ledger.append({"a": 1})
    ledger.append({"a": 2})

    # prev bağlantısı kopar
    copuk = TamgaLedger()
    copuk.entries = [dict(r) for r in ledger.entries]
    copuk.entries[1]["prev"] = "11" * 32
    assert copuk.verify() is False

    # seq atlanmış
    seq_bozuk = TamgaLedger()
    seq_bozuk.entries = [dict(r) for r in ledger.entries]
    seq_bozuk.entries[1]["seq"] = 7
    assert seq_bozuk.verify() is False

    # hash değiştirilmiş
    h_bozuk = TamgaLedger()
    h_bozuk.entries = [dict(r) for r in ledger.entries]
    h_bozuk.entries[0]["h"] = "22" * 32
    assert h_bozuk.verify() is False


# ---------------------------------------------------------------------------
# 2. RFC 8785 JCS — cross-language digest determinism
# ---------------------------------------------------------------------------
def test_jcs_rfc8785_sayilar_ve_kacislar():
    """ECMAScript number grammar + member order (RFC 8785 §3.2.2.2 / §3.2.3)."""
    # 1.0 → "1" (Python json "1.0" der); 2.93e-07 → "2.93e-7"
    assert jcs(1.0) == b"1"
    assert jcs(2.93e-07) == b"2.93e-7"
    assert jcs(1e16) == b"10000000000000000"
    assert jcs(1e21) == b"1e+21"
    assert jcs(1e-7) == b"1e-7"
    assert jcs(0.000001) == b"0.000001"
    assert jcs(-0.0) == b"0"
    assert jcs(0) == b"0"
    assert jcs(123456.789) == b"123456.789"
    assert jcs(True) == b"true"
    assert jcs(None) == b"null"
    assert jcs("a\"b") == b'"a\\"b"'
    assert jcs("İstanbul") == b'"\xc4\xb0stanbul"'  # raw UTF-8, kaçışlanmaz

    # üye-adları UTF-16 kod-birim sırasına göre (a < b < x)
    nesne = {"b": 1.0, "a": 2.93e-07, "x": [None, True, False, "hı"]}
    assert jcs(nesne) == '{"a":2.93e-7,"b":1,"x":[null,true,false,"hı"]}'.encode("utf-8")

    # I-JSON altkümesi dışı sayılar red (sessiz "null" düşüşü yerine)
    with pytest.raises(ValueError):
        jcs(float("nan"))
    with pytest.raises(ValueError):
        jcs(float("inf"))

    # 2^53 dışı tamsayı red (Node yuvarlar, digest uyuşmaz)
    with pytest.raises(ValueError):
        jcs(2 ** 53 + 1)

    # desteklenmeyen tip red
    with pytest.raises(TypeError):
        jcs(object())


# ---------------------------------------------------------------------------
# 3. ölçüm sabitleme + üç katmanlı doğrulama
# ---------------------------------------------------------------------------
def _senaryo_olcumleri():
    return [
        olcum_kanit_uret(
            tesis_id="tr-ist-eqx-02",
            olay="DR_PEAK_SHAVE",
            olay_id="evt-20261005-peak-01",
            saat=h,
            baseline_kw=320.0 + h,
            actual_kw=220.0 + h,
            tarif_try_kwh=3.80,
        )
        for h in (17, 18, 19, 20)
    ]


def test_olcum_sabitle_ve_dogrula():
    sabitleyici = OlcumTamgaSabitleyici()
    olcumler = _senaryo_olcumleri()

    onceki_h = None
    onceki_kok = None
    for i, olcum in enumerate(olcumler, start=1):
        rec = sabitleyici.sabitle(olcum)
        assert rec["seq"] == i                      # 1-based
        assert rec["prev"] == (TAMGA_GENESIS_H if i == 1 else onceki_h)
        assert rec["tip"] == KAYIT_TIPI
        assert rec["payload"] == olcum              # kanıt aynen taşınır
        assert rec["merkle_kok"] != onceki_kok      # kök her ölçümde büyür
        onceki_h = rec["h"]
        onceki_kok = rec["merkle_kok"]

    assert len(sabitleyici.tamga) == 4
    assert sabitleyici.tamga.verify() is True
    assert sabitleyici.dogrula() is True
    assert sabitleyici.ozet()["dogru"] is True
    assert len(sabitleyici.ozet()["tamga_tip"]) == 64


def test_bos_anchor_dogrulanabilir():
    """Hiç kanıt yoksa doğrulama başarısız-değildir; sadece iddia yoktur."""
    sabitleyici = OlcumTamgaSabitleyici()
    assert sabitleyici.dogrula() is True
    assert sabitleyici.merkle_kok() == hashlib.sha256(b"FLEKSA_EMPTY_LEDGER").hexdigest()


def test_sabitle_fonksiyonu_tek_isik():
    sabitleyici = sabitle_olcumler(_senaryo_olcumleri())
    assert sabitleyici.dogrula() is True
    assert len(sabitleyici.tamga) == 4


# ---------------------------------------------------------------------------
# 4. Merkle çapraz-çapa — iki zincirin değer düzeyinde birleşimi
# ---------------------------------------------------------------------------
def test_merkle_capraz_capa_birebir():
    """Taşınan yaprak/kök, bağımsız bir Fleksa defterinin kilerinin aynısı."""
    olcumler = _senaryo_olcumleri()
    sabitleyici = OlcumTamgaSabitleyici()
    for olcum in olcumler:
        sabitleyici.sabitle(olcum)

    # Aynı ölçümleri bağımsız bir CryptographicSavingsLedger ile oynat
    bagimsiz = CryptographicSavingsLedger()
    for olcum in olcumler:
        yaprak = bagimsiz.append_entry(olcum)
    assert sabitleyici.merkle_kok() == bagimsiz.compute_merkle_root()

    # Her Tamga kaydındaki kök de adım-adım aynı olmalı
    yeniden = CryptographicSavingsLedger()
    for rec in sabitleyici.tamga.entries:
        yaprak = yeniden.append_entry(rec["payload"])
        assert rec["olcum_yaprak"] == yaprak
        assert rec["merkle_kok"] == yeniden.compute_merkle_root()


def test_mevcut_fleksa_defteri_oldugu_gibi_sabitlenir():
    """`fleksa audit`'in ürettiği Merkle defteri zincire bağlanır; kökler aynı."""
    ledger = CryptographicSavingsLedger()
    ledger.append_entry({"event": "DR_PEAK_SHAVE", "savings": {
        "total_baseline_kwh": 1280.0, "total_actual_kwh": 880.0,
        "net_curtailed_kwh": 400.0, "net_financial_savings_try": 1520.0,
    }})
    ledger.append_entry({"event": "DR_FAST", "savings": {"net_curtailed_kwh": 60.0}})

    sabitleyici = OlcumTamgaSabitleyici().sabitle_ledger(ledger)

    assert len(sabitleyici.tamga) == len(ledger.entries) == 2
    assert sabitleyici.merkle_kok() == ledger.compute_merkle_root()
    assert sabitleyici.dogrula() is True
    # kaynak defterin son girdisi zincirde payload olarak okunur
    assert sabitleyici.tamga.entries[-1]["payload"]["event"] == "DR_FAST"


def test_ipmvp_entegrasyonu():
    """Uçtan-uca: IPMVP M&V sonucu + her-saat ölçümleri tek Tamga zincirinde."""
    from fleksa.audit.baseline import IpmvpBaselineEngine

    gunler = [[300.0] * 24 for _ in range(10)]
    baseline = IpmvpBaselineEngine.calculate_10_in_10_baseline(gunler)
    actual = [300.0] * 24
    for h in (17, 18, 19, 20):
        actual[h] = 200.0
    ptf = [3.80] * 24
    event_hours = [17, 18, 19, 20]

    savings = IpmvpBaselineEngine.compute_event_savings(
        adjusted_baseline_kw=baseline,
        actual_meter_kw=actual,
        ptf_tariff_try_kwh=ptf,
        event_hours=event_hours,
    )
    assert savings["net_curtailed_kwh"] == pytest.approx(400.0, abs=1e-6)

    sabitleyici = OlcumTamgaSabitleyici()
    for h in event_hours:
        sabitleyici.sabitle(olcum_kanit_uret(
            tesis_id="tr-ist-eqx-02", olay="DR_PEAK_SHAVE", saat=h,
            baseline_kw=baseline[h], actual_kw=actual[h], tarif_try_kwh=ptf[h],
        ))
    # M&V sonucu (iddia) da aynı zincire: Merkle modeliyle birleşik
    sabitleyici.sabitle({"event": "DR_PEAK_SHAVE", "savings": savings})

    assert sabitleyici.dogrula() is True
    assert len(sabitleyici.tamga) == 5
    ozet = sabitleyici.ozet()
    assert ozet["sabitlenen_olcum"] == 5
    assert ozet["merkle_kok"] == sabitleyici.merkle_kok()


# ---------------------------------------------------------------------------
# 5. kurcalama tespiti — her iki zincirde
# ---------------------------------------------------------------------------
def test_kurcalama_payload_yakalanir():
    """Bir ölçümün payload'ı değiştirilirse hem Tamga hem Merkle katmanı vurur."""
    sabitleyici = OlcumTamgaSabitleyici()
    for olcum in _senaryo_olcumleri():
        sabitleyici.sabitle(olcum)
    assert sabitleyici.dogrula() is True

    sabitleyici.tamga.entries[1]["payload"]["actual_kw"] = 1.0
    assert sabitleyici.tamga.verify() is False     # h artık uyuşmaz
    assert sabitleyici.dogrula() is False


def test_kurcalama_sadece_merkle_kok_yakalanir():
    """Zincir kendi içinde geçerli ama Merkle iddiası yalan → çapraz-çapa yakalar."""
    sabitleyici = OlcumTamgaSabitleyici()
    for olcum in _senaryo_olcumleri():
        sabitleyici.sabitle(olcum)
    assert sabitleyici.dogrula() is True

    # Merkle kökünü şişir ve zinciri DÜZGÜN biçimde yeniden inşa et: Tamga
    # katmanı yeşil kalmalı, ama çapraz-çapa katmanı yakalamalı.
    sabitleyici.tamga.entries[1]["merkle_kok"] = "ab" * 32
    _onar_zincir(sabitleyici.tamga)

    assert sabitleyici.tamga.verify() is True      # Tamga zinciri kendi içinde sağlam
    assert sabitleyici.dogrula() is False          # ama Merkle iddiası uyuşmuyor


def test_eksik_olcum_tamlık_katmaninda_yakalanir():
    """Tüm ölçümler sabitlenmemişse tamlık (completeness) başarısız olur."""
    sabitleyici = OlcumTamgaSabitleyici()
    for olcum in _senaryo_olcumleri()[:2]:
        sabitleyici.sabitle(olcum)

    # anchor 2 ölçüm bildiğini sansın ama zincirde 2 kayıt var — tamlık sağlam
    assert sabitleyici.dogrula() is True

    # bir kaydı dışarıdan ekle (kaynak defterde karşılığı yok)
    dis_ledger = sabitleyici.tamga
    dis_ledger.append({"tip": KAYIT_TIPI, "kaynak": "76-Fleksa/audit-ledger",
                       "kaynak_seq": 3, "olcum_yaprak": "x", "merkle_kok": "y",
                       "payload": {"saat": 21}})
    assert sabitleyici.dogrula() is False


# ---------------------------------------------------------------------------
# 6. JSONL round-trip — fail-closed yeniden yükleme
# ---------------------------------------------------------------------------
def test_jsonl_gidis_donusu(tmp_path):
    sabitleyici = sabitle_olcumler(_senaryo_olcumleri())
    yol = tmp_path / "tamga.jsonl"
    sabitleyici.tamga.jsonl_yaz(yol)

    # çıktı tamga-sim/1 JSONL'dir: her satıl bir tam kayıt
    satirlar = yol.read_text(encoding="utf-8").strip().split("\n")
    assert len(satirlar) == 4
    for line in satirlar:
        rec = json.loads(line)
        assert set(rec) >= {"seq", "prev", "h", "tip", "payload"}

    # fail-closed yeniden yükleme
    yeniden = TamgaLedger()
    yeniden.jsonl_oku(yol)
    assert len(yeniden) == 4
    assert yeniden.verify() is True
    assert yeniden.tip() == sabitleyici.tamga.tip()
    assert [r["payload"] for r in yeniden.entries] == [
        r["payload"] for r in sabitleyici.tamga.entries
    ]

    # anchor, disk'ten yüklenen zincirle de doğrulanır
    anchor2 = OlcumTamgaSabitleyici(tamga=yeniden)
    anchor2._sabitlenen = 4  # kaynak defteri disk'ten değil bellekten biliyoruz
    assert anchor2.dogrula() is True


def test_jsonl_kurcalama_fail_closed(tmp_path):
    sabitleyici = sabitle_olcumler(_senaryo_olcumleri())
    yol = tmp_path / "tamga.jsonl"
    sabitleyici.tamga.jsonl_yaz(yol)

    # İLK kaydın payload'ını değiştir → h uyuşmaz → red, hiçbir kayıt belleğe girmez
    satirlar = yol.read_text(encoding="utf-8").splitlines(keepends=True)
    rec = json.loads(satirlar[0])
    rec["payload"]["actual_kw"] = 1.0
    satirlar[0] = json.dumps(rec, ensure_ascii=False) + "\n"
    yol.write_text("".join(satirlar), encoding="utf-8")

    bozuk = TamgaLedger()
    with pytest.raises(BozukTamgaZinciriError):
        bozuk.jsonl_oku(yol)
    assert len(bozuk) == 0  # fail-closed: bozuk zincir belleğe alınmadı


# ---------------------------------------------------------------------------
# 7. HARİCİ doğrulama — Tamga'nın KENDİ verifier'ında GREEN
# ---------------------------------------------------------------------------
def test_jcs_tamga_canon_ile_bayt_paritesi():
    """Gömülü JCS, TamgaProtocol'ün ``tamga_canon.jcs`` ile bayt-bayt aynı."""
    tamga_canon = _tamga_modul("tamga_canon")

    korpus = [
        {"saat": 17, "baseline_kw": 320.5, "actual_kw": 220.0,
         "tarif": 3.80, "olcum_kesinti_kw": 100.5},
        {"b": 1.0, "a": [None, True, False, 2.93e-07, 1e21, -0.0, 1e16],
         "Z": "x", "é": "y", "ü": {"iç": "dış"}},
        {"s": "İstanbul'da \"ölçüm\" \\ var\t", "n": 123456.789, "z": 0.000001},
        {"arr": [1, 2, [3, [4, {"derin": True}]]], "": "boş-anahtar"},
    ]
    for ornek in korpus:
        assert jcs(ornek) == tamga_canon.jcs(ornek), f"parite-bozuk: {ornek!r}"


def test_tamga_kendi_verifierinda_yesil():
    """Üretilen zincir Tamga'nın BİZE AİT olmayan verifier'ında geçerli.

    ``tamga_runner._verify_chain`` (RFC-003 D5/D7/D8) bizim modülümüzün
    yerine geçer: 1-based seq, prev-bağlantısı ve ``sha256(prev ‖ jcs(rec))``
    kuralını bağımsız olarak uygular ve baş-hash'i döner.
    """
    tamga_runner = _tamga_modul("tamga_runner")

    sabitleyici = sabitle_olcumler(_senaryo_olcumleri())
    kayitlar = sabitleyici.tamga.disa_aktar()

    tip, neden = tamga_runner._verify_chain(kayitlar)
    assert neden == "ok", f"Tamga kendi verifier'ında RED: {neden}"
    assert tip == sabitleyici.tamga.tip()
    assert tip is not None and len(tip) == 64


def test_tamga_kendi_verifierinda_kirmizi_kurcalama():
    """Aynı verifier, kurcalanmış zincirimizi reddetmeli (çift-taraflı test)."""
    tamga_runner = _tamga_modul("tamga_runner")

    sabitleyici = sabitle_olcumler(_senaryo_olcumleri())
    kayitlar = sabitleyici.tamga.disa_aktar()
    kayitlar[2]["payload"]["actual_kw"] = 1.0  # h ile uyuşmaz

    tip, neden = tamga_runner._verify_chain(kayitlar)
    assert tip is None
    assert neden.startswith("broken@")


def test_jsonl_tamga_disk_verifierinda_yesil(tmp_path):
    """Yazılan JSONL, Tamga'nın streaming ledger-verifier'ında geçerli."""
    tamga_runner = _tamga_modul("tamga_runner")

    sabitleyici = sabitle_olcumler(_senaryo_olcumleri())
    yol = Path(sabitleyici.tamga.jsonl_yaz(tmp_path / "fleksa-tamga.jsonl"))

    tip, neden = tamga_runner._ledger_head(yol)
    assert neden == "ok", f"Tamga ledger-verify RED: {neden}"
    assert tip == sabitleyici.tamga.tip()
