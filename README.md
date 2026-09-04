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

5. **GitHub Pages sayfası** (`src/fixbet/site.py`)
   - Repo kökündeki **`index.html`** her çalıştırma da yeniden üretilir.
   - Şablondaki sabit/ölü alan adı yerine **güncel site adresi** yazılır,
     7/24 kanal listesi ve **günün maçları** (canlı / yaklaşan / günün maçı / lig bazlı)
     otomatik gömülür. GitHub Actions push ettiği için GitHub Pages her zaman güncel kalır.

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
```

Çıktılar `output/` klasörüne ve güncel adres `config/current_site.yml` dosyasına yazılır.

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
│   ├── models.py             # Match veri modeli
│   └── config.py             # YAML yükleme/kaydetme
└── output/                   # Üretilen raporlar
```

## ⚖️ Uyarı

Bu proje yalnızca eğitim/otomasyon amaçlıdır. Telif hakkı olan içeriklerin yeniden
dağıtımı yasak olabilir; kendi siteniz/datanız için kullanın.
