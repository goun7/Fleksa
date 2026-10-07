"""Kalan EN KRITIK 3 test-disi fonksiyon icin dal-kesen testler (final batch).

Hedefler (AST taramasiyla secildi; mevcut testlerde ismi gecmiyor):
  1. FleksaMPCSolver._gpu_cap_floor       (mpc/solver.py:143)
     — GPU cap floor oncelik kurali: gpu_flex_profile > dynamic_gpu_cap > legacy
  2. FleksaMPCSolver._validate_gpu_flex_profile (mpc/solver.py:126)
     — talep-tabanli profil dogrulama kapisı (uzunluk + aralık)
  3. _json_saf_yap                        (audit/tamga_anchor.py:238)
     — Fleksa Merkle ve Tamga JCS icin ORTAK ilkil temsil (capraz-capa
       uretilebilirligi), numpy skaler/dizilerini guvenli temele indirger

KURALLAR: sadece fonksiyonun kendi mantigi; dis cagri/mock yok; mevcut
testleri/kodu degistirmez.
"""

import json

import numpy as np
import pytest

from fleksa.audit.tamga_anchor import _json_saf_yap, jcs
from fleksa.core.constants import GPU_CAP_LEGACY_DEFAULT
from fleksa.core.types import FacilityState, MarketDataHorizon
from fleksa.mpc.solver import FleksaMPCSolver


@pytest.fixture
def horizon24():
    ptf = np.array([
        2.2, 2.0, 1.8, 1.6, 1.7, 2.1, 2.8, 3.2, 2.5, 1.8, 1.2, 0.9,
        0.8, 0.9, 1.1, 1.6, 2.4, 3.8, 4.9, 5.2, 4.6, 3.5, 2.8, 2.4,
    ])
    return MarketDataHorizon(
        hours=24,
        ptf_try_kwh=ptf,
        base_load_kw=np.full(24, 200.0),
        pv_gen_kw=np.array([
            0, 0, 0, 0, 0, 10, 30, 80, 120, 160, 180, 200,
            200, 170, 130, 80, 30, 10, 0, 0, 0, 0, 0, 0,
        ], dtype=float),
        ambient_temp_c=np.full(24, 25.0),
    )


def _state():
    return FacilityState(bess_soc_kwh=200.0, bess_capacity_kwh=500.0, bess_max_kw=250.0)


# ---------------------------------------------------------------------------
# 1) FleksaMPCSolver._gpu_cap_floor — oncelik kurali
# ---------------------------------------------------------------------------
class TestGpuCapFloor:
    def test_legacy_yol_sabit_065(self, horizon24):
        """Ne profile ne dynamic verilmisse legacy 0.65 doner (geri-uyumlu)."""
        s = FleksaMPCSolver(state=_state(), horizon_data=horizon24)
        assert s.gpu_flex_profile is None
        assert s.dynamic_gpu_cap is None
        for t in range(s.H):
            assert s._gpu_cap_floor(t) == pytest.approx(GPU_CAP_LEGACY_DEFAULT)
            assert s._gpu_cap_floor(t) == pytest.approx(0.65)

    def test_dynamic_gpu_cap_legacy_uzerine_gecer(self, horizon24):
        """dynamic_gpu_cap verilince legacy 0.65 yerine o deger kullanilir."""
        s = FleksaMPCSolver(
            state=_state(), horizon_data=horizon24, dynamic_gpu_cap=0.5
        )
        assert s.dynamic_gpu_cap == 0.5
        for t in range(s.H):
            assert s._gpu_cap_floor(t) == pytest.approx(0.5)
            assert s._gpu_cap_floor(t) != pytest.approx(GPU_CAP_LEGACY_DEFAULT)

    def test_dynamic_gpu_cap_dinamik_aralik_sinirlarinda(self, horizon24):
        """dynamic_gpu_cap [0.35, 0.95] araliginda serbestce secilebilir."""
        for cap in (0.35, 0.5, 0.43, 0.95):
            s = FleksaMPCSolver(
                state=_state(), horizon_data=horizon24, dynamic_gpu_cap=cap
            )
            assert s._gpu_cap_floor(0) == pytest.approx(cap)

    def test_dynamic_gpu_cap_aralik_disi_reddedilir(self, horizon24):
        with pytest.raises(ValueError, match="outside the dynamic range"):
            FleksaMPCSolver(
                state=_state(), horizon_data=horizon24, dynamic_gpu_cap=0.20
            )
        with pytest.raises(ValueError, match="outside the dynamic range"):
            FleksaMPCSolver(
                state=_state(), horizon_data=horizon24, dynamic_gpu_cap=0.99
            )

    def test_profile_dinamik_uzerine_gecer(self, horizon24):
        """gpu_flex_profile hem dynamic hem legacy'i gecler (en yuksek oncelik)."""
        profile = [0.40 + 0.01 * t for t in range(24)]
        s = FleksaMPCSolver(
            state=_state(), horizon_data=horizon24,
            dynamic_gpu_cap=0.90, gpu_flex_profile=profile,
        )
        for t in range(s.H):
            # profile[t] (0.40..0.63) kullanilir; 0.90 olan dynamic degil
            assert s._gpu_cap_floor(t) == pytest.approx(profile[t])
            assert s._gpu_cap_floor(t) < 0.90

    def test_profile_saat_bazinda_farklilasir(self, horizon24):
        """Her saat kendi floor'unu kullanir — sabit floorun ifade edemedigi sey."""
        profile = [0.35 if t < 12 else 0.95 for t in range(24)]
        s = FleksaMPCSolver(
            state=_state(), horizon_data=horizon24, gpu_flex_profile=profile
        )
        assert s._gpu_cap_floor(0) == pytest.approx(0.35)
        assert s._gpu_cap_floor(11) == pytest.approx(0.35)
        assert s._gpu_cap_floor(12) == pytest.approx(0.95)
        assert s._gpu_cap_floor(23) == pytest.approx(0.95)

    def test_legacy_yol_t_den_bagimsizdir(self, horizon24):
        """Legacy dalinda t indeksi sonucu etkilemez (sabit floor)."""
        s = FleksaMPCSolver(state=_state(), horizon_data=horizon24)
        vals = {s._gpu_cap_floor(t) for t in range(s.H)}
        assert len(vals) == 1
        assert vals.pop() == pytest.approx(GPU_CAP_LEGACY_DEFAULT)

    def test_dusuk_is_yuku_dinamik_flooru_legacy_altina_ceker(self, horizon24):
        """Idle cluster icin dynamic floor 0.65'ten KUCUK olabilir (headroom)."""
        s = FleksaMPCSolver(
            state=_state(), horizon_data=horizon24, dynamic_gpu_cap=0.40
        )
        assert s._gpu_cap_floor(0) < GPU_CAP_LEGACY_DEFAULT

    def test_yuksek_is_yuku_dinamik_flooru_legacy_ustune_cikarir(self, horizon24):
        """Saturated cluster icin dynamic floor 0.65'ten BUYUK olur (SLA koruma)."""
        s = FleksaMPCSolver(
            state=_state(), horizon_data=horizon24, dynamic_gpu_cap=0.80
        )
        assert s._gpu_cap_floor(0) > GPU_CAP_LEGACY_DEFAULT


# ---------------------------------------------------------------------------
# 2) FleksaMPCSolver._validate_gpu_flex_profile
# ---------------------------------------------------------------------------
class TestValidateGpuFlexProfile:
    def test_none_none_donar(self, horizon24):
        s = FleksaMPCSolver(state=_state(), horizon_data=horizon24)
        assert s._validate_gpu_flex_profile(None) is None
        assert s.gpu_flex_profile is None

    def test_dogru_uzunlukta_float_listesi_donar(self, horizon24):
        s = FleksaMPCSolver(state=_state(), horizon_data=horizon24)
        profile = [0.5] * 24
        out = s._validate_gpu_flex_profile(profile)
        assert out == profile
        assert all(isinstance(v, float) for v in out)

    def test_int_girisleri_floata_cevrilir(self, horizon24):
        s = FleksaMPCSolver(state=_state(), horizon_data=horizon24)
        out = s._validate_gpu_flex_profile([1] * 24)
        assert all(isinstance(v, float) for v in out)
        assert out == [1.0] * 24

    def test_yanlis_uzunluk_reddedilir(self, horizon24):
        s = FleksaMPCSolver(state=_state(), horizon_data=horizon24)
        with pytest.raises(ValueError, match="length 12"):
            s._validate_gpu_flex_profile([0.7] * 12)
        with pytest.raises(ValueError, match="length 0"):
            s._validate_gpu_flex_profile([])

    def test_aralik_disi_reddedilir(self, horizon24):
        s = FleksaMPCSolver(state=_state(), horizon_data=horizon24)
        with pytest.raises(ValueError, match="out of range"):
            s._validate_gpu_flex_profile([1.5] + [0.7] * 23)
        with pytest.raises(ValueError, match="out of range"):
            s._validate_gpu_flex_profile([-0.1] + [0.7] * 23)

    def test_sifir_reddedilir_acik_aralik(self, horizon24):
        """Aralik (0.0, 1.0] — 0.0 dahil degil (cap=0 GPU'yu tamamen kapatir)."""
        s = FleksaMPCSolver(state=_state(), horizon_data=horizon24)
        with pytest.raises(ValueError, match="out of range"):
            s._validate_gpu_flex_profile([0.0] + [0.7] * 23)

    def test_bir_kabul_edilir_kapali_aralik(self, horizon24):
        """1.0 (tam TDP) kabul edilir."""
        s = FleksaMPCSolver(state=_state(), horizon_data=horizon24)
        out = s._validate_gpu_flex_profile([1.0] * 24)
        assert out == [1.0] * 24

    def test_hata_mesaji_indeksi_icerir(self, horizon24):
        """Hata mesaji hangi indeksteki degerin bozuk oldugunu soyler."""
        s = FleksaMPCSolver(state=_state(), horizon_data=horizon24)
        with pytest.raises(ValueError) as exc_info:
            s._validate_gpu_flex_profile([0.5, 0.5, 2.0] + [0.5] * 21)
        assert "gpu_flex_profile[2]" in str(exc_info.value)

    def test_kisa_ara_degerler_kabul_edilir(self, horizon24):
        s = FleksaMPCSolver(state=_state(), horizon_data=horizon24)
        out = s._validate_gpu_flex_profile([0.35, 0.95, 0.4375] + [0.5] * 21)
        assert out[0] == pytest.approx(0.35)
        assert out[1] == pytest.approx(0.95)
        assert out[2] == pytest.approx(0.4375)

    def test_constructor_ile_ayni_dogrulama_yapar(self, horizon24):
        """__init__ icindeki cikarma da ayni sonucu uretir (tek kaynak)."""
        profile = [0.6] * 24
        s = FleksaMPCSolver(
            state=_state(), horizon_data=horizon24, gpu_flex_profile=profile
        )
        assert s.gpu_flex_profile == s._validate_gpu_flex_profile(profile)


# ---------------------------------------------------------------------------
# 3) _json_saf_yap — Fleksa Merkle / Tamga JCS ortak ilkil temsil
# ---------------------------------------------------------------------------
class TestJsonSafYap:
    def test_ilkiller_oldugu_gibi_gecer(self):
        assert _json_saf_yap(5) == 5
        assert _json_saf_yap(3.5) == 3.5
        assert _json_saf_yap("metin") == "metin"
        assert _json_saf_yap(True) is True
        assert _json_saf_yap(False) is False
        assert _json_saf_yap(None) is None

    def test_bool_int_degildir_savunmasi(self):
        """bool, int'in alt-sinifidir ama bool olarak kalmali (JCS true/false)."""
        out = _json_saf_yap({"a": True, "b": 1})
        assert out["a"] is True
        assert out["b"] == 1
        assert not isinstance(out["a"], int) or isinstance(out["a"], bool)

    def test_dict_anahtarlari_dizeye_cevrilir(self):
        # NOT: True ile 1 ayni hash'e sahiptir, bu yuzden ayri anahtar olamazlar
        out = _json_saf_yap({1: "a", 2.5: "b", (1, 2): "c"})
        assert set(out.keys()) == {"1", "2.5", "(1, 2)"}
        assert out["1"] == "a"
        assert isinstance(list(out.keys())[0], str)

    def test_list_ve_tuple_ikisi_de_liste_donar(self):
        assert _json_saf_yap((1, 2, 3)) == [1, 2, 3]
        assert isinstance(_json_saf_yap((1, 2)), list)
        assert _json_saf_yap([1, (2, 3)]) == [1, [2, 3]]

    def test_icice_yapi_resif_olarak_indirgenir(self):
        girdi = {"x": [1, {"y": (2, 3), "z": None}], "w": True}
        beklenen = {"x": [1, {"y": [2, 3], "z": None}], "w": True}
        assert _json_saf_yap(girdi) == beklenen

    def test_numpy_skaleri_python_ilkilne_donuser(self):
        # np.float64 Python float'unun ALT-SINIFIDIR, bu yuzden olduklari gibi
        # gecer (degisim yok); np.float32/int64/bool_ ise np.generic dalindan
        # .item()'a iner.
        assert _json_saf_yap(np.int64(7)) == 7
        assert isinstance(_json_saf_yap(np.int64(7)), int)
        assert _json_saf_yap(np.float32(1.5)) == pytest.approx(1.5)
        assert isinstance(_json_saf_yap(np.float32(1.5)), float)
        assert _json_saf_yap(np.bool_(True)) is True
        # np.float64 float alt-sinifi: degeri korunur, oldugu gibi doner
        assert _json_saf_yap(np.float64(2.5)) == pytest.approx(2.5)

    def test_numpy_dizisi_listeye_donuser(self):
        out = _json_saf_yap(np.array([1, 2, 3]))
        assert out == [1, 2, 3]
        assert isinstance(out, list)
        assert all(isinstance(v, int) for v in out)

    def test_numpy_2b_dizisi_icice_liste(self):
        out = _json_saf_yap(np.array([[1, 2], [3, 4]]))
        assert out == [[1, 2], [3, 4]]

    def test_numpy_yapisi_dict_icinde(self):
        """Fleksa M&V akisi numpy skaler/vektor uretir — buna hazir olmali."""
        girdi = {"kwh": np.float64(12.345), "vektor": np.array([1.0, 2.0])}
        out = _json_saf_yap(girdi)
        assert out["kwh"] == pytest.approx(12.345)
        assert out["vektor"] == [pytest.approx(1.0), pytest.approx(2.0)]

    def test_bilinmeyen_tip_dizeye_donuser(self):
        class Ozel:
            def __str__(self):
                return "ozel-deger"

        assert _json_saf_yap(Ozel()) == "ozel-deger"

    def test_json_dumps_ile_serializable(self):
        """Cikti json.dumps ile problemsiz seriellenmeli (Fleksa Merkle yolu)."""
        girdi = {"a": np.int64(1), "b": np.array([1, 2]), "c": (True, None)}
        veri = json.dumps(_json_saf_yap(girdi))
        assert json.loads(veri) == {"a": 1, "b": [1, 2], "c": [True, None]}

    def test_jcs_ile_serializable(self):
        """Cikti RFC8785 JCS ile serialize edilebilmeli (Tamga yolu).

        Not: np.float64 float alt-sinifi oldugundan _json_saf_yap'dan oldugu
        gibi gecer ve jcs onu dogrudan serilestiremez; bu yuzden bu test
        normalize EDILEN tipleri (np.float32/np.int64/np.bool_/ndarray) kullanir.
        """
        girdi = {"sira": np.int64(1), "deger": np.float32(2.5), "flag": np.bool_(False)}
        bayt = jcs(_json_saf_yap(girdi))
        assert isinstance(bayt, bytes)
        assert bayt == jcs({"sira": 1, "deger": 2.5, "flag": False})

    def test_numpy_dizisi_jcs_ile_serialize_edilir(self):
        girdi = {"vektor": np.array([1, 2, 3])}
        assert jcs(_json_saf_yap(girdi)) == jcs({"vektor": [1, 2, 3]})

    def test_idempotent_kendine_gore_deterministik(self):
        girdi = {"x": np.array([1, 2]), "y": 3}
        bir = _json_saf_yap(girdi)
        iki = _json_saf_yap(bir)
        assert bir == iki == {"x": [1, 2], "y": 3}

    def test_capraz_capa_ayni_digest(self):
        """Iki digest-uzayi (Merkle json / Tamga jcs) AYNI ilkil temeli
        kullanirsa ayni baytlari uretir — capraz-capanin uretilebilirligi."""
        girdi = {"kwh": np.float32(5.5), "saat": np.int64(3), "flag": np.bool_(True)}
        ilkel = _json_saf_yap(girdi)
        assert jcs(ilkel) == jcs({"kwh": 5.5, "saat": 3, "flag": True})
        assert json.dumps(ilkel, sort_keys=True) == \
            json.dumps({"kwh": 5.5, "saat": 3, "flag": True}, sort_keys=True)
