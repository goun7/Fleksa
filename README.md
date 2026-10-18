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
        ↓ ( ölçüm-kanıtı → hash-zinciri)
   Tamga-anchor ( RFC 8785 JCS + sha256(prev‖jcs)) → mesh-düzeyinde-kanıt
```

---

## ⚡ In 30 seconds ( gerçek komutlar)

Gereksinim: Python ≥ 3.11 ve `scipy`, `numpy`, `pydantic`, `click`, `cryptography`.
Bunlar bu makinede **zaten yüklü** ( scipy 1.18.1, pydantic 2.13.5).

```bash
# 0) Testleri çalıştır ( 641 test, hepsi yeşil olmalı — rc=0, 2026-10-18 LEED-ölçümü)
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
| `tamga-anchor` | Ölçüm kanıtlarını bağımsız **Tamga** hash-zincirine sabitler | RFC 8785 / tamga-sim/1 |
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
| Mesh-kanıtı | Tamga hash-zinciri: `sha256(prev ‖ jcs(rec))`, RFC 8785 JCS |
| Bağımsız-denetim | `audit-verify` ile sıfırdan-yeniden-hesaplama |
| Fiyat-kanıtı | Byzantine 2-of-3 triangulation-canary |
| Kimlik-kanıtı | Ed25519-imzalı W3C Verifiable Credential |
| Flex-Policy-v2 | egemen-stüdyo; dış-politikaya-bağımlı-DEĞİL |

## Tamga anchor ( mesh-düzeyinde kanıt)

Fleksa'nın M&V kanıtı kendi içinde **tamamlanmıştır** ( `audit` + `audit-verify`
sıfırdan-yeniden-hesaplar), ama " kanıt-üretimi-fleksa-içindedir; mesh-düzeyinde-
mutabakat RFC-010'da" sınırına bir adım ekler: enerji ölçüm kanıtlarını **Tamga**'nın
bağımsız hash-zincirine sabitleyen [`src/fleksa/audit/tamga_anchor.py`](src/fleksa/audit/tamga_anchor.py)
modülü. Böylece her ölçüm-kanıtı yalnızca Fleksa'nın Merkle defterinde değil,
Tamga'nın da değiştirilemez zincirinde commitment-altındadır — üreticinin kendisi
( Fleksa) bile geriye-dönük olarak değiştiremez.

**Neden iki zincir?** Merkle-ağacı tek-bir-**anlık-görüntü** commitment'tır: tüm
ölçümleri tek-bir kök-hash'e indirger ve herhangi bir ölçümde geriye-dönük bir
değişiklik kökü değiştirir — ama ağaç, yaprakların **eklenme-sırası** hakkında
bir şey söylemez ( kök aynı kaldığı sürece yer-değiştirme fark-edilmez). Tamga
hash-zinciri bunu tamamlar: her kayıt bir öncekinin hash'ini `prev` ile bağlar,
bu yüzden sıralama da kriptografik olarak dondurulür. İkisini birleştirmek ölçüm
kanıtlarını hem anlık-görüntü hem de sıralı olarak bağlar.

**Tamga ledger modeli** ( TamgaProtocol `docs/ARCHITECTURE.md:42` ve
`tamga_runner._verify_chain` ile birebir):

```
seq  : 1-based artan tamsayı
prev : önceki kaydın h değeri; İLK kayıt için 64×'0' ( genesis)
h    = sha256( prev ‖ jcs( kayıt − {h}))     # RFC 8785 JCS — Python json DEĞİL
kayıt: {seq, prev, h} + yük alanları ( ölçüm kanıtı + Merkle kökü)
```

İki kritik ayrım ( yanlış-anlaşılırsa digest uyuşmaz): (1) `prev` hem **dize-prefix**
olarak hem jcs'in **içinde** bulunur; (2) canonicalization **RFC 8785 (JCS)**'dir —
üye-adları UTF-16 kod-birim sırasıyla ( §3.2.3), sayılar ECMAScript
`Number.prototype.toString` algoritmasıyla ( §3.2.2.2: `1.0` → `"1"`,
`2.93e-07` → `"2.93e-7"`). Bu yüzden Node/Go/Rust ile yazılmış bir Tamga verifier'ı
aynı baytları yeniden türetir; `json.dumps(sort_keys=True)` yalnızca Python'da
çalışır. JCS bu modüle **bağımlılıksız** ( stdlib-only) gömülmüştür — Fleksa
%100-egemen kalır, Tamga kurulumuna runtime bağımlılığı YOK.

**Üç katmanlı doğrulama** ( `OlcumTamgaSabitleyici.dogrula()`):

1. **Tamga zincir bütünlüğü** — 1-based seq + `prev`-bağlantısı + hash-tekrar-hesabı.
2. **Çapraz-çapa ( cross-anchor)** — her kaydın taşıdığı `merkle_kok`, kayıtlı
   ölçümlerden Fleksa'nın KENDİ `CryptographicSavingsLedger` modeliyle
   yeniden-türetilmelidir. Fleksa defterinde geriye-dönük bir değişiklik yapılırsa
   Tamga zinciri artık o kanıtı doğrulamaz ( ve tersi).
3. **Tamlık ( completeness)** — her ölçüm sabitlenmiş olmalı ( atlanmış kanıt yok).

**Merkle modeli yeniden-icat-EDİLMEDİ** — `sabitle_ledger()` mevcut bir Fleksa
defterini olduğu gibi alır, yaprak ve kökleri birebir koruyarak zincire bağlar;
iki digest-uzayı **değer** düzeyinde köprülenir ( Merkle kökü Tamga kaydında taşınır).

```bash
# 1) ölçüm kanıtlarını üret ve bağımsız Tamga hash-zincirine sabitle
PYTHONPATH=src python3 -m fleksa tamga-anchor --ledger /tmp/fleksa-tamga.jsonl
#   → "Anchor verified: YES": event-hour ölçümleri + savings iddiası TEK zincirde.

# 2) çıktı, Tamga'nın KENDİ bağımsız verifier'ında doğrulanır ( dış repo, sıfır-güven):
python3 -c "import sys; sys.path.insert(0,'/home/gokun/projects/05_acik_kaynak/TamgaProtocol'); \
import tamga_runner as t, pathlib; print(t._ledger_head(pathlib.Path('/tmp/fleksa-tamga.jsonl')))"
#   → ( <head-hash>, 'ok')  ← Fleksa'nın hiçbir koduna güvenmeden
```

Test: [`tests/test_tamga_anchor.py`](tests/test_tamga_anchor.py) — 18 test; JCS
bayt-paritesi ( `tamga_canon.jcs` ile), genesis/seq/hash kuralı, Merkle çapraz-çapa
birebilirliği, kurcalama-tespiti ( her iki zincirde), JSONL fail-closed round-trip
ve **Tamga'nın kendi `tamga_runner._verify_chain` verifier'ında GREEN**.

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

---

## Akademik Kaynaklar (2024-2026)

Bu çalışma aşağıdaki araştırmaya dayanır. **Her referans canlı olarak doğrulanmıştır:**
`curl -sIL https://arxiv.org/abs/...` → **HTTP 200** ve başlık/gönderim-tarihi sayfa
içeriğinden birebir teyit edilmiştir (kanıt tablosu en altta).

- **[1] Talep-yanıtı GPU esnekliği** —
  *PowerSlider: Exploiting Phase Asymmetry for LLM Serving under Demand Response* —
  Li et al., arXiv 2026.
  LLM servis kümeleri anlık-güç sınırları altında çalışıyor; şebeke operatörleri yeni
  kapasiteyi **talep-yanıtına** bağlı kılıyor. Compute-bound prefill frekansla lineer
  kayıp yaşarken **memory-bound decode 0.57× nominal güne kadar dayanıklı** — yani
  esneklik iş-yükü fazına göre değişir. Fleksa'nın GPU güç-kapasitesi kararı için
  en doğrudan dayanak; sabit `min_gpu_cap` neden yanlıştır.
  [arXiv:2608.21719](https://arxiv.org/abs/2608.21719)

- **[2] Doğrulanabilir yük esnekliği** —
  *Beyond Scalar Flexibility: From Eligible AI Workloads to Dependable Load Relief* —
  Li, arXiv 2026.
  **155.410 GPU'nun 185 günlük** gerçek üretim izinden: anlık uygun kesinti median
  facility gücünde **%6.35**; ortalama-kalibreli skeler bunu **%17/%25/%47 aşınlatıyor**.
  Esnekliğin süre, portföy ve güvenilirlikle **sözleşmeye yazılması** gerektiğini
  gösterir — Fleksa'nın "esneklik-kanıtı üretir" iddiasının ölçülebilirlik çerçevesi.
  [arXiv:2609.05406](https://arxiv.org/abs/2609.05406)

- **[3] Esnekliği ölçme biçimi** —
  *Measuring Flexibility through Reduction Potential* — Alexeenko et al., arXiv 2025.
  "Reduction potential matrix": esnekliğin **ne zaman** ve **ne kadar** olduğu
  ayrılmazdır; tek bir skaler ("maksimum %35 azaltma") ikisini de yanlış temsil eder.
  Fleksa'nın saat-başı (zaman) + cap-fraksiyonu (büyüklük) formatındaki dinamik GPU
  profili, makalenin önerdiği formata tam olarak uyar.
  [arXiv:2505.09817](https://arxiv.org/abs/2505.09817)

- **[4] Enerji-optimal GPU işletme noktası** —
  *The Joule Point: an Energy-Optimal Operating Point for AI Inference* —
  Apartsin & Aperstein, arXiv 2026.
  Her iş için bir **enerji-optimal işletme noktası** ("Joule Point") vardır ve bu
  nokta **iş-yükü özelliklerine** bağlıdır, donanım özelliklerine değil — "yüksek
  utilization = verimli" **yanlıştır**. Fleksa'nın dinamik GPU esneklik aralığının
  ( `[0.35, 0.95]`) seçiminin temeli.
  [arXiv:2609.27926](https://arxiv.org/abs/2609.27926)

- **[5] Faz-ayrık güç kontrolü** —
  *Phase-Decoupled, Model-Calibrated Power Control for Disaggregated LLM Serving* —
  Kim et al., arXiv 2026.
  Optimal güç ayarı GPU sınıfının değil, **dağıtılan model/quantization/engine
  bileşiminin** bir özelliğidir. 8× B200'de **+20.4% tokens/J, +3.5% mean e2e**
  (Max-Q: +8.6% at +5.2%) — her iki eksende Pareto iyileşmesi. Sabit-oran GPU kapa
  varsayımının ikinci çürütülmesi.
  [arXiv:2609.11133](https://arxiv.org/abs/2609.11133)

- **[6] Soğutma–hesaplama ortak kontrolü** —
  *ETCInfer: An Energy-efficient Thermal-aware Cooling-joint Scheduler for LLM
  Inference in AI Datacenters* — Lu et al., arXiv 2026.
  CRAC setpoint'i + per-GPU frekans + micro-batch boyutunu **ortak** optimize eder:
  iş-başına enerjide **%33.1'e varan düşüş**, termal-throttle maruziyetinde
  **%92.9 düşüş**, SLO ihlali **%0.7'nin altında**. GPU throttle'ının bir özellik
  değil, bir **maliyet** olduğunu kanıtlar.
  [arXiv:2609.15230](https://arxiv.org/abs/2609.15230)

- **[7] Şebeke-tümleşik compute iş-yükü** —
  *Job Class Thermal Intent Aware Liquid Cooling Allocation for AI Data Centers* —
  Sunkara, arXiv 2026.
  İş-sınıfı termal bilgisinin soğutma denetleyicisine doğrudan beslenmesi **%56.4 daha
  az termal ihlal** veriyor; termal-farkındalık **şebeke tarafında ani talebi
  azaltıyor** ve yük tahminini iyileştiriyor. Fleksa'nın `LoadClass` (Class 0–3)
  modelinin doğrulaması.
  [arXiv:2609.30785](https://arxiv.org/abs/2609.30785)

- **[8] Yenilenebilir-tümleşik dağıtık AI** —
  *Green Distributed AI Training: Orchestrating Compute Across Renewable-Powered
  Micro Datacenters* — Tomei et al., arXiv 2025.
  AI iş-yüklerinin büyümesi, giderek kesintili yenilenebilir üretimle çakışıyor;
  iş-yüklerinin mikro veri merkezleri arasında dağıtılması bir çözüm. Fleksa'nın
  tesisler-arası esneklik taşımacılığı ( grid-follower compute) ve mesh entegrasyonu
  için stratejik motivasyon.
  [arXiv:2511.16182](https://arxiv.org/abs/2511.16182)

> **Tam liste:** 24 doğrulanmış 2024–2026 makalesi ( MPC/MILP dispatch, batarya
> degradasyonu, M&V belirsizliği katmanları dahil) için
> [`docs/arastirma/akademik-arastirma-2026.md`](docs/arastirma/akademik-arastirma-2026.md).

### Doğrulama kanıtı ( canlı teyit)

| # | Kaynak | Yayın yılı | `curl -sIL arxiv.org/abs/…` |
|---|---|---|---|
| 1 | arXiv:2608.21719 — PowerSlider | 2026 | **200** |
| 2 | arXiv:2609.05406 — Beyond Scalar Flexibility | 2026 | **200** |
| 3 | arXiv:2505.09817 — Reduction Potential | 2025 | **200** |
| 4 | arXiv:2609.27926 — The Joule Point | 2026 | **200** |
| 5 | arXiv:2609.11133 — Phase-Decoupled Power Control | 2026 | **200** |
| 6 | arXiv:2609.15230 — ETCInfer | 2026 | **200** |
| 7 | arXiv:2609.30785 — JCTI Liquid Cooling | 2026 | **200** |
| 8 | arXiv:2511.16182 — Green Distributed AI Training | 2025 | **200** |

Tüm başlıklar ve gönderim-tarihleri canlı sayfa içeriğinden birebir okunmuştur;
**hiçbir referans uydurulmamıştır**. Eklemiş bir DOI teyidi:
`https://doi.org/10.23919/ACC60939.2024.10644173` → **HTTP 202** (tam listedeki
[18] ACC 2024 makalesi).
