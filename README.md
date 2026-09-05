# ⚽ fixbet-bot

Fixbet TV kaynağından **güncel site adresini** sürekli takip eden, **maç ID'lerini** çeken,
**günün maçlarını kategorize eden** ve **canlı / yaklaşan / günün maçı / lig & spor bazlı**
raporlar üreten gelişmiş otomasyon botu.

---

## 🧠 Nasıl çalışır?

1. **Güncel adres takibi** (`src/fixbet/domain_checker.py`)
   - fixbettv adresleri numaralı aynalardır (fixbettv84.com, fixbettv85.com, …).
   - `config/mirrors.yml` içindeki kalıp ve aralıktaki adayları HTTP sağlık kontrolünden geçirir.
   - Çalışan adresleri bulur, en güvenilir/güncel olanı seçer ve
     **`config/current_site.yml`** dosyasına yazar. → **Linki her zaman güncel tutar.**

2. **Maç ID çekme** (`src/fixbet/scraper.py`, `parser.py`)
   - Sitenin maç listesinin geldiği stabil kaynaktan ham HTML çekilir
     (`data-reality.com/matches.php`, yedeği `matches2.php`).
   - Her maçın **match ID**'si (`channel?id=<id>`) ve takım/lisans/kategori bilgileri çıkarılır.

3. **Kategorize etme** (`src/fixbet/categorizer.py`)
   - Maçlar saate göre **🔴 Canlı / ⏰ Yaklaşan / ✅ Bitti** olarak işaretlenir.
   - `[Günün Maçı]` etiketiyle **⭐ Günün Maçı** kategorisi oluşturulur.
   - **Spor** ve **Lig** bazlı alt gruplar üretilir.

4. **7/24 Kanallar** (`src/fixbet/channels.py`)
   - Güncel adresin ana sayfasındaki kanal listesi çekilir (id + ad + durum).
   - **Marka bazında** kategorize edilir (Bein Sports, Tabii, TRT, SmartSpor, …).
   - `output/channels.json` dosyasına yazılır ve raporlara eklenir.

5. **GitHub Pages sayfası** (`src/fixbet/site.py` + `src/fixbet/templates/index.html`)
   - Repo kökündeki **`index.html`** her çalıştırmada şablondan yeniden üretilir
     (tek kaynak: şablon). Sayfada **uydurma/sabit maç yoktur**; gömülen her maç
     kaynaktan çekilen gerçek programdır.
   - **İki sekme:** 📺 TV KANALLARI ve 📅 GÜNÜN MAÇLARI. Eski "canlı maçlar"
     sekmesi sabit örnek veriyle dolduğu için kaldırıldı — canlılık bilgisi artık
     günün maçları içinde **gerçek başlangıç saatine göre** hesaplanıyor.
   - **Durum hesabı:** Başlangıç saati + spora göre yayın penceresi
     (`settings.yml → categorize.live_window_by_sport`) → 🔴 Canlı / ⏰ Yaklaşan /
     ✅ Bitti. Aynı tablo sayfaya da gömülür, yani bot ile site aynı şeyi söyler.
     Sayaçlar ("1 sa 20 dk kaldı", "≈ 63'") cihazın saatine göre 30 sn'de bir tazelenir.
   - **Kanala tıkla → yayın player'de:** Alttaki kanal kartına (veya maç
     kartındaki ▶ İZLE'ye) tıklayınca yayın doğrudan oynatıcıda açılır ve sayfa
     yumuşakça player'e kayar (kısa altın "flash" animasyonu ile).
   - **Kompakt kartlar + görünüm seçimi:** Kanal kartları küçültüldü ve
     **▦ Izgara / ☰ Liste** (yatay) seçenekleri eklendi; tercih `localStorage`'da saklanır.
   - Ekstra: marka filtreleri (Bein Sports, S Sport, TRT, Tabii Spor, …), kanal & maç
     **arama**, durum/spor filtreleri, canlı saat, takım logoları, ⭐ Günün Maçı rozeti,
     klavye kısayolları (`←`/`→` kanal, `G`/`L` görünüm, `1`/`2` sekme), `#kanal=...` derin bağlantısı,
     JS kapalıysa çalışan `<noscript>` maç listesi.
   - **Canlı tazeleme:** Sayfa açılışta ve 5 dakikada bir `output/today_matches.json`
     dosyasını okumayı dener (bot bu dosyayı 5 dakikada bir günceller); erişilemezse
     gömülü gerçek veriyle sorunsuz çalışmaya devam eder.

6. **Raporlar** (`src/fixbet/reports.py` → `output/`)
   - `report.html` → tarayıcıda açılan, kendi kendine yeten canlı panel (maçlar + 7/24 kanallar).
   - `matches.md` → okunabilir günlük maç listesi + kanal listesi.
   - `matches.json`, `live_matches.json`, `today_matches.json`, `channels.json` → makine okunur veri.

---

## 🚀 Kurulum & Çalıştırma

```bash
pip install -r requirements.txt

# Tam boru hattı (site -> maçlar -> kategori -> raporlar)
python fixbet.py run

# Sadece güncel adresi güncelle
python fixbet.py update-site

# Sadece maçları çek
python fixbet.py matches

# Sürekli izleme (5 dakikada bir)
python fixbet.py serve 5

# Sayfayı ağ olmadan, output/ içindeki son gerçek veriden yeniden üret
python fixbet.py build-index
```

Çıktılar `output/` klasörüne ve güncel adres `config/current_site.yml` dosyasına yazılır.

---

## ✅ Testler

```bash
python tests/test_pipeline.py     # maç ayrıştırma + canlı/yaklaşan/bitti sınıflandırması
python tests/test_channels.py     # 7/24 kanal listesi + marka grupları
python tests/test_site.py         # index.html üretimi (şablon + gerçek veri)

npm install && npm test           # sayfanın kendi JS'i jsdom içinde çalıştırılır
python tests/test_frontend.py     # aynı arayüz testlerinin pytest/sade-python sarmalayıcısı
```

Arayüz testleri üretilen `index.html`'in JavaScript'ini gerçekten çalıştırır: kanal
kartlarının çizilmesi, ızgara/liste geçişi, karta tıklayınca yayının açılıp player'e
kaydırılması, günün maçlarının gerçek veriden gelmesi, arama/filtre ve canlı tazeleme.
`workflow-tests-example.yml` dosyasını `.github/workflows/tests.yml` olarak kopyalarsanız
bu testler her push/PR'da otomatik koşar (bu depodaki GitHub App token'ının `workflows`
yetkisi olmadığı için dosya kökte örnek olarak duruyor).

---

## 🤖 GitHub Actions ile Otomatik Güncelleme

- **`.github/workflows/update.yml`** → her 5 dakikada bir botu çalıştırır ve raporları GitHub'a kendi başına **push** eder (README üstteki rozet güncel adresi gösterir).
- **`.github/workflows/cron.yml`** → her gün belirli saatte uzun süreli izleme + toplu güncelleme çalıştırır.

> Not: Push işleminin çalışması için repoya `GITHUB_TOKEN` yetkisi yeterlidir (Actions için varsayılan).
> Başarılı push yalnızca `settings.yml` içindeki `dry_run: true` değilken gerçekleşir.

---

## 📁 Yapı

```
fixbet-bot/
├── fixbet.py                 # CLI giriş noktası
├── updater.py                # eski giriş noktası -> artık boru hattını çalıştırır
├── index.html                # ⭐ GitHub Pages sayfası (şablondan otomatik üretilir)
├── requirements.txt
├── README.md
├── config/
│   ├── settings.yml          # bot/kaynak/izleme/kategori ayarları
│   ├── mirrors.yml           # güncel adres arayan kalıplar
│   ├── channels.yml          # bilinen kanal kimlikleri
│   └── current_site.yml      # ⭐ BOT TARAFINDAN OTOMATİK GÜNCELLENEN GÜNCEL ADRES
├── src/fixbet/
│   ├── main.py               # orkestratör
│   ├── domain_checker.py     # güncel site adresi takibi
│   ├── scraper.py            # maç listesi çekme
│   ├── parser.py             # HTML -> Match modeli
│   ├── categorizer.py        # canlı/lig/spor/aygünü kategorize etme
│   ├── reports.py            # HTML/MD/JSON çıktılar
│   ├── site.py               # şablondan index.html üretimi
│   ├── channels.py           # 7/24 kanal listesi
│   ├── models.py             # Match veri modeli
│   ├── templates/index.html  # sayfa şablonu (tek kaynak)
│   └── config.py             # YAML yükleme/kaydetme
├── tests/                    # bot + arayüz (jsdom) testleri
└── output/                   # Üretilen raporlar
```

## ⚖️ Uyarı

Bu proje yalnızca eğitim/otomasyon amaçlıdır. Telif hakkı olan içeriklerin yeniden
dağıtımı yasak olabilir; kendi siteniz/datanız için kullanın.
