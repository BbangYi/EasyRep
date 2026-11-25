"""Download a bounded, explicitly selected Commons photo batch with attribution.

Uses saved public MediaWiki imageinfo metadata. Does not label, split, or train.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import html
import json
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from behavior_recorder.analysis_features import save_artifact
from behavior_recorder.core import require
from behavior_recorder.vision_data import image_info, output_directory


def plain(value):
    return " ".join(html.unescape(re.sub(r"<[^>]*>", " ", value)).split())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--indices", required=True, help="Comma-separated indices in title-sorted saved metadata")
    args = parser.parse_args()
    metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
    pages = sorted(metadata["query"]["pages"].values(), key=lambda row: row["title"])
    selected = [int(value) for value in args.indices.split(",")]
    require(0 < len(selected) <= 50 and len(set(selected)) == len(selected), "select 1-50 unique photos")
    plans = []
    for index in selected:
        page = pages[index]
        info = page["imageinfo"][0]
        extended = info["extmetadata"]
        field = lambda name: extended.get(name, {}).get("value", "")
        license_name = field("LicenseShortName")
        require(license_name in {"CC0", "Public domain", "CC BY 2.0", "CC BY 3.0", "CC BY 4.0",
                                "CC BY-SA 2.0", "CC BY-SA 2.5", "CC BY-SA 3.0", "CC BY-SA 4.0"},
                "source license is outside this importer's explicit allowlist")
        url = info.get("thumburl", info["url"])
        parsed = urllib.parse.urlparse(url)
        require(parsed.scheme == "https" and parsed.hostname in {"upload.wikimedia.org", "thumb.wikimedia.org"},
                "download must be a public Wikimedia media URL")
        suffix = Path(urllib.parse.unquote(parsed.path)).suffix.lower()
        require(suffix in {".jpg", ".jpeg", ".png"}, "photo format not supported")
        plans.append({"selection_index": index, "page_id": page["pageid"], "title": page["title"],
                      "image": f"images/commons-{page['pageid']}{suffix}", "download_url": url,
                      "source_url": info["descriptionurl"], "original_url": info["url"],
                      "original_sha1": info["sha1"], "author": plain(field("Artist")),
                      "license": license_name, "license_url": field("LicenseUrl") or info["descriptionurl"],
                      "description": plain(field("ImageDescription")), "date": plain(field("DateTimeOriginal")),
                      "changes": "Wikimedia-supplied thumbnail where available; no annotation yet"})
    with output_directory(args.output, "download_unreviewed_public_photos") as run:
        (run / "images").mkdir()

        def download(row):
            request = urllib.request.Request(row["download_url"], headers={"User-Agent": "EasyRep-Research/0.1 (bounded public photo import)"})
            for attempt in range(2):
                try:
                    with urllib.request.urlopen(request, timeout=40) as response:
                        require(urllib.parse.urlparse(response.url).hostname in {"upload.wikimedia.org", "thumb.wikimedia.org"},
                                "unexpected media redirect")
                        data = response.read(8 * 1024**2 + 1)
                    break
                except urllib.error.HTTPError as exc:
                    if exc.code != 429 or attempt:
                        raise
                    delay = max(60, int(exc.headers.get("Retry-After", "60")))
                    require(delay <= 300, "source rate limit requires a later retry")
                    print(f"Source requested a pause; retrying once after {delay}s", flush=True)
                    time.sleep(delay)
            time.sleep(1)
            require(0 < len(data) <= 8 * 1024**2, "download size outside limit")
            path = run / row["image"]
            path.write_bytes(data)
            return {**row, "sha256": hashlib.sha256(data).hexdigest(), **image_info(path), "reviewed": False}

        with ThreadPoolExecutor(max_workers=1) as pool:
            records = list(pool.map(download, plans))
        save_artifact(run / "sources.json", {"metadata_sha256": hashlib.sha256(args.metadata.read_bytes()).hexdigest(),
                                              "ready_for_training": False, "photos": records})
        print(f"Downloaded {len(records)} unreviewed real-source photos to {run}")


if __name__ == "__main__":
    main()
