import { chromium } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { pathToFileURL, fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const frontendDir = resolve(scriptDir, "..");
const videoPath = resolve(frontendDir, "..", "docs", "assets", "portfolio-demo.webm");
const frameDir = resolve(frontendDir, "test-results", "portfolio-video", "keyframes");
await mkdir(frameDir, { recursive: true });

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
await page.goto(pathToFileURL(videoPath).href);
const video = page.locator("video");
await video.waitFor();
const duration = await video.evaluate((node) => new Promise((resolveDuration) => {
  if (Number.isFinite(node.duration)) resolveDuration(node.duration);
  else node.addEventListener("loadedmetadata", () => resolveDuration(node.duration), { once: true });
}));

const times = [
  5,
  duration * 0.25,
  duration * 0.5,
  duration * 0.75,
  Math.min(duration - 0.1, 210),
  Math.min(duration - 0.1, 230),
  Math.max(0, duration - 5),
];
const frames = [];
for (let index = 0; index < times.length; index += 1) {
  const time = Math.min(times[index], Math.max(0, duration - 0.1));
  await video.evaluate((node, nextTime) => new Promise((resolveSeek) => {
    node.addEventListener("seeked", resolveSeek, { once: true });
    node.currentTime = nextTime;
  }), time);
  const framePath = resolve(frameDir, `frame-${index + 1}.png`);
  await video.screenshot({ path: framePath });
  frames.push({ time_seconds: Number(time.toFixed(2)), path: framePath });
}

await browser.close();
console.log(JSON.stringify({
  videoPath,
  duration_seconds: Number(duration.toFixed(2)),
  frames,
}, null, 2));
