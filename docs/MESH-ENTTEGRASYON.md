# MESH Entegrasyon Değerlendirmesi — Kredent DID + Sester Receipt Zinciri

> **Tarih:** 2026-09-29
> **Soru:** (1) YIELDIX/FLEKSA çıktıları **Kredent DID** ile imzalanabilir mi?
> (2) **Sester receipt zincirine** bağlanabilir mi?
> **Cevap:** **Evet — her ikisi de.** Aşağıda somut gerekçe ve uygulanabilirlik
> analizi. **Dürüst-not:** bu bir *değerlendirmedir*, uygulanmış-bağlantı değil;
> kardeş-bağımlılık-kısıtı ( aşağıda) nedeniyle gerçek-entegrasyon kendi-kararıdır.

---

## 1. Kriptografik-uyum ( neden "evet")

Her-dört-taraf da **aynı kriptografi-temsili** kullanıyor — bu entegrasyonun
temel-önkoşuludur:

| Bileşen | İmza-algoritması | Özet-algoritması | Kimlik-formatı |
|---|---|---|---|
| **YIELDIX** | Ed25519 ( RFC 8032) | SHA-256 ( canonical JSON) | imzalı-KPI-rapor |
| **FLEKSA** | Ed25519 ( W3C VC v2) | SHA-256 ( Merkle-ağacı) | `did:fleksa:...` |
| **Kredent** | Ed25519 ( W3C did:key) | SHA-256 ( canonical attestation) | `did:key:z6Mk...` |
| **Sester** | — ( ödeme-metresi) | SHA-256 ( hash-chained ledger) | seq+prev_hash |

**Anahtar-gözlem:** YIELDIX ve FLEKSA zaten **Ed25519 + SHA-256** kullanıyor.
Kredent'in `did:key` formatı Ed25519 public-key'inden türetilir — yani
YIELDIX/FLEKSA'nın imzaladığı **aynı private-key** ile bir `did:key`
kimliği-üretilebilir. **Yeni bir anahtar-altyapısı gerekmez.**

## 2. Kredent DID ile imzalama ( uygulanabilirlik: YÜKSEK)

### 2.1 YIELDIX — imzalı-KPI-raporu → Kredent attestation

YIELDIX'in `MonthlyReportGenerator.generate_signed_report` çıktısı:
```
sha256_digest + ed25519_signature  →  MonthlyReportPayload
```

Kredent'in `create_attestation(seed, claim)` API'si tam olarak bu-formdadır:
`claim` = KPI-payload ( total_leads, qualified_sql, CPL, p95, …), imza =
Ed25519. **Dönüşüm-maliyeti: düşük** — mevcut `Ed25519ReportSigner`
zaten `sign_dict` ile aynı kanonikleştirme-yolunu ( sorted-JSON) kullanır.

**YIELDIX için önerilen-uyumluluk-katmanı:**
```python
# Kavramsal — mevcut imzalı-raporu Kredent did:key'e sarmalar
from kredent.attest import create_attestation
att = create_attestation(
    seed=yieldix_seed_32bytes,           # AYNI Ed25519 seed
    claim={"report_id":..., "qualified_sql":..., "cpl_try":...},
)
# att.issuer == "did:key:z6Mk..." ( YIELDIX anahtarından türetilmiş)
```

**Sınırlar ( dürüst):**
- YIELDIX imzaları **rapor-başına-yeni-anahtar** üretmez-varsayar; Kredent
  `did:key` kalıcı-kimlik-ister. Çözüm: tenant-başına-bir-seed ( `YIELDIX_TENANT_SEED`).
- **PRIVATE_KEY-ÜRETİM-YASAK** kısıtı-geçerli: seed yalnızca yerel-demoda
  `01*32` ( mevcut-modelle-aynı).

### 2.2 FLEKSA — W3C VC → Kredent ( zaten uyumlu!)

FLEKSA'nın `protocols/attestation.py`'i **W3C Verifiable Credential v2**
üretir — Kredent'in attestation-formatı ile **aynı-standart**. Bu en-düşük-
maliyetli-entegrasyondur: FLEKSA VC'sinin `issuer` alanını `did:key:...`
olarak değiştirmek ( şu-anda `did:fleksa:...`) ve `cryptosuite`'i Kredent'in
beklediği-multibase-formata-getirmek yeterlidir.

## 3. Sester receipt zincirine bağlanma ( uygulanabilirlik: ORTA-YÜKSEK)

### 3.1 Sester receipt-modeli

Sester'in ledger'ı ( `sester/ledger.py`):
```
canonical_line(ts, event_type, agent_id, host, amount, payload, prev_hash)
  → SHA-256 → hash → sonraki-satırın prev_hash'i
```
Yani **her-olay bir öncekinin hash'ine bağlı**; zincir-kırılması
`prev_hash != prev` ile tespit-edilir.

### 3.2 YIELDIX/FLEKSA çıktısının Sester'e bağlanması

**FLEKSA** için doğal-bağlantı-noktası: `CryptographicSavingsLedger`'ın
Merkle-root'u zaten SHA-256 hash-zinciridir. Bir DR-olayı:
```
fleksa audit → Merkle-root → Sester append(
    event_type="FLEKSA_DR_PROOF",
    payload=merkle_root_hex,        # kanıt
    amount=0.0,                     # ödeme-YOK ( kanıt-için)
) → receipt(seq, hash, prev_hash)
```
**Sester'in "herkes sha256 ile doğrular" ilkesi** FLEKSA'nın
`audit-verify`'ı ile **aynı-felsefededir** — iki-bağımsız-doğrulama-katmanı
biri-birini-güçlendirir.

**YIELDIX** için: imzalı-KPI-raporun SHA-256 özeti Sester'e
`payload` olarak-yazılır; receipt, raporun **zaman-damgalı varlık-kanıtı**
olur ( non-repudiation + sıralama).

### 3.3 Sınırlar ( dürüst)

- **Ödeme-metresi-çakışması:** Sester ödeme-için-tasarlanmıştır; YIELDIX/
  FLEKSA **fon-yönetmez** ( README'lerde-açık). `amount=0.0` ile bağlanmak
  Sester'in ödeme-semantiğini **kanıt-defterine** dönüştürür — bu Sester'in
  birincil-amacı-DEĞİLDİR; kardeş-kararı-gerektirir.
- **RFC-010 mesh-mutabakat:** mesh-düzeyinde-mutabakat RFC-010'da-tanımlı;
  bu-değerlendirme **protokol-uyumluluğunu** kanıtlar, **mutabakat-kararını** değil.
- **Egemenlik-kısıtı:** FLEKSA'nın README'si "%100-egemendir; hiçbir-kardeşe-
  zorunlu-bağımlılık-yok" der. Bu entegrasyon **zorunlu-bağımlılık-DEĞİL**,
  opsiyonel-köprü-olmalıdır ( mevcut-yol-korunur).

## 4. Önerilen ilk-adım ( minimum-uygulabilir-kanıt)

YIELDIX'in `verify` CLI'sine opsiyonel bir kapı eklenebilir:
```
kredent_did_signable:  pilot-veri-seti raporu did:key ile imzalanabilir
                       ( aynı-Ed25519-anahtarı, yeni-altyapı-YOK)
```
Bu, **private-key-üretmeden** ve **para-harcamadan** ( kısıtlara-uygun)
entegrasyonun kriptografik-olarak-mümkün olduğunu kanıtlar.

## 5. Sonuç

| Soru | Cevap | Maliyet | Kısıt |
|---|---|---|---|
| Kredent DID ile imzalanabilir mi? | **EVET** — aynı-Ed25519+SHA-256 | düşük ( FLEKSA: en-düşük, W3C VC zaten) | kalıcı-seed-gerekli; demo-anahtarı-yeterli |
| Sester receipt zincirine bağlanabilir mi? | **EVET** — SHA-256 hash-zinciri-uyumlu | orta | opsiyonel-köprü-olmalı ( egemenlik) |

**Neden-şimdi-değil:** Kullanıcı kısıtlarında "Push öncesi BANA SOR" ve
"para-harcama-YASAK" var. Gerçek-entegrasyon kardeş-kararları- içerir;
bu-değerlendirme **uyumluluk-kanıtı** sağlar ve uygulanabilir-yol-haritası
çizer. **Uydurma-YOK:** tüm-format-iddiaları yukarıdaki-dosyalardan-okundu
( `kredent/attest.py`, `sester/ledger.py`, her-iki-projenin-README'si).
