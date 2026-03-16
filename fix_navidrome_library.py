#!/usr/bin/env python3
"""
fix-navidrome-library
---------------------
Scan, fix tags, and organize a messy music library for Navidrome (or any
music server). Built for real-world libraries: SoundCloud rips, niche
releases, inconsistent filenames, mixed formats — all handled gracefully.

Supports: MP3, FLAC, WAV, OGG, M4A, OPUS, AIFF
WAV tagging requires ffmpeg (falls back automatically if available).

Requirements:
    pip install mutagen colorama

Optional (for WAV/AIFF files):
    sudo apt install ffmpeg        # Ubuntu/Debian
    brew install ffmpeg            # macOS

Usage:
    python fix_navidrome_library.py ~/music                  # scan & report
    python fix_navidrome_library.py ~/music --auto-guess     # write guessed tags
    python fix_navidrome_library.py ~/music --batch          # fix folder by folder
    python fix_navidrome_library.py ~/music --fix            # fix file by file
    python fix_navidrome_library.py ~/music --dry-run        # preview reorganization
    python fix_navidrome_library.py ~/music --organize       # reorganize files
    python fix_navidrome_library.py ~/music --auto-guess --organize  # full fix
"""

import os
import re
import sys
import shutil
import argparse
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# ── dependencies ───────────────────────────────────────────────────────────────

try:
    from mutagen import File as MutagenFile
    from colorama import Fore, Style, init as colorama_init
    colorama_init(autoreset=True)
except ImportError:
    print("Missing dependencies. Install with:")
    print("  pip install mutagen colorama")
    print("  # Ubuntu/Debian:")
    print("  pip install mutagen colorama --break-system-packages")
    sys.exit(1)

# ── constants ──────────────────────────────────────────────────────────────────

SUPPORTED = {'.mp3', '.flac', '.wav', '.ogg', '.m4a', '.opus', '.aiff', '.aif'}
FFMPEG    = shutil.which('ffmpeg') is not None
WAV_EXTS  = {'.wav', '.aiff', '.aif'}

# ── data model ─────────────────────────────────────────────────────────────────

@dataclass
class Track:
    path: Path
    artist:    Optional[str] = None
    album:     Optional[str] = None
    title:     Optional[str] = None
    track_num: Optional[str] = None
    guessed_artist: Optional[str] = None
    guessed_album:  Optional[str] = None
    guessed_title:  Optional[str] = None

    @property
    def missing(self) -> list[str]:
        return [f for f, v in [
            ('artist', self.artist),
            ('album',  self.album),
            ('title',  self.title),
        ] if not v]

    @property
    def is_complete(self) -> bool:
        return bool(self.artist and self.album and self.title)


# ── tag reading ────────────────────────────────────────────────────────────────

def _clean(value) -> Optional[str]:
    """Normalize a mutagen tag value to a plain string."""
    if value is None:
        return None
    s = str(value[0] if isinstance(value, (list, tuple)) else value).strip().strip("'\"")
    if s.startswith('[') and s.endswith(']'):
        s = s[1:-1].strip().strip("'\"")
    return s or None


def read_tags(path: Path) -> Track:
    track = Track(path=path)
    try:
        audio = MutagenFile(str(path), easy=True)
        if audio is None:
            return track
        tags = audio.tags or {}

        def get(*keys):
            for k in keys:
                v = _clean(tags.get(k))
                if v:
                    return v
            return None

        track.artist    = get('artist', 'albumartist', 'TPE1', 'TPE2')
        track.album     = get('album', 'TALB')
        track.title     = get('title', 'TIT2')
        track.track_num = get('tracknumber', 'TRCK')
    except Exception:
        pass
    return track


# ── tag guessing ───────────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    """Normalize string for loose comparison."""
    return re.sub(r'[\s_\-]', '', s).lower()


def _matches(a: str, b: str) -> bool:
    return a == b or a in b or b in a


def guess_from_path(track: Track, music_root: Path) -> None:
    """
    Infer artist/album/title from folder structure and filename.

    Handles:
      root/Artist/Album/track.ext
      root/Artist/Album/Artist - Album - ## Title.ext   (WAV rip prefix)
      root/Artist/Album/Artist - Title.ext              (artist prefix)
      root/Artist/track.ext                             (no album folder)
    """
    parts     = track.path.relative_to(music_root).parts
    stem      = track.path.stem
    clean     = re.sub(r'^\d[\d\-]*[\s\.\-]+', '', stem).strip()  # strip leading track nums

    if len(parts) >= 3:
        folder_artist, folder_album = parts[0], parts[1]
        fa, fb = _norm(folder_artist), _norm(folder_album)

        # "Artist - Album - ## Title" pattern (e.g. PilotRedSun WAV rips)
        segs = re.split(r'\s*-\s*', stem, maxsplit=2)
        if len(segs) == 3 and _matches(_norm(segs[0]), fa) and _matches(_norm(segs[1]), fb):
            clean = re.sub(r'^\d+\s+', '', segs[2]).strip()

        # "Artist - Title" prefix pattern (e.g. "Home - Resonance.mp3")
        m = re.match(r'^(.+?)\s*-\s*(.+)$', clean)
        if m and _matches(_norm(m.group(1)), fa):
            clean = m.group(2).strip()

        track.guessed_artist = folder_artist
        track.guessed_album  = folder_album
        track.guessed_title  = clean

    elif len(parts) == 2:
        track.guessed_artist = parts[0]
        track.guessed_album  = parts[0]  # no album folder — use artist as fallback
        track.guessed_title  = clean

    else:
        track.guessed_title = clean


# ── tag writing ────────────────────────────────────────────────────────────────

def write_tags(track: Track, artist: str, album: str, title: str,
               track_num: Optional[str] = None) -> tuple[bool, Optional[str]]:
    """
    Write tags to file. Tries mutagen first; falls back to ffmpeg for
    WAV/AIFF files that mutagen cannot tag (broadcast WAV, RF64, etc.).
    """
    ok, err = _write_mutagen(track.path, artist, album, title, track_num)
    if ok:
        return True, None

    if track.path.suffix.lower() in WAV_EXTS:
        if FFMPEG:
            ok, err2 = _write_ffmpeg(track.path, artist, album, title, track_num)
            if ok:
                return True, None
            return False, f"mutagen: {err}  |  ffmpeg: {err2}"
        else:
            return False, f"{err}  (install ffmpeg to handle WAV/AIFF files)"

    return False, err


def _write_mutagen(path: Path, artist: str, album: str, title: str,
                   track_num: Optional[str]) -> tuple[bool, Optional[str]]:
    try:
        audio = MutagenFile(str(path), easy=True)
        if audio is None:
            return False, "unrecognized format"
        if audio.tags is None:
            audio.add_tags()
        audio.tags['artist']      = artist
        audio.tags['albumartist'] = artist
        audio.tags['album']       = album
        audio.tags['title']       = title
        if track_num:
            audio.tags['tracknumber'] = track_num
        audio.save()
        return True, None
    except Exception as e:
        return False, str(e)


def _write_ffmpeg(path: Path, artist: str, album: str, title: str,
                  track_num: Optional[str]) -> tuple[bool, Optional[str]]:
    """Rewrite a WAV/AIFF with updated metadata via ffmpeg."""
    tmp = path.with_suffix('.fixing' + path.suffix)
    cmd = [
        'ffmpeg', '-y', '-i', str(path),
        '-metadata', f'artist={artist}',
        '-metadata', f'album_artist={artist}',
        '-metadata', f'album={album}',
        '-metadata', f'title={title}',
    ]
    if track_num:
        cmd += ['-metadata', f'track={track_num}']
    cmd += ['-codec', 'copy', str(tmp)]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            if tmp.exists():
                tmp.unlink()
            last_line = (result.stderr or '').strip().splitlines()
            return False, last_line[-1] if last_line else 'ffmpeg error'
        tmp.replace(path)
        return True, None
    except Exception as e:
        if tmp.exists():
            tmp.unlink()
        return False, str(e)


# ── file organization ──────────────────────────────────────────────────────────

def _safe_name(name: str) -> str:
    """Sanitize a string for use as a filename or folder name."""
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    name = name.strip('. ')
    return name[:120]


def organize_file(track: Track, music_root: Path,
                  dry_run: bool = False) -> Optional[Path]:
    """
    Move file to:  music_root / Artist / Album / [##] Title.ext
    Returns the destination path, or None if already in the right place.
    """
    artist = track.artist or track.guessed_artist or 'Unknown Artist'
    album  = track.album  or track.guessed_album  or 'Unknown Album'
    title  = track.title  or track.guessed_title  or track.path.stem

    prefix = ''
    if track.track_num:
        num = re.sub(r'/.*', '', str(track.track_num))  # "3/12" → "3"
        try:
            prefix = f'{int(num):02d} '
        except ValueError:
            prefix = f'{track.track_num} '

    filename = _safe_name(f'{prefix}{title}') + track.path.suffix.lower()
    dest = music_root / _safe_name(artist) / _safe_name(album) / filename

    if dest == track.path:
        return None

    if not dry_run:
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(track.path), str(dest))
            track.path = dest
        except Exception as e:
            print(f'  {Fore.RED}Move failed: {e}{Style.RESET_ALL}')
            return None

    return dest


# ── scan ───────────────────────────────────────────────────────────────────────

def scan(music_root: Path) -> list[Track]:
    tracks = []
    for dirpath, _, filenames in os.walk(music_root):
        for fname in sorted(filenames):
            fpath = Path(dirpath) / fname
            if fpath.suffix.lower() in SUPPORTED:
                t = read_tags(fpath)
                guess_from_path(t, music_root)
                tracks.append(t)
    return tracks


# ── UI helpers ─────────────────────────────────────────────────────────────────

def _header(text: str) -> None:
    print(f'\n{Style.BRIGHT}{"─" * 60}')
    print(f'  {text}')
    print(f'{"─" * 60}{Style.RESET_ALL}')


def _ok(msg: str)   -> None: print(f'  {Fore.GREEN}✓{Style.RESET_ALL}  {msg}')
def _fail(msg: str) -> None: print(f'  {Fore.RED}✗{Style.RESET_ALL}  {msg}')
def _warn(msg: str) -> None: print(f'  {Fore.YELLOW}!{Style.RESET_ALL}  {msg}')


# ── commands ───────────────────────────────────────────────────────────────────

def cmd_report(tracks: list[Track], music_root: Path) -> None:
    complete   = [t for t in tracks if t.is_complete]
    incomplete = [t for t in tracks if not t.is_complete]

    _header(f'SCAN REPORT  ·  {music_root}')
    print(f'  Total files    {len(tracks)}')
    print(f'  {Fore.GREEN}Complete       {len(complete)}{Style.RESET_ALL}')

    if not incomplete:
        print(f'\n{Fore.GREEN}All files have complete tags!{Style.RESET_ALL}')
        return

    print(f'  {Fore.YELLOW}Missing tags   {len(incomplete)}{Style.RESET_ALL}')
    print()

    for t in incomplete:
        missing_str = f'{Fore.YELLOW}[{", ".join(t.missing)}]{Style.RESET_ALL}'
        print(f'  {missing_str}  {t.path.name}')
        print(f'    {Fore.WHITE}{t.path}{Style.RESET_ALL}')
        guesses = []
        if t.guessed_artist: guesses.append(f"artist='{t.guessed_artist}'")
        if t.guessed_album:  guesses.append(f"album='{t.guessed_album}'")
        if t.guessed_title:  guesses.append(f"title='{t.guessed_title}'")
        if guesses:
            print(f'    {Fore.CYAN}guess: {", ".join(guesses)}{Style.RESET_ALL}')
        print()


def cmd_auto_guess(tracks: list[Track]) -> None:
    incomplete = [t for t in tracks if not t.is_complete]
    if not incomplete:
        print(f'{Fore.GREEN}All files already have complete tags.{Style.RESET_ALL}')
        return

    _header(f'AUTO-GUESS  ·  {len(incomplete)} files')
    if not FFMPEG:
        _warn('ffmpeg not found — WAV/AIFF files will be skipped if mutagen fails')
        _warn('Install with: sudo apt install ffmpeg')
        print()

    fixed, failed = 0, 0
    for t in incomplete:
        artist = t.artist or t.guessed_artist
        album  = t.album  or t.guessed_album
        title  = t.title  or t.guessed_title
        if not (artist and album and title):
            _warn(f'{t.path.name}  (not enough info to guess)')
            failed += 1
            continue
        ok, err = write_tags(t, artist, album, title, t.track_num)
        if ok:
            t.artist = artist
            t.album  = album
            t.title  = title
            _ok(t.path.name)
            fixed += 1
        else:
            _fail(f'{t.path.name}  ({err})')
            failed += 1

    print()
    print(f'{Fore.GREEN}Written: {fixed}{Style.RESET_ALL}  '
          f'{Fore.RED}Failed: {failed}{Style.RESET_ALL}')


def cmd_batch(tracks: list[Track]) -> None:
    """Fix tags folder by folder — set artist/album once for all files in a folder."""
    folders = defaultdict(list)
    for t in tracks:
        if not t.is_complete:
            folders[t.path.parent].append(t)

    if not folders:
        print(f'{Fore.GREEN}Nothing to fix — all files have complete tags.{Style.RESET_ALL}')
        return

    _header(f'BATCH FIX BY FOLDER  ·  {len(folders)} folder(s)')
    print('Set artist/album for all files in a folder at once.')
    print('Press ENTER to accept the guess, or type a new value. "s" skips the folder.\n')

    fixed_total = 0
    for folder, folder_tracks in sorted(folders.items()):
        sample        = folder_tracks[0]
        artist_guess  = sample.artist or sample.guessed_artist or ''
        album_guess   = sample.album  or sample.guessed_album  or ''

        print(f'{Style.BRIGHT}{folder}{Style.RESET_ALL}')
        print(f'  {len(folder_tracks)} file(s) with missing tags')
        print(f'  Sample: {sample.path.name}')

        a = input(f'  Artist [{Fore.CYAN}{artist_guess}{Style.RESET_ALL}]: ').strip()
        if a.lower() == 's':
            print('  Skipped.\n')
            continue
        artist = a or artist_guess
        if not artist:
            print('  Skipped (no artist).\n')
            continue

        b = input(f'  Album  [{Fore.CYAN}{album_guess}{Style.RESET_ALL}]: ').strip()
        album = b or album_guess
        if not album:
            print('  Skipped (no album).\n')
            continue

        for t in folder_tracks:
            title = t.title or t.guessed_title or t.path.stem
            ok, err = write_tags(t, artist, album, title, t.track_num)
            if ok:
                t.artist = artist
                t.album  = album
                t.title  = title
                fixed_total += 1
                _ok(t.path.name)
            else:
                _fail(f'{t.path.name}  ({err})')
        print()

    print(f'{Fore.GREEN}Batch fixed {fixed_total} file(s).{Style.RESET_ALL}')


def cmd_fix(tracks: list[Track]) -> None:
    """Fix tags interactively, one file at a time."""
    incomplete = [t for t in tracks if not t.is_complete]
    if not incomplete:
        print(f'{Fore.GREEN}Nothing to fix — all files have complete tags.{Style.RESET_ALL}')
        return

    _header(f'INTERACTIVE FIX  ·  {len(incomplete)} files')
    print('Press ENTER to accept the guess, type a new value, or "s" to skip.\n')

    fixed = 0
    for i, t in enumerate(incomplete, 1):
        print(f'{Style.BRIGHT}[{i}/{len(incomplete)}]  {t.path.name}{Style.RESET_ALL}')
        print(f'  {t.path}')

        artist = t.artist
        album  = t.album
        title  = t.title

        if not artist:
            g = t.guessed_artist or ''
            v = input(f'  Artist [{Fore.CYAN}{g}{Style.RESET_ALL}]: ').strip()
            if v.lower() == 's': print('  Skipped.\n'); continue
            artist = v or g
        if not album:
            g = t.guessed_album or ''
            v = input(f'  Album  [{Fore.CYAN}{g}{Style.RESET_ALL}]: ').strip()
            if v.lower() == 's': print('  Skipped.\n'); continue
            album = v or g
        if not title:
            g = t.guessed_title or ''
            v = input(f'  Title  [{Fore.CYAN}{g}{Style.RESET_ALL}]: ').strip()
            if v.lower() == 's': print('  Skipped.\n'); continue
            title = v or g

        if artist and album and title:
            ok, err = write_tags(t, artist, album, title, t.track_num)
            if ok:
                t.artist = artist; t.album = album; t.title = title
                print(f'  {Fore.GREEN}Tags written.{Style.RESET_ALL}\n')
                fixed += 1
            else:
                _fail(f'{err}\n')
        else:
            print('  Skipped (incomplete input).\n')

    print(f'{Fore.GREEN}Fixed {fixed} / {len(incomplete)} files.{Style.RESET_ALL}')


def cmd_organize(tracks: list[Track], music_root: Path, dry_run: bool = False) -> None:
    label = 'DRY RUN — PREVIEW' if dry_run else 'ORGANIZING FILES'
    _header(f'{label}  ·  Artist / Album / Track layout')

    if dry_run:
        print(f'  {Fore.YELLOW}No files will be moved. Remove --dry-run to apply.{Style.RESET_ALL}\n')

    moved = skipped = errors = 0
    for t in tracks:
        dest = organize_file(t, music_root, dry_run=dry_run)
        if dest is None:
            skipped += 1
            continue
        rel_src  = t.path.relative_to(music_root) if dry_run else Path('(moved)')
        rel_dest = dest.relative_to(music_root)
        if dry_run:
            print(f'  {Fore.WHITE}{rel_src}{Style.RESET_ALL}')
            print(f'    {Fore.CYAN}→{Style.RESET_ALL} {rel_dest}\n')
        else:
            print(f'  {Fore.CYAN}→{Style.RESET_ALL} {rel_dest}')
        moved += 1

    print()
    if dry_run:
        print(f'Would move {Fore.GREEN}{moved}{Style.RESET_ALL} file(s). '
              f'{skipped} already in the right place.')
    else:
        print(f'Moved {Fore.GREEN}{moved}{Style.RESET_ALL} file(s). '
              f'{skipped} already in the right place.')


# ── main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog='fix-navidrome-library',
        description=(
            'Scan, fix tags, and organize a music library for Navidrome '
            '(or any music server). Supports MP3, FLAC, WAV, OGG, M4A, OPUS, AIFF.'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  %(prog)s ~/music                          scan and report missing tags
  %(prog)s ~/music --auto-guess             write guessed tags automatically
  %(prog)s ~/music --batch                  fix tags folder by folder
  %(prog)s ~/music --fix                    fix tags file by file
  %(prog)s ~/music --dry-run                preview how files would be reorganized
  %(prog)s ~/music --organize               move files into Artist/Album/Track layout
  %(prog)s ~/music --auto-guess --organize  full fix in one pass
        """,
    )
    parser.add_argument('directory',
        help='Root music directory (e.g. ~/music)')
    parser.add_argument('--auto-guess', action='store_true',
        help='Automatically write guessed tags to files missing them')
    parser.add_argument('--batch', action='store_true',
        help='Fix missing tags folder by folder (interactive)')
    parser.add_argument('--fix', action='store_true',
        help='Fix missing tags file by file (interactive)')
    parser.add_argument('--organize', action='store_true',
        help='Move files into Artist / Album / Track folder structure')
    parser.add_argument('--dry-run', action='store_true',
        help='Preview what --organize would do without moving any files')
    args = parser.parse_args()

    music_root = Path(args.directory).expanduser().resolve()
    if not music_root.is_dir():
        print(f'{Fore.RED}Error: "{music_root}" is not a directory.{Style.RESET_ALL}')
        sys.exit(1)

    print(f'\n{Style.BRIGHT}Scanning {music_root} ...{Style.RESET_ALL}')
    tracks = scan(music_root)
    print(f'Found {len(tracks)} audio file(s).')

    cmd_report(tracks, music_root)

    did_something = False

    if args.auto_guess:
        cmd_auto_guess(tracks)
        did_something = True

    if args.batch:
        cmd_batch(tracks)
        did_something = True
    elif args.fix:
        cmd_fix(tracks)
        did_something = True

    if args.organize or args.dry_run:
        cmd_organize(tracks, music_root, dry_run=args.dry_run)
        did_something = True

    if not did_something:
        incomplete = [t for t in tracks if not t.is_complete]
        if incomplete:
            print(f'\n{Style.BRIGHT}Suggested next steps:{Style.RESET_ALL}')
            print('  --auto-guess     write guessed tags automatically (safe starting point)')
            print('  --batch          fix remaining tags folder by folder')
            print('  --dry-run        preview how --organize would restructure your files')
            print('  --organize       move files into Artist / Album / Track layout')
            print(f'\n  example: python fix_navidrome_library.py {args.directory} --auto-guess --organize\n')
        else:
            print(f'\n{Fore.GREEN}Library looks clean! Use --organize to restructure files if needed.{Style.RESET_ALL}\n')


if __name__ == '__main__':
    main()
