import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.join(__dirname, "dist");

const FILES = [
  "index.html",
  "404.html",
  "styles.css",
  "script.js",
  ".nojekyll",
];

fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(OUT, { recursive: true });

for (const file of FILES) {
  const from = path.join(__dirname, file);
  if (fs.existsSync(from)) {
    fs.copyFileSync(from, path.join(OUT, file));
    console.log(`copied ${file}`);
  }
}

const ASSETS_SRC = path.join(__dirname, "assets");
if (fs.existsSync(ASSETS_SRC)) {
  fs.cpSync(ASSETS_SRC, path.join(OUT, "assets"), { recursive: true });
  console.log("copied assets/");
}

console.log(`\nStatic site built to ${OUT}`);
console.log("Upload these files to your GitHub repo for GitHub Pages.");
