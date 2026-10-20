# Macweb özel kanal botu — Pydroid 3 kurulumu

Macweb’deki **EK YAYIN KANALLARI** şeridi `output/custom_channels.json` dosyasını okur. Bu manifesti telefonda çalışan Telegram botu günceller; tarayıcıda yönetici girişi, Firebase Auth veya App Check yoktur. Bot en fazla beş kanala izin verir ve iframe HTML’sini çalıştırmaz; yalnızca tek bir iframe’in HTTPS `src` adresini saklar.

## Güvenlik uyarısı

Önceden paylaşılan bot örneği dosyasında etkin kimlik bilgileri bulunuyorsa o Telegram bot tokenını tekrar kullanmayın. **BotFather’da eski tokenı `/revoke` ile iptal edin ve yeni token üretin.** Önceki dosyada bir Google API anahtarı da varsa onu da Google Cloud Console’da iptal edin veya değiştirip kullanımını sınırlandırın. Tokenları bu depoya, sohbete ya da ekran görüntüsüne koymayın. Bu bot Google API anahtarı kullanmaz.

Manifest GitHub Pages üzerinden herkese açık olacağından kanal adları ve iframe adresleri de herkese açık olacaktır. Yalnızca yayımlama/gömme izniniz olan, gizli erişim tokenı ya da özel hesap bilgisi içermeyen HTTPS adresleri ekleyin. Bot `token`, `auth`, `key`, `password`, `secret`, `signature` gibi hassas query parametrelerini reddeder.

## 1. Telegram botunu hazırlayın

1. Telegram’da **@BotFather** üzerinden yeni bir bot oluşturun veya eski tokenı iptal ettikten sonra yeni token alın.
2. Kendi sayısal Telegram kullanıcı ID’nizi **@userinfobot** gibi bir ID botundan öğrenin. Kullanıcı adınız (`burhan_baba_72`) yerine bu sayısal ID kullanılmalıdır; kullanıcı adı değişebilir.
3. Botu Pydroid’de çalıştırdığınız Telegram hesabıyla `/start` üzerinden açın. Bot yalnızca yapılandırmadaki tek kullanıcı ID’sinden ve özel sohbetten gelen işlemleri kabul eder.

## 2. GitHub için dar yetkili token üretin

GitHub’da **Fine-grained personal access token** oluşturun:

- Repository owner: `inadinatv`
- Repository access: yalnızca `macweb`
- Repository permissions: **Contents — Read and write**
- Başka depo, yönetim, workflow veya hesap izni vermeyin.

Tokenı yalnızca telefondaki yerel ayar dosyasına girin. Bu token, botun `main` dalındaki yalnızca `output/custom_channels.json` dosyasına commit gönderebilmesini sağlar.

## 3. Pydroid 3 dosyalarını hazırlayın

1. Bu repodan `tools/pydroid_channel_sync_bot.py` ve `tools/pydroid_channel_sync_config.example.json` dosyalarını telefona indirin; aynı klasöre koyun.
2. Örnek JSON’un bir kopyasını aynı klasörde `pydroid_channel_sync_config.json` adıyla oluşturun.
3. Yeni BotFather tokenını `telegram_bot_token`, dar yetkili GitHub tokenını `github_token`, sayısal Telegram ID’nizi `admin_telegram_user_id` alanlarına yerel kopyada girin. Örnek dosyayı düzenlemeyin ve gizli ayar dosyasını paylaşmayın.
4. Pydroid 3’te bot dosyasını çalıştırın. Ek Python paketi gerekmez. Beklenen başlangıç mesajı: `Macweb kanal botu çalışıyor. Durdurmak için Ctrl+C kullanın.`

## 4. Kullanım

Botta `/start` yazınca kanal yönetim menüsü açılır. **Kanal ekle** akışında önce kanal adı, ardından doğrudan bir HTTPS adresi veya tek bir `<iframe src="https://…"></iframe>` kodu gönderilir. **Kanalı değiştir** ve **Kanal sil** düğmeleri kayıtlı yuvaları listeler. `/channels` mevcut kanal adlarını gösterir; `/cancel` o anki ekleme/değiştirme işlemini iptal eder. Beş kanal dolduğunda önce bir kanalı değiştirin ya da silin.

Bot ham iframe HTML’si, script veya başka etiket saklamaz. Yalnızca onaylanmış HTTPS URL’si `channel1`–`channel5` alanlarından birine yazılır. Bir kayıt başarılı olduğunda GitHub API’si commit atar; GitHub Pages’in yeni sürümü dağıtması birkaç dakika sürebilir. Açık Macweb sayfası manifesti yaklaşık dakikada bir kontrol eder; sekmeye dönünce ve bağlantı yeniden gelince de yeniler.

## Pydroid/Android çalışma durumu

Pydroid yalnızca uygulama sistem tarafından uyutulmadığı sürece botu dinler; bu 7/24 hizmet taahhüdü değildir. Daha uzun süre açık kalması için Android ayarlarında Pydroid pil kullanımını **Kısıtlanmamış/Sınırsız** yapın, arka plan kısıtlamasını kapatın, telefonu internete ve tercihen şarja bağlı tutun, Pydroid’i son uygulamalar ekranında kilitleyin. Bot kapalıyken Telegram’daki ekleme/değiştirme işlemleri çalışmaz.

## Sorun giderme

- **Ayar dosyası yok/JSON hatalı:** `pydroid_channel_sync_config.json` bot dosyasıyla aynı klasörde olmalı ve geçerli JSON olmalı.
- **GitHub kaydı reddedildi:** tokenın yalnızca `inadinatv/macweb` için `Contents: Read and write` yetkisi olduğunu kontrol edin; süresi dolduysa tokenı yenileyin.
- **Telegram `getUpdates` çakışması:** Aynı botu aynı anda başka bir polling sürecinde çalıştırmayın. Webhook kullanan eski bir botu yeniden kullanmak yerine yeni bir BotFather botu tercih edin.
- **Kanal uygulamada görünmüyor:** manifestin `main` dalında güncellendiğini, GitHub Pages dağıtımının tamamlandığını ve iframe kaynağının gerçekten gömülmeye izin verdiğini kontrol edin.
