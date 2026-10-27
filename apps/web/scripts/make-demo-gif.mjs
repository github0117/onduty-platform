#!/usr/bin/env node
/**
 * Build the full-width README demo GIF from the recorded MP4.
 *
 * GitHub only plays README <video> tags from user-attachments (S3). Some
 * Chrome networks cannot reach that host, so the README embeds a GIF instead.
 * The first 1.2s of the recording is a blank intro; skip it so the GIF opens
 * on the workbench.
 *
 * Usage (from apps/web):
 *   pnpm demo:gif
 */
import { spawnSync } from "node:child_process";
import { existsSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const webDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repoDir = resolve(webDir, "../..");
const assetDir = join(repoDir, "docs/assets/demo");
const input = join(assetDir, "on-duty-routing-demo.mp4");
const output = join(assetDir, "on-duty-routing-demo.gif");

if (!existsSync(input)) {
  console.error(`Missing ${input}; run pnpm demo:video first.`);
  process.exit(1);
}

const ffmpeg = spawnSync("ffmpeg", ["-version"], { stdio: "ignore" });
if (ffmpeg.status !== 0) {
  console.error("ffmpeg is required to build the demo GIF.");
  process.exit(1);
}

const filter =
  "fps=8,scale=800:-2:flags=lanczos,split[s0][s1];" +
  "[s0]palettegen=max_colors=96:stats_mode=diff[p];" +
  "[s1][p]paletteuse=dither=bayer:bayer_scale=3";

const result = spawnSync(
  "ffmpeg",
  ["-y", "-ss", "1.2", "-i", input, "-vf", filter, "-loop", "0", output],
  { stdio: "inherit" },
);
if (result.status !== 0) {
  process.exit(result.status ?? 1);
}

const { size } = statSync(output);
console.log(`Saved GIF: ${output} (${(size / 1024 / 1024).toFixed(1)} MB)`);
