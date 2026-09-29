# Fleksa — Otonom Enerji Esnekliği & Dağıtık Batarya Arbitraj Motoru

> **Ana-belge:** [`FLEKSA.md`](FLEKSA.md) — kapsamlı-master-spec.
> **Akademik araştırma:** [`docs/arastirma/akademik-arastirma-2026.md`](docs/arastirma/akademik-arastirma-2026.md)
> — 10 doğrulanmış 2025–2026 makalesi.
> **Dürüst değerlendirme:** [`docs/arastirma/degerlendirme-A-B-C.md`](docs/arastirma/degerlendirme-A-B-C.md)
> — karar **(A) aktif geliştir**, gerekçesiyle.

## Rolü ( TAMGA-MESH-içinde)

Fleksa **fon yönetmez** — **enerji-esnekliği-kanıtı** üretir: bir talep-
yanıtı-kararının gerçekten-yürütüldüğünü ve ölçülebildiğini kaydeder.

```
grid-sinyali → MPC-çekirdeği ( HiGHS) → dispatch-kararı
        ↓ ( her-adımda-ölçüm-kanıtı)
   IPMVP-M&V-stüdyosu → Merkle-kanıt → bağımsız-denetim ( audit-verify)
```

---

## ⚡ In 30 seconds ( gerçek komutlar)

Gereksinim: Python ≥ 3.11 ve `scipy`, `numpy`, `pydantic`, `click`, `cryptography`.
Bunlar bu makinede **zaten yüklü** ( scipy 1.18.1, pydantic 2.13.5).

```bash
# 0) Testleri çalıştır ( 171 test, hepsi yeşil olmalı)
python3 -m pytest tests/ -q

# 1) Kurulum gerektirmeden, kaynak üzerinden çalıştır
PYTHONPATH=src python3 -m fleksa version
PYTHONPATH=src python3 -m fleksa benchmark          # EPIAŞ 2026.1 gerçek PTF/SMF verisi
PYTHONPATH=src python3 -m fleksa solve              # 24-saatlik MPC → OPTIMAL dispatch

# 2) Kanıt üret ve BAĞIMSIZ olarak doğrula
PYTHONPATH=src python3 -m fleksa audit --report /tmp/rapor.json
PYTHONPATH=src python3 -m fleksa audit-verify /tmp/rapor.json
#   → "VERIFICATION PASSED": iddialar, kayıtlı girdilerin deterministik sonucudur.
#   → Değiştirilmiş bir rapor "VERIFICATION FAILED" ile exit 1 verir.

# 3) Web cockpit + REST API ( 127.0.0.1:8076)
PYTHONPATH=src python3 -m fleksa ui
#   tarayıcı: http://127.0.0.1:8076
#   curl -X POST http://127.0.0.1:8076/api/solve -H 'Content-Type: application/json' -d '{}'
```

Kurulumlu kullanım ( opsiyonel):

```bash
pip install -e ".[dev]"
fleksa solve
fleksa ui
```

### MCP çözümü ne döner? ( gerçek çıktı)
```
✓ Optimization Status: OPTIMAL
✓ Projected Cost: ₺18,407.87
✓ Expected Savings vs Baseline: ₺6,163.73
✓ Hour 0 Dispatch Setpoints:
   • BESS Discharge:  117.3 kW
   • Grid Draw:       262.7 kW
   • GPU Power Cap:   65.0%
   • Resulting SoC:   75.0 kWh
```

---

## Komut başvurusu

| Komut | Ne yapar | Standart |
|---|---|---|
| `solve` | 24-saatlik Receding-Horizon MILP ( HiGHS) dispatch | — |
| `audit` | IPMVP Option B baseline + ASHRAE 14 + Merkle kanıt | EVO 10001-1:2022 |
| `audit-verify` | Bir raporu **bağımsız** olarak sıfırdan yeniden hesaplayıp doğrular | bu-sürüme-ait |
| `benchmark` | EPIAŞ 2026.1 PTF/SMF verisini özetler | — |
| `arbitrage-gate` | Arbitraj kârlılık kapısı ( break-even + degradasyon) | — |
| `canary` | Byzantine 2-of-3 fiyat-kaynak konsensüsü | — |
| `credential` | Ed25519-imzalı W3C Verifiable Credential | W3C VC v2 |
| `verify-policy` | Flex-Policy v2 YAML AST doğrulama | — |
| `openadr` | OpenADR 3.0/2.0b VEN olay simülasyonu | OpenADR |
| `modbus` | SunSpec 700-series register kodlama | Modbus TCP |
| `monte-carlo` | Stokastik risk analizi | — |
| `ui` | Web cockpit + REST API | — |

---

## Kardeş-sınırı ( egemenlik)

Fleksa %100-egemendir; **hiçbir-kardeşe-zorunlu-bağımlılık-yok**:
`63-Sester` ( ödeme), `68-Kredent` ( kimlik), `69-Swarmax` ( filo),
`73-Veridrome` ( sertifika), `77-Dümen` ( iç-denetim).

## Güvenlik-modeli

| Özellik | Uygulama |
|---|---|
| M&V-kanıtı | IPMVP Option B baseline + Merkle-ağacı-kökü |
| Bağımsız-denetim | `audit-verify` ile sıfırdan-yeniden-hesaplama |
| Fiyat-kanıtı | Byzantine 2-of-3 triangulation-canary |
| Kimlik-kanıtı | Ed25519-imzalı W3C Verifiable Credential |
| Flex-Policy-v2 | egemen-stüdyo; dış-politikaya-bağımlı-DEĞİL |

## Sınırlar ( dürüst)

- ** Enerji-erişimi-YOK** — bu-bir-karar-motorudur; gerçek-grid-erişimi
  OpenADR/Modbus-entegrasyonları-üzerinden-üretim-dağıtımı-öncesi-istenir.
- ** Degradasyon-maliyeti SABİTTİR** ( 0.35 ₺/kWh) — DoD/sıcaklık-bağımlı bir
  rainflow-modeli-DEĞİL. Akademik-doğrulama için bkz.
  [`docs/arastirma/akademik-arastirma-2026.md`](docs/arastirma/akademik-arastirma-2026.md) §[2.7]/[18].
- ** GPU-esnekliği DİNAMİK ARALIKTIR** — eski sabit `min_gpu_cap=0.65` eşiği
  **2026 akademik çalışmalarıyla geçersiz kılındı**:
  arXiv:2609.27926 *"Joule Point"* ( inference-başına-enerji U-şekillidir ve
  optimum **iş yüküne göre değişir** — büyük GPU'larda tepe-gücün %43-46'sı;
  "yüksek utilization = verimli" **yanlıştır**), arXiv:2608.07971 *"ElastiCo"*
  ( statik ayrımlar underutilization yaratır) ve arXiv:2609.16682
  *"DeepShare"* ( assurance sabit kota değil, sürekli talep-temelli sinyal —
  %70.58 utilization, −%46 gecikme).
  Alt-sınır artık **dinamik esneklik aralığından** iş yüküne göre seçilir:
  `[min_gpu_cap=0.35, max_gpu_cap=0.95]` ( Joule Point'in %43-46 optimum
  bandını kapsar) — `FleksaMPCSolver(dynamic_gpu_cap=...)` veya
  `fleksa solve --dynamic-gpu-cap`. **Geriye dönük uyumludur**: parametre
  verilmezse eski sabit `0.65` tabanı döner ( breaking-change DEĞİL);
  aralık dışı değer ( örn. `0.2`) reddedilir. Önceki dalga hâlâ geçerlidir:
  talep-temelli saatlik profil ( arXiv:2609.05406, `--gpu-flex=dynamic`) ve
  eski sabit yol ( `--gpu-flex=fixed`) yeniden-oynanabilir. Diğer
  bilinen-limitler için bkz.
  [`docs/arastirma/akademik-arastirma-2026.md`](docs/arastirma/akademik-arastirma-2026.md) §4.
- ** Kanıt-üretimi-fleksa-içindedir**; mesh-düzeyinde-mutabakat RFC-010'da.

## Yasal / kısıtlar

- ** PRIVATE_KEY-ÜRETİM-YASAK**, ** mainnet-YASAK**, ** para-harcama-YASAK**.
- `credential` komutu yalnızca yerel-demo-anahtarı ( `01`*32) kullanır; üretim için
  `FLEKSA_FACILITY_KEY` ortam-değişkeni-VERİLMEZ.
