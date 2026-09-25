import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

const root = new URL("..", import.meta.url).pathname;
const dist = join(root, "dist");
if (!existsSync(join(dist, "index.html"))) throw new Error("dist/index.html bulunamadı");
const html = readFileSync(join(dist, "index.html"), "utf8");
if (!html.includes("MACWEB Community")) throw new Error("Uygulama başlığı build çıktısında yok");
const assets = readdirSync(join(dist, "assets"));
if (!assets.some((file) => file.endsWith(".js"))) throw new Error("JavaScript asset üretilmedi");
if (!assets.some((file) => file.endsWith(".css"))) throw new Error("CSS asset üretilmedi");
console.log(`Smoke test passed: ${assets.length} asset, forum shell present.`);
