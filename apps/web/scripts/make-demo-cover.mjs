#!/usr/bin/env node
/**
 * Build a backup cover image for the demo video.
 *
 * Usage (from apps/web):
 *   node scripts/make-demo-cover.mjs [input.mp4] [output.jpg]
 */
import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const webDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repoDir = resolve(webDir, "../..");
const assetDir = join(repoDir, "docs/assets/demo");
const input = resolve(
  process.argv[2] ?? join(assetDir, "on-duty-routing-demo.mp4"),
);
const output = resolve(
  process.argv[3] ?? join(assetDir, "on-duty-routing-demo-cover.jpg"),
);
const frameTime = process.env.DEMO_COVER_TIME ?? "15";

const ffmpeg = spawnSync("ffmpeg", ["-version"], { stdio: "ignore" });
if (ffmpeg.status !== 0) {
  console.error("ffmpeg is required to extract the cover frame.");
  process.exit(1);
}

const tempDir = mkdtempSync(join(tmpdir(), "demo-cover-"));
const framePath = join(tempDir, "frame.png");

try {
  const frame = spawnSync(
    "ffmpeg",
    [
      "-y",
      "-ss",
      frameTime,
      "-i",
      input,
      "-frames:v",
      "1",
      framePath,
    ],
    { stdio: "ignore" },
  );
  if (frame.status !== 0) {
    throw new Error(`Could not extract a frame at ${frameTime}s from ${input}`);
  }

  const frameData = readFileSync(framePath).toString("base64");
  const html = `<!doctype html>
<html><head><meta charset="utf-8"><style>
  * { box-sizing: border-box; }
  html, body { margin: 0; width: 1200px; height: 750px; overflow: hidden; }
  body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; }
  .frame { position: fixed; inset: 0; background: url(data:image/png;base64,${frameData}) center/cover no-repeat; }
  .shade {
    position: fixed; inset: 0;
    background:
      radial-gradient(ellipse at 50% 46%, rgba(15,23,42,0.06) 0%, rgba(15,23,42,0.18) 58%, rgba(15,23,42,0.52) 100%),
      linear-gradient(180deg, rgba(2,6,23,0.36) 0%, rgba(2,6,23,0.04) 24%, rgba(2,6,23,0.02) 62%, rgba(2,6,23,0.48) 100%);
  }
  .play {
    position: fixed; left: 50%; top: 45%;
    width: 132px; height: 132px; margin: -66px 0 0 -66px;
    border-radius: 50%;
    background: rgba(15,23,42,0.60);
    border: 3px solid rgba(255,255,255,0.92);
    box-shadow: 0 18px 60px rgba(2,6,23,0.45), inset 0 0 0 10px rgba(255,255,255,0.06);
    backdrop-filter: blur(6px);
  }
  .tri {
    position: absolute; left: 50%; top: 50%;
    width: 0; height: 0; margin: -26px 0 0 -18px;
    border-top: 26px solid transparent; border-bottom: 26px solid transparent;
    border-left: 42px solid #ffffff;
    filter: drop-shadow(0 2px 6px rgba(2,6,23,0.35));
  }
  .cta {
    position: fixed; left: 50%; top: 45%; transform: translate(-50%, 96px);
    padding: 12px 24px; border-radius: 999px;
    color: #f8fafc; font-size: 22px; font-weight: 600; letter-spacing: 0.02em;
    white-space: nowrap;
    background: rgba(15,23,42,0.78);
    border: 1px solid rgba(255,255,255,0.20);
    box-shadow: 0 10px 30px rgba(2,6,23,0.30);
    backdrop-filter: blur(8px);
  }
  .cta .dot { color: #60a5fa; margin-right: 8px; }
</style></head>
<body>
  <div class="frame"></div>
  <div class="shade"></div>
  <div class="play"><div class="tri"></div></div>
  <div class="cta"><span class="dot">●</span>60 秒演示 · 点击全屏播放</div>
</body></html>`;

  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({
      viewport: { width: 1200, height: 750 },
      deviceScaleFactor: 1,
    });
    await page.setContent(html, { waitUntil: "load" });
    await page.waitForTimeout(250);
    mkdirSync(dirname(output), { recursive: true });
    await page.screenshot({ path: output, type: "jpeg", quality: 90 });
  } finally {
    await browser.close();
  }

  console.log(`Saved cover: ${output}`);
} catch (error) {
  console.error(error instanceof Error ? error.message : error);
  process.exitCode = 1;
} finally {
  rmSync(tempDir, { recursive: true, force: true });
}
