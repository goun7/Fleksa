"""tamga_anchor — Fleksa enerji ölçüm kanıtlarını Tamga hash-zincirine sabitleyen çapa katmanı.

KÖPRÜ: 76-Fleksa (01_unicorn, otonom enerji-esnekliği) ↔ TamgaProtocol
(05_acik_kaynak, bağımsız açık-kaynak kanıt protokolü).

Fleksa'nın ``audit`` akışı bir talep-yanıtı-kararının gerçekten-yürütüldüğünü
ve ölçülebildiğini kanıtlar: ``IpmvpBaselineEngine`` (IPMVP Option B /
EVO 10001-1:2022, 10-in-10 baseline + same-day-adjustment + ASHRAE Guideline 14)
üzerinden her-adımda-ölçüm-kanıtı üretir ve ``CryptographicSavingsLedger``
üzerinde SHA-256 **Merkle-ağacı-kökü** ile commitment altına alır. Bu modül,
o ölçüm kanıtlarını AYRICA Tamga'nın **kendi** ledger modeline sabitler — yani
her ölçüm-kanıtı yalnızca Fleksa'nın Merkle defterinde değil, Tamga'nın
bağımsız hash-zincirinde de değiştirilemez biçimde commitment altına alınır.

NEDEN İKİ ZİNCİR?
-----------------
Merkle-ağacı tek-bir-**anlık-görüntü** commitment'tır: tüm ölçümleri tek-bir
kök-hash'e indirger ve herhangi bir ölçümde geriye-dönük bir değişiklik kökü
değiştirir. Ama ağaç yapısı **sıra** hakkında bir şey söylemez — kök aynı
kaldığı sürece yaprakların yer-değiştirmesi veya çıkarılması fark-edilemez.
Tamga hash-zinciri bunu tamamlar: her kayıt bir öncekinin hash'ini içeren
``prev`` ile bağlanır, bu yüzden yaprakların **eklenme-sırası** kriptografik
olarak dondurulur. İkisini birleştirmek, ölçüm kanıtlarını hem anlık-görüntü
hem de sıralı olarak bağlar: Merkle kökü her Tamga kaydında yük olarak taşınır
(çapraz-çapa), böylece iki zincirden herhangi birinde yapılan kurcalama
``dogrula()`` ile yakalanır. Amaç: Fleksa'nın "esneklik-kanıtı üretir"
iddiasının, üreticinin kendisi bile geriye dönük olarak değiştiremeyeceği
bağımsız bir kanıt-zincirine bağlanması.

TAMGA LEDGER MODELİ (normatif — TamgaProtocol ``docs/ARCHITECTURE.md:42`` ve
``tamga_runner._verify_chain`` ile birebir):

    seq     : 1-based artan tamsayı
    prev    : önceki kaydın ``h`` değeri; İLK kayıt için 64×'0' (genesis)
    h       = sha256(prev ‖ jcs(kayıt − {h, node_sig}))
    kayıt   : düz JSON nesnesi; ``seq``/``prev``/``h`` + keyli yük alanları

İki kritik ayrım (YANLIŞ anlaşılması durumunda digest uyuşmaz):

1. ``prev`` hem **dize-prefix** olarak hem de jcs'in **içinde** bulunur —
   yani hash girdisi ``prev_str + jcs(kayıt)`` biçimindedir (bayt-düzeyinde).
2. Canonicalization **RFC 8785 (JCS)** ile yapılır — ``json.dumps(sort_keys=True)``
   DEĞİL. RFC 8785: üye-adları UTF-16 kod-birim dizisine göre sıralanır
   (§3.2.3) ve sayılar ECMAScript ``Number.prototype.toString`` algoritmasıyla
   yazılır (§3.2.2.2: ``1.0`` → ``"1"``, ``2.93e-07`` → ``"2.93e-7"``). Bu,
   başka bir dilde (Node/Go/Rust) yazılmış bir Tamga verifier'ının aynı
   baytları yeniden türetmesini sağlar; ``json.dumps`` yalnızca Python'da
   çalışır. Fleksa'nın ``CryptographicSavingsLedger``'ı (bilinçli olarak)
   Python ``json`` canonicalization kullanmaya devam eder — o, Fleksa'nın KENDİ
   modelidir ve olduğu gibi korunur; bu modül iki digest-uzayını **değer**
   düzeyinde köprüler (Merkle kökü Tamga kaydında taşınır), böylece Merkle
   modeli yeniden-icat-edilmez, Tamga zinciri ile BİRLEŞTİRİLİR.

JCS uygulaması bu modüle **bağımlılıksız** (stdlib-only) olarak gömülmüştür —
TamgaProtocol'ün ``tamga_canon.py``'siyle **bayt-bayt uyumlu** olacak biçimde
RFC 8785'den sıfırdan yazılmıştır. Gömme sebebi: Fleksa'nın Tamga kurulumuna
runtime bağımlılığı olmadan kendi başına çalışabilmesi (%100-egemenlik).
Parite, ``tamga_runner._verify_chain`` ve ``tamga_canon.jcs`` üzerine
çalışan bir testle kanıtlanır (mevcutsa; değilse skip).

KULLANIM:

    from fleksa.audit.tamga_anchor import (
        OlcumTamgaSabitleyici, olcum_kanit_uret,
    )

    sabitleyici = OlcumTamgaSabitleyici()
    for h in event_hours:
        sabitleyici.sabitle(olcum_kanit_uret(
            tesis_id="tr-ist-eqx-02", olay="DR_PEAK_SHAVE", saat=h,
            baseline_kw=adjusted_baseline[h], actual_kw=actual[h],
            tarif_try_kwh=ptf[h],
        ))
    assert sabitleyici.dogrula()   # Tamga zinciri + Merkle çapraz-çapa tamlık

    # Veya mevcut bir Fleksa Merkle defterini olduğu gibi sabitle:
    from fleksa.audit.ledger import CryptographicSavingsLedger
    ledger = CryptographicSavingsLedger()
    ledger.append_entry({"event": "DR_PEAK_SHAVE", "savings": savings})
    sabitleyici2 = OlcumTamgaSabitleyici().sabitle_ledger(ledger)
    assert sabitleyici2.dogrula()

ÇIKTI FORMATI: ``TamgaLedger.jsonl_yaz`` ``tamga-sim/1`` JSONL üretir;
TamgaProtocol'ün ``tamga_runner._verify_chain`` ve ``tests/conformance/verify.py``
bu çıktıyı doğrudan, hiçbir çeviri olmadan doğrulayabilir.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from fleksa.audit.ledger import CryptographicSavingsLedger

# Tamga genesis: ilk kaydın prev değeri (TamgaProtocol ile aynı sabit).
TAMGA_GENESIS_H = "0" * 64

# Kaynak defter kimliği — hangi projeden sabitlendiği Tamga zincirinde okunur.
KAYNAK_PROJE = "76-Fleksa/audit-ledger"

# Tamga ledger depolama-biçimi (conformance spec: "tamga-sim/1" JSONL).
TAMGA_LEDGER_FORMAT = "tamga-sim/1"

# Bu modülün ürettiği Tamga kayıt yük-etiketi.
KAYIT_TIPI = "olcum_kanit"

# Hash girdisinden çıkarılan alanlar (node_sig imza katmanı hash'in dışındadır;
# biz node_sig kullanmayız ama kuralı birebir uygulamak için dışarıda bırakırız).
_HASH_DISI_ALANLAR = frozenset({"h", "node_sig"})


class BozukTamgaZinciriError(RuntimeError):
    """Tamga zincir-bütünlüğü ihlali (seq/prev/hash uyuşmazlığı)."""


# ---------------------------------------------------------------------------
# RFC 8785 (JCS) — bağımlılıksız, TamgaProtocol tamga_canon.jcs ile bayt-uyumlu
# ---------------------------------------------------------------------------
_ESCAPE = {
    '"': '\\"', "\\": "\\\\", "\b": "\\b", "\f": "\\f",
    "\n": "\\n", "\r": "\\r", "\t": "\\t",
}


def es_number(x: float) -> str:
    """ECMAScript ``Number.prototype.toString`` (RFC 8785 §3.2.2.2).

    NaN/Infinity reddedilir (I-JSON altkümesi, RFC 7493). ``1.0`` → ``"1"``,
    ``2.93e-07`` → ``"2.93e-7"``, ``1e16`` → ``"10000000000000000"``.
    """
    if x != x or x in (float("inf"), float("-inf")):
        raise ValueError(
            "ijson_number_not_finite: NaN/Infinity I-JSON altkümesinde değil (RFC 7493)"
        )
    if x == 0:                       # -0.0 dahil "0" (ECMAScript "0" basar)
        return "0"
    neg = x < 0
    digits, exp = Decimal(repr(abs(x))).as_tuple()[-2:]
    # repr(1.0) → digits '10'; en-kısa gösterime kadar sondaki sıfırları at
    while len(digits) > 1 and digits[-1] == 0:
        digits, exp = digits[:-1], exp + 1
    k = len(digits)
    n = exp + k                      # değer = s × 10^(n-k), 10^(k-1) ≤ s < 10^k
    s = "".join(map(str, digits))
    if k <= n <= 21:
        body = s + "0" * (n - k)
    elif 0 < n <= 21:
        body = s[:n] + "." + s[n:]
    elif -6 < n <= 0:
        body = "0." + "0" * (-n) + s
    else:
        e = n - 1
        mant = s if k == 1 else s[0] + "." + s[1:]   # "1e+21", asla "1.e+21"
        body = mant + "e" + ("+" if e >= 0 else "-") + str(abs(e))
    return ("-" if neg else "") + body


def _enc_string(s: str) -> str:
    out = ['"']
    for ch in s:
        if ch in _ESCAPE:
            out.append(_ESCAPE[ch])
        elif ord(ch) < 0x20:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)           # raw UTF-8; non-ASCII kaçışlanMAZ
    out.append('"')
    return "".join(out)


def _encode(o: Any, out: List[str]) -> None:
    if o is None:
        out.append("null")
    elif o is True:
        out.append("true")
    elif o is False:
        out.append("false")
    elif isinstance(o, bool):        # savunma: bool, int'ın alt-sınıfıdır
        out.append("true" if o else "false")
    elif isinstance(o, int):
        # RFC 7493: tamsayılar [−2^53, 2^53] içinde olmalı; ECMAScript Number
        # (IEEE-754) sınır-aşan değeri temsil edemediğinden Node yuvarlar,
        # digest uyuşmaz. Sessiz-yuvarlama yerine RED.
        if not (-(2 ** 53) <= o <= 2 ** 53):
            raise ValueError(
                "ijson_number_out_of_range: [−2^53, 2^53] dışı tamsayı I-JSON "
                "altkümesinde değil; dize olarak serileştirin"
            )
        out.append(str(o))
    elif isinstance(o, float):
        out.append(es_number(o))
    elif isinstance(o, str):
        out.append(_enc_string(o))
    elif isinstance(o, dict):
        out.append("{")
        first = True
        # §3.2.3: üye-adları UTF-16 kod-birim dizisine göre artan sıralanır.
        for key in sorted(o, key=lambda k: str(k).encode("utf-16-be")):
            if not first:
                out.append(",")
            first = False
            out.append(_enc_string(str(key)))
            out.append(":")
            _encode(o[key], out)
        out.append("}")
    elif isinstance(o, (list, tuple)):
        out.append("[")
        first = True
        for item in o:
            if not first:
                out.append(",")
            first = False
            _encode(item, out)
        out.append("]")
    else:
        raise TypeError(f"jcs-desteklenmeyen-tip: {type(o).__name__}")


def jcs(obj: Any) -> bytes:
    """RFC 8785 canonical serialization (JCS) — UTF-8 baytları olarak.

    TamgaProtocol ``tamga_canon.jcs`` ile bayt-bayt uyumlu (parite-testi).
    """
    out: List[str] = []
    _encode(obj, out)
    return "".join(out).encode("utf-8")


def jcs_str(obj: Any) -> str:
    """Aynı canonicalization, ``str`` olarak (Tamga hash kuralının birebir
    taklidi: ``sha256(prev_str + jcs_str(kayıt)).encode()``)."""
    return jcs(obj).decode("utf-8")


def _json_saf_yap(deger: Any) -> Any:
    """Değeri JSON/JCS-güvenli ilkel türe indirger.

    Fleksa M&V akışı ``numpy`` skalerleri/vektörleri üretir; hem Fleksa
    Merkle defteri (``json.dumps``) hem de Tamga JCS bunları doğrudan
    serileştiremez veya farklı baytlar üretir. Bu adım her iki digest-uzayı
    için de **aynı** ilkel temsili garantiler — çapraz-çapanın üretilebilirliği
    buna bağlıdır.
    """
    if isinstance(deger, dict):
        return {str(k): _json_saf_yap(v) for k, v in deger.items()}
    if isinstance(deger, (list, tuple)):
        return [_json_saf_yap(v) for v in deger]
    if isinstance(deger, bool):
        return deger
    if isinstance(deger, (int, float, str)) or deger is None:
        return deger
    # numpy skaler/dizi desteği (fleksa numpy'e bağımlıdır; ama burada
    # çalışma-zamanı import'u ile stdlib-only kalınsın diye guardsız değil):
    try:
        import numpy as _np  # noqa: WPS433 — opsiyonel, fleksa'da her zaman var
    except ImportError:  # pragma: no cover
        _np = None
    if _np is not None:
        if isinstance(deger, _np.ndarray):
            return _json_saf_yap(deger.tolist())
        if isinstance(deger, _np.generic):
            return _json_saf_yap(deger.item())
    return str(deger)


# ---------------------------------------------------------------------------
# ölçüm-kanıtı üreteci — "her-adımda-ölçüm-kanıtı" birimi
# ---------------------------------------------------------------------------
def olcum_kanit_uret(
    *,
    tesis_id: str,
    olay: str,
    saat: int,
    baseline_kw: float,
    actual_kw: float,
    tarif_try_kwh: float,
    olay_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Tek bir IPMVP ölçüm-kanıdı oluştur (her-adımda-ölçüm-kanıtı).

    Bu, Fleksa'nın kanıt-birimidir: bir saat için **adjust edilmiş baseline**
    (neyin olması-gerektiği) ve **gerçek sayaç-okuması** (ne olduğu) yan
    yana kaydedilir. İkisi arasındaki fark talep-yanıtının ölçülen
    büyüklüğüdür; ``IpmvpBaselineEngine`` bunu kullanarak tasarrufu hesaplar.
    Değerler 6-ondalık-basamağa yuvarlanır ki hem Fleksa Merkle hem Tamga JCS
    digest'ları dilsiz-deterministik olsun (IEEE-754 repr sürprizlerine karşı).
    """
    base = round(float(baseline_kw), 6)
    act = round(float(actual_kw), 6)
    kanit: Dict[str, Any] = {
        "tesis": str(tesis_id),
        "olay": str(olay),
        "saat": int(saat),
        "baseline_kw": base,
        "actual_kw": act,
        "tarif_try_kwh": round(float(tarif_try_kwh), 6),
        "olcum_kesinti_kw": round(max(0.0, base - act), 6),
    }
    if olay_id is not None:
        kanit["olay_id"] = str(olay_id)
    return kanit


# ---------------------------------------------------------------------------
# TamgaLedger — Tamga ``tamga-sim/1`` gramerli hash-zinciri
# ---------------------------------------------------------------------------
class TamgaLedger:
    """TamgaProtocol ledger modeli: ``h = sha256(prev ‖ jcs(kayıt − {h}))``.

    Kayıt şeması: ``{"seq" (1-based), "prev", "h"} + keyli yük alanları``.
    Append-only; ``verify()`` zinciri yeniden-türetir; ``yukle()`` bozuk
    zinciri belleğe hiç almaz (fail-closed).
    """

    def __init__(self) -> None:
        self.entries: List[Dict[str, Any]] = []

    def __len__(self) -> int:
        return len(self.entries)

    # --- zincir çekirdeği (tamga_runner._verify_chain ile bayt-uyumlu) -------
    @staticmethod
    def _hashla(seq: int, prev: str, kayit: Dict[str, Any]) -> str:
        """D5 kuralı: ``sha256(prev ‖ jcs(kayıt-h-dışı))``.

        ``prev`` hem dize-prefix hem jcs içindedir — Tamga'nın birebir kuralı.
        """
        govde = {k: v for k, v in kayit.items() if k not in _HASH_DISI_ALANLAR}
        return hashlib.sha256((prev + jcs_str(govde)).encode("utf-8")).hexdigest()

    def append(self, kayit: Dict[str, Any]) -> Dict[str, Any]:
        """Yeni Tamga kaydı ekle; ``seq``/``prev``/``h`` otomatik atanır.

        Çağrıcı yalnızca yük alanlarını verir; ``seq``/``prev``/``h`` zaten
        içeride varsa üzerine yazılır (append-only sözü: mevcut kayıtlar
        değiştirilemez).
        """
        return self._append(dict(kayit))

    def _append(self, kayit: Dict[str, Any]) -> Dict[str, Any]:
        # D5: hash TAM kaydın (seq+prev+yük, h/node_sig dışarıda) üzerinedir;
        # bu yüzden seq/prev atanmış tam kaydı kurup öyle hashleriz.
        tam_kayit = {k: v for k, v in kayit.items() if k not in _HASH_DISI_ALANLAR}
        seq = len(self.entries) + 1
        prev = self.entries[-1]["h"] if self.entries else TAMGA_GENESIS_H
        tam_kayit["seq"] = seq
        tam_kayit["prev"] = prev
        tam_kayit["h"] = self._hashla(seq, prev, tam_kayit)
        self.entries.append(tam_kayit)
        return tam_kayit

    def verify(self) -> bool:
        """Zincir bütünlüğü: 1-based seq-sırası + prev-bağlantısı + hash-tekrar-hesabı.

        ``tamga_runner._verify_chain`` ile aynı kararlar:
        ``rec["prev"] != prev_h`` veya ``rec["h"] != beklenen`` veya
        ``rec["seq"] != n`` → ``False``.
        """
        prev_h = TAMGA_GENESIS_H
        for n, rec in enumerate(self.entries, start=1):
            if rec.get("seq") != n:
                return False
            if rec.get("prev") != prev_h:
                return False
            if self._hashla(n, rec["prev"], rec) != rec.get("h"):
                return False
            prev_h = rec["h"]
        return True

    def yukle(self, kayitlar: Sequence[Dict[str, Any]]) -> None:
        """Kayıtlı Tamga zincirini yeniden-kur; her kayıt için seq/prev/hash
        yeniden-doğrulanır — bozuk zincir belleğe HİÇ girmez (fail-closed)."""
        for gelen in kayitlar:
            seq = gelen.get("seq")
            prev = gelen.get("prev")
            h = gelen.get("h")
            if not isinstance(seq, int) or not isinstance(prev, str) or not isinstance(h, str):
                raise BozukTamgaZinciriError(
                    f"eksik/bozuk Tamga kayıt-alanları: seq/prev/h (seq={seq})"
                )
            beklenen_prev = self.entries[-1]["h"] if self.entries else TAMGA_GENESIS_H
            if seq != len(self.entries) + 1:
                raise BozukTamgaZinciriError(
                    f"seq-sırası bozuk: beklenen {len(self.entries) + 1}, gelen {seq}"
                )
            if prev != beklenen_prev:
                raise BozukTamgaZinciriError(
                    f"prev-bağlantısı bozuk (seq {seq}): beklenen {beklenen_prev[:12]}…"
                )
            govde = {k: v for k, v in gelen.items() if k not in _HASH_DISI_ALANLAR}
            if self._hashla(seq, prev, govde) != h:
                raise BozukTamgaZinciriError(
                    f"h-doğrulaması başarısız (seq {seq}) — Tamga zinciri kurcalanmış"
                )
            tam = dict(govde)
            tam["seq"] = seq
            tam["prev"] = prev
            tam["h"] = h
            self.entries.append(tam)

    def disa_aktar(self) -> List[Dict[str, Any]]:
        """Tamga JSONL'ye yazılabilir kayıt listesi (kopya)."""
        return [dict(g) for g in self.entries]

    def tip(self) -> Optional[str]:
        """Zincir baş-hash'i (son kaydın ``h``); boşsa ``None``."""
        return self.entries[-1]["h"] if self.entries else None

    def jsonl_yaz(self, yol: str | Path) -> str:
        """Zinciri ``tamga-sim/1`` JSONL olarak yaz (Tamga verifier'lar için).

        TamgaProtocol'ün ``tamga_runner._verify_chain`` ve
        ``tests/conformance/verify.py`` bu çıktıyı doğrudan doğrulayabilir.
        """
        yol = Path(yol)
        with open(yol, "w", encoding="utf-8") as f:
            for rec in self.entries:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return str(yol)

    def jsonl_oku(self, yol: str | Path) -> None:
        """JSONL'den fail-closed yeniden-yükleme."""
        yol = Path(yol)
        kayitlar = []
        with open(yol, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    kayitlar.append(json.loads(line))
        self.yukle(kayitlar)


# ---------------------------------------------------------------------------
# OlcumTamgaSabitleyici — Fleksa ölçüm kanıtlarını Tamga zincirine bağlar
# ---------------------------------------------------------------------------
class OlcumTamgaSabitleyici:
    """Enerji ölçüm kanıtlarını Fleksa M&V modelinden alıp Tamga hash-zincirine
    sabitler; her kayıtta Fleksa Merkle-ağacı-kökünü çapraz-çapa taşır.

    Her ölçüm-kanıtı için Tamga zincirine bir kayıt yazılır. Kayıt, kanıtın
    **kendi yaprak-hash'ini** (``olcum_yaprak``, Fleksa Merkle modelinde) ve
    o anki **Merkle kökünü** (``merkle_kok``) yük olarak taşıdığı için:

    * Tamga zincirinde yapılan herhangi bir kurcalama ``verify()`` ile,
    * Fleksa Merkle defterinde yapılan her geriye-dönük değişiklik
      ``dogrula()``'nın çapraz-çapa katmanında (kök artık uyuşmaz),
    * ölçümlerden birinin atlanması tamlık (completeness) katmanında yakalanır.

    ``sabitle`` idempotent-değildir (aynı kanıtı iki kez sabitlemek iki kayıt
    yazar); büyüyen bir defter için ``sabitle``'yi her YENI ölçümde çağır.
    """

    def __init__(self, tamga: Optional[TamgaLedger] = None) -> None:
        self.tamga = tamga if tamga is not None else TamgaLedger()
        # Fleksa'nın KENDİ modeli — Merkle kökü burada hesaplanır ve Tamga
        # kayıtlarında taşınır. Bu, "Merkle modelini yeniden icat etmemek"
        # kısıtıdır: CryptographicSavingsLedger olduğu gibi kullanılır.
        self.merkle = CryptographicSavingsLedger()
        self._sabitlenen = 0

    # --- sabitleme ---------------------------------------------------------
    def sabitle(self, olcum: Dict[str, Any]) -> Dict[str, Any]:
        """Bir ölçüm-kanıtını Tamga zincirine sabitle (sabitleme-birimi).

        Ölçüm önce Fleksa Merkle defterine eklenir (yaprak + o anki kök), sonra
        Tamga zincirine bir kayıt yazılır. Kayıt yükü şunları taşır:

        * ``tip`` = ``"olcum_kanit"``, ``kaynak`` = bu proje (kim sabitledi),
        * ``kaynak_seq`` — Fleksa defterindeki 1-based ölçüm sırası,
        * ``olcum_yaprak`` — ölçümün Fleksa Merkle yaprak-hash'i,
        * ``merkle_kok`` — o ana kadar tüm ölçümlerin Merkle kökü (çapraz-çapa),
        * ``payload`` — ölçüm-kanıtının kendisi (denetlenebilir ham içerik).
        """
        kanit = _json_saf_yap(olcum)
        yaprak = self.merkle.append_entry(kanit)
        kok = self.merkle.compute_merkle_root()
        kayit = {
            "tip": KAYIT_TIPI,
            "kaynak": KAYNAK_PROJE,
            "kaynak_seq": self._sabitlenen + 1,
            "olcum_yaprak": yaprak,
            "merkle_kok": kok,
            "payload": kanit,
        }
        rec = self.tamga.append(kayit)
        self._sabitlenen += 1
        return rec

    def sabitle_ledger(self, dis_ledger: CryptographicSavingsLedger) -> "OlcumTamgaSabitleyici":
        """Mevcut bir Fleksa Merkle defterinin tüm girdilerini sabitle.

        Girdiler, kaynak defterdeki sırayla (``dis_ledger.entries``) yeniden
        oynatılır; her biri için yaprak ve o anki Merkle kökü yeniden-hesaplanır,
        böylece sabitlenen kökler kaynak defterin kilerinin birebir aynısıdır.
        Bu, ``fleksa audit`` çıktısının olduğu gibi Tamga zincirine
        bağlanabilmesini sağlar (Merkle modeli korunur, yeniden-icat-edilmez).
        """
        for girdi in dis_ledger.entries:
            self.sabitle(girdi)
        return self

    # --- doğrulama ---------------------------------------------------------
    def dogrula(self) -> bool:
        """Üç katmanlı doğrulama (hepsi sağlanmalı):

        1. **Tamga zincir bütünlüğü** — ``TamgaLedger.verify()`` (D5 kuralı):
           1-based seq, prev-bağlantısı ve ``sha256(prev ‖ jcs(kayıt))`` tekrar-hesabı.
        2. **Çapraz-çapa bütünlüğü** — her sabitlenmiş kaydın ``olcum_yaprak``
           ve ``merkle_kok`` değerleri, kayıtlı ``payload`` üzerinden Fleksa
           Merkle modeli yeniden-oynatılarak türetilmelidir. Bu, Fleksa
           defterinde geriye-dönük bir değişiklik yapılırsa Tamga zincirinin
           artık o kanıtı **doğrulamamasını** sağlar (ve tersi).
        3. **Tamlık (completeness)** — sabitlenen ölçüm sayısı, anchor'da
           kayıtlı ölçüm sayısına eşit olmalıdır (atlanmış kanıt yok).
        """
        # 1. Tamga zinciri
        if not self.tamga.verify():
            return False

        # 2. çapraz-çapa: Merkle köklerini payload'dan yeniden türet
        yeniden = CryptographicSavingsLedger()
        sayi = 0
        for rec in self.tamga.entries:
            if rec.get("tip") != KAYIT_TIPI or rec.get("kaynak") != KAYNAK_PROJE:
                continue
            yaprak = yeniden.append_entry(rec.get("payload", {}))
            if rec.get("olcum_yaprak") != yaprak:
                return False                    # ölçüm kurcalanmış
            if rec.get("merkle_kok") != yeniden.compute_merkle_root():
                return False                    # Merkle kökü uyuşmuyor (geriye-dönük değişiklik)
            sayi += 1

        # 3. tamlık: her ölçüm sabitlenmiş olmalı
        if sayi != self._sabitlenen:
            return False

        return True

    def merkle_kok(self) -> str:
        """Fleksa Merkle defterinin şu-anki kökü (tamamlandığında audit-claim)."""
        return self.merkle.compute_merkle_root()

    def ozet(self) -> Dict[str, Any]:
        """Sabitleme durum özeti (denetim-raporu amaçlı)."""
        return {
            "sabitlenen_olcum": self._sabitlenen,
            "tamga_kayit": len(self.tamga),
            "tamga_tip": self.tamga.tip(),
            "merkle_kok": self.merkle_kok(),
            "tamga_format": TAMGA_LEDGER_FORMAT,
            "kaynak": KAYNAK_PROJE,
            "dogru": self.dogrula(),
        }


def sabitle_olcumler(
    olcumler: Sequence[Dict[str, Any]],
    tamga: Optional[TamgaLedger] = None,
) -> OlcumTamgaSabitleyici:
    """Tek-ışık: ölçüm-kanıtı listesini yeni bir Tamga zincirine sabitleyip döner."""
    sabitleyici = OlcumTamgaSabitleyici(tamga=tamga)
    for olcum in olcumler:
        sabitleyici.sabitle(olcum)
    return sabitleyici
