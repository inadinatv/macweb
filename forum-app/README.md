# MACWEB Forum

App Crypto 24 içine WebView, iframe veya doğrudan bağlantı olarak eklenebilecek topluluk forumu arayüzü.

## Mevcut özellikler

- Karanlık, neon-vurgulu responsive forum arayüzü
- Kanal filtreleri, konu arama ve popülerlik sıralaması
- Yeni konu oluşturma modalı
- Konu detay modalı, beğeni ve kaydetme etkileşimleri
- Profil ve rozet koleksiyonu ekranı
- Moderasyon kuyruğu, topluluk istatistikleri ve hızlı admin işlemleri görünümü
- Recharts tabanlı aktivite trendi, kanal etkileşimi, kullanıcı dağılımı ve en aktif üyeler grafik/dashboards
- Dönem, grafik metriği, kanal, kullanıcı durumu ve üye araması için gelişmiş admin filtreleri
- Mobil alt navigasyon ve Vercel SPA rewrite ayarı

## Vercel yayınlama

Vercel projesi oluştururken **Root Directory** olarak `forum-app` klasörünü seçin. Framework otomatik olarak Vite algılanır; build komutu `npm run build`, çıktı klasörü `dist` olarak kalabilir.

## Üretim için sonraki adım

Bu sürüm etkileşimli frontend prototipidir ve hızlı tasarım/UX doğrulaması için örnek veriler kullanır. Gerçek kullanıcı hesabı, kalıcı konu/yanıt verisi, canlı bildirimler, dosya yükleme ve rol bazlı admin yetkisi için `web-db-user` backend'ini veya Vercel uyumlu bir API + Postgres/Neon/Supabase katmanını bağlayın. İstemci tarafına gizli anahtar koymayın.
