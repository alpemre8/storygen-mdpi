# E01-B — Cross-Model and Cross-Precision Feature Extractor Validation

Kullanıcının istediği yeni devam deneyi, `plugins/e01_b` sağlayıcısı üzerinden mevcut engine'e bağlıdır. Eski `e01_canonical_mistral`, `e01_independent_extractor`, `E01B_mistral_f16_full`, `E01_MIN` ve sonuçları değişmez. Yeni rewrite üretimi yoktur.

| Aşama | Engine deney kimliği | Mevcut rewrite kaynağı | Yeni extractor |
|---|---|---|---|
| B1, öncelikli | `e01_b1_cross_model_precision` | Qwen2.5-7B DP-v1 ve CG-v1 | Mistral-7B-Instruct-v0.3 Q4_K_M |
| B2 | `e01_b2_cross_model_precision` | Gemma-3-12B CG-v1 | Aynı Mistral Q4 |
| B3 | `e01_b3_cross_model_precision` | Gemma-3-12B DP-v1 | Aynı Mistral Q4 |

Aşamalar ayrı komutlarla başlar. B1, B2/B3'ü başlatmaz; isteğe bağlı Gemma/FP16 payload'larına bağımlı değildir. Her aşama kendi 400 özgün source/reference sahnesini ölçer; farklı aşamaların ölçümleri otomatik birleştirilmez.

Evren her koşul için 240 görevdir. Mevcut Qwen DP'de 239, Qwen CG'de 235, Gemma DP'de 239 ve Gemma CG'de 238 rewrite vardır. Eksik görevler 240 paydasından çıkarılmaz. B1 iki koşulda 480 görev-koşul gözlemidir, 480 ayrı görev değildir.

## Kopyalanabilir komutlar

Her iki terminalde çalışma dizini:

```bash
cd /home/alp-emre/projects/01-Storygen-area/storygen
```

Sunucuyu açmadan önce **offline preflight**:

```bash
./bin/storygen e01-b preflight
```

Yalnız öncelikli B1'in girdilerini kontrol etmek için:

```bash
./bin/storygen e01-b preflight --phase B1
```

Preflight ağ, model yükleme veya inference yapmaz. Model/binary SHA, gerçek GGUF tensor/quantization metadata'sı, Mistral mimarisi, embedded template, Qwen ayarlarıyla eşitlik, input dosya hash'leri, scene/task eşleştirmeleri ve implementation approval kontrol edilir. Tam kontrolde 5.526 açık tarihsel dosya doğrulanır. Canlı server kontrolü yalnız araştırmacı `run` başlatınca yapılır.

**Terminal 1 — araştırmacı sunucuyu başlatır:**

```bash
./bin/storygen e01-b server
```

Komut foreground'da kalır; server stdout/stderr dosyaya gider. Varsayılan session `e01-b-mistral-q4`, port 8080'dir. Varsayılan başlangıç kontrolü B1 kaynaklarıdır; aynı sunucu tüm aşamalarda kullanılabilir. Başka bir listener'a bağlanılmaz veya onu durdurma işlemi yapılmaz. Terminal 1 mevcut GPU lease'ini tutar. Runner yalnız bu StoryGen oturumunun process identity, parent-child ownership, executable/argv, model, context ve slot kontrolü geçen sunucusuna bağlanır; ikinci experiment client engellenir. Sunucuyu Terminal 1'de Ctrl+C ile bitir. Runner sunucuyu sonlandırmaz.

**Terminal 2 — öncelikli B1:**

```bash
./bin/storygen e01-b run --phase B1 --run-id e01-b1-20261023-01
```

B1 sonrası rapor:

```bash
./bin/storygen e01-b report --b1-run e01-b1-20261023-01 --report-id e01-b-after-b1-20261023-01
```

B2/B3 çalıştırılmadıysa ilgili Mistral Q4 hücreleri `PENDING` kalır. Sonraki aşamalar istendiğinde aynı sunucuyla ayrı ayrı:

```bash
./bin/storygen e01-b preflight --phase B2
./bin/storygen e01-b run --phase B2 --run-id e01-b2-20261023-01
```

```bash
./bin/storygen e01-b preflight --phase B3
./bin/storygen e01-b run --phase B3 --run-id e01-b3-20261023-01
```

Üç aşama tamamlandığında:

```bash
./bin/storygen e01-b report --b1-run e01-b1-20261023-01 --b2-run e01-b2-20261023-01 --b3-run e01-b3-20261023-01 --report-id e01-b-all-20261023-01
```

Report model/server gerektirmez. Kaynak run'lar açıkça seçilir; "en son" run otomatik seçilmez. Run/report kimlikleri üzerine yazılmaz. Kimlikler kullanılmışsa yeni bir kimlik seç ve report komutunda aynı yeni run kimliğini kullan.

## Korunan protokol ve uyumluluk farkları

Özgün Qwen runner `plugins/feature_extraction/historical/feature_extraction/src/storygen_feature/extractor.py`; yeniden ölçüm runner'ı aynı pakette `rewritten.py` dosyasıdır. E01-B aynı `CanonicalFeatureScorer`, parser, normalizasyon, retry ve `GlobalSceneScheduler` kullanır. Before/Target kurulumu eski `E01_MIN/.../EVALUATION_HANDOFF.py:evaluation_plan` ile golden testte eşittir. TI/DA özgün `storygen_evaluation.metrics.evaluate_task` fonksiyonundan gelir.

Gerçek Qwen server ayarlarının kaynağı `plugins/rewrite/historical/components/tasksetv5/v1/SERVER_PROFILES.json` measurement manifesti ve `runtime_profiles/ComputerA.vulkan.yaml` argv'sidir. Yeni profil `runtime_profiles/ComputerA.e01-b-mistral-q4.yaml`:

| Ayar | Korunan değer |
|---|---|
| llama.cpp | Aynı `1425386fd996511e1f3295e7366c38289a92a271` commit'i ve aynı SHA ile Vulkan binary |
| Parallel / total context / slot context | 8 / 98.304 / 12.288 |
| Device / fit | Vulkan0 / off |
| GPU layers | Özgün argv'de açık override yok; aynı binary'nin varsayılanı korunur |
| Batch / ubatch | 16.384 / 2.048 |
| KV | `--no-kv-unified`; K=F16, V=F16 |
| Continuous batching / flash attention | Açık / açık |
| Server timeout / threads / batch threads / HTTP threads | 900 / 6 / 6 / 12 |
| Prompt / feature tanımları / JSON schema | Özgün dosyalar ve aynı SHA-256 |
| Temperature / max tokens | 0 / 256 |
| Diğer sampling alanları | Özgün protokoldeki null alanlar gönderilmez |
| Request timeout / concurrency / schema retry | 600 saniye / 8 / 1 ek deneme |
| Normalizasyon / fallback | Aynı [0,1] clamp; heuristic fallback kapalı |

Server argv'de yalnız model yolu ve alias değişir. Mistral Q4 SHA-256: `1270d22c0fbb3d092fb725d4d96c457b7b687a5f5a715abe1e818da303e562b6`. Protokolün model bloğu yeni model kimliğini kaydeder. Teknik startup readiness bekleme süresi 300 saniyedir; generation/measurement timeout'ları değişmez.

Qwen'in ChatML template'i yerine Mistral GGUF'un kendi `[INST]` template'i kullanılır. Mistral embedded template'i system rolünü doğrudan desteklemez. Aynı sabit llama.cpp sürümündeki `common/chat.cpp:workaround::system_message_not_supported`, system metnini ilk user mesajının başına `\n` ile ekler. Mevcut HTTP system/user mesajları ve prompt byte'ları değiştirilmez; yeni template veya feature yöntemi yoktur. Uyumluluk yerel backend kaynağı ve gerçek embedded template üzerinden offline kontrol edildi; gerçek server çalıştırılmadı.

Eski Gemma CG Mistral FP16 koşusu 9.216 context/slot, 512 batch, 128 ubatch ve 16 GPU layer kullanmıştı. Q4–FP16 karşılaştırması runtime farklarını da içerir; yalnız precision'ın nedensel etkisi olarak yorumlanmaz. Eski kayıtlar korunur.

## Ölçüm ve rapor

Before, referanstan resample edilen Target ve After her extractor'ın kendi ölçüm uzayındadır. Mistral B/T yeniden ölçülen source/reference sahnelerinden kurulur. Generation sırasındaki Qwen transfer planı korunup yeni değerlendirme planına hash ile bağlanır; Qwen target curve'leri Mistral metriğine taşınmaz. Mevcut Qwen ve FP16 kontrolleri kimlik/hash/eşleştirme doğrulamasından sonra okunur.

Ana tablo istenen dokuz birleşimi; TI, DA, Mean Gain, Before–Target ve After–Target MAE, ölçülebilen/ölçülemeyen ve toplam görev sayılarını içerir. TI/DA [0,1] oranıdır. Mean Gain = Before–Target MAE − After–Target MAE. `HISTORICAL`, `MEASURED`, `PENDING` ayrıdır; çalıştırılmayan hücreler doldurulmaz.

Eşli karşılaştırmalar iki tarafta da ölçülebilen görev kesişiminde hesaplanır. Her kontrastın tam görev listesi ve iki tarafın bu listedeki ortalamaları kaydedilir. Extractor, Gemma CG precision ve aynı extractor altındaki CG−DP kontrastları ayrıdır. Eski E01 yöntemi korunur: `base_interval_id` cluster bootstrap, 10.000 tekrar, NumPy PCG64 seed 42, linear percentile %95 CI. İkiden az cluster veya dejenere dağılımda CI üretilemediği yazılır. Teknik tamamlanma kapısı bilimsel hipotezin doğrulanması değildir; otomatik bilimsel başarı iddiası yoktur.

### Hakem için ek analiz (tamamen offline)

`report` komutuna `--reviewer-analysis` eklemek B1/B2/B3'ün üçünün de açık run ID'sini gerektirir. Mevcut input manifesti ve run'lar değişmez; yeni ve kullanılmamış bir report ID seçilir:

```bash
storygen e01-b report --reviewer-analysis \
  --b1-run e01-b1-20261023-01 \
  --b2-run e01-b2-20261023-01 \
  --b3-run e01-b3-20261023-01 \
  --report-id e01-b-reviewer-analysis-20261023-01
```

Mevcut karşılaştırmalara ek olarak Mistral'ın dört Q4 ve bir tarihsel FP16 koşulunun kendi mean gain CI'ları, koşul başına dört ölçümün ortak görevlerinde Qwen−Gemma TI düşüş farkı ve extractor'lar arası TI karar uyumu üretilir. Düşüş farkının işareti `(Qwen rewrite: Qwen extractor − Mistral Q4) − (Gemma rewrite: Qwen extractor − Mistral Q4)` şeklindedir; pozitif değer Qwen rewrite'larında daha büyük düşüşü ifade eder. Bu koşularda ortak N DP için 238, CG için 233; Mistral CG−DP için Qwen'de 234, Gemma'da 237'dir. Tümünde 48 base interval vardır.

Tablo 11b beş boyutta Spearman rho, mutlak uyum ICC(2,1) ve ortalama mutlak farkı verir. B1/B2/B3'ün orijinal sahne ölçümleri ayrı tutulur; aynı 400 sahne üç fazdan birleştirilerek 1.200 bağımsız gözlem sayılmaz. Yeniden yazımlarda model/koşul/görev/film/sahne kimliğiyle eşlenen geçerli skorlar kullanılır; görev TI uygunluğu ayrı kaydedilir. Her özellik ve faz için kaynak-eğrisi korelasyon medyanı ile native resampling/signum üzerinden hedef yönü uyumu da raporlanır. Sabit eğriler için Spearman tanımsızdır; yalnız medyan hesabından çıkarılır ve sayıları/kimlikleri açıklanır. Negatif ICC saklanır.

Yeni klasörde `REPORT.md`, `comparison.json`, `comparison.csv`, `task_records.json` ve `paired_contrasts.csv`, `gain_intervals.csv`, `ti_agreement.csv`, `extractor_agreement.csv` bulunur. JSON tam görev popülasyonlarını, dışlama nedenlerini, skor kaynaklarının receipt/hash'lerini ve yöntemleri içerir. TI/DA farkları yüzde puan; gain ve skor farkları 0–1 ölçeğindedir. Karar uyumu oran olarak yazılır. Tarihsel %73.11 FP16'ya aittir, Q4 uyumu ayrıca hesaplanır. Eksik/değişmiş veya yanlış koşula ait kaynak hata verir; ağ/model/sunucu başlatılmaz. Bayrak olmadan eski ve kısmi rapor davranışı korunur.

## İlerleme ve kurtarma

Terminal 2'de tek renderer aynı satırı günceller:

```text
E01-B1 [████████████░░░░░░░░] 60% (144/240) | Elapsed 00:12:35 | ETA 00:08:23
```

Sayılan işler source/reference ve mevcut rewrite **sahne ölçüm konumlarıdır**, bilimsel görev sayısı değildir. Gerçek toplam preflight'ta `phase_scene_jobs` alanındadır. İlk hız örneğine kadar ETA `00:00:00`; sonrasında tamamlanan yeni işlerin gerçek hızından hesaplanır. Checkpoint işleri hız örneklemine katılmaz. Log, JSON, model yanıtı terminale basılmaz. Exit code 0 teknik tamamlanmadır; hatalar runner logundadır.

Kesinti sonrası aynı kod/model/protokol ve aynı run kimliğiyle:

```bash
./bin/storygen e01-b run --phase B1 --run-id e01-b1-20261023-01 --resume
```

Hash'i doğrulanmış scene sonuçları tekrar çağrı yapmadan kullanılır; kullanım ayrı provenance kaydıdır. Sonucu alınamadan kesilmiş request için yalnız `.started.json` varsa belirsiz çağrı otomatik tekrarlanmaz. `Ambiguous interrupted` tanısı yeni run kimliği gerektirir; eski run korunur. Tamamlanmış run tekrar başlatılamaz. Normal ölçümlerin özgün retry sınırı artırılmaz.

## Dosyaların yeri

Tüm veri `/home/alp-emre/projects/01-Storygen-area/storygen-depot` altındadır:

- `datasets/e01_b_cross_model_precision/inputs.json`: sabit input/receipt SHA'ları ve task/source eşleştirmeleri.
- `experiments/e01_b1_cross_model_precision/runs/e01-b1-20261023-01/`: B1 lock, snapshot, journal ve sonuçları; B2/B3 kendi deney klasöründedir.
- Her run'da `stages/measure/raw.jsonl`: request/response/error, retry ve checkpoint-kullanım provenance'ı.
- Her run'da `native/measure/dataset/<attempt_id>/`: original/after feature'lar, bağımsız transfer planları, görev metrikleri, telemetry, `PROVENANCE.json`.
- Her run'da `e01_b_checkpoints/` ve `e01_b_progress.json`: hash kontrollü scene sonuçları ve ilerleme.
- `experiments/e01_b/logs/<run_id>.log` ve `<run_id>.result.json`: runner ayrıntıları/özetleri.
- `experiments/e01_b/runtime/logs/<session-attempt>/measurement.server.log`: server stdout/stderr.
- `reports/e01_b/<report_id>/REPORT.md`, `comparison.csv`, `comparison.json`, `task_records.json`: insan/makine raporları, eşli örneklemler, CI ve başarısızlık nedenleri.

Depot yereldir; remote yayınlama/push kapısı değişmez. Implementation approval kod HEAD'ine bağlıdır; kod/profil değişirse yeniden doğrulama gerekir. Araştırmacıya verilen `server` ve `run` komutları Codex hazırlığı sırasında çalıştırılmaz.
