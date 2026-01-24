import fs from "fs";
import path from "path";
import https from "https";
import { pipeline } from "stream";
import { promisify } from "util";
import archiver from "archiver";

const streamPipeline = promisify(pipeline);

const DATA_FILE = "./mapping.txt";
const OUT_DIR = "./icons";
const ZIP_FILE = "./icons.zip";

if (!fs.existsSync(OUT_DIR)) {
  fs.mkdirSync(OUT_DIR);
}

const data = JSON.parse(fs.readFileSync(DATA_FILE, "utf8"));

function buildIconUrl(icon) {
  return (
    "https://oldschool.runescape.wiki/images/" +
    encodeURIComponent(icon.replace(/ /g, "_"))
  );
}


function downloadImage(url, dest) {
  return new Promise((resolve, reject) => {
    const req = https.get(
      url,
      {
        headers: {
          "User-Agent": "OSRSIconDownloader/1.0",
          "Accept": "image/png,image/*,*/*"
        }
      },
      (res) => {
        if (res.statusCode !== 200) {
          return reject(new Error(`HTTP ${res.statusCode}`));
        }

        const file = fs.createWriteStream(dest);
        res.pipe(file);
        file.on("finish", () => file.close(resolve));
      }
    );

    req.on("error", reject);
  });
}

const CONCURRENCY = 15; // safe for OSRS Wiki

async function worker(queue) {
  while (queue.length) {
    const item = queue.shift();
    if (!item?.icon) continue;

    const url = buildIconUrl(item.icon);
    const filename = path.join(OUT_DIR, item.icon);

    try {
      await downloadImage(url, filename);
      console.log("Downloaded:", item.icon);
    } catch (err) {
      console.warn("Skipped:", item.icon, err.message);
    }
  }
}

(async () => {
  const queue = [...data];

  const workers = Array.from(
    { length: CONCURRENCY },
    () => worker(queue)
  );

  await Promise.all(workers);

  const output = fs.createWriteStream(ZIP_FILE);
  const archive = archiver("zip", { zlib: { level: 9 } });

  archive.pipe(output);
  archive.directory(OUT_DIR, false);
  await archive.finalize();

  console.log("ZIP created:", ZIP_FILE);
})();
