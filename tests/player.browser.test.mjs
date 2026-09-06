/** Gerçek Chromium + hls.js + sentetik H.264/AAC HLS. Harici yayına/ağa bağlı değil.
 * npm run test:browser (önce npx playwright install --with-deps chromium)
 * İsteğe bağlı: CHROMIUM_EXECUTABLE, PYTHON, SCREENSHOT_DIR.
 */
import { before, after, test } from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { readFileSync, existsSync, mkdirSync } from 'node:fs';
import { createInterface } from 'node:readline';
import { chromium } from 'playwright';

let browser, fixture, urls;
const script = readFileSync('node_modules/hls.js/dist/hls.min.js');
before(async () => {
  const python = process.env.PYTHON || (existsSync('.venv/bin/python') ? '.venv/bin/python' : 'python');
  fixture = spawn(python, ['tests/browser_fixture_server.py'], { stdio: ['ignore', 'pipe', 'pipe'] });
  let stderr = '';
  fixture.stderr.on('data', data => { stderr += data; });
  urls = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('Test service startup timeout: ' + stderr)), 10000);
    createInterface({ input: fixture.stdout }).once('line', line => {
      clearTimeout(timer);
      try { resolve(JSON.parse(line)); } catch (e) { reject(e); }
    });
    fixture.once('exit', code => { clearTimeout(timer); reject(new Error('Test service exited: ' + code + stderr)); });
  });
  browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || undefined,
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--no-zygote'] });
}, { timeout: 20000 });
after(async () => {
  if (browser) await browser.close();
  if (fixture && fixture.exitCode === null) {
    const exited = new Promise(resolve => fixture.once('exit', resolve));
    fixture.kill('SIGTERM');
    await exited;
  }
});

async function page(options = {}) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, ...options });
  // Hls kütüphanesi pinli npm sürümünden, diğer tüm istekler sadece test HTTP servislerinden.
  await context.route('**/*', async route => {
    const url = route.request().url();
    if (url.includes('/hls.js@') && url.endsWith('/hls.min.js')) return route.fulfill({ contentType: 'application/javascript', body: script });
    if (url.startsWith(urls.page) || url.startsWith(urls.upstream)) return route.continue();
    return route.abort();
  });
  const p = await context.newPage();
  const errors = [];
  p.on('pageerror', error => errors.push(error.message));
  await p.goto(urls.page);
  await p.waitForFunction(() => window.inadina?.ready);
  return { p, context, errors };
}

async function play(p, id) {
  await p.evaluate(id => window.inadina.playExtra(id, false), id);
  // Otomatik oynatmayı reddeden gerçek tarayıcıda da kullanıcı yolu sınanır.
  await p.waitForFunction(() => document.getElementById('playerStart').classList.contains('active') ||
    document.getElementById('hlsVideo').currentTime > .15 || document.getElementById('playerError').classList.contains('active'), null, { timeout: 20000 });
  if (await p.locator('#playerStart').evaluate(el => el.classList.contains('active'))) await p.locator('#startStreamBtn').click();
  try {
    await p.waitForFunction(() => document.getElementById('hlsVideo').currentTime > .3 &&
      !document.getElementById('playerLoading').classList.contains('active'), null, { timeout: 15000 });
  } catch (error) {
    throw new Error('Playback failed: ' + JSON.stringify(await p.evaluate(() => window.inadina.playerLogs)), { cause: error });
  }
  const video = await p.locator('#hlsVideo').evaluate(v => ({ width: v.videoWidth, height: v.videoHeight, time: v.currentTime, error: v.error?.code }));
  assert.equal(video.width, 192);
  assert.equal(video.height, 108);
  assert.ok(video.time > 0);
  assert.equal(video.error, undefined);
  assert.equal(await p.locator('#playerError').evaluate(el => el.classList.contains('active')), false);
}

for (const [id, title] of [['test:ts', '302 + master/media + göreli .jpg MPEG-TS'],
  ['test:fmp4', 'master + fMP4 init/audio/video'], ['test:range', 'media-only + byte-range fMP4'],
  ['test:encrypted', 'header gerektiren AES key/segment: doğrudan hata -> gerçek proxy'],
  ['test:range-proxy', 'proxy üzerinden init/byte-range HTTP 206']]) {
  test(title, { timeout: 40000 }, async () => {
    const { p, context, errors } = await page();
    try {
      await play(p, id);
      assert.deepEqual(errors, []);
      assert.ok((await p.evaluate(() => window.inadina.playerLogs)).some(r => r.message.includes('HLS listesi ayrıştırıldı')), 'Chromium MSE/hls.js kullanmalı');
      if (id === 'test:encrypted' || id === 'test:range-proxy') {
        const logs = await p.evaluate(() => window.inadina.playerLogs);
        assert.ok(logs.some(r => r.transport === 'proxy'));
        const requests = await (await fetch(urls.upstream + '/requests')).json();
        const prefix = id === 'test:encrypted' ? '/encrypted/' : '/protected-range/';
        assert.ok(requests.some(r => r.path.startsWith(prefix) && r.headers_ok));
        if (id === 'test:encrypted') {
          assert.ok(requests.some(r => r.path.startsWith('/encrypted/key.bin') && r.headers_ok));
          assert.ok(requests.some(r => r.path.startsWith('/encrypted/part') && r.headers_ok));
        } else assert.ok(requests.some(r => r.path.startsWith(prefix) && r.range && r.headers_ok));
      }
    } finally { await context.close(); }
  });
}

test('mobil/masaüstü skor kartları uzun isimlerde taşmıyor; status ve skor canlı veriden', { timeout: 30000 }, async () => {
  const { p, context, errors } = await page({ timezoneId: 'America/Los_Angeles' });
  const names = ['Çok Uzun Ev Sahibi Takımı Futbol Kulübü', 'Çok Uzun Deplasman Takımı Spor Kulübü'];
  const rows = ['FT','HT','LIVE','NS','PST','CANC'].map((status, i) => ({event_id: 'event'+i, match_id:'ss', home:names[0], away:names[1],
    time:'20:00', sport:'Futbol', league:'Test Ligi', status, status_source:'source', score_home:i === 2 ? 0 : 2, score_away:i === 2 ? 0 : 1,
    score_source:'source', score_updated_at:new Date().toISOString()}));
  try {
    await context.route('**/output/today_matches.json?*', route => route.fulfill({ json: { date:'2026-09-06', matches:rows } }));
    await p.evaluate(async () => { await window.inadina.refreshMatches(); window.inadina.setTab('matchesTab'); });
    assert.equal(await p.locator('.match-score').count(), 3);
    assert.equal(await p.locator('[data-event="event0"] .match-status-tag').textContent(), 'MS');
    for (const width of [320, 375, 768, 1440]) {
      await p.setViewportSize({width, height:1000});
      const problems = await p.evaluate(() => {
        const errors=[];
        for(const card of document.querySelectorAll('.match-card')) {
          const c=card.getBoundingClientRect();
          for(const child of card.querySelectorAll('.match-teams,.match-team,.match-score,.match-status-tag')) {
            const b=child.getBoundingClientRect();
            if(b.right>c.right+1 || b.left<c.left-1) errors.push(child.className);
          }
        }
        if(document.documentElement.scrollWidth>innerWidth) errors.push('document overflow');
        return errors;
      });
      assert.deepEqual(problems, [], 'overflow at '+width);
    }
    if (process.env.SCREENSHOT_DIR) {
      mkdirSync(process.env.SCREENSHOT_DIR, {recursive:true});
      await p.setViewportSize({width:375,height:1000});
      await p.locator('#matchesGrid').screenshot({path:process.env.SCREENSHOT_DIR+'/match-cards-mobile.png'});
    }
    assert.deepEqual(errors, []);
  } finally { await context.close(); }
});
