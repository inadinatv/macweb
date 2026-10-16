/**
 * İNADİNA TV index.html arayüz testleri (jsdom).
 *
 * Bu testler üretilen index.html'in *gerçek* JavaScript'ini çalıştırır:
 * kanal kartları, ızgara/liste görünümü, player'e kaydırma, günün maçları,
 * arama/filtre ve canlı veri tazeleme.
 *
 *   npm install && npm test
 */
import test, { afterEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { JSDOM, VirtualConsole } from "jsdom";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const HTML = readFileSync(path.join(ROOT, "index.html"), "utf8");
const TODAY = JSON.parse(readFileSync(path.join(ROOT, "output", "today_matches.json"), "utf8"));
const EXTRA = JSON.parse(readFileSync(path.join(ROOT, "output", "extra_channels.json"), "utf8"));
const EXTRA_COUNT = EXTRA.panels.reduce((n, p) => n + p.channels.length, 0);

const openPages = new Set();
afterEach(() => { for (const dom of openPages) dom.window.close(); openPages.clear(); });

async function loadPage(options = {}) {
  const errors = [];
  const virtualConsole = new VirtualConsole();
  virtualConsole.on("jsdomError", (e) => errors.push(String(e && e.message)));
  const dom = new JSDOM(options.html || HTML, {
    runScripts: "dangerously",
    pretendToBeVisual: true,
    url: "https://inadinatv.github.io/macweb/",
    virtualConsole,
    beforeParse(window) {
      window.scrolledTo = [];
      // iframe src ataması jsdom'da dış ağ isteği başlatıyor; testi çevrimdışı ve
      // deterministik tutmak için src'i düz bir öznitelik gibi davranmaya zorluyoruz.
      Object.defineProperty(window.HTMLIFrameElement.prototype, "src", {
        configurable: true,
        get() { return this.getAttribute("src") || ""; },
        set(value) { this.setAttribute("src", String(value)); },
      });
      // jsdom scrollIntoView sağlamaz; sayfanın kaydırma çağrısını kaydediyoruz
      window.Element.prototype.scrollIntoView = function () {
        window.scrolledTo.push(this.id || this.className || "?");
      };
      // <video>: jsdom medya yüklemez; çağrıları kaydet, play() Promise döndürsün
      window.HTMLMediaElement.prototype.load = function () { window.videoLoads = (window.videoLoads || 0) + 1; };
      window.HTMLMediaElement.prototype.play = function () { window.videoPlays = (window.videoPlays || 0) + 1; return Promise.resolve(); };
      window.HTMLMediaElement.prototype.pause = function () {};
      // Safari gibi yerel HLS desteği (options.nativeHls) ya da hls.js yolu
      window.HTMLMediaElement.prototype.canPlayType = function (t) {
        return options.nativeHls && /mpegurl/i.test(t) ? "maybe" : "";
      };
      // hls.js CDN'i jsdom içinde yüklenmez: sahte bir Hls sınıfı sağlanır
      window.hlsLog = [];
      if (options.hls !== "none") {
        window.Hls = class FakeHls {
          static isSupported() { return options.hls !== "unsupported"; }
          constructor(config) { this.config = config; this.handlers = {}; window.hlsInstances = (window.hlsInstances || []).concat(this); }
          on(evt, fn) { this.handlers[evt] = fn; }
          loadSource(url) { window.hlsLog.push("load:" + url); this.url = url; }
          attachMedia(video) {
            this.video = video;
            const behavior = (options.behavior && options.behavior(this.url)) || "ok";
            setTimeout(() => {
              if (behavior === "pending") return;
              if (behavior === "ok" || behavior === "manifest-only") {
                this.handlers[FakeHls.Events.MANIFEST_PARSED]?.("manifest", { levels: [{ width: 1920, height: 1080, videoCodec: "avc1.640028", audioCodec: "mp4a.40.2" }] });
                if (behavior === "ok") video.dispatchEvent(new window.Event("playing"));
              }
              else this.handlers[FakeHls.Events.ERROR] && this.handlers[FakeHls.Events.ERROR]("hlsError",
                { fatal: true, type: FakeHls.ErrorTypes.NETWORK_ERROR, details: FakeHls.ErrorDetails.MANIFEST_LOAD_ERROR });
            }, 5);
          }
          destroy() { window.hlsLog.push("destroy:" + this.url); }
          startLoad() { window.hlsLog.push("startLoad"); }
          recoverMediaError() { window.hlsLog.push("recoverMediaError"); }
        };
        window.Hls.Events = { MANIFEST_PARSED: "hlsManifestParsed", ERROR: "hlsError", LEVEL_LOADED: "levelLoaded", BUFFER_CODECS: "bufferCodecs" };
        window.Hls.ErrorTypes = { NETWORK_ERROR: "networkError", MEDIA_ERROR: "mediaError" };
        window.Hls.ErrorDetails = { MANIFEST_LOAD_ERROR: "manifestLoadError", MANIFEST_LOAD_TIMEOUT: "manifestLoadTimeOut", MANIFEST_PARSING_ERROR: "manifestParsingError" };
      }
      if (options.fetchImpl) window.fetch = options.fetchImpl;
      if (options.beforeParse) options.beforeParse(window);
    },
  });
  openPages.add(dom);
  const window = dom.window;
  // init() DOMContentLoaded'da çalışır; bitince window.inadina.ready = true olur
  for (let i = 0; i < 200 && !(window.inadina && window.inadina.ready); i++) {
    await new Promise((r) => setTimeout(r, 10));
  }
  assert.ok(window.inadina && window.inadina.ready, "sayfa script'i çalışmadı (window.inadina hazır değil) — hatalar: " + errors.join("; "));
  return { dom, window, errors };
}

const cards = (window) => window.document.querySelectorAll("#channelGrid .ch-card");
const extraCards = (window) => window.document.querySelectorAll("#extraGrid .ch-card");
const matchCards = (window) => window.document.querySelectorAll(".match-card");
const tick = (ms = 30) => new Promise((r) => setTimeout(r, ms));

test("sayfada sunucu/adres yazısı ve uydurma maç verisi yok", () => {
  assert.ok(!/Sunucu/i.test(HTML), "'Sunucu' yazısı hâlâ duruyor");
  assert.ok(!HTML.includes("Galatasaray - Fenerbahçe"), "uydurma canlı maç duruyor");
  assert.ok(!HTML.includes("Golden State Warriors"), "uydurma NBA maçı duruyor");
  assert.ok(!HTML.includes("Carlos Alcaraz"), "uydurma tenis maçı duruyor");
  assert.ok(HTML.includes("channel.html?id=zirve"), "gerçek kanal bağlantısı yok");
  // sekmeler: ana kanallar + Kodaman kanalları + günün maçları + extra
  assert.equal((HTML.match(/class="tab-btn/g) || []).length, 4, "dört sekme olmalı");
  assert.ok(!/CANLI MAÇLAR/.test(HTML), "sahte canlı maç sekmesi duruyor");
  assert.ok(HTML.includes('data-tab="kodamanTab"'), "TV KANALLARI 2 sekmesi yok");
  assert.ok(HTML.includes('data-tab="extraTab"'), "EXTRA sekmesi yok");
});

test("kanal kartları küçük ızgarada render ediliyor", async () => {
  const { window, dom, errors } = await loadPage();
  assert.deepEqual(errors, [], "sayfa hatası: " + errors.join("; "));
  assert.equal(cards(window).length, 31, "31 kanal kartı bekleniyor");
  // kart boyutları küçültüldü
  assert.ok(HTML.includes("minmax(104px"), "ızgara kartları küçültülmemiş");
  assert.ok(HTML.includes("min-height: 84px"), "kart yüksekliği küçültülmemiş");
  assert.ok(HTML.includes(".channel-grid.view-list"), "liste görünüm CSS'i yok");
  dom.window.close();
});

test("kanal kartına tıklayınca yayın açılıyor ve player'e kayıyor", async () => {
  const { window, dom } = await loadPage();
  const card = cards(window)[2];
  assert.ok(card, "3. kanal kartı yok");
  window.scrolledTo.length = 0;
  card.click();

  const iframe = window.document.getElementById("liveIframe");
  assert.ok(iframe.src.includes("channel.html?id=b3"), "yanlış yayın yüklendi: " + iframe.src);
  assert.deepEqual(window.scrolledTo, ["playerContainer"], "player'e kaydırma yapılmadı");
  assert.equal(window.document.getElementById("nowChannel").textContent, "BEIN SPORTS 3");
  assert.equal(window.document.getElementById("playerTitle").textContent, "BEIN SPORTS 3");
  assert.ok(card.classList.contains("active"), "seçili kart işaretlenmedi");
  dom.window.close();
});

test("TV KANALLARI 2 public manifest’ten ID’leri yükler ve teyitli player hatasını kapatır", async () => {
  const feed = {
    base_url: "https://kodamantv21.com",
    updated_at: "2026-10-16T19:00:00Z",
    channels: [
      { id: "alpha-1", name: "Alpha TV", status: "page" },
      { id: "zirve", name: "Zirve Stream", status: "error" },
      { id: "bad/id", name: "Güvensiz ID", status: "page" },
    ],
  };
  const fetchImpl = async (url) => {
    if (String(url).includes("/output/kodaman_channels.json")) return { ok: true, status: 200, json: async () => feed };
    if (String(url).startsWith("https://data-reality.com/matches.php")) return { ok: true, status: 200, text: async () => "" };
    if (String(url).startsWith("https://data-reality.com/matches2.php")) return { ok: true, status: 200, text: async () => "" };
    return { ok: true, status: 200, json: async () => TODAY, text: async () => "" };
  };
  const { window, dom } = await loadPage({ fetchImpl });
  await tick(30);
  const button = window.document.querySelector('.tab-btn[data-tab="kodamanTab"]');
  assert.ok(button, "TV KANALLARI 2 düğmesi yok");
  button.click();
  assert.equal(window.inadina.state.activeTab, "kodamanTab");
  assert.ok(window.document.getElementById("kodamanTab").classList.contains("active"));
  assert.equal(window.inadina.state.kodamanChannels.length, 2, "geçersiz ID filtrelenmeli");
  assert.match(window.document.getElementById("kodamanMeta").textContent, /2 ID/);
  assert.equal(window.document.getElementById("kodamanExternal").href, "https://kodamantv21.com/");
  const playable = window.document.querySelector('#kodamanGrid [data-kodaman-id="alpha-1"]');
  const unavailable = window.document.querySelector('#kodamanGrid [data-kodaman-id="zirve"]');
  assert.ok(playable, "public player kartı çizilmedi");
  assert.equal(unavailable.disabled, true, "son kontrolde hata veren player açılabilir olmamalı");
  playable.click();
  assert.equal(window.document.getElementById("liveIframe").getAttribute("src"), "https://kodamantv21.com/channel?id=alpha-1");
  assert.equal(window.document.getElementById("playerTitle").textContent, "Alpha TV");
  window.document.dispatchEvent(new window.KeyboardEvent("keydown", { key: "2", bubbles: true }));
  assert.equal(window.inadina.state.activeTab, "kodamanTab", "2 kısayolu ikinci sekmeyi açmalı");
  dom.window.close();
});

test("kırık VIP akışı kaldırıldı; uygulama Trend48’i açmadan normal kanalları oynatır", async () => {
  const { window, dom } = await loadPage();
  const iframe = window.document.getElementById("liveIframe");
  assert.equal(window.document.getElementById("vipStreamBtn"), null, "VIP düğmesi kaldırılmalı");
  assert.equal(window.document.getElementById("vipBrandOverlay"), null, "VIP oynatıcıda logo kaplaması olmamalı");
  assert.equal(iframe.getAttribute("src"), "", "uygulama açılışında kırık Trend48 akışı yüklenmemeli");
  assert.equal(window.document.body.textContent.includes("Trend48"), false, "kırık VIP kaynağı arayüzden kaldırılmalı");

  cards(window)[0].click();
  assert.match(iframe.getAttribute("src"), /channel\.html\?id=/, "normal kanal seçimi çalışmaya devam etmeli");
  dom.window.close();
});

test("canlı skor polling aralığı Fixtoor gibi canlı/yakın/boşta/hata durumuna uyuyor", async () => {
  const { window, dom } = await loadPage();
  const interval = window.inadina.syncIntervalForState;
  assert.equal(interval(true, true, 0, false), 5000, "canlı maç 5 sn'de bir yoklanmalı");
  assert.equal(interval(false, true, 0, false), 15000, "yakın maç 15 sn'de bir yoklanmalı");
  assert.equal(interval(false, false, 0, false), 60000, "boşta 60 sn beklenmeli");
  assert.equal(interval(false, true, 3, false), 120000, "3 hatadan sonra 120 sn beklenmeli");
  assert.equal(interval(true, true, 0, true), 60000, "arka plan sekmesinde istek sıklığı düşmeli");
  dom.window.close();
});

test("ızgara / yatay liste görünümü değiştirilebiliyor", async () => {
  const { window, dom } = await loadPage();
  const grid = window.document.getElementById("channelGrid");
  assert.equal(grid.classList.contains("view-list"), false);

  window.inadina.setView("list");
  assert.equal(grid.classList.contains("view-list"), true, "liste görünümü uygulanmadı");
  assert.equal(window.localStorage.getItem("inadinatv.view"), "list", "görünüm kaydedilmedi");
  const activeBtn = window.document.querySelector('.view-btn[data-view="list"]');
  assert.ok(activeBtn.classList.contains("active"), "liste butonu aktif olmadı");

  // liste görünümünde de kartlar tıklanabilir kalıyor
  cards(window)[0].click();
  assert.ok(window.document.getElementById("liveIframe").src.includes("channel.html?id="), "liste kartı çalışmıyor");

  window.inadina.setView("grid");
  assert.equal(grid.classList.contains("view-list"), false, "ızgaraya geri dönülemedi");
  dom.window.close();
});

test("günün maçları gerçek programdan geliyor", async () => {
  const { window, dom } = await loadPage();
  window.inadina.setTab("matchesTab");
  const list = matchCards(window);
  assert.equal(list.length, TODAY.matches.length, "maç sayısı gerçek veriyle uyuşmuyor");

  const text = window.document.getElementById("matchesGrid").textContent;
  for (const m of TODAY.matches) assert.ok(text.includes(m.home) && text.includes(m.away), "gerçek maç eksik: " + m.home);
  const modCount = window.inadina.decoratedMatches(new Date()).filter((m) => m._isFeatured).length;
  assert.equal(window.document.querySelectorAll(".match-card.is-mod").length, modCount,
    "yalnızca bugünkü Günün Maçı spotlight olarak işaretlenmeli");
  if (modCount) assert.ok(text.includes("⭐ Günün Maçı"), "günün maçı rozeti yok");
  assert.equal(window.document.getElementById("badgeMatches").textContent, String(TODAY.matches.length));
  dom.window.close();
});

test("bugünün Günün Maçı tam genişlikte gösterilir ve diğer maçların önüne sabitlenir", async () => {
  const feed = `<!doctype html>
    <a href="channel?id=normal"><div class="match-detail"><div class="date">Futbol</div>
      <div class="event">12:00 | Test Ligi</div><div class="teams"><div class="home">Normal Ev</div>
      <div class="away">Normal Deplasman</div></div></div></a>
    <a href="channel?id=featured"><div class="match-detail"><div class="date">Futbol</div>
      <div class="event">23:00 | Test Ligi [Günün Maçı]</div><div class="teams"><div class="home">Öne Çıkan Ev</div>
      <div class="away">Öne Çıkan Deplasman</div></div></div></a>`;
  const fetchImpl = async (url) => {
    if (String(url).startsWith("https://data-reality.com/matches.php")) return { ok: true, status: 200, text: async () => feed };
    if (String(url).startsWith("https://data-reality.com/matches2.php")) return { ok: true, status: 200, text: async () => "" };
    return { ok: true, status: 200, json: async () => TODAY };
  };
  const { window, dom } = await loadPage({ fetchImpl });
  assert.equal(await window.inadina.refreshMatches(true), true);
  assert.equal(window.inadina.state.activeTab, "channelsTab", "uygulama ilk açılışta ana sekmede kalmalı");
  const homeFeatured = window.document.querySelector("#homeFeaturedSection .home-featured-match");
  assert.ok(homeFeatured, "maç sekmesine girmeden ana spotlight görünmeli");
  assert.equal(homeFeatured.getAttribute("data-selection"), "official", "kaynağın bugünkü Günün Maçı seçimi ana ekranda öne alınmalı");
  assert.ok(homeFeatured.textContent.includes("Öne Çıkan Ev"), "ana spotlight resmi seçilen maçı göstermiyor");
  assert.doesNotMatch(homeFeatured.textContent, /Fixbet|kaynak/i, "Günün Maçı kartında yayın/veri kaynağı belirtilmemeli");
  const featuredMeta = window.document.getElementById("homeFeaturedMeta");
  assert.ok(featuredMeta.querySelector(".home-featured-time").textContent.includes("23:00"), "spor simgesi yanında maç saati görünmeli");
  assert.ok(featuredMeta.querySelector(".home-featured-status").textContent, "maçın kalan süre/durum bilgisi başlıkta görünmeli");
  assert.ok(!featuredMeta.querySelector(".home-featured-status").textContent.includes("23:00"), "maç saati durum rozetinde yinelenmemeli");
  window.inadina.setTab("matchesTab");
  const list = [...matchCards(window)];
  assert.equal(list.length, 2, "test programındaki iki maç gösterilmeli");
  assert.ok(list[0].textContent.includes("Öne Çıkan Ev"), "Günün Maçı ilk sırada değil");
  assert.ok(list[0].classList.contains("is-mod"), "Günün Maçı spotlight sınıfı almadı");
  assert.ok(HTML.includes("grid-column: 1 / -1"), "spotlight kartı tüm maç sütunlarını kaplamıyor");
  assert.ok(list[0].textContent.includes("⭐ Günün Maçı"), "Günün Maçı etiketi eksik");
  assert.equal(list[1].classList.contains("is-mod"), false, "normal maç spotlight olmamalı");
  dom.window.close();
});

test("Günün Maçı kartındaki Fikstür düğmesi arama/filtreleri sıfırlayıp günlük maçlara götürüyor", async () => {
  const feed = `<!doctype html>
    <a href="channel?id=normal"><div class="match-detail"><div class="date">Futbol</div>
      <div class="event">12:00 | Test Ligi</div><div class="teams"><div class="home">Normal Ev</div>
      <div class="away">Normal Deplasman</div></div></div></a>
    <a href="channel?id=featured"><div class="match-detail"><div class="date">Futbol</div>
      <div class="event">23:00 | Test Ligi [Günün Maçı]</div><div class="teams"><div class="home">Öne Çıkan Ev</div>
      <div class="away">Öne Çıkan Deplasman</div></div></div></a>`;
  const fetchImpl = async (url) => {
    if (String(url).startsWith("https://data-reality.com/matches.php")) return { ok: true, status: 200, text: async () => feed };
    if (String(url).startsWith("https://data-reality.com/matches2.php")) return { ok: true, status: 200, text: async () => "" };
    return { ok: true, status: 200, json: async () => TODAY };
  };
  const { window, dom } = await loadPage({ fetchImpl });
  await window.inadina.refreshMatches(true);
  window.inadina.setTab("matchesTab");
  const featuredFilter = [...window.document.querySelectorAll("#matchFilterRow .chip")]
    .find((button) => button.textContent.includes("Günün Maçı"));
  featuredFilter.click();
  const search = window.document.getElementById("searchInput");
  search.value = "Öne Çıkan Ev";
  search.dispatchEvent(new window.Event("input", { bubbles: true }));
  assert.equal(matchCards(window).length, 1);

  window.scrolledTo.length = 0;
  const fixtureButton = matchCards(window)[0].querySelector(".fixture-match-btn");
  assert.ok(fixtureButton, "featured kartında FİKSTÜR düğmesi olmalı");
  fixtureButton.click();
  assert.equal(window.inadina.state.activeTab, "matchesTab");
  assert.equal(window.inadina.state.activeStatus, "all", "durum filtresi sıfırlanmalı");
  assert.equal(window.inadina.state.activeSport, "all", "spor filtresi sıfırlanmalı");
  assert.equal(search.value, "", "arama temizlenmeli");
  assert.equal(matchCards(window).length, 2, "günlük fikstürdeki tüm maçlar görünmeli");
  assert.ok(window.scrolledTo.includes("matchFilterRow"), "fikstür filtresine kaydırılmalı");
  dom.window.close();
});

test("Günün Maçı ana ekranda açılışta görünür; kaynak seçimi yoksa bugünün sıradaki maçı önerilir", async () => {
  const fixedNow = Date.parse("2026-10-14T12:00:00+03:00");
  const upcomingTime = (offsetHours) => {
    const date = new Date(fixedNow + offsetHours * 60 * 60 * 1000);
    const parts = new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/Istanbul", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(date);
    const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
    return values.hour + ":" + values.minute;
  };
  const firstTime = upcomingTime(2), secondTime = upcomingTime(4);
  const feed = `<!doctype html>
    <a href="channel?id=first"><div class="match-detail"><div class="date">Futbol</div>
      <div class="event">${firstTime} | İlk Lig</div><div class="teams"><div class="home">İlk Ev</div>
      <div class="away">İlk Deplasman</div></div></div></a>
    <a href="channel?id=second"><div class="match-detail"><div class="date">Futbol</div>
      <div class="event">${secondTime} | İkinci Lig</div><div class="teams"><div class="home">İkinci Ev</div>
      <div class="away">İkinci Deplasman</div></div></div></a>`;
  const fetchImpl = async (url) => {
    if (String(url).startsWith("https://data-reality.com/matches.php")) return { ok: true, status: 200, text: async () => feed };
    if (String(url).startsWith("https://data-reality.com/matches2.php")) return { ok: true, status: 200, text: async () => "" };
    return { ok: true, status: 200, json: async () => TODAY };
  };
  const { window, dom } = await loadPage({ fetchImpl, beforeParse: (w) => {
    const NativeDate = w.Date;
    class FixedDate extends NativeDate {
      constructor(...args) { super(...(args.length ? args : [fixedNow])); }
      static now() { return fixedNow; }
    }
    FixedDate.parse = NativeDate.parse;
    FixedDate.UTC = NativeDate.UTC;
    w.Date = FixedDate;
  } });
  assert.equal(window.inadina.state.activeTab, "channelsTab");
  await window.inadina.refreshMatches(true);

  const home = window.document.getElementById("homeFeaturedSection");
  const card = home.querySelector(".home-featured-match");
  assert.ok(card, "ana ekran spotlight kartı render edilmedi");
  assert.equal(card.getAttribute("data-selection"), "suggested", "kaynak seçim yapmadığında öneri olduğu belirtilmeli");
  assert.ok(card.textContent.includes("İlk Ev") && card.textContent.includes("İlk Deplasman"), "bugünün en yakın yaklaşan maçı önerilmedi");
  assert.doesNotMatch(home.textContent, /Fixbet|kaynak|otomatik öneri/i, "kaynak ve öneri açıklaması kullanıcıya gösterilmemeli");
  assert.ok(window.document.querySelector("#homeFeaturedMeta .home-featured-time").textContent.includes(firstTime), "maç saati başlığın yanında görünmeli");
  assert.ok(window.document.querySelector("#homeFeaturedMeta .home-featured-status").textContent, "kalan süre başlığın yanında görünmeli");
  assert.equal(home.previousElementSibling?.tagName, "HEADER", "Günün Maçı kartı uygulama başlığının hemen altında olmalı");
  assert.ok(home.compareDocumentPosition(window.document.querySelector(".system-section")) & window.Node.DOCUMENT_POSITION_FOLLOWING,
    "Günün Maçı paneli kanal/sekme alanından önce ana ekranda yer almalı");

  window.scrolledTo.length = 0;
  home.querySelector(".home-featured-fixture").click();
  assert.equal(window.inadina.state.activeTab, "matchesTab", "ana kartın Fikstür düğmesi maç sekmesine götürmeli");
  assert.equal(matchCards(window).length, 2, "Fikstür açılınca bugünün tüm maçları gösterilmeli");
  assert.ok(window.scrolledTo.includes("matchFilterRow"), "maç listesine kaydırma yapılmalı");
  dom.window.close();
});

test("mobil liste görünümü sabit dokunma hedefleri ve taşmayı önleyen kuralları içeriyor", () => {
  assert.ok(HTML.includes(".channel-grid.view-list .ch-card { min-height: 58px"), "liste satırları için kararlı dokunma yüksekliği yok");
  assert.ok(HTML.includes(".channel-grid.view-list .ch-name { font-size: .84rem; line-height: 1.12;"), "mobil kanal adı dar ekrana göre ayarlanmamış");
  assert.ok(HTML.includes("@media (hover: none)"), "dokunmatik cihazlarda hover kayması kapatılmamış");
  assert.ok(HTML.includes("@media (max-width: 380px)"), "çok dar ekranlar için sıkıştırılmış satır düzeni yok");
});

test("maç kartındaki İZLE butonu yayını player'de açıyor", async () => {
  const { window, dom } = await loadPage();
  window.inadina.setTab("matchesTab");
  const first = matchCards(window)[0];
  const expected = TODAY.matches.find((m) => first.textContent.includes(m.home) && first.textContent.includes(m.away));
  window.scrolledTo.length = 0;
  first.querySelector(".play-match-btn").click();

  const iframe = window.document.getElementById("liveIframe");
  assert.ok(iframe.src.includes("id=" + expected.channel_id),
    `beklenen kanal ${expected.channel_id}, yüklenen ${iframe.src}`);
  assert.ok(window.scrolledTo.includes("playerContainer"), "maçtan player'e kaydırma yok");
  dom.window.close();
});

test("durum hesabı gerçek saate göre yapılıyor", async () => {
  const { window, dom } = await loadPage();
  const cs = window.inadina.computeState;
  const m = { time: "20:00", date: "2026-09-05", sport: "Futbol" };
  assert.equal(cs(m, new Date("2026-09-05T19:30:00+03:00")).status, "upcoming");
  assert.equal(cs(m, new Date("2026-09-05T20:05:00+03:00")).status, "live");
  assert.equal(cs(m, new Date("2026-09-05T21:44:00+03:00")).status, "live");
  assert.equal(cs(m, new Date("2026-09-05T21:46:00+03:00")).status, "finished");
  assert.equal(cs(m, new Date("2026-09-05T22:30:00+03:00")).status, "finished");
  // voleybol için pencere daha uzun (150 dk)
  const v = { time: "20:00", date: "2026-09-05", sport: "Voleybol" };
  assert.equal(cs(v, new Date("2026-09-05T22:20:00+03:00")).status, "live");
  dom.window.close();
});

test("arama ve marka filtresi kanalları daraltıyor", async () => {
  const { window, dom } = await loadPage();
  const input = window.document.getElementById("searchInput");
  input.value = "trt";
  input.dispatchEvent(new window.Event("input"));
  assert.equal(cards(window).length, 3, "TRT araması 3 kanal vermeli");

  input.value = "";
  input.dispatchEvent(new window.Event("input"));
  assert.equal(cards(window).length, 31);

  const trtChip = [...window.document.querySelectorAll(".chip")].find((c) => c.textContent.includes("TRT"));
  assert.ok(trtChip, "TRT marka filtresi yok");
  trtChip.click();
  assert.equal(cards(window).length, 3, "marka filtresi çalışmıyor");
  dom.window.close();
});

test("output/today_matches.json ile canlı tazeleme çalışıyor", async () => {
  const fetchImpl = async () => ({
    ok: true,
    status: 200,
    json: async () => TODAY,
  });
  const { window, dom } = await loadPage({ fetchImpl });
  const ok = await window.inadina.refreshMatches(true);
  assert.equal(ok, true, "tazeleme başarısız");
  window.inadina.setTab("matchesTab");
  assert.equal(matchCards(window).length, TODAY.matches.length);
  assert.ok(window.document.getElementById("updatedAtText").textContent.includes("canlı veri"),
    "tazeleme bilgisi gösterilmedi");
  dom.window.close();
});

test("canlı Fixbet programı eski snapshot'ı dengeler ve MS skoru Bitti filtresine taşır", async () => {
  const feed = `<!doctype html><a href="channel?id=final-1"><div class="match-detail">
    <div class="date">Futbol</div><div class="event">12:00 | Trendyol Süper Lig</div>
    <div class="teams"><div class="home">Final Takım <span class="score">3</span></div>
    <div class="away">Rakip Takım <span class="score">1</span></div></div><div class="match-status">MS</div>
  </div></a>
  <a href="channel?id=next-1"><div class="match-detail"><div class="date">Futbol</div>
    <div class="event">19:00 | Trendyol Süper Lig</div><div class="teams"><div class="home">Yeni Ev</div>
    <div class="away">Yeni Deplasman</div></div></div></a>`;
  const fetchImpl = async (url) => {
    if (String(url).startsWith("https://data-reality.com/matches.php")) {
      return { ok: true, status: 200, text: async () => feed };
    }
    if (String(url).startsWith("https://data-reality.com/matches2.php")) {
      return { ok: true, status: 200, text: async () => "" };
    }
    return { ok: true, status: 200, json: async () => TODAY };
  };
  const { window, dom } = await loadPage({ fetchImpl });
  assert.equal(await window.inadina.refreshMatches(true), true, "canlı feed tazelenmedi");
  window.inadina.setTab("matchesTab");
  assert.equal(matchCards(window).length, 2, "eski snapshot maçları canlı listenin üzerinde kaldı");
  const final = [...matchCards(window)].find((card) => card.getAttribute("data-event").includes("Final Takım"));
  assert.ok(final, "canlı feed’deki final maç yok");
  assert.equal(final.getAttribute("data-status"), "finished", "MS durumu Bitti olmadı");
  assert.match(final.querySelector(".match-score").textContent, /3.*1/, "kaynağın final skoru gösterilmedi");
  const finishedChip = [...window.document.querySelectorAll("#matchFilterRow .chip")]
    .find((chip) => chip.textContent.includes("Bitti"));
  assert.ok(finishedChip && Number(finishedChip.querySelector(".chip-count").textContent) >= 1,
    "Bitti filtresi final maçı saymıyor: " + JSON.stringify([...window.document.querySelectorAll("#matchFilterRow .chip")].map((chip) => chip.textContent)));
  assert.ok(window.document.getElementById("updatedAtText").textContent.includes("Fixbet canlı program"),
    "canlı program kaynağı kullanıcıya belirtilmedi");
  dom.window.close();
});

test("gece yarısından sonra tarihsiz eski schedule maçı yarının yaklaşan maçı olmaz", async () => {
  const { window, dom } = await loadPage();
  const now = new window.Date("2026-10-14T00:15:00+03:00");
  const existing = [{
    sport: "Futbol", league: "Test Kupası", home: "Galatasaray", away: "Barcelona", time: "22:00",
    date: "2026-10-13", startsAt: "2026-10-13T22:00:00+03:00", status: "finished",
    statusSource: "schedule", rawStatus: "", isMod: true,
  }];
  const nextDayStampedFeedRow = [{
    sport: "Futbol", league: "Test Kupası", home: "Galatasaray", away: "Barcelona", time: "22:00",
    date: "2026-10-14", status: "upcoming", statusSource: "schedule", rawStatus: "", isMod: true,
  }, {
    sport: "Futbol", league: "Test Kupası", home: "Gece Takımı", away: "Rakip", time: "00:05",
    date: "2026-10-14", status: "upcoming", statusSource: "schedule", rawStatus: "",
  }];
  existing.push({
    sport: "Futbol", league: "Test Kupası", home: "Gece Takımı", away: "Rakip", time: "00:05",
    date: "2026-10-13", startsAt: "2026-10-13T00:05:00+03:00", status: "finished",
    statusSource: "schedule", rawStatus: "",
  });
  const merged = window.inadina.mergeRemoteMatches(nextDayStampedFeedRow, existing, now);
  assert.equal(merged[0].startsAt, "2026-10-13T22:00:00+03:00", "orijinal kickoff tarihi kaybolmamalı");
  assert.equal(window.inadina.computeState(merged[0], now).status, "finished", "biten maç tekrar yaklaşan görünmemeli");
  assert.equal(merged[1].startsAt, "2026-10-13T00:05:00+03:00", "gece yarısı sonrası eski saat de korunmalı");
  assert.equal(window.inadina.computeState(merged[1], now).status, "finished", "00:05 maçı yanlışlıkla canlı olmamalı");
  dom.window.close();
});

test("tazeleme başarısız olursa gömülü gerçek veri kullanılıyor", async () => {
  const fetchImpl = async () => ({ ok: false, status: 404, json: async () => ({}) });
  const { window, dom, errors } = await loadPage({ fetchImpl });
  await window.inadina.refreshMatches(true);
  window.inadina.setTab("matchesTab");
  assert.equal(matchCards(window).length, TODAY.matches.length, "gömülü veri kullanılmadı");
  assert.deepEqual(errors, [], "beklenmeyen sayfa hatası: " + errors.join("; "));
  dom.window.close();
});


/* ---------------- ⚡ EXTRA (m3u8) paneli ---------------- */

test("EXTRA sekmesi panellerdeki kanalları listeliyor", async () => {
  const { window, dom, errors } = await loadPage();
  assert.deepEqual(errors, [], "sayfa hatası: " + errors.join("; "));
  assert.ok(EXTRA_COUNT >= 14, "extra_channels.json en az 14 Atom kanalı içermeli");
  assert.equal(window.document.getElementById("badgeExtra").textContent, String(EXTRA_COUNT));

  window.inadina.setTab("extraTab");
  assert.ok(window.document.getElementById("extraTab").classList.contains("active"));
  assert.equal(window.document.getElementById("panelRow").style.display, "flex", "panel çipleri görünmüyor");
  assert.equal(extraCards(window).length, EXTRA_COUNT);
  const first = extraCards(window)[0];
  assert.ok(first.classList.contains("extra"));
  assert.ok(["M3U8", "PLAYER"].includes(first.querySelector(".ch-status").textContent));
  assert.equal(first.querySelector(".ch-status").textContent, "M3U8", "Atom kanalında m3u8 kaynağı olmalı");
  assert.ok(first.querySelector(".ch-brand").textContent.includes("ATOM"), "panel adı kartta yok");
  const chips = [...window.document.querySelectorAll("#panelRow .chip")].map((c) => c.textContent);
  assert.ok(chips.some((t) => t.includes("ATOM SPOR")), "ATOM SPOR çipi yok: " + chips.join(","));
  // kanal listesi (kanallar sekmesi) EXTRA'dan etkilenmedi
  assert.equal(cards(window).length, 31);
  // istatistik: site kanalları + extra
  assert.equal(window.document.getElementById("totalChannelsCount").textContent, String(31 + EXTRA_COUNT));
  dom.window.close();
});

test("EXTRA karta tıklayınca m3u8 yayını hls.js ile <video> içinde açılıyor", async () => {
  const { window, dom } = await loadPage();
  window.inadina.setTab("extraTab");
  const card = extraCards(window)[0];
  const id = card.getAttribute("data-extra-id");
  const ch = window.inadina.extraChannels().find((c) => c.id === id);
  window.scrolledTo.length = 0;
  card.click();
  await tick();

  const wrap = window.document.getElementById("playerWrap");
  assert.ok(wrap.classList.contains("mode-hls"), "HLS moduna geçilmedi");
  assert.equal(window.inadina.state.playerMode, "hls");
  assert.equal(window.inadina.state.currentExtraId, id);
  assert.equal(window.hlsLog[0], "load:" + ch.sources[0].url, "ilk m3u8 kaynağı yüklenmedi: " + window.hlsLog);
  assert.ok((window.videoPlays || 0) >= 1, "video.play() çağrılmadı");
  assert.ok(!window.document.getElementById("playerError").classList.contains("active"), "hata katmanı açık");
  assert.equal(window.document.getElementById("playerTitle").textContent, ch.name);
  assert.ok(/M3U8|PLAYER/.test(window.document.getElementById("nowStatus").textContent));
  assert.deepEqual(window.scrolledTo, ["playerContainer"], "player'e kaydırma yapılmadı");
  assert.ok(card.classList.contains("active"), "seçili extra kart işaretlenmedi");
  assert.equal(window.location.hash, "#extra=" + encodeURIComponent(id), "derin bağlantı yazılmadı");
  // birden fazla kaynak varsa kaynak çipleri görünür
  if (ch.sources.length > 1) {
    const chips = window.document.querySelectorAll("#sourceRow .src-chip");
    assert.equal(chips.length, ch.sources.length, "kaynak çipleri eksik");
    assert.ok(chips[0].classList.contains("active"));
  }
  // iframe boşaltıldı (site yayını durdu)
  assert.equal(window.document.getElementById("liveIframe").src, "about:blank");
  dom.window.close();
});

test("m3u8 kaynağı açılmazsa sıradaki kaynak otomatik deneniyor, hepsi düşerse hata gösteriliyor", async () => {
  const failing = new Set();
  const { window, dom } = await loadPage({ behavior: (url) => (failing.has(url) ? "fail" : "ok") });
  const ch = window.inadina.extraChannels().find((c) => c.sources.filter((s) => s.type === "hls").length >= 2)
    || window.inadina.extraChannels()[0];
  const hlsSources = ch.sources.filter((s) => s.type === "hls");
  hlsSources.forEach((s) => failing.add(s.url));

  window.inadina.playExtra(ch.id, false);
  await tick(80);
  const err = window.document.getElementById("playerError");
  if (hlsSources.length >= 2) {
    // her hls kaynağı sırayla denendi
    const loads = window.hlsLog.filter((l) => l.startsWith("load:"));
    assert.deepEqual(Array.from(loads), Array.from(hlsSources.map((s) => "load:" + s.url)), "kaynaklar sırayla denenmedi");
  }
  assert.ok(err.classList.contains("active"), "hata katmanı gösterilmedi");
  assert.ok(window.document.getElementById("playerErrorMsg").textContent.length > 10);
  assert.ok(window.document.getElementById("openExternalBtn").getAttribute("href").length > 5, "yeni sekme bağlantısı yok");

  // ⏭ Diğer kaynak -> site (embed) yedeği iframe'de açılır
  const embed = ch.sources.find((s) => s.type === "embed");
  if (embed) {
    window.document.getElementById("nextSourceBtn").click();
    await tick();
    assert.ok(!err.classList.contains("active"), "hata katmanı kapanmadı");
    assert.equal(window.document.getElementById("liveIframe").src, embed.url, "site yedeği iframe'de açılmadı");
    assert.ok(!window.document.getElementById("playerWrap").classList.contains("mode-hls"));
  }
  // 🔄 Tekrar dene ilk kaynağa değil, seçili kaynağa yeniden gider
  failing.clear();
  window.inadina.playSource(0, true);
  await tick(60);
  assert.ok(!err.classList.contains("active"), "yeniden deneme başarısız");
  assert.ok(window.document.getElementById("playerWrap").classList.contains("mode-hls"));
  dom.window.close();
});

test("Safari (yerel HLS) yolunda video.src doğrudan m3u8 alıyor", async () => {
  const { window, dom } = await loadPage({ nativeHls: true, hls: "none" });
  const ch = window.inadina.extraChannels()[0];
  window.inadina.playExtra(ch.id, false);
  await tick();
  const video = window.document.getElementById("hlsVideo");
  assert.equal(video.getAttribute("src"), ch.sources[0].url, "yerel HLS kaynağı atanmadı");
  assert.ok((window.videoLoads || 0) >= 1, "video.load() çağrılmadı");
  assert.equal(window.hlsLog.length, 0, "yerel destek varken hls.js kullanılmamalı");
  dom.window.close();
});

test("EXTRA yayından site kanalına geçince oynatıcı iframe moduna dönüyor", async () => {
  const { window, dom } = await loadPage();
  const ch = window.inadina.extraChannels()[0];
  window.inadina.playExtra(ch.id, false);
  await tick();
  assert.ok(window.document.getElementById("playerWrap").classList.contains("mode-hls"));

  cards(window)[2].click();
  const wrap = window.document.getElementById("playerWrap");
  assert.ok(!wrap.classList.contains("mode-hls"), "iframe moduna dönülmedi");
  assert.equal(window.inadina.state.playerMode, "iframe");
  assert.equal(window.inadina.state.currentExtraId, null);
  assert.ok(window.hlsLog.some((l) => l.startsWith("destroy:")), "hls örneği yok edilmedi");
  assert.ok(window.document.getElementById("liveIframe").src.includes("channel.html?id=b3"));
  assert.equal(window.document.querySelectorAll("#sourceRow .src-chip").length, 0, "kaynak çipleri temizlenmedi");
  window.inadina.setTab("extraTab");
  assert.equal(window.document.querySelectorAll("#extraGrid .ch-card.active").length, 0, "extra kart hâlâ seçili");
  dom.window.close();
});

test("◀ ▶ EXTRA yayın açıkken extra kanallar arasında gezer, arama extra kartları da süzer", async () => {
  const { window, dom } = await loadPage();
  const list = window.inadina.extraChannels();
  window.inadina.playExtra(list[0].id, false);
  await tick();
  window.document.getElementById("navNext").click();
  await tick();
  assert.equal(window.inadina.state.currentExtraId, list[1].id, "sonraki extra kanala geçilmedi");
  window.document.getElementById("navPrev").click();
  await tick();
  assert.equal(window.inadina.state.currentExtraId, list[0].id);

  window.inadina.setTab("extraTab");
  const input = window.document.getElementById("searchInput");
  input.value = "tivibu";
  input.dispatchEvent(new window.Event("input"));
  const names = [...extraCards(window)].map((c) => c.querySelector(".ch-name").textContent);
  assert.ok(names.length >= 1 && names.every((n) => /tivibu/i.test(n)), "extra arama çalışmıyor: " + names.join(","));
  input.value = "";
  input.dispatchEvent(new window.Event("input"));
  assert.equal(extraCards(window).length, EXTRA_COUNT);
  dom.window.close();
});

test("#extra= derin bağlantısı EXTRA sekmesini açıp yayını başlatıyor", async () => {
  const id = EXTRA.panels[0].channels[1].id;
  const errors = [];
  const virtualConsole = new VirtualConsole();
  virtualConsole.on("jsdomError", (e) => errors.push(String(e && e.message)));
  const dom = new JSDOM(HTML, {
    runScripts: "dangerously", pretendToBeVisual: true, virtualConsole,
    url: "https://inadinatv.github.io/macweb/#extra=" + encodeURIComponent(id),
    beforeParse(window) {
      Object.defineProperty(window.HTMLIFrameElement.prototype, "src", {
        configurable: true,
        get() { return this.getAttribute("src") || ""; },
        set(value) { this.setAttribute("src", String(value)); },
      });
      window.Element.prototype.scrollIntoView = function () {};
      window.HTMLMediaElement.prototype.load = function () {};
      window.HTMLMediaElement.prototype.play = function () { return Promise.resolve(); };
      window.HTMLMediaElement.prototype.pause = function () {};
      window.HTMLMediaElement.prototype.canPlayType = function () { return "maybe"; };
    },
  });
  openPages.add(dom);
  const window = dom.window;
  for (let i = 0; i < 200 && !(window.inadina && window.inadina.ready); i++) await tick(10);
  assert.deepEqual(errors, [], "sayfa hatası: " + errors.join("; "));
  assert.equal(window.inadina.state.currentExtraId, id);
  assert.equal(window.inadina.state.activeTab, "extraTab");
  assert.ok(window.document.getElementById("playerWrap").classList.contains("mode-hls"));
  dom.window.close();
});

test("output/extra_channels.json ile EXTRA listesi canlı tazeleniyor", async () => {
  const fresh = JSON.parse(JSON.stringify(EXTRA));
  fresh.panels = fresh.panels.slice(0, 1);                       // yalnızca ilk panel kaldı
  fresh.panels[0].channels = fresh.panels[0].channels.slice(0, 3);
  fresh.panels[0].channels[0].sources.unshift({ type: "hls", url: "https://edge.test/new/bs1.m3u8", label: "Kaynak 0" });
  const fetchImpl = async (url) => ({
    ok: true, status: 200,
    json: async () => (String(url).includes("extra_channels") ? fresh : TODAY),
  });
  const { window, dom } = await loadPage({ fetchImpl });
  const ok = await window.inadina.refreshExtra(true);
  assert.equal(ok, true, "extra tazeleme başarısız");
  window.inadina.setTab("extraTab");
  assert.equal(extraCards(window).length, 3);
  assert.equal(window.document.getElementById("badgeExtra").textContent, "3");
  window.inadina.playExtra(fresh.panels[0].channels[0].id, false);
  await tick();
  assert.equal(window.hlsLog[0], "load:https://edge.test/new/bs1.m3u8", "yeni m3u8 adresi kullanılmadı");
  dom.window.close();
});

test("panel çipleri EXTRA kartlarını panele göre süzüyor", async () => {
  const { window, dom } = await loadPage();
  window.inadina.setTab("extraTab");
  assert.ok(EXTRA.panels.length >= 2, "en az iki extra panel bekleniyor");
  const chips = [...window.document.querySelectorAll("#panelRow .chip")];
  assert.equal(chips.length, EXTRA.panels.length + 1, "TÜMÜ + her panel için bir çip olmalı");
  const selcuk = chips.find((c) => c.textContent.includes("SELÇUK"));
  assert.ok(selcuk, "SELÇUK SPOR çipi yok: " + chips.map((c) => c.textContent).join(","));
  selcuk.click();
  const selPanel = EXTRA.panels.find((p) => p.id === "selcuk");
  assert.equal(extraCards(window).length, selPanel.channels.length, "Selçuk filtresi yanlış sayıda kart verdi");
  assert.ok([...extraCards(window)].every((c) => c.querySelector(".ch-brand").textContent.includes("SELÇUK")));
  // Selçuk kanalı da HLS oynatıcıda açılır (kaynaklar: m3u8 ve/veya oynatıcı sayfası)
  extraCards(window)[0].click();
  await tick();
  assert.equal(window.inadina.state.currentExtraId, selPanel.channels[0].id);
  const first = selPanel.channels[0].sources[0];
  if (first.type === "hls") {
    assert.equal(window.hlsLog[0], "load:" + first.url);
  } else {
    assert.equal(window.document.getElementById("liveIframe").src, first.url, "oynatıcı sayfası iframe'de açılmadı");
  }
  chips[0].click(); // TÜMÜ
  assert.equal(extraCards(window).length, EXTRA_COUNT);
  dom.window.close();
});

test("EXTRA tazelemesi başarısız olursa gömülü liste kullanılmaya devam ediyor", async () => {
  const fetchImpl = async () => ({ ok: false, status: 404, json: async () => ({}) });
  const { window, dom, errors } = await loadPage({ fetchImpl });
  const ok = await window.inadina.refreshExtra(true);
  assert.equal(ok, false);
  window.inadina.setTab("extraTab");
  assert.equal(extraCards(window).length, EXTRA_COUNT);
  assert.deepEqual(errors, [], "beklenmeyen sayfa hatası: " + errors.join("; "));
  dom.window.close();
});

/* ---------------- Gerçek durum + dinamik skor ---------------- */
function remoteRow(event, status, scores = [2, 1], extra = {}) {
  return { match_id: "ss", channel_id: "ss", event_id: event, home: "Ev " + event, away: "Dep " + event,
    league: "Test Ligi", sport: "Futbol", time: "20:00", status, status_source: "source",
    score_home: scores[0], score_away: scores[1], score_source: "source", score_updated_at: new Date().toISOString(),
    url: "https://player.test/channel?id=ss", ...extra };
}
const byEvent = (window, id) => [...matchCards(window)].find(c => c.dataset.event === id);
function withExtra(data, playback = {}) {
  return HTML.replace(/let extraData = [^\n]+;/, "let extraData = " + JSON.stringify(data) + ";")
    .replace(/const playbackConfig = [^\n]+;/, "const playbackConfig = " + JSON.stringify(playback) + ";");
}
function withMatches(rows) {
  return HTML.replace(/let matchesData = [^\n]+;/, "let matchesData = " + JSON.stringify(rows) + ";");
}
function singleExtra(source) {
  return { panels: [{ id: "test", name: "Test", channels: [{ id: "test:one", name: "Test", sources: [source] }] }] };
}

test("final, canlı, devre skorları doğru takımlarla; diğer durumlarda skor gizli", async () => {
  const rows = [remoteRow("ft", "FT"), remoteRow("live", "CANLI", [0, 0]), remoteRow("ht", "HT", [1, 3]),
    remoteRow("pre", "NS", [0, 0]), remoteRow("ppd", "PST"), remoteRow("cancel", "CANC"),
    remoteRow("abandoned", "ABD"), remoteRow("partial", "FT", [null, 2]), remoteRow("none", "FT", [null, null])];
  const json = { date: "2026-09-06", timezone: "Europe/Istanbul", matches: rows };
  const { window } = await loadPage({ fetchImpl: async url => ({ ok: true, json: async () => String(url).includes("extra_channels") ? EXTRA : json }) });
  await window.inadina.refreshMatches();
  window.inadina.setTab("matchesTab");
  for (const [id, status, score] of [["ft", "finished", [2,1]], ["live", "live", [0,0]], ["ht", "halftime", [1,3]]]) {
    const c = byEvent(window, id);
    assert.equal(c.dataset.status, status);
    assert.equal(c.querySelector('[data-score-side="home"]').textContent, String(score[0]));
    assert.equal(c.querySelector('[data-score-side="away"]').textContent, String(score[1]));
    assert.ok(c.querySelector('.match-score').getAttribute('aria-label').includes("Ev " + id));
  }
  assert.ok(byEvent(window,"ft").querySelector('.match-status-tag').textContent.includes('MS'));
  assert.equal(byEvent(window,"ht").querySelector('.match-status-tag').textContent, 'DEVRE');
  for (const id of ["pre","ppd","cancel","abandoned","partial","none"]) assert.equal(byEvent(window,id).querySelector('.match-score'), null, id);
  // Biten fakat skoru alınamayan maç: sahte 0-0 yerine açık placeholder.
  for (const id of ["partial","none"]) assert.equal(byEvent(window,id).querySelector('.mt-vs').textContent, 'Skor yok', id);
  // Henüz oynanmamış/oynanmayacak maçlarda placeholder değil "vs" kalır.
  for (const id of ["pre","ppd","cancel"]) assert.equal(byEvent(window,id).querySelector('.mt-vs').textContent, 'vs', id);
  assert.equal(byEvent(window,"ppd").querySelector('.match-status-tag').textContent, 'Ertelendi');
  assert.equal(byEvent(window,"cancel").querySelector('.match-status-tag').textContent, 'İptal');
  assert.equal(window.document.getElementById('totalLiveCount').textContent, '2');
  // Canlı filtresi devre arasındaki maçı kaybetmez.
  const chip = [...window.document.querySelectorAll('#matchFilterRow .chip')].find(c=>c.textContent.includes('Canlı'));
  chip.click();
  assert.equal(matchCards(window).length, 2);
});

test("skorlar canlı yenilemede güncellenir; biten maç saat hesabıyla tekrar canlı olmaz", async () => {
  let json = {date:'2026-09-06', matches:[remoteRow('event', 'HT', [1,0])]};
  const {window} = await loadPage({fetchImpl:async url=>({ok:true,json:async()=>String(url).includes('extra_channels')?EXTRA:json})});
  await window.inadina.refreshMatches();
  assert.equal(byEvent(window,'event').dataset.status,'halftime');
  json = {date:'2026-09-06',matches:[remoteRow('event','FT',[2,1])]};
  await window.inadina.refreshMatches();
  assert.equal(byEvent(window,'event').dataset.status,'finished');
  const normalized=window.inadina.normalizeRemote(json)[0];
  assert.equal(window.inadina.computeState(normalized,new Date('2026-09-06T20:30:00+03:00')).status,'finished');
  assert.equal(byEvent(window,'event').querySelector('[data-score-side="home"]').textContent,'2');
});

test("snapshot gerçek dakikayı taşır ve daha taze doğrudan canlı skoru geriye götürmez", async () => {
  let json = {date:'2026-09-06', matches:[remoteRow('fresh','NS',[null,null],{
    home:'Bournemouth',away:'Liverpool',league:'İngiltere Premier Lig',starts_at:'2026-09-06T20:00:00+03:00',
    score_updated_at:'2020-01-01T00:00:00Z',status_clock:'12\''
  })]};
  const {window}=await loadPage({fetchImpl:async url=>({ok:true,json:async()=>String(url).includes('extra_channels')?EXTRA:json})});
  await window.inadina.refreshMatches();
  assert.equal(window.inadina.normalizeRemote(json)[0].statusClock,"12'");
  window.inadina.applyLiveSync('soccer/eng.1',[{id:'ev',start:new Date('2026-09-06T20:00:00+03:00'),
    homeName:'Bournemouth',awayName:'Liverpool',homeScore:1,awayScore:0,status:'live',clock:"34'",neutral:false}]);
  window.inadina.renderMatches();
  assert.ok(byEvent(window,'fresh').textContent.includes("34'"));
  await window.inadina.refreshMatches();
  assert.equal(byEvent(window,'fresh').dataset.status,'live','eski snapshot canlı durumu geriletmemeli');
  assert.equal(byEvent(window,'fresh').querySelector('[data-score-side="home"]').textContent,'1');
  assert.ok(byEvent(window,'fresh').textContent.includes("34'"),'eski snapshot dakikayı geriletmemeli');
});

test("gömülü ve uzaktan alınan durum/skor verisi eşdeğer, eski saat tahmini korunur", async () => {
  const raw=remoteRow('embedded','finished',[3,0]);
  const embedded={id:raw.match_id,eventId:raw.event_id,home:raw.home,away:raw.away,league:raw.league,sport:raw.sport,time:raw.time,date:'2026-09-06',
    status:'finished',statusSource:'source',scoreHome:3,scoreAway:0,scoreSource:'source',scoreUpdatedAt:raw.score_updated_at};
  const html=HTML.replace(/let matchesData = [^\n]+;/,'let matchesData = '+JSON.stringify([embedded])+';');
  const {window}=await loadPage({html});
  const before=byEvent(window,'embedded').querySelector('.match-score').textContent;
  window.fetch=async()=>({ok:true,json:async()=>({date:'2026-09-06',matches:[raw]})});
  await window.inadina.refreshMatches();
  assert.equal(byEvent(window,'embedded').querySelector('.match-score').textContent,before);
  const legacy=window.inadina.normalizeRemote({date:'2026-09-06',matches:[{...raw,status:'upcoming',status_source:undefined,score_home:undefined,score_away:undefined}]})[0];
  assert.equal(legacy.statusSource,'schedule');
  assert.equal(window.inadina.computeState(legacy,new Date('2026-09-06T20:30:00+03:00')).status,'live');
});

test("eksik/geçersiz skor 0 olmaz; uzun takım isimleri kaçırılır ve üç sütun düzenini korur", async () => {
  const name='Çok Uzun Takım Adı '.repeat(8)+'<img src=x onerror=alert(1)>';
  const json={date:'2026-09-06',matches:[remoteRow('long','FT',[123,101],{home:name}),
    remoteRow('bad1','FT',[false,2]),remoteRow('bad2','FT',['',0]),remoteRow('bad3','FT',[-1,2]),remoteRow('bad4','FT',[2.5,1])]};
  const {window}=await loadPage({fetchImpl:async url=>({ok:true,json:async()=>String(url).includes('extra_channels')?EXTRA:json})});
  await window.inadina.refreshMatches();
  const long=byEvent(window,'long');
  assert.equal(long.querySelector('.team-name').textContent,name);
  assert.equal(long.querySelector('.team-name').title,name);
  assert.equal(long.querySelector('.match-teams').children.length,3);
  assert.equal(long.querySelectorAll('img').length,0);
  for (const id of ['bad1','bad2','bad3','bad4']) assert.equal(byEvent(window,id).querySelector('.match-score'),null);
});

test("maç saati ziyaretçinin saat dilimine bağlı değil; geçerli start ISO ve 30 saniye sınırı",async()=>{
  const {window}=await loadPage();
  const cs=window.inadina.computeState, m={time:'20:00',date:'2026-09-06',sport:'Futbol',statusSource:'schedule'};
  assert.equal(cs(m,new Date('2026-09-06T16:59:30Z')).status,'upcoming');
  assert.equal(cs(m,new Date('2026-09-06T17:00:00Z')).status,'live');
  assert.equal(cs({...m,startsAt:'2026-09-05T23:30:00+03:00'},new Date('2026-09-06T00:30:00+03:00')).status,'live');
  assert.equal(cs({...m,time:'25:99'},new Date()).start,null);
  assert.equal(cs({...m,status:'cancelled',statusSource:'source'},new Date()).status,'cancelled');
});

test("canlı skor kaynağı eskidiyse son skor notu görünür; eski snapshot final yapılmaz",async()=>{
  const json={date:'2026-09-06',matches:[remoteRow('stale','live',[1,0],{score_updated_at:'2020-01-01T00:00:00Z'})]};
  const {window}=await loadPage({fetchImpl:async url=>({ok:true,json:async()=>String(url).includes('extra_channels')?EXTRA:json})});
  await window.inadina.refreshMatches();
  assert.equal(byEvent(window,'stale').dataset.status,'live');
  assert.equal(byEvent(window,'stale').querySelector('.score-note').textContent,'son skor');
});

/* ---------------- HLS hata/race/timeout regresyonları ---------------- */
function captureDeadlines(window) {
  const set=window.setTimeout.bind(window), clear=window.clearTimeout.bind(window);
  let id=100000;
  const pending=new Map();
  window.setTimeout=(fn,ms,...args)=>{
    if(ms>=15000 && ms<=25000){pending.set(++id,{fn,ms,args});return id;}
    return set(fn,ms,...args);
  };
  window.clearTimeout=(key)=>{pending.delete(key);clear(key);};
  window.fireDeadline=(ms)=>{
    const entry=[...pending].find(([key,t])=>t.ms===ms);
    assert.ok(entry,'beklenen timer yok: '+ms);
    pending.delete(entry[0]);entry[1].fn(...entry[1].args);
  };
}

test("playlist parse edilmesi loading'i kapatmaz, segment gelmezse süreli hata oluşur",async()=>{
  const {window}=await loadPage({behavior:()=> 'manifest-only',beforeParse:captureDeadlines});
  window.inadina.playExtra(window.inadina.extraChannels()[0].id,false);
  await tick();
  assert.ok(window.document.getElementById('playerLoading').classList.contains('active'));
  for (let i = 0; i < 3 && !window.document.getElementById('playerError').classList.contains('active'); i++) {
    try { window.fireDeadline(25000); } catch (e) {}
    await tick(20);
  }
  assert.ok(window.document.getElementById('playerError').classList.contains('active'));
  assert.ok(!window.document.getElementById('playerLoading').classList.contains('active'));
});

test("HLS Promise beklerken site kanalına geçiş eski yayını yeniden başlatmaz",async()=>{
  const {window}=await loadPage();
  window.inadina.playExtra(window.inadina.extraChannels()[0].id,false);
  window.inadina.playChannel(2,false); // Hls Promise callback'inden ÖNCE
  await tick();
  assert.equal(window.hlsLog.length,0);
  assert.equal(window.inadina.state.playerMode,'iframe');
  assert.ok(window.document.getElementById('liveIframe').src.includes('id=b3'));
});

test("fatal network sonsuz startLoad yapmaz; media recovery sadece bir kez",async()=>{
  const html=withExtra(singleExtra({type:'hls',url:'https://cdn.test/one.m3u8'}));
  const {window}=await loadPage({html,behavior:()=> 'pending'});
  window.inadina.playExtra('test:one',false);await tick();
  let hls=window.hlsInstances.at(-1);
  const media={fatal:true,type:'mediaError',details:'bufferAppendError'};
  hls.handlers.hlsError('error',media);hls.handlers.hlsError('error',media);
  await tick();
  assert.equal(window.hlsLog.filter(x=>x==='recoverMediaError').length,1);
  assert.ok(window.document.getElementById('playerError').classList.contains('active'));
  window.inadina.playSource(0,true);await tick();hls=window.hlsInstances.at(-1);
  hls.handlers.hlsError('error',{fatal:true,type:'networkError',details:'fragLoadError',response:{code:404,url:'https://cdn.test/s.ts?token=secret'}});
  await tick();
  assert.ok(!window.hlsLog.includes('startLoad'));
  assert.ok(!JSON.stringify(window.inadina.playerLogs).includes('secret'));
  assert.ok(window.document.getElementById('playerErrorMsg').textContent.includes('404'));
});

test("oynatma başladıktan sonra stall loading ve timeout etkin kalır",async()=>{
  const html=withExtra(singleExtra({type:'hls',url:'https://cdn.test/one.m3u8'}));
  const {window}=await loadPage({html,beforeParse:w=>{
    captureDeadlines(w);Object.defineProperty(w.HTMLMediaElement.prototype,'paused',{configurable:true,get(){return false;}});
  }});
  window.inadina.playExtra('test:one',false);await tick();
  const video=window.document.getElementById('hlsVideo');
  assert.ok(!window.document.getElementById('playerLoading').classList.contains('active'));
  video.dispatchEvent(new window.Event('waiting'));
  assert.ok(window.document.getElementById('playerLoading').classList.contains('active'));
  window.fireDeadline(20000);await tick();
  assert.ok(window.document.getElementById('playerError').classList.contains('active'));
});

test("autoplay engeli hata değil: kullanıcı tek dokunuşla yayını başlatabilir",async()=>{
  const {window}=await loadPage({behavior:()=> 'manifest-only',beforeParse:w=>{
    w.HTMLMediaElement.prototype.play=function(){return Promise.reject(new w.DOMException('Not allowed','NotAllowedError'));};
  }});
  window.inadina.playExtra(window.inadina.extraChannels()[0].id,false);await tick();
  assert.ok(window.document.getElementById('playerStart').classList.contains('active'));
  assert.ok(!window.document.getElementById('playerError').classList.contains('active'));
  window.HTMLMediaElement.prototype.play=function(){this.dispatchEvent(new window.Event('playing'));return Promise.resolve();};
  window.document.getElementById('startStreamBtn').click();await tick();
  assert.ok(!window.document.getElementById('playerStart').classList.contains('active'));
});

test("kaynak header'ları bütün HLS isteklerinde kullanılır; native yol custom header'ı yutmaz",async()=>{
  const html=withExtra(singleExtra({type:'hls',url:'https://cdn.test/extensionless?ID=a',headers:{'X-Stream-Client':'test'}}));
  const {window}=await loadPage({html,nativeHls:true});
  window.inadina.playExtra('test:one',false);await tick();
  const hls=window.hlsInstances[0];assert.ok(hls);
  for(const request of ['manifest','segment','key']){
    const sent={};const xhr={setRequestHeader:(k,v)=>sent[k]=v};
    hls.config.xhrSetup(xhr,'https://cdn.test/'+request);
    assert.deepEqual(sent,{'X-Stream-Client':'test'});assert.equal(xhr.withCredentials,false);
  }
});

test("CORS/network hatasında aynı kaynak yapılandırılmış proxy ile bir kez denenir",async()=>{
  const html=withExtra(singleExtra({type:'hls',url:'https://cdn.test/one.m3u8'}),{proxy_url:'https://proxy.test/api/hls'});
  const {window}=await loadPage({html,behavior:url=>url.includes('proxy.test')?'ok':'fail'});
  window.inadina.playExtra('test:one',false);await tick(60);
  const loads=window.hlsLog.filter(x=>x.startsWith('load:'));
  assert.equal(loads.length,2);
  const proxied=new URL(loads[1].slice(5));
  assert.equal(proxied.searchParams.get('channel'),'test:one');assert.equal(proxied.searchParams.get('source'),'0');
  assert.equal(window.inadina.state.currentSourceIndex,0);
  assert.ok(!window.document.getElementById('playerError').classList.contains('active'));
});

test("yasak header ve mixed content istemcide taklit edilmez",async()=>{
  for (const source of [{type:'hls',url:'https://cdn.test/one.m3u8',headers:{Referer:'https://site.test',Origin:'https://site.test','User-Agent':'ExternalPlayer'}},
    {type:'hls',url:'http://cdn.test/one.m3u8'}]) {
    const {window,dom}=await loadPage({html:withExtra(singleExtra(source))});
    window.inadina.playExtra('test:one',false);await tick();
    assert.equal(window.hlsLog.length,0);
    assert.ok(window.document.getElementById('playerErrorMsg').textContent.includes('hizmeti gerekiyor'));
    dom.window.close();
  }
});

test("yüklenemeyen CDN Promise'i sıfırlanır, tekrar deneme yeni script yükleyebilir",async()=>{
  const html=withExtra(singleExtra({type:'hls',url:'https://cdn.test/one.m3u8'}));
  const {window}=await loadPage({html,beforeParse:w=>{w.SavedHls=w.Hls;delete w.Hls;}});
  window.inadina.playExtra('test:one',false);
  let script=window.document.querySelector('script[src*="hls.js"]');
  script.dispatchEvent(new window.Event('load')); // onload, ama Hls export yok
  await tick();script=window.document.querySelector('script[src*="unpkg"]');
  assert.ok(script);script.dispatchEvent(new window.Event('error'));await tick();
  assert.ok(window.document.getElementById('playerError').classList.contains('active'));
  window.inadina.playSource(0,true);
  script=window.document.querySelector('script[src*="hls.js"]');assert.ok(script);
  window.Hls=window.SavedHls;script.dispatchEvent(new window.Event('load'));await tick();
  assert.ok(window.hlsLog.some(x=>x.startsWith('load:')));
  assert.ok(!window.document.getElementById('playerError').classList.contains('active'));
});

test('gecikmiş liste isteği daha yeni dinamik skoru ezmez',async()=>{
  const {window}=await loadPage();
  const pending=[];
  window.fetch=(url)=>String(url).startsWith('https://data-reality.com/')
    ? Promise.resolve({ok:false,status:503})
    : new Promise(resolve=>pending.push(resolve));
  const old=window.inadina.refreshMatches();
  const fresh=window.inadina.refreshMatches();
  await tick(); // canlı feed düşer; iki istek artık snapshot yedeğinde bekler
  assert.equal(pending.length,2,'iki snapshot isteği sırayla başlatılmadı');
  pending[1]({ok:true,json:async()=>({date:'2026-09-06',matches:[remoteRow('latest','FT',[3,1])]})});
  await fresh;
  pending[0]({ok:true,json:async()=>({date:'2026-09-06',matches:[remoteRow('latest','live',[1,1])]})});
  await old;
  assert.equal(byEvent(window,'latest').dataset.status,'finished');
  assert.equal(byEvent(window,'latest').querySelector('[data-score-side="home"]').textContent,'3');
});

test('Chromium native HLS maybe bildirse de MSE/hls.js tercih edilir',async()=>{
  const {window}=await loadPage({nativeHls:true,beforeParse:w=>{
    w.MediaSource={isTypeSupported:()=>true};
    Object.defineProperty(w.navigator,'vendor',{value:'Google Inc.',configurable:true});
  }});
  window.inadina.playExtra(window.inadina.extraChannels()[0].id,false);await tick();
  assert.ok(window.hlsInstances?.length);
});

test('üretilen index aynı şablonun CSS ve player/kart kodunu kullanıyor',()=>{
  const template=readFileSync(path.join(ROOT,'src/fixbet/templates/index.html'),'utf8');
  assert.equal(HTML.split('/*BOT_END*/')[1],template.split('/*BOT_END*/')[1], 'index.html yeniden üretilmeli');
  assert.equal(HTML.match(/<style>([\s\S]*?)<\/style>/)[1],template.match(/<style>([\s\S]*?)<\/style>/)[1]);
});

/* ---------------- LİG PUANI butonu + PUAN DURUMU modalı ---------------- */
const STANDINGS_JSON = JSON.parse(readFileSync(path.join(ROOT, "output", "standings.json"), "utf8"));
const leagueBtn = (window) => window.document.getElementById("leagueBtn");
const modal = (window) => window.document.getElementById("leagueModal");
const modalOpen = (window) => modal(window).classList.contains("open");
const bodyRows = (window) => window.document.querySelectorAll("#standingsBody tr");

test("LİG PUANI butonu saatin hemen yanında ve tablo ikonu içeriyor", () => {
  // buton, saat widget'ı ile aynı header-meta satırında ve ondan SONRA gelmeli
  assert.ok(HTML.includes('id="liveClock"'), "saat widget'ı yok");
  assert.ok(HTML.includes('id="leagueBtn"'), "LİG PUANI butonu yok");
  assert.ok(HTML.includes("LİG PUANI"), "LİG PUANI etiketi yok");
  assert.ok(/class="league-btn"/.test(HTML), "league-btn sınıfı yok");
  assert.ok(/\.league-btn \{/.test(HTML), "league-btn CSS'i yok");
  // solunda küçük tablo ikonu (inline SVG)
  const btn = HTML.slice(HTML.indexOf('id="leagueBtn"'));
  assert.ok(/lg-icon[\s\S]{0,80}<svg/.test(btn), "butonun solunda tablo ikonu yok");
  assert.ok(HTML.indexOf('id="liveClock"') < HTML.indexOf('id="leagueBtn"'), "buton saatten önce gelmemeli");
  // neon mavi + pembe parlama
  const css = HTML.slice(HTML.indexOf(".league-btn {"), HTML.indexOf(".league-btn .lg-caret"));
  assert.ok(/rgba\(0,234,255/.test(css) && /rgba\(255,45,122/.test(css), "mavi+pembe neon parlama yok");
});

test("FİKSTÜR butonu LİG PUANI butonunun yanında ve go:fixtor bağlantısı içeriyor", () => {
  assert.ok(HTML.includes('id="fixtureBtn"'), "FİKSTÜR butonu yok");
  assert.ok(HTML.includes('href="go:fixtor"'), "go:fixtor yönlendirme bağlantısı yok");
  assert.ok(HTML.includes("FİKSTÜR"), "FİKSTÜR etiketi yok");
  assert.ok(HTML.includes("fixture-btn"), "fixture-btn sınıfı yok");
  assert.ok(HTML.indexOf('id="leagueBtn"') < HTML.indexOf('id="fixtureBtn"'), "Fikstür butonu LigPuan butonunun yanında olmalı");
});

test("PUAN DURUMU modalı backdrop-filter karartma ve neon pembe kenar kullanıyor", () => {
  assert.ok(/\.modal-overlay \{[\s\S]*?backdrop-filter: blur/.test(HTML), "backdrop-filter karartma yok");
  assert.ok(/\.modal-panel \{[\s\S]*?border: 2px solid var\(--neon-pink\)/.test(HTML), "neon pembe modal kenarı yok");
  assert.ok(HTML.includes('id="leagueModalClose"'), "kapatma (X) butonu yok");
  assert.ok(/<h2 class="modal-title"[^>]*>PUAN DURUMU<\/h2>/.test(HTML), "PUAN DURUMU başlığı yok");
  assert.ok(/\.modal-title \{[\s\S]*?color: var\(--neon-pink\)/.test(HTML), "başlık neon pembe değil");
  // erişilebilirlik
  assert.ok(HTML.includes('aria-modal="true"') && HTML.includes('aria-labelledby="leagueModalTitle"'), "dialog ARIA eksik");
  // satır ayracı: liste görünümü için belirgin çizgi
  assert.ok(/\.standings-table tbody td \{[\s\S]*?border-bottom: 1px solid rgba\(255,255,255,0\.16\)/.test(HTML),
    "satır ayracı yok");
});

test("tablo başlıkları SIRA/TAKIM/O/G/B/M/AV/P sırasında", () => {
  const head = HTML.slice(HTML.indexOf('id="standingsTable"'), HTML.indexOf('id="standingsBody"'));
  const cols = [...head.matchAll(/<th[^>]*>([^<]+)<\/th>/g)].map((m) => m[1]);
  assert.deepEqual(cols, ["SIRA", "TAKIM", "O", "G", "B", "M", "AV", "P"]);
});

test("modal başlangıçta kapalı; LİG PUANI'na tıklayınca açılıyor ve tabloyu çiziyor", async () => {
  const { window, dom } = await loadPage();
  assert.equal(modalOpen(window), false, "modal açık başlamamalı");
  assert.equal(bodyRows(window).length, STANDINGS_JSON.leagues[0].rows.length, "satır sayısı gerçek veriyle uyuşmuyor");

  leagueBtn(window).click();
  assert.equal(modalOpen(window), true, "modal açılmadı");
  assert.equal(leagueBtn(window).getAttribute("aria-expanded"), "true");
  assert.equal(window.document.body.style.overflow, "hidden", "arka plan kaydırması kilitlenmedi");
  assert.equal(window.document.activeElement, window.document.getElementById("leagueModalClose"),
    "odak kapatma butonuna gitmedi");

  // Beklenen değerler gerçek veriden (output/standings.json) türetilir: tablo bot
  // tarafından yenilendikçe test bayatlamaz, ama DOM ile kaynak birebir uyuşmak zorunda.
  const source = STANDINGS_JSON.leagues[0];
  const rows = bodyRows(window);
  assert.equal(rows.length, source.rows.length, "satır sayısı kaynak tabloyla uyuşmuyor");
  assert.ok(rows.length >= 18, "Süper Lig 18 takımla gömülmeli: " + rows.length);
  const cellTexts = (tr) => [...tr.querySelectorAll("td")].map((td) => td.textContent.trim());
  const av = (v) => (v == null ? "–" : v > 0 ? "+" + v : String(v));
  const expected = (r) => [String(r.rank), r.team, String(r.played), String(r.wins), String(r.draws),
    String(r.losses), av(r.diff), String(r.points)];

  const cells = cellTexts(rows[0]);
  assert.equal(cells.length, 8, "8 sütun olmalı");
  assert.deepEqual(cells, expected(source.rows[0]), "lider satırı kaynak verisiyle uyuşmuyor");
  // son sıradaki takım
  const lastIdx = source.rows.length - 1;
  assert.deepEqual(cellTexts(rows[lastIdx]), expected(source.rows[lastIdx]),
    "son sıra kaynak verisiyle uyuşmuyor");
  assert.ok(window.document.getElementById("leagueModalSub").textContent.includes(source.name));
  dom.window.close();
});

test("modal X butonu, Escape ve karartılmış alana tıklama ile kapanıyor", async () => {
  const { window, dom } = await loadPage();
  const close = window.document.getElementById("leagueModalClose");

  window.inadina.openLeagueModal();
  assert.equal(modalOpen(window), true);
  close.click();
  assert.equal(modalOpen(window), false, "X butonu kapatmadı");
  assert.equal(window.document.body.style.overflow, "", "kaydırma kilidi açılmadı");
  assert.equal(leagueBtn(window).getAttribute("aria-expanded"), "false");

  window.inadina.openLeagueModal();
  window.document.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  assert.equal(modalOpen(window), false, "Escape kapatmadı");

  window.inadina.openLeagueModal();
  modal(window).dispatchEvent(new window.MouseEvent("click", { bubbles: true })); // overlay'in kendisi
  assert.equal(modalOpen(window), false, "dışarı tıklama kapatmadı");

  window.inadina.openLeagueModal();
  window.document.querySelector(".modal-panel").dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  assert.equal(modalOpen(window), true, "panele tıklama kapatmamalı");
  dom.window.close();
});

test("modal açıkken kanal kısayolları çalışmıyor", async () => {
  const { window, dom } = await loadPage();
  window.inadina.openLeagueModal();
  const before = window.inadina.state.currentIndex;
  window.document.dispatchEvent(new window.KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
  assert.equal(window.inadina.state.currentIndex, before, "ok tuşu kanal değiştirmemeli");
  assert.equal(modalOpen(window), true, "ok tuşu modalı kapatmamalı");
  dom.window.close();
});

test("puan tablosu yoksa uydurma satır basılmıyor, dürüst boş durum gösteriliyor", async () => {
  const html = HTML.replace(/let standingsData = \{[\s\S]*?\};\n/, "let standingsData = {leagues: []};\n");
  assert.notEqual(html, HTML, "standingsData değiştirilemedi");
  const { window, dom } = await loadPage({ html });
  window.inadina.openLeagueModal();
  assert.equal(bodyRows(window).length, 0, "boş tabloda satır olmamalı");
  assert.equal(window.document.getElementById("standingsTable").hidden, true, "boş tablo gizlenmeli");
  assert.equal(window.document.getElementById("standingsEmpty").hidden, false, "boş durum mesajı görünmeli");
  assert.ok(window.document.getElementById("standingsEmpty").textContent.includes("uydurma"),
    "boş durum kaynağı açıklamalı");
  dom.window.close();
});

test("eksik sayısal alan tire gösterilir, uydurma sayıya dönüşmez", async () => {
  assert.deepEqual(
    (await loadPage()).window.inadina.normalizeStandings({
      source: "test", generated_at: "",
      leagues: [{ id: "x", name: "X", season: "", updated_at: "", rows: [
        { team: "A Takımı", rank: 1, played: 3, wins: 1, draws: null, losses: 2, diff: null, points: 3 },
      ] }],
    }).leagues[0].rows[0].draws, null);
  const { window, dom } = await loadPage();
  const norm = window.inadina.normalizeStandings({ leagues: [{ rows: [
    { team: "<img src=x onerror=alert(1)>", played: "çok", wins: "1", draws: 0, losses: 0, diff: 0, points: 3,
      logo: "javascript:alert(1)" },
  ] }] });
  assert.equal(norm.leagues[0].rows[0].played, null, "sayı olmayan O null olmalı");
  assert.equal(norm.leagues[0].rows[0].logo, "", "https olmayan logo atılmalı");
  assert.equal(norm.leagues[0].rows[0].team, "<img src=x onerror=alert(1)>", "takım adı korunmalı");
  dom.window.close();
});

test("uzak puan durumu tazelenir; boş yanıt son bilinen tabloyu silmez", async () => {
  const fresh = JSON.parse(JSON.stringify(STANDINGS_JSON));
  fresh.leagues[0].rows[0].points = 99;
  fresh.leagues[0].rows[0].team = "Taze Takım";

  const { window, dom } = await loadPage({
    fetchImpl: async (url) => ({ ok: true, json: async () => (String(url).includes("standings") ? fresh : { panels: [] }) }),
  });
  await window.inadina.refreshStandings(true);
  const first = [...bodyRows(window)[0].querySelectorAll("td")].map((td) => td.textContent.trim());
  assert.ok(first[1].includes("Taze Takım"), "taze tablo çizilmedi");
  assert.equal(first[7], "99");

  const empty = await (await loadPage({
    fetchImpl: async (url) => ({ ok: true, json: async () => (String(url).includes("standings") ? { leagues: [] } : { panels: [] }) }),
  })).window.inadina.refreshStandings(true);
  assert.equal(empty, false, "boş yanıt kabul edilmemeli");

  const { window: w3, dom: d3 } = await loadPage({
    fetchImpl: async () => ({ ok: false, status: 404, json: async () => ({}) }),
  });
  assert.equal(await w3.inadina.refreshStandings(true), false, "hata yanıtı false dönmeli");
  assert.equal(bodyRows(w3).length, 18, "kaynak kesilince gömülü tablo kalmalı");
  d3.window.close();
  dom.window.close();
});

test("üretilen index.html gerçek puan durumu verisini gömüyor", () => {
  assert.ok(HTML.includes('"Trendyol Süper Lig"'), "lig adı gömülmedi");
  // kaynak etiketi gerçek kaynaktan gelir (iddaa/mackolik/espn/mixed)
  const realSource = STANDINGS_JSON.source;
  assert.ok(["iddaa", "mackolik", "espn", "mixed"].includes(realSource), "beklenmeyen kaynak: " + realSource);
  assert.ok(HTML.includes(`"source": "${realSource}"`) || HTML.includes(`"source":"${realSource}"`),
    "kaynak belirtilmedi");
  assert.ok(HTML.includes('const standingsSource = "output/standings.json"'), "canlı tazeleme yolu yok");
  // JS'siz ortam için noscript tablosu
  const noscript = HTML.slice(HTML.indexOf("<noscript>"), HTML.indexOf("</noscript>"));
  assert.ok(/PUAN DURUMU/.test(noscript) && /Galatasaray/.test(noscript), "noscript puan tablosu yok");
  assert.ok(!/Sunucu/i.test(HTML), "'Sunucu' yazısı olmamalı");
});

/* ---------------- Takım adı tekrarı + sıra bölgeleri (Avrupa / küme düşme hattı) ---------------- */
const ZONES = ["champions", "europa", "relegation"];
const rowZone = (tr) => ZONES.find((z) => tr.classList.contains("zone-" + z)) || "";
const DOUBLED = /^(.{2,}?)\1$/;

test("takım adları tabloda tek kez yazılıyor (yapışık tekrar temizleniyor)", async () => {
  const sourceRows = STANDINGS_JSON.leagues[0].rows;
  sourceRows.forEach((r) => assert.ok(!DOUBLED.test(r.team), "kaynak dosyada tekrarlı ad: " + r.team));

  const { window, dom } = await loadPage();
  window.inadina.openLeagueModal();
  [...bodyRows(window)].forEach((tr, i) => {
    const name = tr.querySelectorAll("td")[1].textContent.trim();
    assert.ok(!DOUBLED.test(name), "tabloda tekrarlı takım adı: " + name);
    assert.equal(name, sourceRows[i].team, `${i + 1}. sıra adı kaynakla uyuşmuyor`);
  });

  // istemci tarafı güvenlik ağı: bayat/bozuk veri gelse bile ad tekilleştirilir
  assert.equal(window.inadina.dedupeTeamName("GalatasarayGalatasaray"), "Galatasaray");
  assert.equal(window.inadina.dedupeTeamName("Amed SK Amed SK"), "Amed SK");
  assert.equal(window.inadina.dedupeTeamName("Ç. RizesporÇ. Rizespor"), "Ç. Rizespor");
  assert.equal(window.inadina.dedupeTeamName("Fenerbahçe"), "Fenerbahçe", "tekrarsız ad değişmemeli");
  assert.equal(window.inadina.dedupeTeamName("Kocaelispor"), "Kocaelispor");
  dom.window.close();
});

test("ilk 3 sıra yükseliş (Avrupa) hattı, son 3 sıra küme düşme hattı olarak işaretli", async () => {
  const { window, dom } = await loadPage();
  window.inadina.openLeagueModal();
  const rows = [...bodyRows(window)];
  const total = rows.length;
  assert.ok(total >= 18, "18 takımlık tablo bekleniyor: " + total);

  assert.equal(rowZone(rows[0]), "champions", "lider Şampiyonlar Ligi hattında olmalı");
  assert.equal(rowZone(rows[1]), "europa", "2. sıra Avrupa hattında olmalı");
  assert.equal(rowZone(rows[2]), "europa", "3. sıra Avrupa hattında olmalı");
  for (let i = 3; i < total - 3; i++) {
    assert.equal(rowZone(rows[i]), "", `${i + 1}. sıra işaretsiz olmalı`);
  }
  for (let i = total - 3; i < total; i++) {
    assert.equal(rowZone(rows[i]), "relegation", `${i + 1}. sıra küme düşme hattında olmalı`);
  }

  // sıra rozeti + açıklama (tooltip) aynı bölgeyi taşır
  assert.ok(rows[0].querySelector(".cell-rank .rk.champions"), "lider rozeti renksiz");
  assert.ok(rows[2].querySelector(".cell-rank .rk.europa"), "3. sıra rozeti renksiz");
  assert.ok(rows[total - 1].querySelector(".cell-rank .rk.relegation"), "son sıra rozeti renksiz");
  assert.match(rows[0].getAttribute("title") || "", /Şampiyonlar Ligi/, "lider açıklaması yok");
  assert.match(rows[total - 1].getAttribute("title") || "", /Küme düşme/, "düşme hattı açıklaması yok");
  assert.ok(!rows[4].getAttribute("title"), "işaretsiz sıraya bölge açıklaması yazılmamalı");
  dom.window.close();
});

test("bölge renkleri CSS'te tanımlı ve lejant sıra aralıklarını gösteriyor", async () => {
  // şerit + zemin + rozet renkleri (yalnızca bölge sınıfları üzerinden)
  assert.ok(/\.standings-table tbody tr\.zone-champions \{/.test(HTML), "champions zemin rengi yok");
  assert.ok(/\.standings-table tbody tr\.zone-europa \{/.test(HTML), "europa zemin rengi yok");
  assert.ok(/\.standings-table tbody tr\.zone-relegation \{/.test(HTML), "relegation zemin rengi yok");
  assert.ok(/tr\.zone-relegation td:first-child \{ box-shadow: inset 3px 0 0/.test(HTML), "sol renkli şerit yok");
  assert.ok(/\.cell-rank \.rk\.champions \{/.test(HTML), "champions rozeti yok");
  assert.ok(/\.rk\.relegation, \.standings-table \.cell-rank \.rk\.relegate \{/.test(HTML), "relegation rozeti yok");
  // ▲ yükseliş hattı / ▼ küme düşme hattı okları (pseudo-element: hücre metnini kirletmez)
  assert.ok(/tr\.zone-europa \.cell-team::after \{ content: "▲"/.test(HTML), "yükseliş oku (▲) yok");
  assert.ok(/tr\.zone-relegation \.cell-team::after \{ content: "▼"/.test(HTML), "düşme oku (▼) yok");
  assert.ok(/<span style="color:#ff9ba7;">▼<\/span>/.test(HTML), "noscript tabloda düşme oku yok");
  assert.ok(/<span style="color:#7dffc0;">▲<\/span>/.test(HTML), "noscript tabloda yükseliş oku yok");

  const { window, dom } = await loadPage();
  window.inadina.openLeagueModal();
  const legend = window.document.getElementById("standingsLegend");
  assert.equal(legend.hidden, false, "bölge lejantı görünmeli");
  const text = legend.textContent.replace(/\s+/g, " ").trim();
  const total = STANDINGS_JSON.leagues[0].rows.length;
  assert.ok(text.includes("Şampiyonlar Ligi"), "lejantta Şampiyonlar Ligi yok: " + text);
  assert.ok(text.includes("2-3") && text.includes("Avrupa kupaları"), "lejantta Avrupa hattı yok: " + text);
  assert.ok(text.includes(`${total - 2}-${total}`) && text.includes("Küme düşme hattı"),
    "lejantta küme düşme hattı yok: " + text);
  assert.equal(legend.querySelectorAll(".zl-item").length, 3, "üç bölge açıklanmalı");
  assert.ok(legend.querySelector(".zl-item.champions .zl-sw"), "lejant renk kutusu yok");
  dom.window.close();
});

test("kaynak bölge vermezse not metninden okunur, bilinmeyen bölge işaretsiz kalır", async () => {
  const { window, dom } = await loadPage();
  assert.equal(window.inadina.zoneFromNote("Relegated"), "relegation");
  assert.equal(window.inadina.zoneFromNote("Champions League"), "champions");
  assert.equal(window.inadina.zoneFromNote("UEFA Europa League"), "europa");
  assert.equal(window.inadina.zoneFromNote(""), "", "not yoksa bölge uydurulmaz");

  const norm = window.inadina.normalizeStandings({ leagues: [{ rows: [
    { team: "Konyaspor", rank: 18, note: "Relegated" },
    { team: "Galatasaray", rank: 1, zone: "champions", zoneLabel: "Şampiyonlar Ligi" },
    { team: "Bozuk Bölge", rank: 5, zone: '"><script>alert(1)</script>' },
    { team: "Ara Sıra", rank: 9 },
  ] }] });
  const rows = norm.leagues[0].rows;
  assert.equal(rows[0].zone, "relegation", "ESPN notu bölgeye dönüşmeli");
  assert.equal(rows[1].zoneLabel, "Şampiyonlar Ligi", "kaynak etiketi korunmalı");
  assert.equal(rows[2].zone, "", "bilinmeyen bölge değeri sınıfa sızmamalı");
  assert.equal(rows[3].zone, "", "notu olmayan sıra işaretsiz kalmalı");
  // lejant ardışık sıraları aralığa toplar
  assert.equal(window.inadina.zoneGroups([
    { rank: 1, zone: "champions", zoneLabel: "Şampiyonlar Ligi" },
    { rank: 2, zone: "europa", zoneLabel: "Avrupa kupaları" },
    { rank: 3, zone: "europa", zoneLabel: "Avrupa kupaları" },
    { rank: 4, zone: "", zoneLabel: "" },
  ]).map((g) => g.ranks + " " + g.label).join(" | "), "1 Şampiyonlar Ligi | 2-3 Avrupa kupaları");
  dom.window.close();
});

test("noscript puan tablosu da bölgeleri ve lejantı basıyor", () => {
  const noscript = HTML.slice(HTML.indexOf("<noscript>"), HTML.indexOf("</noscript>"));
  assert.ok(/box-shadow:inset 3px 0 0 #ffcc33/.test(noscript), "noscript lider şeridi yok");
  assert.ok(/box-shadow:inset 3px 0 0 #ff9ba7/.test(noscript), "noscript düşme hattı şeridi yok");
  assert.ok(/Küme düşme hattı/.test(noscript) && /Şampiyonlar Ligi/.test(noscript), "noscript lejantı yok");
  // sayfaya gömülen takım adları tekrarsız olmalı (kaynak adı iki kez basıyordu)
  const teams = [...HTML.matchAll(/"team": "([^"]+)"/g)].map((m) => m[1]);
  assert.ok(teams.length >= 18, "gömülü takım adları okunamadı: " + teams.length);
  teams.forEach((t) => assert.ok(!DOUBLED.test(t), "sayfada tekrarlı takım adı kaldı: " + t));
});

/* ---------------- Canlı akış: kaynak gecikmesi + canlı skor senkronu ---------------- */

test("kaynak gecikirse maç başlama saatine göre CANLI'ya yükseltilir", async () => {
  const { window, dom } = await loadPage();
  const cs = window.inadina.computeState;
  const m = { time: "20:00", date: "2026-09-06", sport: "Futbol", status: "upcoming", statusSource: "mackolik", startsAt: "2026-09-06T20:00:00+03:00" };
  // Başladıktan 20 dk sonra kaynak hâlâ "başlamadı" diyorsa sayfa CANLI varsayar
  const st = cs(m, new Date("2026-09-06T20:20:00+03:00"));
  assert.equal(st.status, "live");
  assert.equal(st.estimated, true, "yükseltme tahmin olarak işaretlenmeli");
  assert.equal(st.waitingSource, true, "kaynak gecikmesi işaretlenmeli");
  // Canlı penceresi dışına düşen bayat kayıt (ertesi gün) yükseltilmez
  assert.equal(cs(m, new Date("2026-09-07T23:00:00+03:00")).status, "upcoming");
  // Gerçek kaynak durumu aynen korunur
  assert.equal(cs({ ...m, status: "live" }, new Date("2026-09-06T20:20:00+03:00")).status, "live");
  assert.equal(cs({ ...m, status: "postponed" }, new Date("2026-09-06T20:20:00+03:00")).status, "postponed");
  dom.window.close();
});

test("ESPN scoreboard ayrıştırıcısı durum, skor ve dakika çıkarır", async () => {
  const { window, dom } = await loadPage();
  const scoreboard = (status, id = "401") => ({
    events: [{ id, date: "2026-09-06T17:00:00Z", competitions: [{
      id: "c1", date: "2026-09-06T17:00:00Z", neutralSite: false,
      competitors: [{ homeAway: "home", score: "1", team: { displayName: "Kasimpasa" } },
                    { homeAway: "away", score: "0", team: { displayName: "Goztepe" } }], status,
    }] }],
  });
  const comps = window.inadina.parseEspnScoreboard(scoreboard({ displayClock: "63:12", type: { name: "STATUS_IN_PROGRESS", shortDetail: "63'", state: "in" } }), "soccer/eng.1");
  assert.equal(comps.length, 1);
  assert.equal(comps[0].status, "live");
  assert.equal(comps[0].clock, "63′");
  assert.equal(comps[0].homeScore, 1);
  assert.equal(comps[0].awayScore, 0);
  const stoppage = window.inadina.parseEspnScoreboard(scoreboard({ displayClock: "45:00", type: {
    name: "STATUS_IN_PROGRESS", shortDetail: "45'+3", state: "in" } }, "402"), "soccer/uefa.champions")[0];
  assert.equal(stoppage.clock, "45+3′", "uzatma dakikası kısa detaydan korunmalı");
  const halftime = window.inadina.parseEspnScoreboard(scoreboard({ displayClock: "45:00", type: {
    name: "STATUS_HALFTIME", shortDetail: "Halftime", state: "post" } }, "403"), "soccer/uefa.champions")[0];
  assert.equal(halftime.status, "halftime");
  assert.equal(halftime.clock, "", "devre arasında eskimiş 45. dakika gösterilmemeli");
  const secondHalf = window.inadina.parseEspnScoreboard(scoreboard({ period: 2, displayClock: "11:24", type: {
    name: "STATUS_IN_PROGRESS", shortDetail: "Second Half", detail: "Second Half", state: "in" } }, "404"), "soccer/uefa.europa")[0];
  assert.equal(secondHalf.clock, "56′", "ikinci yarı saat sayacı 45 dakikaya eklenmeli; 11′ olarak sıfırlanmamalı");
  dom.window.close();
});

function featuredLiveRow(minutesAgo = 30, extra = {}) {
  const start = new Date(Date.now() - minutesAgo * 60000);
  const time = new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/Istanbul", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(start);
  return {
    match_id: "trt1", event_id: "featured-event", starts_at: start.toISOString(),
    home: "Aston Villa", away: "Fenerbahçe", league: "UEFA Şampiyonlar Ligi", sport: "Futbol", time,
    status: "live", status_source: "schedule", status_clock: "29′", raw_status: "",
    score_home: 0, score_away: 0, score_source: "espn", score_updated_at: new Date(Date.now() - 60000).toISOString(),
    is_match_of_day: true, channel_id: "trt1", url: "https://fixbet.test/channel.html?id=trt1", ...extra,
  };
}

test("Günün Maçı basketboldan önce bugünün futbol fikstürünü seçer ve Fixtoor uyumlu ESPN skorunu eşler", async () => {
  const fixedNow = Date.UTC(2026, 9, 16, 16, 30, 0);
  const row = (id, sport, league, home, away, startAt) => {
    const start = new Date(startAt);
    const time = new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/Istanbul", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(start);
    return featuredLiveRow(0, {
      event_id: id, sport, league, home, away, starts_at: start.toISOString(), time,
      date: "2026-10-16", status: "upcoming", status_source: "mackolik", raw_status: "NS",
      score_home: null, score_away: null, score_source: "", score_updated_at: "", is_match_of_day: false,
    });
  };
  const football = row("corum-rize", "Futbol", "Trendyol Süper Lig", "Çorum FK", "Ç.Rizespor", "2026-10-16T17:00:00Z");
  const basketball = row("earlier-basketball", "Basketbol", "Euroleague", "Beşiktaş", "Bayern Münih", "2026-10-16T15:00:00Z");
  const { window, dom } = await loadPage({
    html: withMatches([basketball, football]),
    fetchImpl: async () => ({ ok: false, status: 503, json: async () => ({}) }),
    beforeParse: (w) => {
      const NativeDate = w.Date;
      w.Date = class FixedDate extends NativeDate {
        constructor(...args) { if (!args.length) super(fixedNow); else super(...args); }
        static now() { return fixedNow; }
      };
      Object.defineProperty(w.document, "hidden", { configurable: true, get: () => true });
    },
  });
  let card = window.document.querySelector("#homeFeaturedSection .home-featured-match");
  assert.ok(card.textContent.includes("Çorum FK") && card.textContent.includes("Ç.Rizespor"),
    "aynı günün futbol maçı, daha erken basketbol fikstüründen önce seçilmeli");
  assert.deepEqual(Array.from(window.inadina.syncPathsFor(football)), ["soccer/tur.1"],
    "Çorum–Rize maçı Fixtoor ile aynı günlük ESPN scoreboard yoluna bağlanmalı");
  assert.deepEqual(Array.from(window.inadina.syncDatesForPath("soccer/tur.1")), ["20261016"],
    "maçın UTC fikstür günü tekil scoreboard sorgusu için üretilmeli");
  assert.ok(Array.from(window.inadina.syncWantedPaths(new Date(fixedNow))).includes("soccer/tur.1"),
    "başlama saatine yaklaşan maçın scoreboard yolu canlı poll’a dahil edilmeli");

  const changed = window.inadina.applyLiveSync("soccer/tur.1", [{
    id: football.event_id, start: new Date(football.starts_at), homeName: "Corum FK", awayName: "Caykur Rizespor",
    homeScore: 1, awayScore: 0, status: "live", clock: "12′", neutral: false,
  }], fixedNow);
  assert.equal(changed, 1, "alternatif scoreboard yolundan gelen kesin takım+saat eşleşmesi uygulanmalı");
  window.inadina.renderMatches();
  card = window.document.querySelector("#homeFeaturedSection .home-featured-match");
  assert.equal(card.dataset.score, "1-0");
  assert.equal(card.dataset.clock, "12′");
  dom.window.close();
});

test("ana Günün Maçı kartı gol, canlı dakika, kanal ve devre arasıyla aynı state’i izliyor", async () => {
  const fixedNow = Date.UTC(2026, 9, 16, 12, 0, 0);
  const start = new Date(fixedNow - 30 * 60000);
  const time = new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/Istanbul", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(start);
  const row = featuredLiveRow(30, {
    starts_at: start.toISOString(), time, score_updated_at: new Date(fixedNow - 60000).toISOString(),
  });
  const { window, dom } = await loadPage({
    html: withMatches([row]),
    fetchImpl: async () => ({ ok: false, status: 503, json: async () => ({}) }),
    beforeParse: (w) => {
      const NativeDate = w.Date;
      w.Date = class FixedDate extends NativeDate {
        constructor(...args) { if (!args.length) super(fixedNow); else super(...args); }
        static now() { return fixedNow; }
      };
      Object.defineProperty(w.document, "hidden", { configurable: true, get: () => true });
    },
  });
  const path = "soccer/uefa.champions";
  let homeCard = window.document.querySelector("#homeFeaturedSection .home-featured-match");
  assert.ok(homeCard, "Günün Maçı ana kartta açılmalı");
  assert.equal(homeCard.dataset.selection, "official", "ham snapshot is_match_of_day bayrağı açılışta tanınmalı");
  assert.equal(homeCard.dataset.score, "0-0");
  assert.ok(window.document.querySelector("#homeFeaturedSection .home-featured-channel").textContent.includes("TRT"),
    "ham channel_id kanal adı olarak çözülmeli");

  const live = { id: "featured-event", start, homeName: row.home, awayName: row.away, homeScore: 1, awayScore: 0,
    status: "live", clock: "45+3′", neutral: false };
  assert.equal(window.inadina.applyLiveSync(path, [live], fixedNow), 1);
  window.inadina.renderMatches();
  homeCard = window.document.querySelector("#homeFeaturedSection .home-featured-match");
  assert.equal(homeCard.dataset.score, "1-0", "gol sonrası skor ana kartta anında değişmeli");
  assert.equal(homeCard.dataset.clock, "45+3′", "duraklama dakikası kartta görünmeli");
  assert.ok(window.document.querySelector("#homeFeaturedMeta .home-featured-status").textContent.includes("45+3′"));
  assert.equal(window.document.querySelector("#homeFeaturedSection .home-featured-goal")?.textContent, "GOL!");
  assert.ok(window.document.querySelector("#homeFeaturedSection .home-featured-freshness").textContent.includes("CANLI SKOR"));

  assert.equal(window.inadina.applyLiveSync(path, [{ ...live, status: "halftime", clock: "" }], fixedNow), 1);
  window.inadina.renderMatches();
  homeCard = window.document.querySelector("#homeFeaturedSection .home-featured-match");
  assert.equal(homeCard.dataset.status, "halftime");
  assert.equal(homeCard.dataset.score, "1-0", "devre arasında skor korunmalı");
  assert.equal(window.document.querySelector("#homeFeaturedMeta .home-featured-status").textContent, "DEVRE ARASI");
  assert.equal(window.document.querySelector("#homeFeaturedSection .home-featured-goal"), null,
    "devre durumunda önceki GOL bildirimi yinelenmemeli");
  dom.window.close();
});

test("resmi Günün Maçı bitmişse kart bugünün canlı maçına geçer ve final skorunu korur", async () => {
  const fixedNow = Date.UTC(2026, 9, 15, 18, 0, 0);
  const fixedRow = (startAt, extra) => {
    const start = new Date(startAt);
    const time = new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/Istanbul", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(start);
    return featuredLiveRow(0, {
      ...extra, starts_at: start.toISOString(), time, score_updated_at: new Date(fixedNow - 60000).toISOString(),
    });
  };
  const finishedOfficial = fixedRow(Date.UTC(2026, 9, 15, 16, 45, 0), {
    event_id: "kups-finished", home: "KuPS", away: "Trabzonspor", league: "UEFA Avrupa Konferans Ligi",
    status: "finished", status_source: "source", raw_status: "FT", status_clock: "",
    score_home: null, score_away: null, score_source: "", score_updated_at: "",
  });
  const liveBeşiktaş = fixedRow(Date.UTC(2026, 9, 15, 19, 0, 0), {
    event_id: "besiktas-live", home: "Hoffenheim", away: "Beşiktaş", league: "UEFA Avrupa Ligi",
    status: "live", status_source: "espn", raw_status: "STATUS_SECOND_HALF", status_clock: "56′",
    score_home: 0, score_away: 1, score_source: "espn",
  });
  const { window, dom } = await loadPage({
    html: withMatches([finishedOfficial, liveBeşiktaş]),
    fetchImpl: async () => ({ ok: false, status: 503, json: async () => ({}) }),
    beforeParse: (w) => {
      const NativeDate = w.Date;
      w.Date = class FixedDate extends NativeDate {
        constructor(...args) { if (!args.length) super(fixedNow); else super(...args); }
        static now() { return fixedNow; }
      };
      Object.defineProperty(w.document, "hidden", { configurable: true, get: () => true });
    },
  });
  let card = window.document.querySelector("#homeFeaturedSection .home-featured-match");
  assert.ok(card.textContent.includes("Hoffenheim") && card.textContent.includes("Beşiktaş"),
    "biten KuPS maçı yerine bugünün devam eden Beşiktaş maçı seçilmeli");
  assert.equal(card.dataset.selection, "official", "canlı resmi Günün Maçı seçimi korunmalı");
  assert.equal(card.dataset.status, "live");
  assert.equal(card.dataset.score, "0-1");
  assert.equal(card.dataset.clock, "56′");
  assert.ok(window.document.querySelector("#homeFeaturedMeta").textContent.includes("56′"));

  const updated = window.inadina.applyLiveSync("soccer/uefa.europa", [{
    id: liveBeşiktaş.event_id, start: new Date(liveBeşiktaş.starts_at), homeName: "TSG Hoffenheim",
    awayName: "Besiktas", homeScore: 1, awayScore: 1, status: "live", clock: "69′", neutral: false,
  }], fixedNow);
  assert.equal(updated, 1, "provider takım adı farkıyla da canlı skor eşleşmeli");
  window.inadina.renderMatches();
  card = window.document.querySelector("#homeFeaturedSection .home-featured-match");
  assert.equal(card.dataset.score, "1-1", "ESPN gol skoru ana kartta anında güncellenmeli");
  assert.equal(card.dataset.clock, "69′", "ikinci yarı dakikası ana kartta ilerlemeli");

  const finalized = window.inadina.applyLiveSync("soccer/uefa.europa", [{
    id: liveBeşiktaş.event_id, start: new Date(liveBeşiktaş.starts_at), homeName: "TSG Hoffenheim",
    awayName: "Besiktas", homeScore: null, awayScore: null, status: "finished", clock: "", neutral: false,
  }], fixedNow);
  assert.equal(finalized, 1, "skorsuz maç sonu state’i uygulanmalı");
  window.inadina.renderMatches();
  card = window.document.querySelector("#homeFeaturedSection .home-featured-match");
  assert.equal(card.dataset.status, "finished");
  assert.equal(card.dataset.score, "1-1", "final yanıtı skorsuzsa son bilinen skor silinmemeli");
  assert.equal(window.document.querySelector("#homeFeaturedMeta").textContent.includes("BİTTİ"), true);

  const finalScoreArrived = window.inadina.applyLiveSync("soccer/uefa.europa", [{
    id: liveBeşiktaş.event_id, start: new Date(liveBeşiktaş.starts_at), homeName: "TSG Hoffenheim",
    awayName: "Besiktas", homeScore: 2, awayScore: 3, status: "finished", clock: "", neutral: false,
  }], fixedNow);
  assert.equal(finalScoreArrived, 1, "gecikmeli final skoru sonuca işlenmeli");
  window.inadina.renderMatches();
  card = window.document.querySelector("#homeFeaturedSection .home-featured-match");
  assert.equal(card.dataset.score, "2-3", "gecikmeli gelen final skor ekranda güncellenmeli");
  dom.window.close();
});

test("skorsuz bitiş feed’i daha önce doğrulanmış skoru remote merge’de korur", async () => {
  const row = featuredLiveRow(60, {
    home: "Hoffenheim", away: "Beşiktaş", league: "UEFA Avrupa Ligi",
    status: "live", status_source: "espn", raw_status: "STATUS_SECOND_HALF",
    score_home: 1, score_away: 3, score_source: "espn",
  });
  const { window, dom } = await loadPage({
    html: withMatches([row]),
    fetchImpl: async () => ({ ok: false, status: 503, json: async () => ({}) }),
    beforeParse: (w) => Object.defineProperty(w.document, "hidden", { configurable: true, get: () => true }),
  });
  const old = window.inadina.normalizeRemote({ matches: [row] })[0];
  const remoteFinal = window.inadina.normalizeRemote({ matches: [{
    ...row, status: "finished", status_source: "source", raw_status: "FT",
    score_home: null, score_away: null, score_source: "", score_updated_at: "",
  }] })[0];
  const merged = window.inadina.mergeRemoteMatches([remoteFinal], [old], new Date())[0];
  assert.equal(merged.status, "finished", "final status alınmalı");
  assert.equal(merged.scoreHome, 1, "final feed skorsuzsa önceki ev sahibi skoru silinmemeli");
  assert.equal(merged.scoreAway, 3, "final feed skorsuzsa önceki deplasman skoru silinmemeli");
  assert.equal(merged.scoreSource, "espn");
  dom.window.close();
});

test("UEFA Avrupa Konferans Ligi ve KuPS Kuopio adı final skoruna eşleşir", async () => {
  const row = featuredLiveRow(210, {
    event_id: "401915858", home: "KuPS", away: "Trabzonspor",
    league: "UEFA Avrupa Konferans Ligi", status: "finished", status_source: "source", raw_status: "FT",
    starts_at: "2026-10-15T16:45:00.000Z", time: "19:45",
    score_home: null, score_away: null, score_source: "", score_updated_at: "",
  });
  const { window, dom } = await loadPage({
    html: withMatches([row]),
    fetchImpl: async () => ({ ok: false, status: 503, json: async () => ({}) }),
    beforeParse: (w) => Object.defineProperty(w.document, "hidden", { configurable: true, get: () => true }),
  });
  const updated = window.inadina.applyLiveSync("soccer/uefa.europa.conf", [{
    id: row.event_id, start: new Date(row.starts_at), homeName: "KuPS Kuopio", awayName: "Trabzonspor",
    homeScore: 2, awayScore: 4, status: "finished", clock: "", neutral: false,
  }]);
  assert.equal(updated, 1, "alternatif lig ve provider takım adıyla final olayı eşleşmeli");
  const match = window.inadina.decoratedMatches(new Date()).find((m) => m.home === "KuPS");
  assert.deepEqual(Array.from(match._score), [2, 4], "KuPS–Trabzonspor final skoru 2–4 olarak saklanmalı");
  dom.window.close();
});

test("skoru eksik bitmiş maç 24 saat boyunca dakikada bir final skoru için izlenir", async () => {
  let hidden = true;
  const fixedNow = Date.UTC(2026, 9, 16, 12, 0, 0);
  const start = new Date(fixedNow - 5 * 60 * 60000);
  const time = new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/Istanbul", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(start);
  const row = featuredLiveRow(300, {
    event_id: "kups-final-retry", home: "KuPS", away: "Trabzonspor", league: "UEFA Avrupa Konferans Ligi",
    starts_at: start.toISOString(), time, status: "finished", status_source: "source", raw_status: "FT",
    status_clock: "", score_home: null, score_away: null, score_source: "", score_updated_at: "",
  });
  const { window, dom } = await loadPage({
    html: withMatches([row]),
    fetchImpl: async () => ({ ok: false, status: 503, json: async () => ({}) }),
    beforeParse: (w) => {
      const NativeDate = w.Date;
      w.Date = class FixedDate extends NativeDate {
        constructor(...args) { if (!args.length) super(fixedNow); else super(...args); }
        static now() { return fixedNow; }
      };
      Object.defineProperty(w.document, "hidden", { configurable: true, get: () => hidden });
    },
  });
  hidden = false;
  const now = new window.Date(fixedNow);
  const path = "soccer/uefa.europa.conf";
  assert.ok(window.inadina.syncWantedPaths(now).includes(path),
    "kickoff’tan beş saat sonra skor yoksa final sonucu aranmaya devam etmeli");
  assert.deepEqual(Array.from(window.inadina.syncDatesForPath(path)), ["20261016"],
    "ESPN’e maçın başladığı gün sorulmalı");
  assert.equal(window.inadina.liveSyncInterval(now), 60000,
    "canlı maç kadar sık değil, eksik final skoru dakikada bir denenmeli");
  assert.ok(!window.inadina.syncWantedPaths(new window.Date(fixedNow + 25 * 60 * 60000)).includes(path),
    "eksik final skoru için sınırsız polling yapılmamalı");

  const updated = window.inadina.applyLiveSync(path, [{
    id: row.event_id, start, homeName: "KuPS Kuopio", awayName: "Trabzonspor",
    homeScore: 2, awayScore: 4, status: "finished", clock: "", neutral: false,
  }], fixedNow);
  assert.equal(updated, 1, "gecikmeli ESPN final olayı eşleşmeli");
  assert.ok(!window.inadina.syncWantedPaths(now).includes(path),
    "final skor geldiğinde 24 saatlik eksik-skor retry’si sona ermeli");
  dom.window.close();
});

test("resmi Günün Maçı bitince kart sıradaki resmi yaklaşan maça geçer", async () => {
  const fixedNow = Date.UTC(2026, 9, 15, 12, 0, 0);
  const fixedRow = (offsetMinutes, extra) => {
    const start = new Date(fixedNow + offsetMinutes * 60000);
    const time = new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/Istanbul", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(start);
    return featuredLiveRow(0, {
      ...extra, starts_at: start.toISOString(), time, score_updated_at: new Date(fixedNow - 60000).toISOString(),
    });
  };
  const trabzon = fixedRow(-70, {
    event_id: "trabzon-first", home: "Trabzonspor", away: "Basel", league: "UEFA Konferans Ligi",
    status: "live", status_source: "espn", raw_status: "STATUS_SECOND_HALF", status_clock: "70′",
    score_home: 1, score_away: 0, score_source: "espn", is_match_of_day: true,
  });
  const besiktas = fixedRow(10, {
    event_id: "besiktas-next", home: "Beşiktaş", away: "Porto", league: "UEFA Avrupa Ligi",
    status: "upcoming", status_source: "schedule", raw_status: "", status_clock: "",
    score_home: null, score_away: null, score_source: "", is_match_of_day: true,
  });
  const unrelatedLive = fixedRow(-30, {
    event_id: "unrelated-live", home: "Chelsea", away: "Arsenal", league: "İngiltere Premier Lig",
    status: "live", status_source: "espn", raw_status: "STATUS_FIRST_HALF", status_clock: "30′",
    score_home: 0, score_away: 0, score_source: "espn", is_match_of_day: false,
  });
  const { window, dom } = await loadPage({
    html: withMatches([trabzon, besiktas, unrelatedLive]),
    fetchImpl: async () => ({ ok: false, status: 503, json: async () => ({}) }),
    beforeParse: (w) => {
      const NativeDate = w.Date;
      w.Date = class FixedDate extends NativeDate {
        constructor(...args) { if (!args.length) super(fixedNow); else super(...args); }
        static now() { return fixedNow; }
      };
      Object.defineProperty(w.document, "hidden", { configurable: true, get: () => true });
    },
  });
  let card = window.document.querySelector("#homeFeaturedSection .home-featured-match");
  assert.ok(card.textContent.includes("Trabzonspor"), "devam eden resmi Günün Maçı korunmalı");

  const finished = window.inadina.applyLiveSync("soccer/uefa.europa.conf", [{
    id: trabzon.event_id, start: new Date(trabzon.starts_at), homeName: trabzon.home, awayName: trabzon.away,
    homeScore: 2, awayScore: 0, status: "finished", clock: "", neutral: false,
  }]);
  assert.equal(finished, 1, "ilk maçın bitiş durumu işlenmeli");
  window.inadina.renderMatches();
  card = window.document.querySelector("#homeFeaturedSection .home-featured-match");
  assert.ok(card.textContent.includes("Beşiktaş") && card.textContent.includes("Porto"),
    "Trabzon maçı bitince sıradaki resmi Beşiktaş maçı öne alınmalı");
  assert.equal(card.dataset.selection, "official");
  assert.equal(card.dataset.status, "upcoming");
  assert.equal(card.dataset.event, "besiktas-next");
  dom.window.close();
});

test("15 dakika eski canlı skor cache’i uygulama dönüşünde ESPN’den hemen tazelenir", async () => {
  let hidden = true;
  const fixedNow = Date.UTC(2026, 9, 16, 12, 0, 0);
  const start = new Date(fixedNow - 35 * 60000);
  const time = new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/Istanbul", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(start);
  const oldAt = fixedNow - 15 * 60000;
  const row = featuredLiveRow(35, {
    starts_at: start.toISOString(), time, status_clock: "34′", score_updated_at: new Date(oldAt).toISOString(),
  });
  const path = "soccer/uefa.champions";
  const cached = { savedAt: oldAt, base: "site.web", paths: { [path]: { at: oldAt, comps: [{
    id: "cached-event", start: row.starts_at, homeName: row.home, awayName: row.away,
    homeScore: 0, awayScore: 0, status: "live", clock: "34′", neutral: false,
  }] } } };
  const freshScoreboard = { events: [{ id: "fresh-event", date: row.starts_at, competitions: [{
    id: "fresh-comp", date: row.starts_at, competitors: [
      { homeAway: "home", score: "1", team: { displayName: row.home } },
      { homeAway: "away", score: "0", team: { displayName: row.away } },
    ], status: { displayClock: "50:00", type: { name: "STATUS_IN_PROGRESS", shortDetail: "50'", state: "in" } },
  }] }] };
  const scoreboardCalls = [];
  const fetchImpl = async (url) => {
    if (String(url).includes("site.web.api.espn.com")) {
      scoreboardCalls.push(String(url));
      return { ok: true, json: async () => freshScoreboard };
    }
    return { ok: false, status: 503, json: async () => ({}) };
  };
  const { window, dom } = await loadPage({
    html: withMatches([row]), fetchImpl,
    beforeParse: (w) => {
      const NativeDate = w.Date;
      w.Date = class FixedDate extends NativeDate {
        constructor(...args) { if (!args.length) super(fixedNow); else super(...args); }
        static now() { return fixedNow; }
      };
      Object.defineProperty(w.document, "hidden", { configurable: true, get: () => hidden });
      w.localStorage.setItem("inadinatv.live-scores.v1", JSON.stringify(cached));
    },
  });
  hidden = false;
  window.document.dispatchEvent(new window.Event("visibilitychange"));
  for (let attempt = 0; attempt < 50 && !scoreboardCalls.length; attempt++) {
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  for (let attempt = 0; attempt < 50; attempt++) {
    const current = window.document.querySelector("#homeFeaturedSection .home-featured-match");
    if (current && current.dataset.clock === "50′") break;
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  const card = window.document.querySelector("#homeFeaturedSection .home-featured-match");
  assert.ok(scoreboardCalls.length > 0, "15 dakikalık cache poll’u engellememeli, görünür olunca ESPN hemen çağrılmalı");
  assert.equal(card.dataset.score, "1-0", "uygulamaya dönünce yeni skor Günün Maçı kartına gelmeli");
  assert.equal(card.dataset.clock, "50′");
  assert.ok(!window.document.querySelector("#homeFeaturedSection .home-featured-freshness").classList.contains("is-stale"),
    "başarılı veri yenilemesi eski skor uyarısını kaldırmalı");
  dom.window.close();
});

test("canlı skor senkronu kesin eşleşmeye skor, dakika ve gol animasyonu işler", async () => {
  const row = remoteRow("b4", "NS", [null, null], { home: "Bournemouth", away: "Liverpool",
    league: "İngiltere Premier Lig", sport: "Futbol", starts_at: "2026-09-06T20:00:00+03:00" });
  const json = { date: "2026-09-06", matches: [row] };
  const { window } = await loadPage({ fetchImpl: async (url) => ({ ok: true, json: async () => String(url).includes("extra_channels") ? EXTRA : json }) });
  await window.inadina.refreshMatches();
  const comps = [{ id: "ev1", start: new Date("2026-09-06T20:00:00+03:00"), homeName: "Bournemouth", awayName: "Liverpool",
    homeScore: 1, awayScore: 0, status: "live", clock: "34'", neutral: false }];
  const cachedAt = Date.parse("2026-09-06T18:10:00.000Z");
  const changes = window.inadina.applyLiveSync("soccer/eng.1", comps, cachedAt);
  assert.equal(changes, 1, "eşleşen maça dokunulmalıydı");
  window.inadina.renderMatches();
  const card = byEvent(window, "b4");
  assert.equal(card.dataset.status, "live");
  assert.equal(card.querySelector('[data-score-side="home"]').textContent, "1");
  assert.ok(card.textContent.includes("34'"), "canlı dakika rozeti yok");
  assert.ok(card.querySelector(".match-score").title.includes("2026-09-06T18:10:00.000Z"),
    "eski yerel cache skoru yeni alınmış gibi timestamp almamalı");
  assert.ok(card.querySelector(".match-score").classList.contains("bump"), "gol animasyonu yok");
  const clockOnly = window.inadina.applyLiveSync("soccer/eng.1", [{ ...comps[0], clock: "35'" }]);
  assert.equal(clockOnly, 1, "skor değişmese de dakika değişimi render tetiklemeli");
  window.inadina.renderMatches();
  assert.ok(byEvent(window, "b4").textContent.includes("35'"));
  const finalChange = window.inadina.applyLiveSync("soccer/eng.1", [{ ...comps[0],
    homeScore: 2, awayScore: 1, status: "finished", clock: "90'" }]);
  assert.equal(finalChange, 1, "final durumu anında işlenmeli");
  window.inadina.renderMatches();
  assert.equal(byEvent(window, "b4").dataset.status, "finished");
  assert.equal(byEvent(window, "b4").querySelector('[data-score-side="home"]').textContent, "2");
  assert.equal(byEvent(window, "b4").querySelector('.match-status-tag').textContent, "MS");
  // Belirsiz (çift aday) eşleşme: hiçbir veri eklenmez
  const before = byEvent(window, "b4").querySelector('[data-score-side="home"]').textContent;
  window.inadina.applyLiveSync("soccer/eng.1", [comps[0], { ...comps[0], id: "ev2" }]);
  window.inadina.renderMatches();
  assert.equal(byEvent(window, "b4").querySelector('[data-score-side="home"]').textContent, before);
});

test("canlı skor senkronu gerçek MS sonucunu canlıya çevirmez", async () => {
  const row = remoteRow("ftx", "FT", [2, 1], { home: "Bournemouth", away: "Liverpool",
    league: "İngiltere Premier Lig", sport: "Futbol", starts_at: "2026-09-06T20:00:00+03:00" });
  const json = { date: "2026-09-06", matches: [row] };
  const { window } = await loadPage({ fetchImpl: async (url) => ({ ok: true, json: async () => String(url).includes("extra_channels") ? EXTRA : json }) });
  await window.inadina.refreshMatches();
  const comps = [{ id: "ev1", start: new Date("2026-09-06T20:00:00+03:00"), homeName: "Bournemouth", awayName: "Liverpool",
    homeScore: 2, awayScore: 2, status: "live", clock: "88'", neutral: false }];
  assert.equal(window.inadina.applyLiveSync("soccer/eng.1", comps), 0, "MS maça dokunulmamalı");
  assert.equal(byEvent(window, "ftx").dataset.status, "finished");
});

test("canlı senkron Fixtoor adaptif temposunu ve tekil UTC-gün scoreboard isteğini kullanır", () => {
  assert.match(HTML, /const SYNC_INTERVALS = \{ live: 5 \* 1000, near: 15 \* 1000, final: 60 \* 1000, idle: 60 \* 1000, error: 120 \* 1000 \}/);
  assert.ok(HTML.includes("FINAL_SCORE_RETRY_WINDOW = 24 * 60 * 60 * 1000"), "skorsuz final sonuçlar 24 saat izlenmeli");
  assert.ok(HTML.includes('start.toISOString().slice(0, 10).replace(/-/g, "")'), "maçın UTC tarihi kullanılmıyor");
  assert.ok(HTML.includes('"?dates=" + encodeURIComponent(day) + "&limit=100"'), "tekil gün query’si yok");
  assert.ok(!HTML.includes('"&_ts="'), "eski 10 saniyelik query cache-buster kalmış");
  assert.ok(HTML.includes("(liveWindowFor(m) + 90) * 60000"), "normal sonuç düzeltme penceresi korunmalı");
});

test("canlı ESPN isteği Fixtoor gibi 200 hata gövdesinde yedek hosta geçer", async () => {
  const calls = [];
  const optionsSeen = [];
  const fetchImpl = async (url, options) => {
    const target = String(url);
    if (target.includes("site.web.api.espn.com")) {
      calls.push("site.web");
      optionsSeen.push(options);
      return { ok: true, json: async () => ({ code: 400, message: "Failed to get events endpoint." }) };
    }
    if (target.includes("site.api.espn.com")) {
      calls.push("site.api");
      optionsSeen.push(options);
      return { ok: true, json: async () => ({ events: [] }) };
    }
    if (target.includes("today_matches.json")) return { ok: true, json: async () => TODAY };
    if (target.includes("extra_channels.json")) return { ok: true, json: async () => EXTRA };
    return { ok: true, json: async () => ({}) };
  };
  const { window, dom } = await loadPage({
    fetchImpl,
    beforeParse(w) { Object.defineProperty(w.document, "hidden", { configurable: true, value: true }); },
  });
  const result = await window.inadina.fetchLiveScoreboard("soccer/eng.1", "?dates=20260906");
  assert.deepEqual(calls, ["site.web", "site.api"]);
  assert.ok(optionsSeen.every((o) => o.mode === "cors" && o.credentials === "omit" && o.cache === "no-store"),
    "cross-origin request Fixtoor’daki gibi credentials olmadan no-store olmalı");
  assert.deepEqual(result.events, []);
  dom.window.close();
});
