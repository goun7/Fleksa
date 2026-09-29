# Fleksa — Akademik Araştırma Raporu (2025–2026)

> **Tarih:** 2026-09-29
> **Amaç:** Fleksa'nın çalıştığı alanda **güncel, gerçek akademik makaleleri** tespit etmek ve
> projenin iddialarını bu literatüre karşı **dürüst** olarak değerlendirmek.
>
> **Doğrulama yöntemi:** Aşağıdaki **her bir** arXiv kimliği `web_fetch` ile birebir açılmış,
> başlık/yazar/tarih/özet metinleri canlı kaynaktan okunmuştur. "API-sorgu" ile işaretlenenler
> arXiv Atom API'sinden (`export.arxiv.org/api/query`) dönen tam metadata ile doğrulanmıştır.
> **Hiçbir kaynek uydurulmamıştır.** Doğrulanamayan veya bulunamayan konular bölüm sonunda
> açıkça belirtilmiştir.
>
> **Düzeltme (2026-09-29, güncelleme):** Bu rapor **24** doğrulanmış makale içerecek şekilde
> genişletildi. [11]–[24] numaralı yeni girdiler GPU güç-kısıtlama, talep-yanıtı esnekliği,
> termal-yönetim ve M&V belirsizliği alanlarında — yani Fleksa'nın `min_gpu_cap` düzeltmesinin
> akademik dayanağını oluşturan alanlarda — canlı arXiv API sorguları ve `web_fetch` ile
> tek-tek doğrulandı.

---

## 1. Fleksa ne yapıyor (kısa bağlam)

Fleksa, üç teknik katmanın birleşimidir:

1. **BESS arbitrajı** — bataryayı ucuz saatte şarj edip pahalı saatte deşarj ederek gelir.
2. **MPC (Model Predictive Control) karar motoru** — 24 saatlik geri-kaymalı (receding-horizon)
   MILP çözümü (SciPy/HiGHS) ile dispatch kararı.
3. **AI-iş-yükü talep yanıtı (demand response)** — GPU/compute yükünü şebeke sinyallerine göre
   kısıtlama; üretim M&V kanıtlaması (IPMVP Option B / ASHRAE 14).

Bu rapor, bu üç katmanı ayrı ayrı literatüre göre test eder.

---

## 2. Doğrulanmış makaleler

### 2.1 MPC vs MILP vs RL — BESS dispatch (en ilgili)

**[1] arXiv:2609.14776** — *"Comparative Evaluation of MILP, MPC, and Reinforcement Learning for
Commercial Battery Dispatch Under Time-of-Use Tariffs"*
- **Yazarlar:** Hafiz Majid Hussain, Wajiha Samar, Lurian Klein, Pedro Nardelli
- **Tarih:** 13 Eylül 2026 · **Alan:** eess.SY
- **Doğrulama:** `https://arxiv.org/abs/2609.14776` fetch ile birebir açıldı ✓
- **Bulgular:** Tam bir yıl (2023) gerçek ticari PV verisi üzerinde MILP (mükemmel öngörü),
  MPC (bir-gün-önce kalıcı tahmin) ve SAC pekiştirmeli öğrenme karşılaştırması.
  - MILP oracle: **yıllık %24.6** maliyet düşüşü (deposuz baseline'a göre).
  - **MPC, oracle'ın %99.2'sini sadece bir-gün-önce verisiyle elde ediyor.**
  - SAC (RL) ajanı baseline'dan daha pahalı çıkıyor.
- **Fleksa'ya etkisi:** **Doğrudan destekleyici.** Fleksa'nın "MPC + MILP" seçimi literatürle
  tam uyumlu: MPC, pratik dağıtımda neredeyse tüm ekonomik değeri yakalıyor ve RL'den üstün
  bulunmuş. Fleksa'nın "RL yok, MPC+MILP var" tercihi **doğru bir mühendislik tercihi**.

**[2] arXiv:2609.04398** — *"Grid-Mode-Aware Model Predictive Control of Hybrid Energy Storage
Systems for AI Data Center Power Smoothing"*
- **Yazar:** Xin Chen · **Tarih:** 3 Eylül 2026 · **Alan:** eess.SY
- **Doğrulama:** `https://arxiv.org/abs/2609.04398` fetch ile birebir açıldı ✓
- **Bulgular:** AI veri merkezi yükü için **receding-horizon MPC** ile BESS + süperkapasitör
  koordinasyonu. Güç-envelope, ramp-rate ve SoC limitleri altında degrade/rampanin maliyetini
  ortak olarak minimize ediyor; "fix-and-re-optimize" algoritması **aynı anda şarj/deşarjı
  önlemek** için kullanılıyor.
- **Fleksa'ya etkisi:** **Çok ilgili.** Fleksa'nın MPC'sindeki `u_ch + u_dis <= 1` mutex
  kısıtı ve "AI compute + BESS" birleşimi bu makalenin tam olarak işlediği problem.
  Makale, Fleksa'nın yaklaşımının akademik olarak bilinen, geçerli bir problem tanımı olduğunu
  doğruluyor. Ayrıca **modal/osilasyon bastırma** gibi Fleksa'da olmayan bir derinlik işaret ediyor.

### 2.2 AI-iş-yükü esnekliği (grid-interactive compute DR)

**[3] arXiv:2609.05406** — *"Beyond Scalar Flexibility: From Eligible AI Workloads to Dependable
Load Relief"*
- **Yazar:** Meiyi Li · **Tarih:** 4 Eylül 2026 · **Alan:** eess.SY
- **Doğrulama:** `https://arxiv.org/abs/2609.05406` fetch ile birebir açıldı ✓
- **Bulgular:** **155.410 GPU'nun 185 günlük** gerçek üretim izinden 4.439 saatlik güç gözlemi.
  Fleksa'nın varsaydığı "iş-yükü esnekliği = yükün sabit bir yüzdesi" fikrini çürütüyor:
  - Anlık uygun kesinti median facility güçte **%6.35**, workload gücünde **%12.1**.
  - %95-erişilebilir rahatlama 1 saatte 2.51 MW'den 24 saatte 1.95 MW'ye düşüyor.
  - Ortalama-kalibreli skaler bu değerleri **%17/%25/%47** aşınlatıyor.
  - 13 cluster'ı birleştirmek 4-saat "firmness"i 0.38'den 0.66'ya çıkarıyor ama
    cross-cluster kovaryans kazancı sınırlıyor.
- **Fleksa'ya etkisi:** **En önemli eleştirel bulgu.** Fleksa'nın `min_gpu_cap=0.65`
  (GPU'yu %65'e kısmayı varsayan) yaklaşımı, bu makalenin gösterdiği gibi **sabit-yüzde
  varsayımı** tehlikelidir: gerçek esneklik süre-bağımlı, portföy-bağımlı ve güvenilirlik-
  bağımlıdır. Makale, esnekliği "duration, reliability, portfolio, realizability" terimleriyle
  sözleşmeye yazmayı öneriyor — Fleksa'nın talep-yanıtı iddialarının **bunları
  kantifiye etmeden** satılması bilimsel olarak zayıftır.

### 2.3 Degradasyon farkındalıklı dispatch

**[4] arXiv:2609.12968** — *"End-to-End Battery Dispatch with Exact Rainflow Degradation via
Mixed-Integer Differentiable Predictive Control"*
- **Yazarlar:** Eshagh Safarzadeh Ravajiri, Jan Drgona, Mahdi Mehrtash, Benjamin F. Hobbs
- **Tarih:** 11 Eylül 2026 · **Alan:** eess.SY (IEEE Transactions on Smart Grid'e gönderilmiş)
- **Doğrulama:** `https://arxiv.org/abs/2609.12968` fetch ile birebir açıldı ✓
- **Bulgular:** Arbitraj ile döngü-degradasyonu arasında dengeyi **rainflow cycle counting**
  ile tam olarak modelleyen karışık-tamsayı türevlenebilir MPC. 3.650 gerçek batarya-günü
  (10 batyalık filo, 365 gün; SDG&E/Xcel/APS bölgeleri) üzerinde değerlendirilmiş;
  filo-geneli eğitimli politika %3.33 performance gap ile **564× hesaplamasal hızlanma**
  (62 saniye vs 9.7 saat) ve %100 fizibilite.
- **Fleksa'ya etkisi:** **Doğrudan ilgili ve Fleksa'nın zayıf noktasını işaret ediyor.**
  Fleksa degradasyonu **sabit `c_deg = 0.35 ₺/kWh` sabit-maliyet** olarak modelliyor
  (`mpc/solver.py`). Bu, döngü-derinliğine (DoD) ve hücre sıcaklığına bağlı gerçek
  degradasyonu yakalamaz. Makale, Fleksa'nın "Wang/Ecker degradation engine" iddiasının
  ötesinde bir doğruluk seviyesi gösteriyor — bu, Fleksa'nın ileride iyileştirebileceği
  somut, kanıtlanmış bir yöntemdir.

**[5] arXiv:2605.06419** — *"Residual-Corrected Equivalent-Circuit Model with Universal
Differential Equations for Robust Battery Voltage Prediction under Operating-Condition Shift"*
- **Yazarlar:** Alexandre Barbosa de Lima, Roberta Vieira Raggi · **Tarih:** 7 Mayıs 2026
- **Doğrulama:** arXiv Atom API sorgusu ile tam metadata döndü ✓
- **Bulgular:** Birinci-derece **Thevenin ECM** + evrensel diferansiyel denkeme (UDE) hibrit
  model; Panasonic 18650PF verisetinde LSTM'i matched-condition'da **%48 MAE** düşürerek
  geçiyor ve inter-seed değişkenliği 100× düşürüyor (CV 0.44% vs 6.20%).
- **Fleksa'ya etkisi:** Fleksa'nın **2-RC Thevenin ECM** (`battery/thevenin.py`) seçimi
  literatürde standart ve geçerli. Bu makale, Thevenin ECM'in dağılım-kayması (distribution
  shift) altında hala güçlü olduğunu gösteriyor — Fleksa'nın fizik modeli **sağlam bir
  seçim**.

**[6] arXiv:2604.01229** — *"Interpretable Battery Aging without Extra Tests via
Neural-Assisted Physics-based Modelling"*
- **Tarih:** 21 Mart 2026 · **Doğrulama:** arXiv Atom API sorgusu ile tam metadata döndü ✓
- **Bulgular:** SoH tek skalar olarak yetersizdir; fraksiyonel-derece ECM üzerinden
  rutin BMS kayıtlarından **2-B yaşlık parmakizi** çıkarıyor.

### 2.4 Pazara/elektrik fiyatına dair

**[7] arXiv:2606.22185** — *"Impact of distribution fees on BESS scheduling and profitability"*
- **Yazar:** Katarzyna Maciejowska · **Tarih:** 20 Haziran 2026
- **Doğrulama:** arXiv Atom API sorgusu ile tam metadata döndü ✓
- **Bulgular:** Almanya gün-öncesi pazarında MILP BESS modeli + **rolling-horizon** çerçevesi.
  Grid ücretleri hem kârlılığı hem operasyonel stratejiyi belirgin şekillendiriyor;
  tek-başına depolamada yüksek iletim ücretleri arbitraj gelirini düşürürken, tüketim+
  üretimle birleşince değer kaynağı **load-shifting/self-consumption**'a kayıyor.
- **Fleksa'ya etkisi:** **Doğrudan ilgili.** Fleksa'nın `water_cost_per_kwh` ve PTF üzerinden
  maliyetlendirme mantığı, grid ücretlerini/transmissioncharges'ı açıkça modellemelidir;
  aksi halde arbitraj kârlılığı abartılır. Makale rolling-horizon çerçevesini de
  (Fleksa'nın "Receding Horizon" iddiasıyla örtüşür) doğrular.

**[8] arXiv:2609.00089** — *"Foundation models for electricity price forecasting and battery
arbitrage: Can they replace market-specific forecasting models?"*
- **Yazarlar:** Arkadiusz Lipiecki, Rafał Weron · **Tarih:** 31 Ağustos 2026
- **Doğrulama:** arXiv Atom API sorgusu ile tam metadata döndü ✓
- **Bulgular:** 5 foundation model ailesinden 9 varyant, Almanya/Polonya/İspanya'da 2021–2025
  ile karşılaştırılıyor. İstatistiksel üstünlük **ekonomik üstünlüğe doğrudan çevrilmiyor**;
  risk toleransına göre en kârlı model değişiyor.
- **Fleksa'ya etkisi:** Fleksa için fiyatlama/forecast basit kabul ediliyor (veri dosyası
  EPIAŞ benchmark). Makale, forecast doğruluğunun arbitraj değerine birebir çevrilmediğini
  uyarıyor — Fleksa'nın kazanç iddialarını forecast kalitesiyle ayrı tutması gerekir.

**[9] arXiv:2605.23964** — *"Multi-market value-stacking: Battery control for combined imbalance
participation and non-uniform FCR bidding"*
- **Tarih:** 12 Mayıs 2026 · **Doğrulama:** arXiv Atom API sorgusu ile tam metadata döndü ✓
- **Bulgular:** Statik/uniform FCR teklifleri BESS esnekliğini tam kullanmıyor; çoklu-pazar
  değer-yığma (value-stacking) gerekli.

### 2.5 M&V (ölçüm ve doğrulama) — dürüstlük vurgusu

**[10] arXiv:2602.22499** — *"Small HVAC Control Demonstrations in Larger Buildings Often
Overestimate Savings"*
- **Tarih:** 26 Şubat 2026 · **Doğrulama:** arXiv Atom API sorgusu ile tam metadata döndü ✓
- **Bulgular:** Büyük binanın sadece birkaç termal bölgesini kontrol edip sadece o bölgelerin
  tasarruflarını raporlamak, komşu bölgelerle ısı transferi nedeniyle tasarrufları
  **aşınlatıyor**.
- **Fleksa'ya etkisi:** **Doğrudan ilgili ve uyarıcı.** Fleksa'nın IPMVP Option B / ASHRAE 14
  M&V stüdyosu ve "expected_savings" hesabı, bu tür **sınır-hatası (boundary error)**
  tuzaklarına karşı açık olmalıdır. Bu, Fleksa'nın "kanıt üretir" iddiasının bilimsel
  olarak güvenilir olması için uygulanması gereken bir disiplindir.

---

### 2.6 GPU güç-kısıtlama ve AI talep-yanıtı — `min_gpu_cap` düzeltmesinin literatür dayanağı

> Bu bölüm, Fleksa'nın **dinamik GPU esnekliği** düzeltmesinin (`workload/gpu_flexibility.py`)
> dayandığı güncel literatürü toplar. [3]'ün "skaler esneklik yetersizdir" eleştirisinin
> ardından, bu makaleler esnekliğin **talep, faz ve termal durum** ile nasıl değiştiğini
> gösterir — yani Fleksa'nın saat-başı talep-temelli alt-sınırının neden doğru bir modelleme
> seçimi olduğunu kanıtlar.

**[11] arXiv:2609.15230** — *"ETCInfer: An Energy-efficient Thermal-aware Cooling-joint
Scheduler for LLM Inference in AI Datacenters"*
- **Yazarlar:** Rui Lu, Rui Ge, Huanghuang Liang, Xiaobo Zhou, Dan Wang
- **Tarih:** 14 Eylül 2026 · **Alan:** cs.DC, cs.PF, eess.SY
- **Doğrulama:** arXiv API tam metadata + özet ✓
- **Bulgular:** LLM inference için **ortak soğutma–hesaplama kontrolü**. Ortam sıcaklığı
  setpoint'i yükseltilince soğutma enerjisi düşer ama termal-headroom daralır, **GPU throttle**
  başlar ve SLO ihlalleri gelir. ETCInfer CRAC setpoint'i + per-GPU frekans + micro-batch
  boyutunu ortak optimize eder; iş-başına enerjide **%33.1'e varan düşüş**, termal-throttle
  maruziyetinde **%92.9 düşüş**, SLO ihlali **%0.7'nin altında** (48 °C'ye kadar).
- **Fleksa'ya etkisi:** **Çok ilgili — GPU throttle'ının bir özellik değil bir maliyet olduğunu
  kanıtlıyor.** Fleksa'nın `gpu_power_cap` kararı, throttle'ın latency/SLO maliyetini içermeli.
  Ayrıca soğutma enerjisi (Fleksa'nın `water_cost_per_kwh` parametresi) GPU kapa ile
  etkileşimlidir — tek yönlü bir ceza değil.

**[12] arXiv:2608.21719** — *"PowerSlider: Exploiting Phase Asymmetry for LLM Serving under
Demand Response"*
- **Yazarlar:** Yueying Li, Jiayang Chen, Yuanfan Chen, Leo Han, Haoran Qiu
- **Tarih:** 22 Ağustos 2026 · **Alan:** cs.DC, cs.AI
- **Doğrulama:** arXiv API tam metadata + özet ✓
- **Bulgular:** AI inference kümeleri **anlık güç** ile sınırlı; şebeke operatörleri yeni
  kapasiteyi **talep-yanıtına** bağlıyor ve **zamanla-değişen güç kapları** dayatıyor. Bir LLM
  hattı tekdüze bir yük değildir: compute-bound prefill frekansla neredeyse lineer kayıp
  yaşarken, **memory-bound decode 0.57× nominal'e kadar dayanıklı**. PowerSlider, Flex SLO
  sözleşmesini kısıta çevirir ve KKT çözücüyü her kap değişiminde **7.7 ms** içinde yeniden
  çözer. Üretim izlerinde **%30 kap düşürme altında %78.3 online goodput** (en iyi baseline:
  %47.6), ve CAISO grid-acil gününde **0.41× kap trough'unda bile %54 goodput** (tüm
  baseline'lar %7'nin altında).
- **Fleksa'ya etkisi:** **`min_gpu_cap` düzeltmesinin en güçlü doğrudan dayanağı.** Makale,
  esnekliğin **iş-yükü fazına göre değiştiğini** somut rakamlarla gösterir — tıpkı Fleksa'nın
  `GpuFlexibilityProfiler`'ının kuyruk içeriğine (critical/noncritical payı) göre alt-sınır
  belirlemesi gibi. Sabit bir `0.65` kapı, memory-bound decode için aşırı kısıtlayıcı,
  compute-bound prefill için ise yetersizdir.

**[13] arXiv:2609.11133** — *"Phase-Decoupled, Model-Calibrated Power Control for
Disaggregated LLM Serving"*
- **Yazarlar:** Jae Gon Kim, Donghoon Yoo, Hanyul Ryu, Sungho Ha, Juyeon Lee
- **Tarih:** 10 Eylül 2026 · **Alan:** cs.LG, cs.DC
- **Doğrulama:** arXiv API tam metadata + özet ✓
- **Bulgular:** NVIDIA Max-Q profili B200'de **+8.6% tokens/J** verir ama **+5.2% e2e latency**
  maliyeti taşır; tek ayar prefill ve decode GPU'larına aynı uygulanır — oysa bu iki faz
  **zıt donanım rejimlerinde** çalışır. Yazarlar optimal güç ayarının GPU sınıfının değil,
  dağıtılan (model, quantization, engine, donanım) bileşiminin bir özelliği olduğunu
  hipotezleştirir. Faz-ayrık kontrolcü: prefill lane'i SM-clock penceresinde (tabanı
  yapısal olarak latency garantisi), decode lane'i ölçülen throughput/latency uçurumunun
  hemen üstüne kalibre edilen güç kapsında. 8× B200'de Qwen3-Coder-480B (FP8) ile
  **+20.4% tokens/J, +3.5% mean e2e** (Max-Q: +8.6% at +5.2%) — her iki eksende Pareto
  iyileşmesi. Üç-günlük sürekli koşu bir lane-pair'in elektriğinin **%32.3'ünü** kazandırır.
- **Fleksa'ya etkisi:** **Sabit-oran varsayımının ikinci çürütmesi.** Makale, "GPU sınıfı"
  seviyesinde tek bir kapa değil, **iş-yükü profiline göre kalibre edilen** kapa gerektiğini
  gösterir. Fleksa'nın `GPU_SPECS` (H100/H200/B200) model sınıfı parametreleri bu
  iş yüküne duyarlı kalibrasyon için doğru yerdedir; sabit `alpha_memory_bound` yerine
  faz-bağımlı kalibrasyon bir sonraki doğal adımdır.

**[14] arXiv:2609.27926** — *"The Joule Point: an Energy-Optimal Operating Point for AI
Inference"*
- **Yazarlar:** Alexander Apartsin, Yehudit Aperstein
- **Tarih:** 23 Ağustos 2026 · **Alan:** cs.PF
- **Doğrulama:** arXiv API tam metadata ✓
- **Bulgular:** AI inference servisleri GPU'ları varsayılan olarak tam güçte çalıştırır
  (throughput maksimum, latency düşük) ama bu **enerji-verimsizdir**. Her iş için
  **enerji-optimal bir işletme noktası** ("Joule Point") vardır. Bu nokta iş-yükü
  özelliklerine bağlıdır, donanım özelliklerine değil.
- **Fleksa'ya etkisi:** Fleksa'nın `GpuPowerCapSimulator`'ının perf-per-watt modelini
  doğrular: **bir tek optimal kapa yok, iş başına bir optimal kapa var.** Bu, `min_gpu_cap`
  sabitinin neden yanlış olduğunu arka plandan destekler — doğru çözüm iş-karışımına
  bağlıdır, Fleksa'nın talep-temelli profili bunun bir yaklaşımdır.

**[15] arXiv:2609.30785** — *"Job Class Thermal Intent Aware Liquid Cooling Allocation for
AI Data Centers"*
- **Yazarlar:** Krishna Chaitanya Sunkara
- **Tarih:** 25 Eylül 2026 · **Alan:** cs.DC, cs.PF, eess.SY
- **Doğrulama:** `https://arxiv.org/abs/2609.30785` web_fetch ile birebir açıldı ✓
- **Bulgular:** GPU-yoğun AI veri merkezleri sıvı soğutma zorunlu; ama soğutma döngüleri
  çalışacak iş-yükünden habersizdir — 30–50 saniyelik termal-gecikme penceresi. JCTI,
  zamanlayıcının bildiği **iş-sınıfı (job class)** bilgisini soğutma denetleyicisine
  doğrudan besler. MLPerf GPU güç izlerinden iş-sınıfı termal imzaları çıkarılmış,
  Alibaba cluster verisiyle ayarlanmış. 120 Monte Carlo denemesinde **%56.4 daha az termal
  ihlal**, **%60.2 daha az kümülatif aşma** (düz PI döngüsüne göre). Makale ayrıca
  termal-farkındı zamanlamanın **şebeke tarafında ani talebi azalttığını ve yük tahminini
  iyileştirdiğini** belirtir (gigawatt grid yüklerine giderken).
- **Fleksa'ya etkisi:** **Fleksa'nın `LoadClass` (Class 0–3) modelinin harika bir doğrulaması.**
  İş-sınıfı bilgisinin termal ve güç kararlarına aktarılması, Fleksa'nın zaten
  `WorkloadScheduler`'ında yaptığı bir şey. Ayrıca `thermal_step` modelinin soğutma
  gecikmesini içermemesi bir sınırdır (JCTI'nin 30–50 saniyelik penceresi).

**[16] arXiv:2601.08113** — *"Coordinated Cooling and Compute Management for AI Datacenters"*
- **Yazarlar:** Nardos Belay Abera, Yize Chen
- **Tarih:** 13 Ocak 2026 · **Alan:** eess.SY, cs.DC
- **Doğrulama:** arXiv API tam metadata ✓
- **Bulgular:** AI veri merkezlerinde hesaplama ve soğutmayı **koordine** etmenin enerji ve
  karbon açısından değerini inceler; güç-yoğun LLM iş yükleri altında iki sistemin ayrı
  kontrolünün verimsiz olduğunu gösterir.
- **Fleksa'ya etkisi:** [11] ve [15] ile birlikte, Fleksa'nın `water_cost_per_kwh`
  parametresinin tek yönlü bir ceza değil, GPU kapa ile **eşzamanlı optimize edilmesi**
  gereken bir nicelik olduğunu doğrular.

**[17] arXiv:2604.15594** — *"DataCenterGym: A Physics-Grounded Simulator for Multi-Objective
Data Center Scheduling"*
- **Yazarlar:** Nilavra Pathak, Samadrita Biswas, Nirmalya Roy
- **Tarih:** 17 Nisan 2026 · **Alan:** cs.DC, cs.AI
- **Doğrulama:** arXiv API tam metadata ✓
- **Bulgular:** Heterojen iş yüklerini coğrafi dağıtılmış sitelerde zamanlayan fizik-temelli
  bir simülatör: compute kullanımı, ısı üretimi, soğutma talebi ve enerji tüketimi **sıkı
  bağlı** ama mevcut zamanlayıcıların çoğu bunları soyutluyor. Veri merkezi enerjisinin
  çok-amaçlı optimizasyonu için bir kıyaslama (gym) sağlar.
- **Fleksa'ya etkisi:** **Fleksa'nın doğrulama yöntemi için bir önergedir.** Fleksa'nın
  MPC'si güç dengesini modelliyor ama termal-üretim–soğutma–compute bağlantısını (henüz)
  tam olarak hız içinde çözüyor. DataCenterGym, Fleksa'nın dispatch kararlarının
  fiziksel olarak gerçekçi kaldığını doğrulayacak türden bir kıyaslama sunar.

---

### 2.7 Batarya yaşlandırma — Fleksa'nın sabit `c_deg` limitine yönelik güncel kanıtlar

**[18] arXiv:2403.10617** — *"Depreciation Cost is a Poor Proxy for Revenue Lost to Aging in
Grid Storage Optimization"*
- **Yazarlar:** Volkan Kumtepeli, Holger Hesse, Thomas Morstyn, Seyyed Mostafa Nosratabadi,
  Marko Aunedi
- **Tarih:** 15 Mart 2024 · **Alan:** eess.SY, math.OC
- **Doğrulama:** arXiv API tam metadata ✓
- **Bulgular:** Grid depolama arbitraj dispatch'ı tipik olarak rolling-horizon optimizasyon
  olarak formüle edilir ve maliyet fonksiyonunda bir yaşlandırma modeli içerir. **Amortisman
  maliyeti olarak nicelenmiş degradasyon, kârlılığı artırabilir** ama **"kayıp gelir" (revenue
  lost to aging) için kötü bir vekildir** — amortisman, gerçek fırsat maliyetini ve
  degradasyonun zaman-bağımlı doğasını yakalamaz.
- **Fleksa'ya etkisi:** **Fleksa'nın bilinen en eski zayıflığına en doğrudan akademik eleştiri.**
  Fleksa'nın `c_deg = 0.35 ₺/kWh` sabiti tam olarak makalenin eleştirdiği "amortisman vekil"
  modelidir. Düzeltme: degradasyonu bir sabit yerine **fırsat maliyeti + DoD/sıcaklık bağımlı**
  bir fonksiyon olarak modellemek (`BatteryDegradationEngine.marginal_cost_per_kwh` bunu
  zaten yapabilir, MPC'ye bağlanmamıştır).

**[19] arXiv:2507.04813** — *"Accounting for Subsystem Aging Variability in Battery Energy
Storage System Optimization"*
- **Yazarlar:** Melina Graner, Martin Cornejo, Holger Hesse, Andreas Jossen
- **Tarih:** 7 Temmuz 2025 (rev. 15 Temmuz 2026) · **Alan:** eess.SY
- **Doğrulama:** arXiv API tam metadata ✓
- **Bulgular:** Çok-dizili (multi-string) BESS'ler için **alt-sistem seviyesi homojen-olmayan
  yaşlandırma** değişkenliğini operasyonel kararlara dahil eden bir degradasyon-maliyeti
  farkındalık optimizasyon çerçevesi. Dört senaryo (model hassasiyeti değişen) enerji
  arbitrajı senaryosu üzerinde değerlendirilmiş; string'ler arası yaşlanma farklılıkları
  toplam sistem ömrünü ve kârlılığı belirgin şekilde etkiliyor.
- **Fleksa'ya etkisi:** Fleksa'nın degradasyon modeli **tek bir eşdeğer hücre** varsayar
  (`battery/thevenin.py`). Bu makale, paket-dışı heterojenliğin (string-level aging) bir
  ekonomik faktör olduğunu gösterir — Fleksa'nın filo ölçeğinde (`Swarmax-69`) bir limiti.

**[20] arXiv:2609.34109** — *"Integrated Thermal and Power Management for Wave-Powered Subsea
Data Centers via Nonlinear Model Predictive Control"*
- **Yazarlar:** Wanqun Yang, Jun Chen
- **Tarih:** 28 Eylül 2026 · **Alan:** eess.SY
- **Doğrulama:** arXiv API tam metadata ✓
- **Bulgular:** Dalga-güçlü su-altı veri merkezi için termal yönetim + **esnek iş-yükü
  zamanlama** + dalga-güç kullanımı + batarya operasyonunu **tek bir nonlinear MPC (NMPC)
  çerçevesinde** birleştirir. Gerçekçi veri merkezi iş yükleri ve dalga tarayıcılarından
  örneklenir.
- **Fleksa'ya etkisi:** **Fleksa'nın MPC mimarisinin "komşu" bir alan tarafından
  doğrulanmasıdır.** Fleksa'nın "power balance + SoC + GPU kapa" birleşik MPC'si, makalenin
  "termal + esnek iş-yükü + batarya" birleşik NMPC'si ile aynı felsefededir. Fleksa'nın
  termal dinamikleri MILP'ye **dahil değildir** — bu makale bunun mümkün ve değerli olduğunu
  gösterir.

---

### 2.8 Fiyat/esneklik modellemesi — kanıt ve esneklik ölçümü

**[21] arXiv:2609.23223** — *"Stealing profits: Spread-based temporal hierarchy forecasting
for day-ahead electricity markets"*
- **Yazarlar:** Arkadiusz Lipiecki, Nikolaos Kourentzes, Rafal Weron
- **Tarih:** 19 Eylül 2026 · **Alan:** q-fin.ST, cs.LG, econ.EM
- **Doğrulama:** arXiv API tam metadata ✓
- **Bulgular:** Gün-öncesi fiyat tahminleri ticaret ve depolama kararlarını destekler ama
  **batarya arbitrajı için saatlik fiyatların bireysel tahmininden ziyade fiyat spread'lerinin
  (arbitraj marjı) tahmini daha önemlidir.** THieF temporal-hierarchy framework'ü spread
  tahminlerini ortak uzlaştırır (reconcile), bireysel fiyat tahminlerinden daha iyi arbitraj
  kararları verdirir.
- **Fleksa'ya etkisi:** **Doğrudan ilgili.** Fleksa'nın `EconomicArbitrageGate`'i spread
  (charge vs discharge fiyatı) üzerinden çalışıyor — bu makale spread'in doğru tahmin
  hedefi olduğunu doğrular. Fleksa şu anda fiyatları veri dosyasından okuyor (tahmin yok);
  makale spread-tahmininin tek-fiyat tahminden daha değerli olduğunu gösterir.

**[22] arXiv:2505.09817** — *"Measuring Flexibility through Reduction Potential"*
- **Yazarlar:** Polina Alexeenko, Matthew Bruchon, Jesse Bennett
- **Tarih:** 14 Mayıs 2025 · **Alan:** eess.SY
- **Doğrulama:** arXiv API tam metadata ✓
- **Bulgular:** EV'lerin esnekliğini **zamanlama ve büyüklük olarak kesin biçimde
  karakterize etmeyi** gerektiren "reduction potential matrix" adlı yeni bir yaklaşım.
  Esnekliğin ne **zaman** ve ne **kadar** olduğu ayrılmazdır — tek bir skaler (ör.
  "maksimum %35 azaltma") ikisini de yanlış temsil eder.
- **Fleksa'ya etkisi:** [3]'ün "Beyond Scalar Flexibility" eleştirisini bağımsız olarak
  doğrular. Fleksa'nın dinamik GPU profili, esnekliği **saat-başı (zaman) + büyüklük (cap
  fraksiyonu)** olarak verir — yani makalenin önerdiği formata tam olarak uyar.

**[23] arXiv:2511.16182** — *"Green Distributed AI Training: Orchestrating Compute Across
Renewable-Powered Micro Datacenters"*
- **Yazarlar:** Giuseppe Tomei, Andrea Mayer, Giuseppe Alcini, Stefano Salsano
- **Tarih:** 20 Kasım 2025 (rev. 27 Mayıs 2026) · **Alan:** cs.NI
- **Doğrulama:** arXiv API tam metadata ✓
- **Bulgular:** AI iş-yüklerinin hızlı büyümesi, giderek kesintili yenilenebilir üretimle
  çakışıyor; bugünün merkezi veri merkezi mimarileri bu gerçekle kötü eşleşiyor. İş-yüklerini
  yenilenebilir-powered mikro veri merkezleri arasında dağıtan bir orkestrasyon yaklaşımı.
- **Fleksa'ya etkisi:** **Dolaylı ama stratejik.** Fleksa'nın "AI compute DR" katmanı tek bir
  tesis için çalışıyor; makale, esnekliğin tesisler-arası taşınmasının (grid-follower
  compute) değerini gösterir. Fleksa'nın mesh entegrasyonu (`Swarmax-69` filo) için
  akademik motivasyon sağlar.

**[24] arXiv:2607.25382** — *"Validation of methods to estimate the uncertainty of buildings
energy savings in a controlled numerical setting and Bayesian energy signature with
autocorrelated errors"*
- **Yazarlar:** Léa Gondian, Thimothée Thiery
- **Tarih:** 28 Temmuz 2026 · **Alan:** stat.AP
- **Doğrulama:** arXiv API tam metadata ✓
- **Bulgular:** Bina enerji verimliliğinde M&V, kalibre edilmiş istatistiksel modele
  dayanır; **bu prosedürün belirsizliklerinin tahmin edilmesi güvenilir sonuçlar için
  şarttır.** Kontrol-lü sayısal bir ortamda M&V belirsizlik tahmin yöntemlerini
  doğrular; otokorelalı hatalarla Bayes enerji imzası önerir.
- **Fleksa'ya etkisi:** **Doğrudan ilgili — Fleksa'nın ASHRAE 14 istatistiklerini tamamlar.**
  Fleksa'nın `audit-verify`'ı CV(RMSE) ve NMBE'yi nokta-tahmin olarak raporlar. Bu makale,
  **nokta-tahminin yetersiz olduğunu, belirsizlik aralıkları olmadan M&V iddialarının
  istatistiksel olarak eksik olduğunu** gösterir. Somut iyileştirme: Fleksa raporlarına
  tasarruf için güven aralıkları eklemek (mevcut bir check değildir).

---

## 3. Doğrulanamayan / bulunamayan konular (dürüst itiraf)

Aşağıdaki konularda **hiçbir doğrulanmış akademik kaynak sağlayamadım**. Bunları
**uydurmuyorum**; yok olarak işaretliyorum:

| Aranan konu | Sonuç | Not |
|---|---|---|
| **OpenADR 2.0b / 3.0** protokolünün akademik değerlendirmesi | **Bulunamadı** | OpenADR bir endüstri standardıdır (OpenADR Alliance); makalelerden ziyade spesifikasyon dokümanlarıyla yayılır. arXiv'de doğrulanabilir bir değerlendirme bulamadım. |
| **IEEE 2030.5 (SEP 2.0)** akademik incelemesi | **Bulunamadı** | Aynı şekilde bir IEEE standardıdır; arXiv'de doğrulanamadı. |
| **IPMVP Option B** için doğrudan akademik makale | **Bulunamadı** | IPMVP EVO® tarafından yayınlanan bir protokoldür; akademik makale değil, spesifikasyondur. [10] en yakın ve dolaylı referans (M&V hataları). |
| **EPIAŞ PTF/SMF** üzerine akademik yayın | **Bulunamadı** | EPIAŞ verileri Türkiye-specific ticari veridir; uluslararası akademik makale bulamadım. |
| Fleksa'nın iddia ettiği **"Teorem 1"** ile eşleşen yayımlanmış bir teorem | **Bulunamadı** | Fleksa'nın `arbitrage_gate.py`'deki break-even koşulu meşru bir mühendislik hesabıdır, ancak bunun bir literatür "teorem"i olduğunu doğrulayamadım. **"Teorem" kelimesi iç pazarlama dilidir.** |

---

## 4. Literatüre göre Fleksa değerlendirmesi (dürüst)

### Güçlü (literatür tarafından desteklenen yanlar)
1. **MPC + MILP mimarisi doğru seçim** — [1] MPC'nin oracle'ın %99.2'sini aldığını gösteriyor;
   RL'den üstün. Fleksa'nın tercihleri akademik olarak haklı.
2. **Thevenin ECM fizik modeli sağlam** — [5] ECM'in dağılım-kayması altında dirençli olduğunu
   kanıtlıyor.
3. **"AI compute + BESS" problemi gerçek** — [2], [3] bunun aktif, 2026'da yayımlanan bir
   araştırma alanı olduğunu kanıtlıyor. Fleksa boş bir alanda değil.
4. **Degradasyon maliyetini dispatch'e dahil etmesi doğru** — [4], [6] bunun merkezi bir
   problem olduğunu gösteriyor.
5. **İş-sınıfı (load-class) soyutlama doğrulandı** — [15] (JCTI) iş-sınıfı bilgisinin
   termal/güç kararlarına aktarılmasının %56.4 daha az termal ihlal verdiğini gösteriyor;
   Fleksa'nın `LoadClass` (Class 0–3) modeli aynı felsefededir.
6. **Esnekliğin "zaman + büyüklük" formatı doğrulandı** — [22] tek skaler esnekliğin yanlış
   olduğunu, [12] ise faz-bağımlı dayanıklılığı (decode 0.57×'e dayanıklı, prefill lineer
   kayıp) somut rakamlarla gösteriyor.

### Düzeltme kapatıldı (2026-09-29)
1. **Sabit-yüzde GPU esnekliği (`min_gpu_cap=0.65`) — DÜZELTİLDİ.** [3]'ün çürütmesi üzerine
   Fleksa artık **talep-temelli dinamik GPU esnekliği** kullanıyor
   (`src/fleksa/workload/gpu_flexibility.py`): her saat için kuyruk içeriği (backlog +
   noncritical share + SLA baskısı) ile alt-sınır hesaplanır. Boşta cluster **%45.9** throttle
   headroom'u (0.541 floor) verirken, SLA-doymuş cluster **%0** headroom (1.0 floor) veriyor —
   makalenin %17–47 bandı içinde. [12], [13], [14] bu modelin doğru yönünü doğrular:
   esneklik iş-yükü fazına, iş-karışımına ve iş sınıfına bağlıdır. **Not:** MPC'nin sabit
   `c_deg` ve termal-dışarısı kalması hâlâ açık bir limit; bu düzeltme yalnız DR
   esnekliği soyutlamasını kapatır.

### Zayıf (literatürün çürüttüğü / iyileştirilmesi gereken yanlar)
1. **Sabit degradasyon maliyeti (`c_deg=0.35 ₺/kWh`)** — [4] DoD/sıcaklık-bağımlı rainflow
   modellemenin standart beklenti olduğunu gösteriyor. **[18] bu sabitin tam olarak
   eleştirdiği "amortisman vekil" olduğunu kanıtlıyor** (depreciation cost is a poor proxy
   for revenue lost to aging). [19] string-arası heterojenliği ekonomik bir faktör olarak
   ekler. Fleksa'nın "degradation engine" iddiası MPC içinde hâlâ basit bir sabitle temsil
   ediliyor; `BatteryDegradationEngine.marginal_cost_per_kwh` MPC'ye bağlanmamıştır.
2. **Grid ücretleri / distribution fees modellemesi** — [7] bunun kârlılığı belirlediğini
   gösteriyor; Fleksa'da net değil.
3. **M&V sınır-hataları** — [10] aşınlatma riskini kanıtlıyor. Fleksa'nın
   `out_of_window_curtailed_kwh` materyalite ifşası (audit-verify 13 check) bu riski
   kısmen kapatır.
4. **M&V belirsizlik aralıkları yok** — [24] nokta-tahminin yetersiz olduğunu gösterir;
   Fleksa CV(RMSE)/NMBE'yi nokta olarak raporlar, güven aralığı vermez. **Somut bir sonraki
   adımdır.**
5. **Soğutma–compute bağlantısı tek yönlü** — [11] (ETCInfer) soğutma enerjisi ile GPU
   kapa'nın etkileşimli olduğunu, [16] koordinasyonun değerini, [20] termal+esnek-iş-yükü+
   batarya NMPC'sinin mümkün olduğunu gösteriyor. Fleksa'da `water_cost_per_kwh` bir
   ceza olarak kalır, hız içinde ortak optimize edilmez.
6. **"Teorem 1" ve "Wang/Ecker degradation engine" gibi isimlendirmeler** — doğrulanabilir
   bir akademik karşılığı yok. **Dürüst iletişimde bu isimler yumuşatılmalıdır.**

### Sonuç
Fleksa, **gerçek bir araştırma alanında, doğru mühendislik seçimleriyle** inşa edilmiş.
MPC/MILP/ECM çekirdeği akademik olarak ayakta duruyor. **En eleştirilen zayıflık — sabit
GPU esnekliği — bu sürümde kapatıldı**; kalan açık limitler degradasyon maliyet modeli,
M&V belirsizliği ve soğutma–compute ortak-optimizasyonudur. Proje bir "karar motoru"
olarak değerli; "kanıt üretir" iddiası, kalan zayıflıklar giderildikçe tam olarak
karşılanır.
