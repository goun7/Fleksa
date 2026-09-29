# Changelog — Fleksa

## [0.1.1] — 2026 — 2. dalga: dinamik GPU esneklik aralığı

### Dürüst-not: sabit `min_gpu_cap = 0.65` geçersizdir

Eski sabit `min_gpu_cap = 0.65` eşiği 2026 akademik çalışmalarıyla **geçersiz
kılındı** ( doğrudan kaldırılmadı, geriye dönük uyumlu bir aralağa
dönüştürüldü):

- **arXiv:2609.27926 "Joule Point"** — inference-başına harcanan enerji, güç
  kapına göre **U-şekillidir** ve optimum **iş yüküne göre değişir** ( büyük
  GPU'larda tepe-gücün **%43-46'sında** yatar). "yüksek utilization = verimli"
  varsayımı yanlıştır; tek sabit kap her iş yükü için optimal olamaz.
- **arXiv:2608.07971 "ElastiCo"** — statik kapasite ayrımları kalıcı
  **underutilization** yaratır; ayrım esnemelidir, sabit kalmamalıdır.
- **arXiv:2609.16682 "DeepShare"** — assurance sabit kota değil, **sürekli ve
  talep-temelli** bir sinyal olmalı ( %70.58 utilization, −%46 gecikme).

### Değişiklikler ( dar kapsamlı — GPU mantığı yeniden yazılmadı)

- **`FleksaMPCSolver`:** `min_gpu_cap = 0.65` → **dinamik aralık**
  `min_gpu_cap: float = 0.35`, `max_gpu_cap: float = 0.95`
  ( Joule Point %43-46 optimum bandını kapsar).
- **Yeni parametre `dynamic_gpu_cap`** — iş yükü sinyaline ( [0,1] aralığında
  DeepShare assurance sinyali) göre aralıktan alt-sınır seçer:
  `FleksaMPCSolver.select_dynamic_gpu_cap(workload)` ( yüksek iş yükü →
  yüksek kapasite).
- **Geriye dönük uyum:** `dynamic_gpu_cap` verilmezse eski sabit **0.65**
  döner — **breaking change DEĞİL**. Öncelik sırası:
  `gpu_flex_profile` ( arXiv:2609.05406) > `dynamic_gpu_cap` > eski sabit 0.65.
- **Aralık dışı değer RED:** `dynamic_gpu_cap=0.2` → `ValueError`.
- **CLI:** yeni `--dynamic-gpu-cap`; `--gpu-cap-min` ( 0.35) ve yeni
  `--gpu-cap-max` ( 0.95) aralığı tanımlar.
- **Sunucu ( REST `/api/solve`):** değiştirilmedi — mevcut `gpu_flex_mode`
  davranışı korunur.
- **Testler:** **166 → 171** ( 5 yeni odak test,
  [`tests/test_dynamic_gpu_cap.py`](tests/test_dynamic_gpu_cap.py) ), **0 failed**.
