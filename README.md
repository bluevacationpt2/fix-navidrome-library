# fix-navidrome-library

A command-line tool to scan, fix tags, and organize a messy music library.

If you've ever had half your library show up as **Unknown Artist** due to files with inconsistent filenames and no embedded tags, this fixes that.
---

## Features

- **Scans** any music directory and reports which files are missing tags
- **Guesses** tags from folder/filename structure automatically
- **Handles messy filename patterns** out of the box:
  - `Artist - Album - ## Title.wav` (common in WAV/lossless rips)
  - `Artist - Title.mp3` (artist prefix in filename)
  - `01 - Track Name.flac` (numbered tracks)
  - SoundCloud-style filenames with `@`, `#`, emoji, brackets, etc.
- **Writes tags** back into the files (not just renames — actual metadata)
- **WAV/AIFF support** via ffmpeg fallback (handles broadcast WAV and RF64 that mutagen can't tag)
- **Organizes** files into a clean `Artist / Album / Track` folder structure
- **Dry-run mode** so you can preview everything before touching any files
- Supports **MP3, FLAC, WAV, OGG, M4A, OPUS, AIFF**

---

## Installation

**Clone the repo:**
```bash
git clone https://github.com/bluevacationpt2/fix-navidrome-library.git
cd fix-navidrome-library
```

**Install Python dependencies:**
```bash
pip install -r requirements.txt
# Ubuntu/Debian:
pip install -r requirements.txt --break-system-packages
```

**Optional — install ffmpeg for WAV/AIFF tag support:**
```bash
# Ubuntu/Debian
sudo apt install ffmpeg

# macOS
brew install ffmpeg
```

---

## Usage

### 1. Scan and report
See what's missing — no files are changed:
```bash
python fix_navidrome_library.py ~/music
```

Example output:
```
Scanning /home/user/music ...
Found 651 audio files.

──────────────────────────────────────────────────────────────
  SCAN REPORT  ·  /home/user/music
──────────────────────────────────────────────────────────────
  Total files    651
  Complete       548
  Missing tags   103

  [artist, album, title]  Resonance.mp3
    /home/lyn/music/HOME/Odyssey/Resonance.mp3
    guess: artist='HOME', album='Odyssey', title='Resonance'
```

### 2. Auto-guess (recommended first step)
Automatically write guessed tags to all files that are missing them. Safe to run — it only touches files with missing tags, and only when it has a confident guess:
```bash
python fix_navidrome_library.py ~/music --auto-guess
```

For most well-organized libraries this will fix the majority of issues in one shot.

### 3. Fix remaining tags by folder
For anything auto-guess couldn't handle, fix a whole folder at once:
```bash
python fix_navidrome_library.py ~/music --batch
```
You'll be prompted per folder to confirm or override the guessed artist/album. Press Enter to accept, type to override, `s` to skip.

### 4. Fix remaining tags file by file
For granular control:
```bash
python fix_navidrome_library.py ~/music --fix
```

### 5. Preview the reorganization
See how files would be moved without actually moving anything:
```bash
python fix_navidrome_library.py ~/music --dry-run
```

### 6. Reorganize into Artist / Album / Track layout
```bash
python fix_navidrome_library.py ~/music --organize
```

Files are moved to:
```
music/
  Artist/
    Album/
      01 Track Title.mp3
      02 Another Track.flac
```

### Do everything in one pass
```bash
python fix_navidrome_library.py ~/music --auto-guess --organize
```

---

## After running

**If you're using Navidrome with Docker**, trigger a rescan from the web UI:
- Open Navidrome → click your username (top right) → **Personal** → **Scan Library**

Or via the API:
```bash
curl -X POST "http://localhost:4533/rest/startScan" \
  -u "admin:yourpassword" \
  -d "f=json"
```

Or restart the container:
```bash
docker restart navidrome
```
---

## Requirements

- Python 3.10+
- [mutagen](https://mutagen.readthedocs.io/) — audio tag reading/writing
- [colorama](https://pypi.org/project/colorama/) — terminal colors
- ffmpeg (optional) — WAV/AIFF tag support



---

## Notes

- Files are **moved, not copied** during `--organize`. Make sure you have a backup if your library is important.
- Tags are written **into the files** (ID3/Vorbis/MP4 metadata) — not just renames.
- WAV files need ffmpeg installed for tagging. The script will warn you and skip them gracefully if ffmpeg isn't available.
- The `--dry-run` flag only previews `--organize` — it doesn't affect `--auto-guess` or `--batch`.

