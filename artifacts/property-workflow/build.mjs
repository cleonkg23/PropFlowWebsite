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

console.log(`\nStatic site built to ${OUT}`);
console.log("Upload these files to your GitHub repo for GitHub Pages.");
