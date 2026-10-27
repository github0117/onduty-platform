#!/usr/bin/env node
/**
 * Record the routed-dispatch demo against the seeded local stack and export
 * the video to docs/assets/demo/.
 *
 * Usage (from apps/web):
 *   pnpm demo:video
 *
 * Prerequisites:
 *   - the compose stack is running (web on 5173 by default)
 *   - demo data is seeded (make seed / scripts/seed_demo_data.py)
 */
import { spawnSync } from "node:child_process";
import {
  copyFileSync,
  existsSync,
  mkdirSync,
  readdirSync,
  statSync,
} from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const webDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repoDir = resolve(webDir, "../..");
const outputDir = join(webDir, "demo-output");
const assetDir = join(repoDir, "docs/assets/demo");
const baseName = "on-duty-routing-demo";

function findVideos(directory) {
  if (!existsSync(directory)) return [];
  const videos = [];
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const fullPath = join(directory, entry.name);
    if (entry.isDirectory()) {
      videos.push(...findVideos(fullPath));
    } else if (entry.name.endsWith(".webm")) {
      videos.push({
        path: fullPath,
        mtime: statSync(fullPath).mtimeMs,
      });
    }
  }
  return videos;
}

const npx = process.platform === "win32" ? "npx.cmd" : "npx";
const recording = spawnSync(
  npx,
  ["playwright", "test", "-c", "playwright.demo.config.ts"],
  {
    cwd: webDir,
    stdio: "inherit",
    env: { ...process.env, RECORD_DEMO: "1" },
  },
);

if (recording.status !== 0) {
  process.exit(recording.status ?? 1);
}

const videos = findVideos(outputDir).sort((left, right) => right.mtime - left.mtime);
if (videos.length === 0) {
  console.error(`No recorded video found under ${outputDir}`);
  process.exit(1);
}

mkdirSync(assetDir, { recursive: true });
const webmPath = join(assetDir, `${baseName}.webm`);
copyFileSync(videos[0].path, webmPath);
console.log(`\nSaved video: ${webmPath}`);

const ffmpeg = spawnSync("ffmpeg", ["-version"], { stdio: "ignore" });
if (ffmpeg.status === 0) {
  const mp4Path = join(assetDir, `${baseName}.mp4`);
  const conversion = spawnSync(
    "ffmpeg",
    [
      "-y",
      "-i",
      webmPath,
      "-an",
      "-c:v",
      "libx264",
      "-preset",
      "medium",
      "-crf",
      "22",
      "-pix_fmt",
      "yuv420p",
      "-movflags",
      "+faststart",
      mp4Path,
    ],
    { stdio: "inherit" },
  );
  if (conversion.status === 0) {
    console.log(`Saved MP4:   ${mp4Path}`);
  } else {
    console.warn("ffmpeg conversion failed; the WebM recording is still usable.");
  }

  const posterPath = join(assetDir, `${baseName}.jpg`);
  const poster = spawnSync(
    "ffmpeg",
    ["-y", "-ss", "4", "-i", mp4Path, "-frames:v", "1", "-vf", "scale=1200:-1", posterPath],
    { stdio: "ignore" },
  );
  if (poster.status === 0) {
    console.log(`Saved poster: ${posterPath}`);
  }

  const coverScript = join(webDir, "scripts/make-demo-cover.mjs");
  const cover = spawnSync(
    process.execPath,
    [coverScript, mp4Path, join(assetDir, `${baseName}-cover.jpg`)],
    { stdio: "inherit" },
  );
  if (cover.status !== 0) {
    console.warn("Cover generation failed; the recorded video is still usable.");
  }
} else {
  console.log("ffmpeg is not installed; skipped MP4 export and poster.");
}
