# Macweb özel iframe kanalları — Firebase kurulumu

Macweb, oynatıcı altındaki **EK YAYIN KANALLARI** şeridinde en fazla beş özel yayın düğmesi gösterebilir. Yönetici paneli ad ve iframe girdisini Firebase Realtime Database’de `/macweb/customChannels` yoluna kaydeder; ziyaretçilerde açık olan sayfalar Firebase’in canlı `value` dinleyicisiyle güncellenir.

## İlk kullanım

1. Firebase Console’da mevcut botun kullandığı Firebase projesini açın. **Authentication → Sign-in method** bölümünde **Email/Password** sağlayıcısını etkinleştirin ve **Users** bölümünden yalnızca yönetici olarak kullanılacak bir hesap oluşturun. Kullanıcı kaydı uygulamada açık değildir.
2. O hesabın Firebase **UID** değerini bulun.
3. **Realtime Database → Rules** alanında mevcut kuralları koruyarak `config/firebase-custom-channels.rules.json` içindeki `macweb` düğümünü mevcut `rules` nesnesinin içine ekleyin. `REPLACE_WITH_ADMIN_UID` metnini yöneticinin gerçek UID’siyle değiştirip kuralları yayımlayın. Bu dosya tüm mevcut kuralların yerine geçecek tam bir rules dosyası değildir.
4. Mevcut kurallarda kök seviyede veya daha üstte herkese `".write": true` izni varsa kaldırın. Realtime Database kuralları yukarıdan aşağıya kümülatiftir; geniş bir üst düğüm izni alt düğümdeki kısıtlamayı etkisiz bırakabilir.
5. Macweb’i açıp player altındaki **⚙ Yönetici** düğmesine dokunun. Yönetici e-postası ve parolasıyla giriş yapın. Beş yuvaya kadar kanal adıyla birlikte doğrudan HTTPS adresi veya tek bir `<iframe src="…"></iframe>` kodu ekleyip **5 kanalı kaydet** deyin.

İstemci, iframe kodunu HTML olarak çalıştırmaz. Koddan yalnızca tek bir HTTPS `src` adresi ayıklanır; `http`, `javascript:`, script ve birden fazla iframe kabul edilmez. Özel yayınlar player içinde kısıtlı `sandbox` ile açılır; bu nedenle bazı siteler kendi güvenlik başlıkları nedeniyle iframe’de görüntülenmeyebilir. Kaynağın gömülmeye izin vermeyen politikasını atlatmaya çalışılmaz.

## Güvenlik ve veri kapsamı

Firebase Web API key’i istemci uygulamasını projeye tanıtan herkese açık yapılandırmadır; yönetici yetkisi değildir. Yetkiyi Firebase Authentication oturumu ve Realtime Database Security Rules verir. Uygulamaya bot tokenı, admin parolası veya service-account anahtarı konulmaz. Yönetici parolası yalnızca Firebase Auth giriş formuna yazılır ve girişten sonra alan temizlenir.

Bu özellik yalnızca `/macweb/customChannels` düğümünü okur/yazar; botun mevcut `extras`, `online_users`, `reports` ve diğer verilerine dokunmaz. Doğrulama testleri Firebase’i taklit eder, canlı veritabanına yazma yapmaz.

## Kaynaklar

- [Firebase web password authentication](https://firebase.google.com/docs/auth/web/password-auth)
- [Realtime Database web read/write](https://firebase.google.com/docs/database/web/read-and-write)
- [Realtime Database Security Rules](https://firebase.google.com/docs/database/security)
- [Firebase API keys](https://firebase.google.com/docs/projects/api-keys)
