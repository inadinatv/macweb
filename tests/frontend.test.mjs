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
  // sekmeler: kanallar + günün maçları + extra (ayrı "canlı maçlar" sekmesi kaldırıldı)
  assert.equal((HTML.match(/class="tab-btn/g) || []).length, 3, "üç sekme olmalı");
  assert.ok(!/CANLI MAÇLAR/.test(HTML), "sahte canlı maç sekmesi duruyor");
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
  assert.ok(text.includes("⭐ Günün Maçı"), "günün maçı rozeti yok");
  assert.equal(window.document.querySelectorAll(".match-card.is-mod").length, 1, "tek günün maçı olmalı");
  assert.equal(window.document.getElementById("badgeMatches").textContent, String(TODAY.matches.length));
  dom.window.close();
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
  assert.equal(cs(m, new Date("2026-09-05T21:59:00+03:00")).status, "live");
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

test("EXTRA sekmesi Atom kanallarını m3u8 kartları olarak listeliyor", async () => {
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
    assert.deepEqual(loads, hlsSources.map((s) => "load:" + s.url), "kaynaklar sırayla denenmedi");
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

test("panel çipleri EXTRA kartlarını panele göre süzüyor (ATOM / SELÇUK)", async () => {
  const { window, dom } = await loadPage();
  window.inadina.setTab("extraTab");
  assert.ok(EXTRA.panels.length >= 2, "en az iki extra panel bekleniyor (atom + selcuk)");
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
  window.fireDeadline(25000);await tick();
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
  const {window}=await loadPage({beforeParse:w=>{
    captureDeadlines(w);Object.defineProperty(w.HTMLMediaElement.prototype,'paused',{configurable:true,get(){return false;}});
  }});
  window.inadina.playExtra(window.inadina.extraChannels()[0].id,false);await tick();
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
  const {window}=await loadPage({beforeParse:w=>{w.SavedHls=w.Hls;delete w.Hls;}});
  window.inadina.playExtra(window.inadina.extraChannels()[0].id,false);
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
  window.fetch=()=>new Promise(resolve=>pending.push(resolve));
  const old=window.inadina.refreshMatches();
  const fresh=window.inadina.refreshMatches();
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
