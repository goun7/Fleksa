"""tamga_anchor dal-kesen testleri — HER public fonksiyon için başarı/başarısızlık/sınır dalları.

Kapsanan modül: ``fleksa.audit.tamga_anchor`` (567 satır). Bu dosya YALNIZCA
dal-kesim (branch-cutting) amaçlıdır; mevcut ``tests/test_tamga_anchor.py`` ve
``tests/test_tamga_anchor_cmd_dal.py`` dosyalarına DOKUNMAZ.

Kapsanan public semboller ve dal listesi (docstring'de talep edildiği üzere):

* ``es_number`` — NaN/+inf/-inf reddi; x==0 (−0.0 dahil); negatif önek;
  k<=n<=21 (büyük tamsayı); 0<n<=21 (olağan ondalık); −6<n<=0 (küçük ondalık);
  else üslü; k==1 vs k>1 mantis; e>=0 vs e<0 üs işareti.
* ``jcs`` / ``jcs_str`` — None/True/False/int/float/str/dict/list/tuple;
  bool alt-sınıf savunma dalı; kaçış karakterleri; <0x20 kontrol karakterleri;
  ham UTF-8 (non-ASCII kaçışlanmaz); UTF-16-BE üye-adı sıralaması;
  ±2^53 I-JSON tamsayı sınırı; desteklenmeyen tip → TypeError.
* ``_json_saf_yap`` — dict/list/tuple/bool/int/float/str/None; numpy ndarray;
  numpy generic; geri-dönüş str(). İÇEREN: np.float64 tip-sızıntı BUG'ı (xfail).
* ``olcum_kanit_uret`` — normal kesinti; actual>baseline → 0; eşit → 0;
  olay_id var/yok; 6-ondalık yuvarlama; tip zorlaması.
* ``TamgaLedger`` — genesis/seq/prev/h ataması; append override; verify True +
  3 False dalı (seq/prev/h); yukle geçerli + 6 hata dalı; disa_aktar kopya
  izolasyonu; tip; jsonl_yaz/jsonl_oku gidis-dönüşü + boş-satır.
* ``OlcumTamgaSabitleyici`` — sabitle yük alanları; kaynak_seq artışı;
  dogrula 3 katman (Tamga zinciri / çapraz-çapa / tamlık) + yabancı-kayıt
  atlama dalı; sabitle_ledger geri-oynatma; merkle_kok; ozet.
* ``sabitle_olcumler`` — boş liste; N öğe; enjekte edilen tamga; dönüş tipi.

DIŞBAĞIMLILIK: Hepsi saf in-memory'dir; ağ/RPC/subprocess YOK. Kardeş
TamgaProtocol ağacı (``tamga_canon``) yalnızca bayt-paritesi testi için
opsiyonel okunur — yoksa test temiz atlar (skip).
"""

from __future__ import annotations

import hashlib
import importlib
import json
import sys
from pathlib import Path

import numpy as np
import pytest

from fleksa.audit.ledger import CryptographicSavingsLedger
from fleksa.audit.tamga_anchor import (
    KAYIT_TIPI,
    KAYNAK_PROJE,
    TAMGA_GENESIS_H,
    BozukTamgaZinciriError,
    OlcumTamgaSabitleyici,
    TamgaLedger,
    _json_saf_yap,
    es_number,
    jcs,
    jcs_str,
    olcum_kanit_uret,
    sabitle_olcumler,
)

# Kardeş açık-kaynak protokol ağacı — bayt-paritesi oraklığı (yoksa skip).
TAMGA_REPO = Path("/home/gokun/projects/05_acik_kaynak/TamgaProtocol")

# Node-verify edilmiş (gerçek V8 ECMAScript Number.prototype.toString ile
# birebir karşılaştırılmış) değer tablosı: (python repr, ECMAScript çıktısı).
# 6035 farklı finite double üzerinden 0 uyumsuzluk çıkmıştır (diff-test).
ES_NUMBER_V8_TABLOSU = [
    ("0.0", "0"),
    ("-0.0", "0"),
    ("1.0", "1"),
    ("-1.0", "-1"),
    ("100.0", "100"),
    ("254.0", "254"),
    ("2.5", "2.5"),
    ("123.456", "123.456"),
    ("-123.456", "-123.456"),
    ("0.1", "0.1"),
    ("0.3333333333333333", "0.3333333333333333"),
    ("1000000000000000.0", "1000000000000000"),
    ("1e+16", "10000000000000000"),
    ("1e+17", "100000000000000000"),
    ("1e+20", "100000000000000000000"),
    ("1e+21", "1e+21"),
    ("1e+22", "1e+22"),
    ("1.5e+300", "1.5e+300"),
    ("1.7976931348623157e+308", "1.7976931348623157e+308"),
    ("0.0001", "0.0001"),
    ("1e-05", "0.00001"),
    ("1e-06", "0.000001"),
    ("1e-07", "1e-7"),
    ("1e-08", "1e-8"),
    ("1e-09", "1e-9"),
    ("2.93e-07", "2.93e-7"),
    ("1.5e-07", "1.5e-7"),
    ("9.99e-08", "9.99e-8"),
    ("5e-324", "5e-324"),
    ("2.220446049250313e-16", "2.220446049250313e-16"),
    ("9007199254740992.0", "9007199254740992"),
    ("0.30000000000000004", "0.30000000000000004"),
    ("1234567890.1234567", "1234567890.1234567"),
    ("10000000.0", "10000000"),
    ("-1e-06", "-0.000001"),
    ("-1e-07", "-1e-7"),
    ("-1e+21", "-1e+21"),
]


def _tamga_canon_getir():
    """Kardeş TamgaProtocol ``tamga_canon`` modülünü getir; yoksa skip."""
    if not TAMGA_REPO.is_dir():
        pytest.skip(f"TamgaProtocol bulunamadı: {TAMGA_REPO}")
    if str(TAMGA_REPO) not in sys.path:
        sys.path.insert(0, str(TAMGA_REPO))
    try:
        return importlib.import_module("tamga_canon")
    except Exception as exc:  # bağımlılık yoksa skip, asla fail verme
        pytest.skip(f"tamga_canon import edilemedi: {exc}")


def _beklenen_hash(seq: int, prev: str, kayit: dict) -> str:
    """Tamga D5 kuralını bağımsız olarak yeniden hesapla (oraklık için)."""
    govde = {k: v for k, v in kayit.items() if k not in ("h", "node_sig")}
    return hashlib.sha256((prev + jcs_str(govde)).encode("utf-8")).hexdigest()


def _dogru_kayitlar(n: int = 3) -> list[dict]:
    """İçeriden tutarlı (seq/prev/h'si doğru) n adet Tamga kaydı üret."""
    ledger = TamgaLedger()
    for i in range(n):
        ledger.append({"olcum": f"h{i}", "kw": float(100 + i)})
    return ledger.disa_aktar()


# ---------------------------------------------------------------------------
# 1. es_number — ECMAScript Number.prototype.toString (RFC 8785 §3.2.2.2)
# ---------------------------------------------------------------------------
class TestEsNumber:
    """es_number: başarı + başarısızlık + bütün formatlama sınır dalları."""

    @pytest.mark.parametrize("repr_str, beklenen", ES_NUMBER_V8_TABLOSU)
    def test_v8_ile_dogrulanmis_degerler(self, repr_str: str, beklenen: str):
        """Dal: tüm format rejimleri — gerçek V8 çıktısıyla birebir.

        Kapsanan dallar: x==0 (−0.0 dahil), negatif önek, k<=n<=21,
        0<n<=21, −6<n<=0, üslü (k==1 ve k>1 mantis, ± işaret).
        """
        assert es_number(float(repr_str)) == beklenen

    @pytest.mark.parametrize("deger, beklenen", [
        (0.0, "0"),          # x == 0 dalı (pozitif sıfır)
        (-0.0, "0"),         # x == 0 dalı (negatif sıfır; ECMAScript "0" basar)
        (1.0, "1"),          # 0 < n <= 21, tek hane → tamsayı gövde
        (254.0, "254"),      # 0 < n <= 21, çok hane
        (1e16, "10000000000000000"),   # k <= n <= 21 sınırı (n=17)
        (1e20, "100000000000000000000"),  # k <= n <= 21 sınırının tam üstü (n=21)
        (1e21, "1e+21"),     # üslü dal, k == 1, e >= 0 (n=22 → e=21)
        (1e22, "1e+22"),     # üslü dal, k == 1, e >= 0
        (2.93e-07, "2.93e-7"),  # üslü dal, k > 1, e < 0 (n=-6 → e=-7)
        (1.5e-07, "1.5e-7"),    # üslü dal, k > 1, e < 0
        (1e-06, "0.000001"),    # -6 < n <= 0 dalı (n=-5)
        (1e-07, "1e-7"),        # n == -6 → üslü dala düşer (−6 < n False)
        (0.0001, "0.0001"),     # -6 < n <= 0 dalı (n=-3)
        (-123.456, "-123.456"),  # negatif önek + 0 < n <= 21
        (-1e+21, "-1e+21"),     # negatif önek + üslü, k == 1, e >= 0
        (-1e-07, "-1e-7"),      # negatif önek + üslü, k == 1, e < 0
    ])
    def test_dal_sinirlari(self, deger: float, beklenen: str):
        """Her formatlama dalının tam sınır değerini Xunit tarzı tablola."""
        assert es_number(deger) == beklenen

    @pytest.mark.parametrize("deger, etiket", [
        (float("nan"), "NaN"),
        (float("inf"), "Infinity"),
        (float("-inf"), "-Infinity"),
    ])
    def test_sonlu_olmayan_reddedilir(self, deger: float, etiket: str):
        """Başarısızlık dalı: NaN/Infinity I-JSON (RFC 7493) altkümesinde değil."""
        with pytest.raises(ValueError, match="ijson_number_not_finite"):
            es_number(deger)

    def test_sifir_dali_negatif_sifir_dahil(self):
        """Sınır: x == 0 dalı −0.0'ı da yakalar (ECMAScript "0" basar)."""
        assert es_number(0.0) == "0"
        assert es_number(-0.0) == "0"
        # signed-zero ayrımı yapılmaz — bu bilinçli bir RFC 8785 uyumudur
        assert es_number(-0.0) == es_number(0.0)

    def test_jcs_ile_tutarli_cift_yonlu(self):
        """Başarı: es_number çıktısı jcs(_encode) ile bayt-bayt tutarlı."""
        for deger in (2.5, 1e21, 2.93e-07, -0.0001, 123456.789):
            assert jcs(deger).decode("utf-8") == es_number(deger)

    def test_trailing_zero_atilir(self):
        """Dal: repr(1.0) → digits '10'; sondaki sıfır atılarak '1' yazılır."""
        assert es_number(1.0) == "1"
        assert es_number(10.0) == "10"
        assert es_number(100.0) == "100"
        assert es_number(1.0) != "1.0"


# ---------------------------------------------------------------------------
# 2. jcs / jcs_str — RFC 8785 canonical serialization
# ---------------------------------------------------------------------------
class TestJcsKodlayici:
    """jcs + jcs_str: ililkel/konteyner başarı, hata ve sınır dalları."""

    @pytest.mark.parametrize("deger, beklenen", [
        (None, b"null"),
        (True, b"true"),
        (False, b"false"),
        (0, b"0"),
        (-17, b"-17"),
        (2.5, b"2.5"),
        ("", b'""'),
        ("ağ", '"ağ"'.encode("utf-8")),  # non-ASCII ham UTF-8 (kaçışlanmaz)
    ])
    def test_ilkeller(self, deger, beklenen: bytes):
        """Başarı: her ilkel tip kendi JCS gösterimine serileşir."""
        assert jcs(deger) == beklenen

    def test_bool_savunma_dali_odur_kod(self):
        """Dal/GÖZLEM: ``_encode`` içindeki ``isinstance(o, bool)`` dalı (modül
        satır 181) ÖLÜ-KODDUR — hiçbir girdi onu çalıştıramaz.

        İspat: ``bool``'un yalnızca iki örneği vardır (``True``/``False``) ve
        ``class X(bool)`` Python'da yasaktır ("type 'bool' is not an acceptable
        base type"), yani bir bool ALT-SINIFI da üretilemez. Dolayısıyla
        ``o is True`` / ``o is False`` kimlik dalları her bool'u yakalar ve
        ``isinstance(o, bool)`` dalına ASLA düşülmez. Bu test o gerçeği belgeler:
        production'a DOKUNULMADI; dal kesme amacıyla gerçek (ulaşılamayan) dal
        olarak işaretlendi.
        """
        # bool alt-sınıfı oluşturulamaz → savunma dalı canlandırılamaz
        with pytest.raises(TypeError, match="not an acceptable base type"):
            class _BoolAltSinif(bool):  # noqa: N801
                pass

        from fleksa.audit.tamga_anchor import _encode
        # saf True/False kimlik dallarına düşer ve doğru çıktı verir
        cikti: list[str] = []
        _encode(True, cikti)
        _encode(False, cikti)
        _encode([True, False], cikti)
        assert "".join(cikti) == "truefalse[true,false]"
        # bool'ların özeti: True/False dışında bool örneği yoktur
        assert {True, False} == set(b for b in (True, False) if isinstance(b, bool))

    @pytest.mark.parametrize("girdi, beklenen", [
        ('"', '\\"'),        # _ESCAPE tablosu — çift tırnak
        ("\\", "\\\\"),      # _ESCAPE tablosu — ters eğik çizgi
        ("\b", "\\b"),       # _ESCAPE tablosu — backspace
        ("\f", "\\f"),       # _ESCAPE tablosu — form feed
        ("\n", "\\n"),       # _ESCAPE tablosu — newline
        ("\r", "\\r"),       # _ESCAPE tablosu — carriage return
        ("\t", "\\t"),       # _ESCAPE tablosu — tab
        ("\x00", "\\u0000"),  # ord < 0x20 → \uXXXX (en alt sınır)
        ("\x01", "\\u0001"),  # ord < 0x20
        ("\x1f", "\\u001f"),  # ord < 0x20 (en üst sınır)
        (" ", " "),            # 0x20 ham kalır (kaçış yok)
        ("~", "~"),            # 0x7E ham kalır (kaçış yok)
        ("ğ", "ğ"),            # non-ASCII ham UTF-8
        ("ünide", "ünide"),    # çoklu non-ASCII ham
    ])
    def test_dize_kacislari(self, girdi: str, beklenen: str):
        """Dal: _ESCAPE tablosu + <0x20 kontrol karakterleri + ham UTF-8."""
        assert jcs(girdi) == ('"' + beklenen + '"').encode("utf-8")

    def test_dize_karisik_unicode_ham_utf8(self):
        """Başarı: non-ASCII karakterler \\uXXXX değil ham UTF-8 olarak yazılır.

        Bu RFC 8785 §3.2.2.1'in birebir uygulamasıdır ve Node/Go verifier'larla
        bayt uyumunu garanti eder.
        """
        assert jcs("ölçüm-ğ-ı-ü") == '"ölçüm-ğ-ı-ü"'.encode("utf-8")
        # emoji (astral düzlem) — UTF-16-BE sıralamasını etkilemez, ham kalır
        assert jcs("😀") == '"😀"'.encode("utf-8")

    def test_utf16_be_uye_adi_siralama(self):
        """Başarı: üye adları UTF-16 kod-birimi dizisine göre artan sıralanır.

        'a'<'b' (ASCII), ama 'g'(U+0067) < 'ğ'(U+011F) < 'ı'(U+0131) — yani
        Türkçe harfler ASCII'den SONRA gelir. ``json.dumps(sort_keys=True)``
        bunu YANLIŞ sıralardı (kod-noktasına göre); JCS UTF-16-BE ister.
        """
        sonuc = jcs_str({"ğ": 1, "a": 2, "ı": 3, "b": 4, "Z": 5})
        # beklenen sıra: Z(0x005A), a(0x0061), b(0x0062), ğ(0x011F), ı(0x0131)
        assert sonuc == '{"Z":5,"a":2,"b":4,"ğ":1,"ı":3}'
        # unicode dumps ile karşılaştırma: python sort_keys FARKLI bayt verir
        import json
        assert json.dumps({"ğ": 1, "a": 2, "ı": 3}, sort_keys=True) != sonuc

    @pytest.mark.parametrize("girdi, beklenen", [
        ([], "[]"), ([1, 2, 3], "[1,2,3]"), ([1, [2, [3]]], "[1,[2,[3]]]"),
        ({}, "{}"), ({"a": 1}, '{"a":1}'),
        ({"b": 2, "a": 1}, '{"a":1,"b":2}'),  # anahtar sıralaması
        ({"k": {"z": 1, "a": 2}}, '{"k":{"a":2,"z":1}}'),  # iç içe sıralama
        ((1, 2), "[1,2]"),  # tuple, list ile AYNI çıktı (§3.1)
        ([None, True, False, 1, 2.5, "x"], '[null,true,false,1,2.5,"x"]'),
    ])
    def test_konteynerler(self, girdi, beklenen: str):
        """Başarı: list/tuple/dict iç içe sıralama ile serileşir."""
        assert jcs_str(girdi) == beklenen

    @pytest.mark.parametrize("tamsayi", [
        2 ** 53,           # izin verilen en büyük (sınırın tam üstü)
        -2 ** 53,          # izin verilen en küçük
        0, 1, -1,
        9007199254740991,  # 2^53 - 1
    ])
    def test_tamsayi_izin_verilen_aralik(self, tamsayi: int):
        """Başarı/sınır: [−2^53, 2^53] içindeki tamsayılar serileşir (RFC 7493)."""
        assert jcs_str(tamsayi) == str(tamsayi)

    @pytest.mark.parametrize("tamsayi", [
        2 ** 53 + 1,       # sınırın 1 fazlası
        -2 ** 53 - 1,      # sınırın 1 eksiği
        2 ** 64,           # açıkça aşan
        -(2 ** 64),        # açıkça aşan (negatif)
    ])
    def test_tamsayi_aralik_disi_reddedilir(self, tamsayi: int):
        """Başarısızlık dalı: ±2^53 dışı tamsayı ValueError (sessiz yuvarlama yok)."""
        with pytest.raises(ValueError, match="ijson_number_out_of_range"):
            jcs(tamsayi)

    @pytest.mark.parametrize("tip_disi", [
        object(), complex(1, 2), {1, 2}, (lambda: None),  # desteklenmeyen tipler
    ])
    def test_desteklenmeyen_tip_type_error(self, tip_disi):
        """Başarısızlık dalı: JCS desteklemediği tip için TypeError fırlatır."""
        with pytest.raises(TypeError, match="jcs-desteklenmeyen-tip"):
            jcs(tip_disi)

    def test_jcs_ve_jcs_str_bayt_tutarligi(self):
        """Başarı: jcs bytes, jcs_str onun UTF-8 kodçözümüdür."""
        obje = {"z": 2.93e-07, "a": [1, {"ğ": "x"}], "n": None}
        assert jcs_str(obje).encode("utf-8") == jcs(obje)
        # deterministik: aynı girdi hep aynı bayt
        assert jcs(obje) == jcs(obje)

    def test_tamga_canon_ile_bayt_paritesi(self):
        """Başarı (opsiyonel): kardeş TamgaProtocol tamga_canon.jcs ile bayt-bayt."""
        tamga_canon = _tamga_canon_getir()
        objeler = [
            {"b": 1, "a": 2}, [None, True, False, 1, 1.5, "x"],
            {"ğ": 1, "ı": 2, "g": 3}, {"y": 1e21, "z": 2.93e-07},
            {}, [], [[]], {"k": {}}, {"k": [1, {"y": "ğ"}]},
            {"s": "ağ\"\\ \t\n\r\b\f\x01"}, {"big": 2 ** 53, "neg": -(2 ** 53)},
        ]
        for obje in objeler:
            assert jcs(obje) == tamga_canon.jcs(obje)


# ---------------------------------------------------------------------------
# 3. _json_saf_yap — JSON/JCS-güvenli ilkel türe indirgeme
# ---------------------------------------------------------------------------
class TestJsonSafYap:
    """_json_saf_yap: ililkel/konteyner/numpy/geri-dönüş dalları + np.float64 BUG."""

    @pytest.mark.parametrize("deger, beklenen", [
        (None, None), (True, True), (False, False),
        (42, 42), (-7, -7), (3.5, 3.5), ("metin", "metin"),
    ])
    def test_ilkeller_oldugu_gibi_donar(self, deger, beklenen):
        """Başarı: None/bool/int/float/str dokunulmadan geçer."""
        cikti = _json_saf_yap(deger)
        assert cikti == beklenen
        assert type(cikti) is type(beklenen)  # tip korunur (pure python)

    def test_bool_int_den_ayrilir(self):
        """Sınır: bool, int dalına DÜŞMEZ — kendi dalını korur (True != 1 tipi)."""
        assert type(_json_saf_yap(True)) is bool
        assert type(_json_saf_yap(False)) is bool

    def test_dict_ve_list_ozuyen(self):
        """Başarı: dict/list değerleri özüyerek indirgenir."""
        girdi = {"a": [1, {"b": 2.5}], "n": None}
        assert _json_saf_yap(girdi) == {"a": [1, {"b": 2.5}], "n": None}

    def test_tuple_liste_donuser(self):
        """Başarı: tuple → list (JSON'da tuple yok)."""
        cikti = _json_saf_yap((1, "a", None))
        assert cikti == [1, "a", None]
        assert isinstance(cikti, list)

    def test_dict_anahtar_str_donuser(self):
        """Başarı: int/float anahtarlar str'ye dönüştürülür (JSON anahtar kuralı)."""
        cikti = _json_saf_yap({1: "a", 2.5: "b"})
        assert cikti == {"1": "a", "2.5": "b"}
        assert all(isinstance(k, str) for k in cikti)

    def test_numpy_dizi_1d_ve_2d_liste_donuser(self):
        """Başarı: numpy ndarray → iç içe python listesi."""
        import numpy as np
        bir = _json_saf_yap(np.array([1, 2.5, 3]))
        assert bir == [1.0, 2.5, 3.0]
        assert isinstance(bir, list) and isinstance(bir[0], float)
        iki = _json_saf_yap(np.array([[1, 2], [3, 4]]))
        assert iki == [[1, 2], [3, 4]]
        assert isinstance(iki, list) and isinstance(iki[0], list)

    @pytest.mark.parametrize("skaler, beklenen_tip", [
        (np.int64(7), int), (np.int32(7), int), (np.int8(3), int),
        (np.uint8(3), int), (np.uint64(9), int),
        (np.float32(3.5), float), (np.float16(1.5), float),
        (np.bool_(True), bool), (np.bool_(False), bool),
    ])
    def test_numpy_generic_saf_tipe_iner(self, skaler, beklenen_tip):
        """Başarı: numpy generic skalerleri SAF python tipine iner (.item() dalı)."""
        cikti = _json_saf_yap(skaler)
        assert cikti == skaler
        assert type(cikti) is beklenen_tip, (
            f"{type(skaler).__name__} -> {type(cikti).__module__}.{type(cikti).__name__}"
        )

    def test_desteklenmeyen_tip_str_donuser(self):
        """Başarı/geri-dönüş: bilinmeyen tip str()'ye düşer (complex örneği)."""
        cikti = _json_saf_yap(complex(1, 2))
        assert cikti == "(1+2j)"
        assert isinstance(cikti, str)

    @pytest.mark.xfail(strict=True, reason=(
        "BULGU-1 (gerçek bug, production'a DOKUNİLMEDİ): _json_saf_yap "
        "np.float64'ü SAF python float'ına indirgemez. np.float64, Python "
        "float'ının alt-sınıfı olduğundan isinstance(deger,(int,float,str)) "
        "dalı (modül satır 253) onu yakalar ve np.generic dalı (satır 264, "
        ".item()) HİÇ çalışmaz → değer numpy.float64 olarak sızar. Sonuç: "
        "sabitle() np.float64 içeren bir payload ile çağrılırsa tamga.append "
        "→ jcs → es_number → Decimal(repr(np.float64(3.5))) → NumPy 2.x "
        "skaler repr'ı 'np.float64(3.5)' olduğundan decimal.InvalidOperation "
        "fırlatır. Düzeltme: float dalından önce numpy generic kontrolü veya "
        "float(...) ile sarmak. Test düzeltilince XPASS→FAIL sinyali verir."
    ))
    def test_numpy_float64_saf_tipe_iner(self):
        """İDDİA (bozuk): np.float64 SAF python float'ına inmelidir."""
        import numpy as np
        cikti = _json_saf_yap(np.float64(3.5))
        assert type(cikti) is float

    @pytest.mark.xfail(strict=True, reason=(
        "BULGU-1'nin uç-nokta etkisi: sabitle() belgelenen numpy M&V akışında "
        "(modül docstring'i 'Fleksa M&V akışı numpy skalerleri/vektörleri "
        "üretir' der) np.float64 içeren ölçümü InvalidOperation ile çöktürür. "
        "Mevcut CLI yolu (olcum_kanit_uret her şeyi float() ile sarar) bu "
        "yüzden çalışır; sadece doğrudan sabitle()/sabitle_ledger() çağrısı "
        "tetikler. Production'a dokunulmadı."
    ))
    def test_sabitle_numpy_float64_payload_cokmemeli(self):
        """İDDİA (bozuk): numpy ölçüm kanıtı sabitlenebilmelidir."""
        import numpy as np
        sabitleyici = OlcumTamgaSabitleyici()
        sabitleyici.sabitle({
            "tesis": "tr-ist-eqx-02", "olay": "DR_PEAK_SHAVE", "saat": 17,
            "baseline_kw": np.float64(300.0), "actual_kw": np.float64(200.0),
        })
        assert sabitleyici.dogrula()


# ---------------------------------------------------------------------------
# 4. olcum_kanit_uret — IPMVP ölçüm-kanıdı birimi
# ---------------------------------------------------------------------------
class TestOlcumKanitUret:
    """olcum_kanit_uret: başarı, sınır (kesinti ≥ 0) ve olay_id dalları."""

    def test_normal_kesinti_hesaplanir(self):
        """Başarı: baseline > actual → olcum_kesinti_kw = baseline − actual."""
        kanit = olcum_kanit_uret(
            tesis_id="tr-ist-eqx-02", olay="DR_PEAK_SHAVE", saat=17,
            baseline_kw=300.0, actual_kw=200.0, tarif_try_kwh=3.8,
        )
        assert kanit["olcum_kesinti_kw"] == 100.0
        assert kanit["tesis"] == "tr-ist-eqx-02"
        assert kanit["olay"] == "DR_PEAK_SHAVE"
        assert kanit["saat"] == 17
        assert kanit["baseline_kw"] == 300.0
        assert kanit["actual_kw"] == 200.0
        assert kanit["tarif_try_kwh"] == 3.8

    @pytest.mark.parametrize("base, actual, beklenen", [
        (300.0, 200.0, 100.0),   # normal kesinti
        (200.0, 300.0, 0.0),     # actual > baseline → negatif değil 0 (max(0,·))
        (250.0, 250.0, 0.0),     # eşit → 0
        (0.0, 0.0, 0.0),         # ikisi de sıfır
        (100.0, 99.9999999, 0.0),  # 6-ondalık yuvarlama sonra 0.000001 → 0.0
    ])
    def test_kesinti_negatif_olamaz(self, base: float, actual: float, beklenen: float):
        """Sınır: olcum_kesinti_kw asla negatif olmaz — max(0.0, base−act)."""
        kanit = olcum_kanit_uret(
            tesis_id="t", olay="DR", saat=1, baseline_kw=base,
            actual_kw=actual, tarif_try_kwh=1.0,
        )
        assert kanit["olcum_kesinti_kw"] == beklenen

    @pytest.mark.parametrize("deger, beklenen", [
        (300.123456789, 300.123457),   # 6'ya yuvarla (yukarı)
        (300.1234564, 300.123456),     # 6'ya yuvarla (aşağı)
        (100.0, 100.0),                # zaten 6 basamak
        (0.0000004, 0.0),              # çok küçük → 0
    ])
    def test_alti_ondalık_yuvarlama(self, deger: float, beklenen: float):
        """Sınır: tüm kw değerleri 6-ondalık basamağa yuvarlanır (digest determinizmi)."""
        kanit = olcum_kanit_uret(
            tesis_id="t", olay="DR", saat=1, baseline_kw=deger,
            actual_kw=0.0, tarif_try_kwh=1.0,
        )
        assert kanit["baseline_kw"] == beklenen

    def test_olay_id_var_eklenir(self):
        """Başarı: olay_id verilince kanıda 'olay_id' anahtarı oluşur."""
        kanit = olcum_kanit_uret(
            tesis_id="t", olay="DR", saat=17, baseline_kw=300.0,
            actual_kw=200.0, tarif_try_kwh=3.8, olay_id="evt-20261005-peak-01",
        )
        assert kanit["olay_id"] == "evt-20261005-peak-01"

    def test_olay_id_yoksa_anahtar_olmaz(self):
        """Başarı/sınır: olay_id verilmezse 'olay_id' anahtarı HİÇ olmaz."""
        kanit = olcum_kanit_uret(
            tesis_id="t", olay="DR", saat=17, baseline_kw=300.0,
            actual_kw=200.0, tarif_try_kwh=3.8,
        )
        assert "olay_id" not in kanit

    def test_tip_zorlamasi(self):
        """Sınır: tesis/olay str'ye, saat int'ye, kw/tarif float'a zorlanır."""
        kanit = olcum_kanit_uret(
            tesis_id=12345, olay=67890, saat="17",
            baseline_kw=300, actual_kw=200, tarif_try_kwh="3.8",
        )
        assert kanit["tesis"] == "12345"
        assert kanit["olay"] == "67890"
        assert kanit["saat"] == 17
        assert isinstance(kanit["saat"], int)
        assert isinstance(kanit["baseline_kw"], float)
        assert kanit["tarif_try_kwh"] == 3.8

    def test_deterministik_ayni_deger(self):
        """Başarı: aynı girdi her çağrıda bayt-bayt aynı kanıt üretir."""
        a = olcum_kanit_uret(tesis_id="t", olay="DR", saat=17, baseline_kw=300.0,
                             actual_kw=200.0, tarif_try_kwh=3.8)
        b = olcum_kanit_uret(tesis_id="t", olay="DR", saat=17, baseline_kw=300.0,
                             actual_kw=200.0, tarif_try_kwh=3.8)
        assert a == b
        assert jcs(a) == jcs(b)


# ---------------------------------------------------------------------------
# 5. TamgaLedger — tamga-sim/1 hash-zinciri
# ---------------------------------------------------------------------------
class TestTamgaLedger:
    """TamgaLedger: append/verify/yukle/disa_aktar/tip/jsonl başarı+hata dalları."""

    def test_bos_zincir(self):
        """Başarı/sınır: boş zincir — len 0, tip None, verify True (iddiasız)."""
        ledger = TamgaLedger()
        assert len(ledger) == 0
        assert ledger.tip() is None
        assert ledger.verify() is True

    def test_genesis_sabiti(self):
        """Sınır: genesis prev değeri tam 64×'0'dır."""
        assert TAMGA_GENESIS_H == "0" * 64
        assert len(TAMGA_GENESIS_H) == 64

    def test_append_seq_prev_h_atar(self):
        """Başarı: append seq (1-based), prev (genesis) ve h'yi otomatik atar."""
        ledger = TamgaLedger()
        rec = ledger.append({"olcum": "h17", "kw": 100.0})
        assert rec["seq"] == 1
        assert rec["prev"] == TAMGA_GENESIS_H
        assert rec["h"] == _beklenen_hash(1, TAMGA_GENESIS_H, rec)
        assert len(ledger) == 1

    def test_append_ikinci_kayit_prev_baglar(self):
        """Başarı: 2. kaydın prev'i 1. kaydın h'sidir; seq 2'dir."""
        ledger = TamgaLedger()
        ilk = ledger.append({"kw": 100.0})
        iki = ledger.append({"kw": 200.0})
        assert iki["seq"] == 2
        assert iki["prev"] == ilk["h"]
        assert iki["h"] == _beklenen_hash(2, ilk["h"], iki)
        assert ledger.tip() == iki["h"]

    def test_append_cagirici_seq_h_overwrite(self):
        """Sınır: çağrıcının verdiği seq/h/node_sig overwrite/drop edilir.

        append-only sözü: mevcut kayıtlar değiştirilemez; seq/prev/zorla
        atanır, node_sig hash-dışı olduğundan tamamen atılır.
        """
        ledger = TamgaLedger()
        rec = ledger.append({"seq": 999, "h": "zzz", "node_sig": "imza", "x": 1})
        assert rec["seq"] == 1                 # 999 → 1
        assert rec["h"] != "zzz"               # yeniden hesaplandı
        assert rec["prev"] == TAMGA_GENESIS_H
        assert "node_sig" not in rec           # hash-dışı alan atıldı

    def test_verify_gecerli_zincir_true(self):
        """Başarı: içeriden tutarlı 3 kayıtlı zincir verify True döner."""
        ledger = TamgaLedger()
        for i in range(3):
            ledger.append({"olcum": f"h{i}", "kw": float(100 + i)})
        assert ledger.verify() is True

    def _zincir_kir(self, alan: str, deger):
        """verify() False döndürmesi için bir kaydın tek alanını bozar."""
        ledger = TamgaLedger()
        for i in range(3):
            ledger.append({"olcum": f"h{i}", "kw": float(100 + i)})
        ledger.entries[1][alan] = deger
        return ledger

    @pytest.mark.parametrize("alan, deger, aciklama", [
        ("seq", 99, "seq-sırası bozuk"),
        ("prev", "0" * 64, "prev-bağlantısı bozuk (genesis ile değiştirildi)"),
        ("h", "a" * 64, "h-doğrulaması başarısız (kurcalanmış hash)"),
    ])
    def test_verify_kirik_zincir_false(self, alan: str, deger, aciklama: str):
        """Başarısızlık dalı: seq/prev/h'den herhangi biri bozuk → False."""
        ledger = self._zincir_kir(alan, deger)
        assert ledger.verify() is False, aciklama

    def test_verify_alan_eksikse_false(self):
        """Başarısızlık dalı: seq alanı yoksa (None) n ile eşleşmez → False."""
        ledger = TamgaLedger()
        ledger.append({"kw": 1.0})
        del ledger.entries[0]["seq"]
        assert ledger.verify() is False

    # --- yukle (fail-closed) ---
    def test_yukle_gecerli_zincir(self):
        """Başarı: doğru seq/prev/h'li kayıtlar belleğe alınır, verify True."""
        ledger = TamgaLedger()
        ledger.yukle(_dogru_kayitlar(3))
        assert len(ledger) == 3
        assert ledger.verify() is True

    def test_yukle_bos_liste(self):
        """Sınır: boş liste → hiçbir kayıt eklenmez."""
        ledger = TamgaLedger()
        ledger.yukle([])
        assert len(ledger) == 0
        assert ledger.verify() is True

    def test_yukle_append_uzerine_devam_ettirir(self):
        """Başarı: yukle, mevcut zincirin seq/prev'ini devam ettirir.

        Gelen kayıtların seq'si mevcut uzunluğun devamlısı olmalıdır; prev
        bağlantısı da mevcut son h'ye eşleşmelidir. Aynı payload → aynı h.
        """
        a = TamgaLedger()
        for i in range(3):
            a.append({"kw": float(100 + i)})
        tum = a.disa_aktar()

        b = TamgaLedger()
        b.append({"kw": 100.0})  # a'nın 1. kaydıyla aynı payload → aynı h
        b.yukle(tum[1:])          # seq 2 ve 3, prev b[0].h ile eşleşir
        assert len(b) == 3
        assert b.verify() is True
        assert b.tip() == a.tip()

    @pytest.mark.parametrize("kayit, mesaj", [
        ({"prev": "x" * 64, "h": "y" * 64, "kw": 1.0}, "seq int değil (yok)"),
        ({"seq": 1, "h": "y" * 64, "kw": 1.0}, "prev str değil (yok)"),
        ({"seq": 1, "prev": "x" * 64, "kw": 1.0}, "h str değil (yok)"),
        ({"seq": 1.5, "prev": "x" * 64, "h": "y" * 64, "kw": 1.0}, "seq float"),
        ({"seq": 1, "prev": 1234, "h": "y" * 64, "kw": 1.0}, "prev int"),
        ({"seq": 1, "prev": "x" * 64, "h": 1234, "kw": 1.0}, "h int"),
    ])
    def test_yukle_tip_eksik_alan_reddeder(self, kayit: dict, mesaj: str):
        """Başarısızlık dalı: seq/prev/h tipi yanlış/eksik → BozukTamgaZinciriError."""
        ledger = TamgaLedger()
        with pytest.raises(BozukTamgaZinciriError):
            ledger.yukle([kayit])

    def test_yukle_seq_sira_disi_reddeder(self):
        """Başarısızlık dalı: seq 1 yerine 2 gelirse sıra hatası."""
        ledger = TamgaLedger()
        kayitlar = _dogru_kayitlar(1)
        kayitlar[0]["seq"] = 2
        with pytest.raises(BozukTamgaZinciriError, match="seq-sırası"):
            ledger.yukle(kayitlar)

    def test_yukle_prev_baglantisi_reddeder(self):
        """Başarısızlık dalı: prev genesis değilse bağlantı hatası."""
        ledger = TamgaLedger()
        kayitlar = _dogru_kayitlar(1)
        kayitlar[0]["prev"] = "f" * 64
        with pytest.raises(BozukTamgaZinciriError, match="prev-bağlantısı"):
            ledger.yukle(kayitlar)

    def test_yukle_bozuk_hash_reddeder(self):
        """Başarısızlık dalı: h yeniden hesaplanamıyorsa kurcalama hatası."""
        ledger = TamgaLedger()
        kayitlar = _dogru_kayitlar(1)
        kayitlar[0]["h"] = "a" * 64
        with pytest.raises(BozukTamgaZinciriError, match="h-doğrulaması"):
            ledger.yukle(kayitlar)

    def test_yukle_fail_closed_kirik_kayit_alinmaz(self):
        """Başarısızlık dalı: BOZUK kayıt belleğe ALINMAZ ve hata fırlar.

        GÖZLEM (production'a dokunulmadı): ``yukle`` kayıtları tek-tek
        doğrulayıp her geçerli kaydı hemen eklediği için, N. kayıt bozuksa
        ilk N−1 geçerli kayıt ledger'da KALIR. Docstring'in "bozuk zincir
        belleğe HİÇ girmez" sözü tam olarak yalnızca BOZUK kayıt için
        geçerlidir; geçerli önek akış halinde yüklenir. Bu test gerçek
        davranışı belgeler: 3 kayıttan 3.'sü bozuksa → hata + 2 geçerli kayıt
        kalır (kırık kayıt değil).
        """
        ledger = TamgaLedger()
        kayitlar = _dogru_kayitlar(3)
        kayitlar[2]["h"] = "a" * 64
        with pytest.raises(BozukTamgaZinciriError):
            ledger.yukle(kayitlar)
        assert len(ledger) == 2          # geçerli önek kaldı
        assert ledger.verify() is True   # ve kendi içinde hala tutarlı
        # bozuk kaydın içeriği bellekte YOK
        assert all("h3" != r.get("olcum") for r in ledger.entries)

    def test_yukle_hash_disi_alanlar_etkilenmez(self):
        """Sınır: node_sig hash-dışı olduğundan h'yi değiştirmez."""
        ledger = TamgaLedger()
        ledger.append({"kw": 1.0})
        kayitlar = ledger.disa_aktar()
        kayitlar[0]["node_sig"] = "yeni-imza"
        temiz = TamgaLedger()
        temiz.yukle([{k: v for k, v in kayitlar[0].items()}])
        assert temiz.verify() is True

    # --- disa_aktar / tip ---
    def test_disa_aktar_kopya_izolasyonu(self):
        """Başarı: disa_aktar kopya döner — dış mutasyon ledger'i etkilemez."""
        ledger = TamgaLedger()
        ledger.append({"kw": 1.0})
        dis = ledger.disa_aktar()
        dis[0]["kw"] = 999.0
        assert ledger.entries[0]["kw"] == 1.0

    def test_tip_son_hash_ve_bos_none(self):
        """Başarı/sınır: tip son kaydın h'si; boş zincirde None."""
        ledger = TamgaLedger()
        assert ledger.tip() is None
        rec = ledger.append({"kw": 1.0})
        assert ledger.tip() == rec["h"]

    # --- jsonl ---
    def test_jsonl_gidis_donusu(self, tmp_path):
        """Başarı: jsonl_yaz → jsonl_oku round-trip verify True kalır."""
        ledger = TamgaLedger()
        for i in range(3):
            ledger.append({"olcum": f"h{i}", "kw": float(100 + i)})
        yol = ledger.jsonl_yaz(tmp_path / "tamga.jsonl")
        assert Path(yol).exists()

        geri = TamgaLedger()
        geri.jsonl_oku(yol)
        assert len(geri) == 3
        assert geri.verify() is True
        assert geri.tip() == ledger.tip()

    def test_jsonl_yaz_yol_str_donuser(self, tmp_path):
        """Başarı: jsonl_yaz yazılan yolun str'sini döner (Path alır)."""
        ledger = TamgaLedger()
        ledger.append({"kw": 1.0})
        yol = ledger.jsonl_yaz(tmp_path / "a.jsonl")
        assert yol == str(tmp_path / "a.jsonl")

    def test_jsonl_oku_bos_satirlari_atlar(self, tmp_path):
        """Sınır: boş satırlar (örn. sonda newline) atlanır."""
        ledger = TamgaLedger()
        ledger.append({"kw": 1.0})
        yol = tmp_path / "bosluk.jsonl"
        yol.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False)
                      for r in ledger.disa_aktar()) + "\n\n\n",
            encoding="utf-8",
        )
        geri = TamgaLedger()
        geri.jsonl_oku(yol)
        assert len(geri) == 1
        assert geri.verify() is True

    def test_jsonl_kurcalama_fail_closed(self, tmp_path):
        """Başarısızlık dalı: JSONL'de bir h değiştirilirse okuma reddeder."""
        ledger = TamgaLedger()
        for i in range(3):
            ledger.append({"kw": float(100 + i)})
        yol = tmp_path / "kurban.jsonl"
        ledger.jsonl_yaz(yol)
        satirlar = yol.read_text(encoding="utf-8").splitlines()
        bozuk = json.loads(satirlar[1])
        bozuk["h"] = "a" * 64
        satirlar[1] = json.dumps(bozuk, ensure_ascii=False)
        yol.write_text("\n".join(satirlar) + "\n", encoding="utf-8")

        geri = TamgaLedger()
        with pytest.raises(BozukTamgaZinciriError):
            geri.jsonl_oku(yol)
        # bozuk 2. kayıt alınmadı; geçerli 1. kayıt akıştan kaldı (yukle davranışı)
        assert len(geri) == 1
        assert geri.verify() is True


# ---------------------------------------------------------------------------
# 6. OlcumTamgaSabitleyici — 3 katmanlı doğrulama
# ---------------------------------------------------------------------------
class TestOlcumTamgaSabitleyici:
    """sabitle / sabitle_ledger / dogrula / merkle_kok / ozet dalları."""

    def _kanit(self, saat: int = 17, base: float = 300.0, act: float = 200.0):
        return olcum_kanit_uret(
            tesis_id="tr-ist-eqx-02", olay="DR_PEAK_SHAVE", saat=saat,
            baseline_kw=base, actual_kw=act, tarif_try_kwh=3.8,
        )

    def test_bos_sabitleyici_dogrulanir(self):
        """Başarı/sınır: hiç sabitleme yapılmamışsa dogrula True (boş tüm iyi)."""
        s = OlcumTamgaSabitleyici()
        assert s.dogrula() is True
        assert s.ozet()["sabitlenen_olcum"] == 0
        assert s.tamga.tip() is None

    def test_sabitle_yuk_alanlari(self):
        """Başarı: sabitle yükünde tip/kaynak/kaynak_seq/yaprak/kok/payload vardır.

        Sınır gözlemi: TEK ölçümde Fleksa Merkle ağacı tek-yapraklıdır ve
        ``compute_merkle_root`` o yaprağın birebir hash'ini döner — yani
        ``olcum_yaprak == merkle_kok``. İkinci ölçümde kök farklılaşır.
        """
        s = OlcumTamgaSabitleyici()
        rec0 = s.sabitle(self._kanit())
        assert rec0["tip"] == KAYIT_TIPI
        assert rec0["kaynak"] == KAYNAK_PROJE
        assert rec0["kaynak_seq"] == 1
        assert rec0["payload"]["tesis"] == "tr-ist-eqx-02"
        # tek-yapraklı Merkle ağacı: yaprak == kök
        assert rec0["olcum_yaprak"] == rec0["merkle_kok"]

        # ikinci ölçümde yaprak ve kök farklılaşır
        rec1 = s.sabitle(self._kanit(saat=18, act=150.0))
        assert rec1["kaynak_seq"] == 2
        assert rec1["olcum_yaprak"] != rec1["merkle_kok"]

        # olcum_yaprak bağımsız bir defterden yeniden türetilebilir (oraklık)
        beklenen = CryptographicSavingsLedger()
        beklenen.append_entry(rec0["payload"])
        beklenen_yaprak = beklenen.append_entry(rec1["payload"])
        assert rec1["olcum_yaprak"] == beklenen_yaprak

    def test_sabitle_kaynak_seq_artar(self):
        """Başarı: her sabitlede kaynak_seq 1-based artar."""
        s = OlcumTamgaSabitleyici()
        for i, saat in enumerate([17, 18, 19], start=1):
            rec = s.sabitle(self._kanit(saat=saat))
            assert rec["kaynak_seq"] == i
        assert s.ozet()["sabitlenen_olcum"] == 3

    def test_sabitle_idempotent_degil(self):
        """Sınır/davranış: aynı kanıtı iki kez sabitlemek İki kayıt yazar
        (docstring'in 'sabitle idempotent-değildir' notu)."""
        s = OlcumTamgaSabitleyici()
        kanit = self._kanit()
        s.sabitle(kanit)
        s.sabitle(kanit)
        assert len(s.tamga) == 2
        assert s.dogrula() is True

    def test_dogrula_uc_katman_gecerli(self):
        """Başarı: N farklı ölçüm sabitlenince 3 katman da geçer."""
        s = OlcumTamgaSabitleyici()
        for saat in [17, 18, 19, 20]:
            s.sabitle(self._kanit(saat=saat, act=250.0 + saat))
        assert s.dogrula() is True
        assert len(s.tamga) == 4

    def test_dogrula_tamga_zinciri_kiriksa_false(self):
        """Başarısızlık katman-1: Tamga zinciri bozuksa dogrula False."""
        s = OlcumTamgaSabitleyici()
        s.sabitle(self._kanit())
        s.sabitle(self._kanit(saat=18, act=150.0))
        s.tamga.entries[1]["seq"] = 99  # zinciri kır
        assert s.tamga.verify() is False
        assert s.dogrula() is False

    def test_dogrula_payload_kurcalaninca_false(self):
        """Başarısızlık katman-2: payload değiştirilirse olcum_yaprak uyumsuz."""
        s = OlcumTamgaSabitleyici()
        s.sabitle(self._kanit())
        s.tamga.entries[0]["payload"]["actual_kw"] = 999.0
        # zincir hash'i değişti → önce zincir, sonra çapraz-çapa yakalar
        assert s.dogrula() is False

    def test_dogrula_sadece_merkle_kok_kurcalaninca_false(self):
        """Başarısızlık katman-2: merkle_kok değişirse çapraz-çapa yakalar.

        Zincir hash'ini yeniden onarsak bile (zincir katmanı geçse) çapraz-çapa
        katmanı Fleksa Merkle kökü uyuşmazlığını yakalar.
        """
        s = OlcumTamgaSabitleyici()
        s.sabitle(self._kanit())
        s.sabitle(self._kanit(saat=18, act=150.0))
        # 2. kaydın merkle kökünü boz ama seq/prev/h'yi yeniden onar
        s.tamga.entries[1]["merkle_kok"] = "b" * 64
        kayitlar = s.tamga.disa_aktar()
        s.tamga.entries.clear()
        for rec in kayitlar:
            govde = {k: v for k, v in rec.items() if k not in ("h", "seq", "prev")}
            s.tamga.append(govde)
        assert s.tamga.verify() is True          # zincir katmanı TEMİZ
        assert s.dogrula() is False              # ama çapraz-çapa YAKALADI

    def test_dogrula_eksik_olcum_tamliksa_false(self):
        """Başarısızlık katman-3: son kayıt düşürülüp zincir onarılırsa
        tamlık (completeness) katmanı sayi ≠ _sabitlenen'i yakalar."""
        s = OlcumTamgaSabitleyici()
        s.sabitle(self._kanit())
        s.sabitle(self._kanit(saat=18, act=150.0))
        kayitlar = s.tamga.disa_aktar()[:-1]  # son kaydı düşür
        s.tamga.entries.clear()
        for rec in kayitlar:
            govde = {k: v for k, v in rec.items() if k not in ("h", "seq", "prev")}
            s.tamga.append(govde)
        assert s.tamga.verify() is True          # zincir geçerli
        assert s.dogrula() is False              # ama 1 ≠ 2 → tamlık yakalandı

    def test_dogrula_yabanci_kayitlari_atlar(self):
        """Dal: dogrula, tip/kaynağı farklı kayıtları atlar (bağlı zincir
        senaryosu: aynı Tamga ledger'da başka projenin kayıtları olabilir)."""
        ortak = TamgaLedger()
        ortak.append({"tip": "baska_kayit", "kaynak": "diger-proje", "x": 1})
        s = OlcumTamgaSabitleyici(tamga=ortak)
        s.sabitle(self._kanit())
        s.sabitle(self._kanit(saat=18, act=150.0))
        assert len(s.tamga) == 3                 # 1 yabancı + 2 ölçüm
        assert s.dogrula() is True               # yabancı atlandı, tamlık 2==2

    def test_enjekte_edilen_tamga_kullanilir(self):
        """Başarı: __init__ verilen TamgaLedger'ı kullanır (varsayılan değil)."""
        ortak = TamgaLedger()
        s = OlcumTamgaSabitleyici(tamga=ortak)
        s.sabitle(self._kanit())
        assert s.tamga is ortak
        assert len(ortak) == 1

    def test_sabitle_ledger_geri_oynar(self):
        """Başarı: dış ledger girdileri kaynak sırayla sabitlenir; kökler
        kaynak defterin birebir aynısıdır (Merkle modeli korunur)."""
        dis = CryptographicSavingsLedger()
        dis.append_entry({"event": "DR", "saat": 17})
        dis.append_entry({"event": "DR", "saat": 18})
        s = OlcumTamgaSabitleyici().sabitle_ledger(dis)
        assert s.ozet()["sabitlenen_olcum"] == 2
        assert s.merkle_kok() == dis.compute_merkle_root()
        assert s.dogrula() is True

    def test_sabitle_ledger_bos_defter(self):
        """Sınır: boş dış ledger → hiçbir şey sabitlenmez, yine de geçerli."""
        s = OlcumTamgaSabitleyici().sabitle_ledger(CryptographicSavingsLedger())
        assert s.ozet()["sabitlenen_olcum"] == 0
        assert s.dogrula() is True

    def test_sabitle_ledger_self_donuser(self):
        """Başarı: sabitle_ledger fluent API için self döner."""
        s = OlcumTamgaSabitleyici()
        sonuc = s.sabitle_ledger(CryptographicSavingsLedger())
        assert sonuc is s

    def test_merkle_kok_bos_ledger(self):
        """Sınır: boş Merkle defteri bile deterministik bir kök döner."""
        s = OlcumTamgaSabitleyici()
        kok = s.merkle_kok()
        assert isinstance(kok, str) and len(kok) == 64
        assert kok == CryptographicSavingsLedger().compute_merkle_root()

    def test_ozet_anahtarlar_ve_degerler(self):
        """Başarı: ozet denetim-raporu tüm alanları doğru döner."""
        s = OlcumTamgaSabitleyici()
        s.sabitle(self._kanit())
        ozet = s.ozet()
        assert set(ozet) == {
            "sabitlenen_olcum", "tamga_kayit", "tamga_tip", "merkle_kok",
            "tamga_format", "kaynak", "dogru",
        }
        assert ozet["sabitlenen_olcum"] == 1
        assert ozet["tamga_kayit"] == 1
        assert ozet["tamga_tip"] == s.tamga.tip()
        assert ozet["merkle_kok"] == s.merkle_kok()
        assert ozet["tamga_format"] == "tamga-sim/1"
        assert ozet["kaynak"] == KAYNAK_PROJE
        assert ozet["dogru"] is True


# ---------------------------------------------------------------------------
# 7. sabitle_olcumler — tek-ışık yardımcı
# ---------------------------------------------------------------------------
class TestSabitleOlcumler:
    """sabitle_olcumler: boş liste, N öğe, enjekte tamga, dönüş tipi."""

    def _olcumler(self, n: int = 3) -> list[dict]:
        return [
            olcum_kanit_uret(tesis_id="tr-ist", olay="DR", saat=17 + i,
                             baseline_kw=300.0, actual_kw=200.0 + i,
                             tarif_try_kwh=3.8)
            for i in range(n)
        ]

    def test_bos_liste(self):
        """Sınır: boş liste → boş sabitleyici, yine de geçerli."""
        s = sabitle_olcumler([])
        assert s.ozet()["sabitlenen_olcum"] == 0
        assert s.dogrula() is True

    @pytest.mark.parametrize("n", [1, 2, 5])
    def test_n_oge_hepsi_sabitlenir(self, n: int):
        """Başarı: N ölçümün hepsi sabitlenir ve zincir geçerli kalır."""
        s = sabitle_olcumler(self._olcumler(n))
        assert s.ozet()["sabitlenen_olcum"] == n
        assert len(s.tamga) == n
        assert s.dogrula() is True

    def test_donus_tipi_sabitleyici(self):
        """Başarı: dönüş bir OlcumTamgaSabitleyici'dir."""
        s = sabitle_olcumler(self._olcumler(2))
        assert isinstance(s, OlcumTamgaSabitleyici)

    def test_enjekte_edilen_tamga_kullanilir(self):
        """Başarı: verilen tamga ledger'ına yazılır, başkası oluşturulmaz."""
        ortak = TamgaLedger()
        s = sabitle_olcumler(self._olcumler(2), tamga=ortak)
        assert s.tamga is ortak
        assert len(ortak) == 2
        assert s.dogrula() is True

    def test_siralamayi_korur(self):
        """Başarı: ölçümler verilme sırasıyla sabitlenir (seq/kaynak_seq)."""
        olcumler = self._olcumler(3)
        s = sabitle_olcumler(olcumler)
        saatlar = [rec["payload"]["saat"] for rec in s.tamga.entries]
        assert saatlar == [17, 18, 19]
