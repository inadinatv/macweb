# Macweb özel iframe kanalları — Firebase kurulumu

Macweb, oynatıcının altındaki **EK YAYIN KANALLARI** şeridinde en fazla beş özel yayın düğmesi gösterir. Yönetici paneli kanal adını ve HTTPS iframe adresini `/macweb/customChannels` yoluna yazar; ziyaretçiler değişiklikleri canlı alır.

## Güvenli parola-only yönetici girişi

Panel yalnızca parola sorar; e-posta hesabı kullanılmaz. Parola tarayıcıda doğrulanmaz ve sayfa kodunda tutulmaz. HTTPS callable Cloud Function parolayı Secret Manager’daki değerle karşılaştırır, başarılı olursa sabit `macweb-admin` UID’si ve `admin: true` claim’i için Firebase custom token verir. Realtime Database yazma izni yalnızca bu kimlik ve claim’e tanınır. Callable function App Check zorunluluğuyla çalışır. Web oturumu yalnızca geçerli browser oturumu boyunca saklanır; yönetici paneli kapatılırken çıkış yapılır.

**Önemli:** Parolayı daha önce sohbet üzerinden paylaştığınız için onu yeniden kullanmayın; yeni, benzersiz ve rastgele üretilmiş en az 16 karakterli bir parola belirleyin. Parolayı chat’e veya GitHub’a yazmayın. Secret Manager’a yalnızca Firebase CLI’nin etkileşimli isteminde girin.

Yanlış parola için IP başına en fazla 5 deneme / 15 dakika uygulanır. Bu sınırlayıcı Cloud Function örneğinin belleğindedir ve yeniden başlatmada sıfırlanabilir; kalıcı dağıtık bir kötüye kullanım önleme sistemi değildir. App Check ve güçlü benzersiz parola zorunludur.

## İlk kurulum

1. Firebase Console’da botun kullandığı Firebase projesini açın ve **Authentication** hizmetinin etkin olduğundan emin olun. E-posta/şifre sağlayıcısı veya yönetici kullanıcı hesabı oluşturmanız gerekmez. **App Check** bölümünde Macweb Web uygulamasını reCAPTCHA v3 ile kaydedin. reCAPTCHA’nın **site key** değerini `config/macweb_firebase.json` dosyasındaki `appCheckSiteKey` alanına yazın. reCAPTCHA **secret key** yalnızca Firebase Console’da kalmalı; bu depoya eklenmemelidir. Pages alan adınız reCAPTCHA’da izin verilen domain’ler arasında olmalıdır.
2. Repo kökünden `firebase functions:secrets:set MACWEB_ADMIN_PASSWORD` çalıştırın ve yeni parolayı CLI’nin gizli istemine girin. Komut satırına parola eklemeyin. Secret ilk kez oluşturuluyorsa veya değiştirildiyse fonksiyonu yeniden deploy edin.
3. Firebase Realtime Database → **Rules** bölümünde, mevcut kurallarınızı koruyarak `config/firebase-custom-channels.rules.json` içindeki `macweb` düğümünü mevcut `rules` nesnesine ekleyin ve yayımlayın. Bu dosya tek başına mevcut bütün kuralların yerine geçmez. Kök veya üst seviyelerdeki herkese açık `.write` izinlerini kaldırın; RTDB kuralları yukarıdan aşağıya kümülatiftir.
4. Firebase CLI’nin kurulu ve doğru Firebase hesabıyla giriş yapılmış olduğundan; seçili projenin de botun kullandığı doğru proje olduğundan emin olun. Cloud Functions için gerekli servisler ve billing plan etkin olmalıdır. Ardından repo kökünde `npm --prefix functions install` ve `firebase deploy --only functions:macwebAdminLogin` çalıştırın. Firebase CLI, `.firebaserc` içindeki bot projesini varsayılan proje olarak seçer.
   Custom token imzalama izni yoksa, Function’ın çalışma zamanı service account’una kendi proje service account’u için `Service Account Token Creator` (`iam.serviceAccounts.signBlob`) rolü verin. İndirilebilir service-account JSON anahtarı oluşturup depoya eklemeyin.
5. `config/macweb_firebase.json` içindeki herkese açık site key’i ekledikten sonra Macweb statik sayfasını yeniden üretin (`python fixbet.py build-index`) ve GitHub Pages’e yayımlayın. Paneldeki **⚙ Yönetici** düğmesine dokunup yeni parolayla giriş yapın.

Cloud Function’lar deploy edilmeden, `MACWEB_ADMIN_PASSWORD` Secret Manager’da ayarlanmadan ve doğru App Check site key yayımlanmadan parola girişinin çalışması beklenmemelidir. Bu kurulum adımları tamamlanana kadar panel yayın listesi için yalnızca okuyucu olarak kalır.

## Kanal ekleme ve güvenlik sınırları

Yönetici beş yuvaya kadar kanal adıyla birlikte doğrudan HTTPS adresi veya tek bir `<iframe src="…"></iframe>` kodu girebilir. Ham HTML sayfaya eklenmez; yalnızca tek bir HTTPS iframe adresi ayıklanır. HTTP, `javascript:`, script ve birden fazla iframe kabul edilmez. Özel yayınlar kısıtlı iframe sandbox’ında açılır. Kaynağın kendi gömme engeli aşılmaz.

Web API key ve reCAPTCHA site key istemci tarafında kullanılan herkese açık yapılandırma değerleridir. reCAPTCHA secret key, yönetici parolası ve service-account anahtarı istemciye veya depoya konulmaz. Function yalnızca parola doğrular ve custom token üretir; kanal verisini yazan istemciyi RTDB Security Rules sınırlar. Mevcut bot verilerinin diğer yollarına dokunulmaz.

## Kaynaklar

- [Firebase App Check — reCAPTCHA v3 for web](https://firebase.google.com/docs/app-check/web/recaptcha-provider)
- [App Check enforcement for Cloud Functions](https://firebase.google.com/docs/app-check/cloud-functions)
- [Callable Cloud Functions](https://firebase.google.com/docs/functions/callable)
- [Firebase Admin SDK custom tokens](https://firebase.google.com/docs/auth/admin/create-custom-tokens)
- [Web sign-in with a custom token](https://firebase.google.com/docs/auth/web/custom-auth)
- [Cloud Functions secrets](https://firebase.google.com/docs/functions/config-env)
- [Cloud Functions quotas and Blaze plan requirement](https://firebase.google.com/docs/functions/quotas)
- [Custom token signing permissions](https://firebase.google.com/docs/auth/admin/create-custom-tokens)
- [Realtime Database Security Rules](https://firebase.google.com/docs/database/security)
- [Firebase API keys](https://firebase.google.com/docs/projects/api-keys)
