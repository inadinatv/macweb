/**
 * İNADİNA TV index.html arayüz testleri (jsdom).
 *
 * Bu testler üretilen index.html'in *gerçek* JavaScript'ini çalıştırır:
 * kanal kartları, ızgara/liste görünümü, player'e kaydırma, günün maçları,
 * arama/filtre ve canlı veri tazeleme.
 *
 *   npm install && npm test
 */
import test from "node:test";
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

async function loadPage(options = {}) {
  const errors = [];
  const virtualConsole = new VirtualConsole();
  virtualConsole.on("jsdomError", (e) => errors.push(String(e && e.message)));
  const dom = new JSDOM(HTML, {
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
          constructor() { this.handlers = {}; window.hlsInstances = (window.hlsInstances || []).concat(this); }
          on(evt, fn) { this.handlers[evt] = fn; }
          loadSource(url) { window.hlsLog.push("load:" + url); this.url = url; }
          attachMedia(video) {
            this.video = video;
            const behavior = (options.behavior && options.behavior(this.url)) || "ok";
            setTimeout(() => {
              if (behavior === "ok") this.handlers[FakeHls.Events.MANIFEST_PARSED] && this.handlers[FakeHls.Events.MANIFEST_PARSED]();
              else this.handlers[FakeHls.Events.ERROR] && this.handlers[FakeHls.Events.ERROR]("hlsError",
                { fatal: true, type: FakeHls.ErrorTypes.NETWORK_ERROR, details: FakeHls.ErrorDetails.MANIFEST_LOAD_ERROR });
            }, 5);
          }
          destroy() { window.hlsLog.push("destroy:" + this.url); }
          startLoad() {}
          recoverMediaError() {}
        };
        window.Hls.Events = { MANIFEST_PARSED: "hlsManifestParsed", ERROR: "hlsError" };
        window.Hls.ErrorTypes = { NETWORK_ERROR: "networkError", MEDIA_ERROR: "mediaError" };
        window.Hls.ErrorDetails = { MANIFEST_LOAD_ERROR: "manifestLoadError", MANIFEST_LOAD_TIMEOUT: "manifestLoadTimeOut", MANIFEST_PARSING_ERROR: "manifestParsingError" };
      }
      if (options.fetchImpl) window.fetch = options.fetchImpl;
    },
  });
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
  assert.ok(text.includes("Fenerbahçe"), "gerçek maç yok: " + text.slice(0, 120));
  assert.ok(text.includes("Newcastle"), "gerçek maç yok");
  assert.ok(text.includes("⭐ Günün Maçı"), "günün maçı rozeti yok");
  assert.equal(window.document.querySelectorAll(".match-card.is-mod").length, 1, "tek günün maçı olmalı");
  assert.equal(window.document.getElementById("badgeMatches").textContent, String(TODAY.matches.length));
  dom.window.close();
});

test("maç kartındaki İZLE butonu yayını player'de açıyor", async () => {
  const { window, dom } = await loadPage();
  window.inadina.setTab("matchesTab");
  const first = matchCards(window)[0];
  const expected = [...TODAY.matches].sort((a, b) => a.time.localeCompare(b.time))[0];
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
  assert.equal(cs(m, new Date("2026-09-05T19:30:00")).status, "upcoming");
  assert.equal(cs(m, new Date("2026-09-05T20:05:00")).status, "live");
  assert.equal(cs(m, new Date("2026-09-05T21:59:00")).status, "live");
  assert.equal(cs(m, new Date("2026-09-05T22:30:00")).status, "finished");
  // voleybol için pencere daha uzun (150 dk)
  const v = { time: "20:00", date: "2026-09-05", sport: "Voleybol" };
  assert.equal(cs(v, new Date("2026-09-05T22:20:00")).status, "live");
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
  assert.equal(first.querySelector(".ch-status").textContent, "M3U8");
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
  assert.ok(window.document.getElementById("nowStatus").textContent.includes("M3U8"));
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
