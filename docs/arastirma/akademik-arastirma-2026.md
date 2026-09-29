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

### Zayıf (literatürün çürüttüğü / iyileştirilmesi gereken yanlar)
1. **Sabit-yüzde GPU esnekliği varsayımı (`min_gpu_cap=0.65`)** — [3] bu yaklaşımın esnekliği
   %17–47 aşınlattığını kanıtlıyor. Fleksa'nın DR iddiaları **duration/reliability/
   realizability** içermiyor.
2. **Sabit degradasyon maliyeti (`c_deg=0.35 ₺/kWh`)** — [4] DoD/sıcaklık-bağımlı rainflow
   modellemenin standart beklenti olduğunu gösteriyor. Fleksa'nın "degradation engine"
   iddiası, MPC içinde basit bir sabitle temsil ediliyor.
3. **Grid ücretleri / distribution fees modellemesi** — [7] bunun kârlılığı belirlediğini
   gösteriyor; Fleksa'da net değil.
4. **M&V sınır-hataları** — [10] aşınlatma riskini kanıtlıyor; Fleksa'nın
   "expected_savings" hesabı buna karşı savunmasız olabilir.
5. **"Teorem 1" ve "Wang/Ecker degradation engine" gibi isimlendirmeler** — doğrulanabilir
   bir akademik karşılığı yok. **Dürüst iletişimde bu isimler yumuşatılmalıdır.**

### Sonuç
Fleksa, **gerçek bir araştırma alanında, doğru mühendislik seçimleriyle** inşa edilmiş.
MPC/MILP/ECM çekirdeği akademik olarak ayakta duruyor. Ancak **maliyet modeli ve DR
esnekliği soyutlama seviyesi** literatürün (özellikle [3] ve [4]) gerisinde. Proje bir
"karar motoru" olarak değerli; ama "kanıt üretir" iddiası, yukarıdaki zayıflıklar
giderilmeden tam olarak karşılanamaz.
