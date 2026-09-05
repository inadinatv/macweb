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
      if (options.fetchImpl) window.fetch = options.fetchImpl;
    },
  });
  const window = dom.window;
  // init() DOMContentLoaded'da çalışır
  for (let i = 0; i < 100 && !window.inadina; i++) {
    await new Promise((r) => setTimeout(r, 10));
  }
  assert.ok(window.inadina, "sayfa script'i çalışmadı (window.inadina yok) — hatalar: " + errors.join("; "));
  return { dom, window, errors };
}

const cards = (window) => window.document.querySelectorAll(".ch-card");
const matchCards = (window) => window.document.querySelectorAll(".match-card");

test("sayfada sunucu/adres yazısı ve uydurma maç verisi yok", () => {
  assert.ok(!/Sunucu/i.test(HTML), "'Sunucu' yazısı hâlâ duruyor");
  assert.ok(!HTML.includes("Galatasaray - Fenerbahçe"), "uydurma canlı maç duruyor");
  assert.ok(!HTML.includes("Golden State Warriors"), "uydurma NBA maçı duruyor");
  assert.ok(!HTML.includes("Carlos Alcaraz"), "uydurma tenis maçı duruyor");
  assert.ok(HTML.includes("channel.html?id=zirve"), "gerçek kanal bağlantısı yok");
  // sekmeler: kanallar + günün maçları (ayrı "canlı maçlar" sekmesi kaldırıldı)
  assert.equal((HTML.match(/class="tab-btn/g) || []).length, 2, "iki sekme olmalı");
  assert.ok(!/CANLI MAÇLAR/.test(HTML), "sahte canlı maç sekmesi duruyor");
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
