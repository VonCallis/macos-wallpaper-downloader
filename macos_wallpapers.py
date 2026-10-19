#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
macOS Wallpaper Downloader

Downloads official macOS wallpapers straight from Apple's
MobileAsset catalog (mesu.apple.com → updates.cdn-apple.com).

Usage:
    python macos_wallpapers.py --list
    python macos_wallpapers.py --all --extract
    python macos_wallpapers.py --select 1,3,5 -o ~/wallpapers

Requirements: requests, tqdm  (pip install requests tqdm)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import plistlib
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime, timezone

# ── Windows UTF-8 fix ────────────────────────────────────────────────────────
for _stream in (sys.stdout, sys.stderr):
    if _stream and getattr(_stream, "encoding", "utf-8").lower().replace("-", "") != "utf8":
        _stream.reconfigure(encoding="utf-8", errors="replace")

try:
    import requests
    from tqdm import tqdm
except ImportError:
    sys.exit("Dependencias faltando. Execute:  pip install requests tqdm")

# ── Constants ────────────────────────────────────────────────────────────────

_MESU = "https://mesu.apple.com/assets/macos"

CATALOGS: dict[str, dict[str, str]] = {
    "desktop": {
        "label": "Desktop Wallpapers",
        "url": f"{_MESU}/com_apple_MobileAsset_DesktopPicture/com_apple_MobileAsset_DesktopPicture.xml",
    },
    "aerial": {
        "label": "Aerial Screensavers",
        "url": f"{_MESU}/com_apple_MobileAsset_IdleScreenBulider/com_apple_MobileAsset_IdleScreenBulider.xml",
    },
}

USER_AGENT = "AssetCacheLocatorService/1.0 Darwin/23.0.0 (MacBookPro18,1; macOS 15.0)"
CHUNK = 1 << 16  # 64 KiB


# ── Helpers ──────────────────────────────────────────────────────────────────

def hr(char: str = "-", width: int = 70) -> None:
    print(char * width)


def fmt_size(n: int | float) -> str:
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} TB"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# ── Asset helpers ────────────────────────────────────────────────────────────

def asset_url(a: dict) -> str | None:
    """Build the full CDN URL for an asset entry."""
    base = a.get("__BaseURL", "")
    rel = a.get("__RelativePath", "")
    if base and rel:
        return f"{base.rstrip('/')}/{rel.lstrip('/')}"
    return a.get("URL") or a.get("url")


def asset_label(a: dict) -> str:
    """Human-readable one-liner for an asset."""
    name = next(
        (a[k] for k in ("LocaleName", "DisplayName", "copyright", "DesktopDescription") if a.get(k)),
        None,
    )
    ver = a.get("OSVersion", "")
    build = a.get("Build", "")
    parts = [x for x in (name, f"macOS {ver}" if ver else "", f"[{build}]" if build else "") if x]
    return " - ".join(parts) or "(no description)"


def asset_size(a: dict) -> int:
    return a.get("_DownloadSize") or a.get("DownloadSize") or 0


def asset_hash(a: dict) -> str | None:
    return a.get("_Measurement") or a.get("SHA256")


# ── Catalog ──────────────────────────────────────────────────────────────────

def fetch_catalog(catalog_key: str, session: requests.Session) -> list[dict]:
    """Fetch and parse the Apple MobileAsset XML plist catalog."""
    cat = CATALOGS[catalog_key]
    print(f"[*] Fetching catalog: {cat['label']}")
    print(f"    {cat['url']}")

    resp = session.get(cat["url"], timeout=30)
    resp.raise_for_status()

    assets: list[dict] = plistlib.loads(resp.content).get("Assets", [])
    print(f"[+] {len(assets)} asset(s) found\n")
    return assets


# ── Display ──────────────────────────────────────────────────────────────────

def print_table(assets: list[dict]) -> None:
    hr()
    print(f"{'#':>4}  {'Description':<48} {'Size':>9}")
    hr()
    for i, a in enumerate(assets, 1):
        print(f"{i:>4}  {asset_label(a):<48} {fmt_size(asset_size(a)):>9}")
    hr()


# ── Download / Extract ───────────────────────────────────────────────────────

def download(url: str, dest: Path, session: requests.Session, expected_hash: str | None = None) -> bool:
    """Stream-download *url* to *dest* with progress bar and optional SHA-256 check."""
    tmp = dest.with_suffix(".part")
    try:
        resp = session.get(url, stream=True, timeout=120)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"    FAIL: {exc}")
        return False

    total = int(resp.headers.get("Content-Length", 0))
    with tmp.open("wb") as fh, tqdm(
        total=total or None,
        unit="B",
        unit_scale=True,
        unit_divisor=1024,
        desc=f"    {dest.name[:50]}",
        leave=False,
    ) as bar:
        for chunk in resp.iter_content(CHUNK):
            fh.write(chunk)
            bar.update(len(chunk))

    if expected_hash and sha256_of(tmp) != expected_hash:
        print(f"    SHA-256 mismatch — deleted")
        tmp.unlink(missing_ok=True)
        return False

    tmp.rename(dest)
    return True


def extract_zip(zip_path: Path, out: Path) -> list[Path]:
    """Extract *zip_path* into *out*, returning the list of extracted files."""
    files: list[Path] = []
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            target = out / Path(info.filename).name
            if not target.exists():
                with z.open(info) as src, target.open("wb") as dst:
                    dst.write(src.read())
            files.append(target)
    return files


# ── Interactive selection ────────────────────────────────────────────────────

def prompt_selection(total: int) -> list[int]:
    """Interactive prompt — returns 0-based indices."""
    print("\nSelect assets to download:")
    print("  Numbers separated by comma (e.g. 1,3,5)")
    print("  'all' to download everything")
    print("  'q'   to quit\n")

    while True:
        raw = input("Choice: ").strip().lower()
        if raw == "q":
            return []
        if raw == "all":
            return list(range(total))
        try:
            idx = [int(x) - 1 for x in raw.split(",")]
            if all(0 <= i < total for i in idx):
                return idx
        except ValueError:
            pass
        print(f"  Invalid input. Enter numbers between 1 and {total}.")


# ── Stats ────────────────────────────────────────────────────────────────────

@dataclass
class Stats:
    ok: int = 0
    skipped: int = 0
    failed: int = 0

    def summary(self) -> str:
        return f"Downloaded: {self.ok}  |  Skipped: {self.skipped}  |  Failed: {self.failed}"


# ── Core pipeline ────────────────────────────────────────────────────────────

def download_selected(
    assets: list[dict],
    indices: list[int],
    out_dir: Path,
    session: requests.Session,
    do_extract: bool,
) -> Stats:
    """Download the selected assets and optionally extract zips."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stats = Stats()

    print(f"\n[*] Downloading {len(indices)} asset(s) to: {out_dir.resolve()}\n")

    for idx in indices:
        a = assets[idx]
        url = asset_url(a)
        if not url:
            print(f"[{idx+1}] No URL — skipped")
            stats.failed += 1
            continue

        filename = Path(url.split("?")[0]).name or f"asset_{idx+1}.zip"
        dest = out_dir / filename

        print(f"[{idx+1}/{len(assets)}] {asset_label(a)}")
        print(f"    File: {filename}  ({fmt_size(asset_size(a))})")

        if dest.exists():
            print(f"    Already exists — skipped")
            stats.skipped += 1
            continue

        if download(url, dest, session, expected_hash=asset_hash(a)):
            print(f"    Saved: {dest.name}")
            stats.ok += 1

            if do_extract and dest.suffix.lower() == ".zip":
                print(f"    Extracting...")
                try:
                    for f in extract_zip(dest, out_dir):
                        print(f"      -> {f.name}")
                except Exception as exc:
                    print(f"    Extract error: {exc}")
        else:
            stats.failed += 1

        print()

    return stats


def save_metadata(assets: list[dict], out_dir: Path) -> Path:
    """Write a JSON metadata file listing every asset in the catalog."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "metadata.json"
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total": len(assets),
        "assets": [
            {
                "index": i + 1,
                "description": asset_label(a),
                "url": asset_url(a),
                "size_bytes": asset_size(a),
                "os_version": a.get("OSVersion"),
                "build": a.get("Build"),
            }
            for i, a in enumerate(assets)
        ],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[+] Metadata saved: {path}")
    return path


# ── CLI ──────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Download official macOS wallpapers from Apple.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  python macos_wallpapers.py --list
  python macos_wallpapers.py --all --extract
  python macos_wallpapers.py --select 1,3,5 -o wallpapers
  python macos_wallpapers.py --catalog aerial --list""",
    )
    p.add_argument("--catalog", choices=CATALOGS, default="desktop",
                    help="Catalog to use (default: desktop)")
    p.add_argument("-o", "--out", default="macos_wallpapers",
                    help="Output directory (default: ./macos_wallpapers)")
    p.add_argument("-l", "--list", action="store_true",
                    help="List available assets without downloading")
    p.add_argument("-a", "--all", action="store_true",
                    help="Download every asset (no interactive prompt)")
    p.add_argument("-s", "--select", metavar="N,N,...",
                    help="Comma-separated asset numbers to download")
    p.add_argument("-e", "--extract", action="store_true",
                    help="Auto-extract .zip files after download")
    p.add_argument("-m", "--meta", action="store_true",
                    help="Save catalog metadata to metadata.json")
    return p


def main() -> None:
    args = build_parser().parse_args()
    out = Path(args.out)

    hr("=")
    print("  macOS Wallpaper Downloader — Apple MobileAsset Catalog")
    hr("=")
    print()

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    # 1. Fetch catalog
    try:
        assets = fetch_catalog(args.catalog, session)
    except requests.RequestException as exc:
        sys.exit(f"Failed to fetch catalog: {exc}")

    if not assets:
        sys.exit("No assets found in catalog.")

    # 2. Display
    print_table(assets)

    if args.meta:
        save_metadata(assets, out)

    if args.list:
        return

    # 3. Resolve selection
    if args.select:
        try:
            indices = [int(x) - 1 for x in args.select.split(",")]
        except ValueError:
            sys.exit("Invalid --select value. Use comma-separated numbers.")
        bad = [i + 1 for i in indices if not 0 <= i < len(assets)]
        if bad:
            sys.exit(f"Out-of-range asset numbers: {bad}")
    elif args.all:
        indices = list(range(len(assets)))
    else:
        indices = prompt_selection(len(assets))

    if not indices:
        print("Nothing selected.")
        return

    # 4. Download
    stats = download_selected(assets, indices, out, session, args.extract)

    hr()
    print(f"  {stats.summary()}")
    print(f"  Output: {out.resolve()}")
    hr()


if __name__ == "__main__":
    main()
