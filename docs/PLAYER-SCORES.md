# Player ve maç skorları — inceleme / işletim notları

## 6 Eylül 2026 incelemesi: doğrulananlar ve sınırlar

| Katman | Bulgu | Değişiklik |
| --- | --- | --- |
| Atom kanal sayfası | Repo `/kanal/<slug>` kullanıyordu; güncel sitedeki bağlantılar `/matches?id=<slug>`. Eski yol incelemede HTTP 500 döndü, yeni yol player sayfasını açtı. Kayıtlı Atom çıktısı **0/14 çözülmüş yayın**, yalnızca worker yedeği içeriyordu. | Doğru sayfa şablonu ve ana sayfa sağlık kontrolü; iframe/yeni sekme adresi de düzeltildi. |
| Atom worker | `https://tv.atomspor.workers.dev/?ID=bein-sports-1`, incelemede `https://corestream.ardastream.live//beintv/tracks-v1a1/mono.m3u8` adresine yönlendi. `s-sport` da kendi medya listesine yönlendi. | Bot, uzantısız worker yanıtını/redirect'i çözer ve nihai HLS URL'sini öne alır. Sabit CDN adresi üretim koduna yazılmadı; worker yedeği korunur. |
| Master / media | `.../beintv/index.m3u8` master'ı göreli bir media URI'si, `avc1.640028,mp4a.40.2`, 1920×1080, 25 fps bildirdi. Media listesi `.jpg` uzantılı segment URI'leri içeriyordu. | Playlist kendi nihai URL'siyle tutulur; ilk alt varyant yanlışlıkla kaynak sanılmaz. URI uzantıları değiştirilmez; query imzaları bozulmaz. HLS ayrıştırması hls.js'e bırakılır. Proxy gerçek TS/MP4 baytlarından MIME belirler. |
| Native HLS seçimi | Gerçek Chromium testinde `canPlayType(HLS)` olumlu olmasına rağmen bazı media-only/byte-range kaynaklar native yolda `MediaError 4` verdi. Aynı medya hls.js ile oynadı. | Apple WebKit'te native HLS, diğer MSE tarayıcılarında hls.js; uygun durumda native geri dönüş. Custom header'lar native yolda sessizce kaybolmaz. |
| Player yaşam döngüsü | Eski kod manifest parse olur olmaz loading/timeout'u kapatıyor; bazı fatal hatalarda sınırsız `startLoad` / `recoverMediaError` çağırıyordu. Iframe'e geçerken bekleyen HLS callback'leri geçersizleşmiyordu. | Başarı `playing` olayıdır. 25 sn başlangıç / 20 sn stall sınırı, istek başına en fazla iki retry, bir medya kurtarma denemesi, session token ve cleanup. |
| Header / CORS | Bot `referrer` tutuyordu fakat sayfa payload'ı bunu siliyordu. Tarayıcıdan başka sitenin `Origin`, `Referer`, `User-Agent` header'ları serbestçe gönderilemez. | Metadata korunur; gerektiğinde gerçek backend üzerinden tüm HLS zinciri taşınır. İstemcide yasak header taklidi, `no-cors`, açık üçüncü taraf proxy veya SSL doğrulamasını kapatma yok. |
| Günün maçları | İncelenen `matches.php` / `matches2.php` yanıtlarında skor ve gerçek durum yok. Eski `status` botun süre tahmini; frontend tazelemesi bu alanı da atıyordu. `match_id` bir **kanal** kimliği ve gün içinde tekrar ediyor. | Kaynak durumu/skoru ayrı provenance alanlarıyla korunur. İkincil ESPN scoreboard kesin etkinlik eşleşmesiyle kullanılır; kanal ID'sinden skor eşleştirilmez. |

**Doğrulama sınırı:** Bu çalışma ortamında doğrudan `requests`/curl çağrıları yayın ve skor servislerinde TLS bağlantısı kurulmadan kesildi. Ayrı web okuma aracıyla playlist/sayfa/scoreboard şemaları görülebildi, fakat Atom segmentlerinin gerçek HTTP/CORS header'ları ve kullanıcının çalışan harici player'ının HAR kaydı karşılaştırılamadı. Bu nedenle “Atom'da kesinlikle yalnızca CORS hatası vardı” veya “canlı Atom yayını uçtan uca doğrulandı” iddiası yok. Yukarıdaki kod/veri akışı hataları düzeltildi; gerçek HLS taşıması kontrollü, sentetik medya ile test edildi. Atom upstream segmentlerinin codec'i ayrıca decode edilmedi; master'ın **bildirdiği** codec ile gerçek decode doğrulamasını karıştırmayın.

## Statik GitHub Pages ve HLS hizmeti

CORS izinleri doğru bir HTTPS kaynağı doğrudan oynar. Yeni hls.js sürümü **1.7.2** olarak sabittir, ilk kullanımda yüklenir ve ikinci CDN yedeği vardır. Safari/iOS native yolu korunur. Tarayıcının codec/DRM desteğini bir proxy değiştirmez, transcode/decryption bypass yapılmaz.

CORS, HTTP mixed-content veya gerekli özel header nedeniyle doğrudan oynatılamayan bir kaynak için:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python fixbet.py web --host 0.0.0.0 --port 8000
```

- Sayfa ve `/api/hls` aynı köktedir. İstemci `api/playback.json` üzerinden hizmeti keşfeder; tarayıcı kodunda localhost backend URL'si yoktur.
- Üretimde bu hizmeti **HTTPS reverse proxy arkasında**, bağlantı/rate limitleriyle ve yalnızca yetkili yayınlar için çalıştırın. Hizmet açıldığı için GitHub Pages kendiliğinden backend kazanmaz.
- **GitHub Pages ayrı kalacaksa** hizmeti kendi HTTPS hostunuza deploy edin. Sonra `config/settings.yml` içindeki `playback.proxy_url` alanına gerçek `/api/hls` URL'sini yazın ve index'i yeniden üretin. Buraya örnek/var olmayan bir host yazıp çalışıyormuş gibi davranılmadı; varsayılan boş.
- Hizmet botla aynı checkout / `output/` dizinini paylaşabilir. Ayrı host ediliyorsa `playback.registry_url` alanını `https://inadinatv.github.io/macweb/output/extra_channels.json` yapın. Hizmet aynı yayımlanmış kaydı 60 sn önbellekle takip eder; hata halinde son kayıt korunur. Böylece kaynaklar değiştiğinde hizmeti sürekli yeniden deploy etmek gerekmez.
- `playback.allowed_origins` GitHub Pages kökenini içerir. Farklı bir site için o origin'i açıkça ekleyin. Gerekli proxy deployment'ı ve harici yayınların erişim izinleri bu repo değişikliğiyle otomatik sağlanmış **değildir**.

### Header ve güvenlik sınırı

`config/extra_channels.yml → panels[].playback`:

- `allowed_hosts`: tam alan adı izin listesi; wildcard yok. Atom için gözlenen worker/manifest/segment hostları tanımlı. CDN yeni bir alana taşınırsa tanılayıp listeyi güncelleyin.
- `headers`: backend tarafından gönderilecek `Referer`, `Origin`, gerekiyorsa sağlayıcıya uygun `User-Agent`. `{referrer}`, `{origin}`, `{page_url}` yer tutucuları kullanılabilir.
- `header_env`: gizli header değerlerini yalnızca hizmet ortamından okumak için header adı → ortam değişkeni adı. **Gizli değerleri YAML'a, kaynak JSON'una, index'e veya Git'e koymayın.** Gizli header kullanılan zincirde HTTP'ye dönüş reddedilir.
- `channels[].request_headers`: yalnızca herkese açık istemci header'ları. hls.js bunları playlist/key/segment isteklerinde uygular. Yasak browser header'ı varsa proxy gerekir.
- `playback.require_proxy: true`: doğrudan denemeden hizmet gerektiren kaynaklar için. Varsayılan yayın davranışı değiştirilmez; normalde önce doğrudan yayın, ağ hatasında aynı kaynağın proxy yolu, sonra diğer HLS kaynağı denenir. Site iframe'ine sessizce düşülmez; kullanıcı seçer.

Proxy başlangıçta yalnızca kayıtlı kanal/kaynak seçimini kabul eder; `?url=...` gibi açık URL proxy'si değildir. Alt playlist, segment, audio, subtitle, key, init/MAP, PART, preload ve rendition URI'leri süreli HMAC biletleriyle yeniden yazılır. Her URI/redirect izin listesi ve public DNS/IP kontrolünden geçer. Özel port, kullanıcı bilgili URL ve özel/yerel IP reddedilir. Soket tam olarak
kontrol edilen sayısal adrese bağlanır (DNS-rebinding/check-use yarışı yok);
Host/SNI ve TLS sertifika kontrolü gerçek host adıyla devam eder. Hizmet ortamın
`HTTP_PROXY`/`HTTPS_PROXY` ayarlarını kullanmaz; egress firewall ek savunma sağlar. Range/206 korunur, medya akıtılır; gelen kullanıcı cookie/header'ları upstream'e kopyalanmaz. 1 MiB playlist / 32 MiB medya boyutu, 5 sn bağlantı / 20 sn okuma bekleme sınırı ve 32 eşzamanlı aktarım sınırı vardır. HMAC biletleri URL gizleme/şifreleme ya da kullanıcı yetkilendirmesi değildir; özel yayınlar için ayrıca kendi erişim denetiminiz gerekir.

Birden fazla worker/instance çalıştıracaksanız tümünde aynı güçlü **`STREAM_PROXY_SECRET` ortam değişkenini** kullanın. Aksi halde süreçler birbirinin biletlerini doğrulayamaz. Tek instance varsayılan olarak rastgele anahtar üretir; restart sonrası kullanıcı yeniden deneyebilir.

Desteklenmeyen playlist değişken URI'leri (`{$...}`) sessizce bozulmak yerine açık hata verir. DRM, gerçek resim döndüren segment, codec uyumsuzluğu veya yetkisiz kaynağa erişim header değiştirerek çözülmüş sayılmaz.

## Maç durumları ve skor modeli

| Normalize durum | Kart | Skor |
| --- | --- | --- |
| `upcoming` | Saat + geri sayım / başlaması bekleniyor | Yok (kaynak 0–0 verse bile) |
| `live` | CANLI | Varsa gerçek skor |
| `halftime` | DEVRE, canlı filtre/sayacına dahil | Varsa gerçek skor |
| `finished` | Kaynaktan doğrulanmışsa MS; yalnızca saat tahminiyse Bitti | Yalnızca iki tarafın da skoru varsa |
| `postponed` | Ertelendi | Yok |
| `cancelled` | İptal | Yok |
| `suspended` / `abandoned` | Durduruldu / Oynanmadı | Yok |

- `status_source`: `schedule` (tahmin), `source` (asıl HTML), `espn` (ikincil kaynak).
- `raw_status`: sağlayıcının özgün kodu; `match_state.py` sözlüğü **aynı şekilde JS'e gömülür**.
- `score_home`, `score_away`: integer veya `null`; sıfır geçerlidir, eksik skor asla sıfır yapılmaz.
- `score_source`, `score_updated_at`: kaynağı/yaşı saklar. Canlı skor 15 dk'dan eskiyse kartta “son skor” notu vardır. Snapshot'ın saati geçti diye canlı skor final yapılmaz.
- `event_id`: sağlayıcının gerçek etkinlik ID'si. `match_id` / `channel_id` eski kanal oynatma işlevinde kalır.
- `starts_at`: saat dilimli ISO başlangıcı; tarayıcının yerel dilimi maç durumunu değiştirmez. Eski JSON da Türkiye / yapılandırılmış program saat dilimiyle okunur.

`config/scores.yml` varsayılan olarak ESPN zenginleştirmesini açar. Tanımlı başlıca futbol ligleri ile NBA/WNBA desteklenir; **her lig/spor kapsanmıyor**. Lig + spor + yerel takvim günü + en fazla 45 dk başlangıç farkı + iki takımın açık isim eşleşmesi gerekir. Ev/deplasman `homeAway` alanından seçilir, array sırasından değil. Türkçe/aksan normalizasyonu ve lig bazlı açık isim alias'ları vardır; fuzzy eşleşme yok. Birden fazla adayda veya eksik/yanlış eşleşmede skor yok.

ESPN'nin herkese açık scoreboard uç noktası bağımsız bir hizmettir; resmi bir SLA'ya güvenilmez. Kapatılabilir/değiştirilebilir; desteklenmeyen liglerde mevcut program korunur. Asıl kaynak gerçek status veriyorsa önceliklidir. Hata veya boş/malformed ikincil cevap mevcut programı silmez; aynı gün/aynı karşılaşmanın son doğrulanmış sonucu korunur. Skoru gelmeyen bir final, eski canlı skordan doldurulmaz.

Botun normal `run` / `matches` akışı skorları JSON'a ve index'e taşır. Sayfa açılışta ve **5 dakikada bir** bu yayımlanmış JSON'u yeniler; bu saniyelik bir canlı skor servisi değildir. `build-index` çevrimdışıdır, dışarıdan yeni skor çektiğini iddia etmez. İnceleme sırasında gerçek skorlar elle output dosyalarına yazılmadı.

## Tanılama

Tarayıcı konsolu ve `window.inadina.playerLogs` son 60 olayı içerir: istek/hata tipi, HTTP kodu, query'si maskelenmiş kaynak, level/codec/çözünürlük, audio track ve MediaSource desteği. Autoplay engelinde hata yerine **Yayını başlat** düğmesi görünür. Yeniden Dene yayımlanmış yeni kaynak listesini de kontrol eder.

Yayına ağ erişimi olan ortamda:

```bash
python fixbet.py diagnose-stream atom:bein-sports-1
python fixbet.py diagnose-stream atom:s-sport --source 0 --page-origin https://inadinatv.github.io
```

Araç aynı HLS adresini browser-like ve kaynak-site header bağlamlarıyla karşılaştırır; redirect, master/media, MIME, CORS, segment/key/init erişimini raporlar. `ffprobe` kuruluysa örnek segmentin track/codec bilgisini de dener. Bu, gerçek tarayıcı HAR'ının yerine geçmez. TLS/ağ bağlantısı kesildiyse bunu CORS veya codec hatası diye etiketlemez. Loglarda query/token ve key içerikleri yoktur.

## Testler

```bash
pip install -r requirements-dev.txt
npm install
python -m pytest -q tests
npm test
npx playwright install --with-deps chromium
npm run test:browser
```

- Python: mevcut pipeline/lig/kanal listeleri; skor parser/normalize/payload/roundtrip; scoreboard eşleşme ve kesinti; proxy URI/redirect/range/header, SSRF/HMAC/origin sınırları.
- jsdom: gerçek index script'i, gömülü/remote skor eşitliği, bütün durumlar, sıfır/eksik skor, timestamp, gecikmiş fetch, player race, retry, timeout, stall, autoplay, CDN hatası, Safari/native seçimi. Üretilen index'in CSS ve script'inin şablonla eşitliği de kontrol edilir.
- Chromium + gerçek hls.js: 302 master → media → `.jpg` MPEG-TS; fMP4 init/audio/video; byte-range media; AES key/segment header reddinden gerçek proxy ile oynatmaya geçiş; proxy HTTP 206; 320/375/768/1440 px taşma kontrolü. Web güvenliği/CORS **devre dışı bırakılmaz**.

Tarayıcı testleri `tests/fixtures/hls/` içindeki küçük, sentetik H.264/AAC test görüntülerini kullanır; gerçek maç kaydı veya üretim skorları değildir. Harici CDN/stream bağımlılığı yoktur. Safari/iOS native yolu jsdom'da sınanmıştır; gerçek iPhone cihaz testi ve canlı Atom uçtan uca doğrulaması ayrıca gereklidir.
