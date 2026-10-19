# macOS Wallpaper Downloader

Downloads official macOS wallpapers directly from Apple's servers via the MobileAsset catalog (`mesu.apple.com`).

No third-party sources — files come straight from `updates.cdn-apple.com`.

## Features

- **Direct from Apple** — queries the same MobileAsset catalog that macOS uses internally
- **Two catalogs** — desktop wallpapers and aerial screensaver videos
- **Progress bars** — powered by `tqdm`
- **SHA-256 verification** — integrity check when hash is available in the catalog
- **Smart skipping** — won't re-download files that already exist
- **ZIP extraction** — optionally extract downloaded archives automatically
- **Metadata export** — save the full catalog as `metadata.json`

## Installation

```bash
pip install requests tqdm
```

## Usage

```bash
# List all available wallpapers
python macos_wallpapers.py --list

# Interactive download (pick which ones you want)
python macos_wallpapers.py

# Download everything + extract
python macos_wallpapers.py --all --extract

# Download specific items
python macos_wallpapers.py --select 1,3,5

# Aerial screensaver videos
python macos_wallpapers.py --catalog aerial --list

# Custom output directory + metadata
python macos_wallpapers.py --all -o ~/wallpapers --meta
```

### Options

| Flag | Short | Description |
|------|-------|-------------|
| `--catalog {desktop,aerial}` | | Catalog to query (default: `desktop`) |
| `--out DIR` | `-o` | Output directory (default: `./macos_wallpapers`) |
| `--list` | `-l` | List assets without downloading |
| `--all` | `-a` | Download all assets (no prompt) |
| `--select N,N,...` | `-s` | Download specific asset numbers |
| `--extract` | `-e` | Auto-extract `.zip` files |
| `--meta` | `-m` | Save catalog metadata as JSON |

## How It Works

```
mesu.apple.com          Apple's MobileAsset catalog server
       │
       ▼
  XML plist catalog     Lists every wallpaper with CDN URLs
       │
       ▼
updates.cdn-apple.com   Apple's CDN — actual file downloads
       │
       ▼
  Local .zip files      Contain HEIC/HEIF images or MOV videos
```

The script fetches the XML property list catalog from `mesu.apple.com`, parses it with Python's built-in `plistlib`, extracts the CDN download URLs, and streams each file with a progress bar.

## Windows Note

If you see encoding issues in PowerShell, set UTF-8 mode first:

```powershell
$env:PYTHONUTF8=1
python macos_wallpapers.py --list
```

## License

MIT
