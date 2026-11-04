#!/usr/bin/env python3
"""Вивантажує «Швидкий вибір» (Quick picks) з YouTube Music на iPod.

Що робить скрипт:
  1. Читає вашу головну сторінку YouTube Music (через ytmusicapi і cookies
     з браузера, де ви увійшли в акаунт) і бере полицю «Quick picks».
  2. З --fill далі бере «радіо» від кожного треку «Швидкого вибору» (те, що
     YouTube Music грає, коли ви натискаєте на трек), поки на плеєрі є місце.
  3. Завантажує кожен трек через yt-dlp (m4a/AAC або mp3), записує теги й
     квадратну обкладинку.
  4. Створює плейлист .m3u8 і, за бажанням:
       --itunes   додає треки в плейлист iTunes (Windows) або Музики (macOS),
                  звідки iPod зі стандартною прошивкою синхронізується;
       --rockbox  копіює файли й плейлист прямо на iPod з прошивкою Rockbox.

Приклади:
  python quickpicks_to_ipod.py --browser firefox --list
  python quickpicks_to_ipod.py --browser firefox --fill --max-size 28G --itunes
  python quickpicks_to_ipod.py --browser firefox --fill --rockbox /media/IPOD

Детальніше: README.md поруч зі скриптом.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import importlib
import io
import json
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

QUICK_PICKS_TITLES = {"quick picks", "швидкий вибір", "быстрый выбор"}
YTM_ORIGIN = "https://music.youtube.com"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/130.0.0.0 Safari/537.36")
MANIFEST_NAME = ".quickpicks.json"
COVER_SIZE = 500
RADIO_LENGTH = 50             # tracks asked for per radio in --fill mode
MAX_FAILS_IN_ROW = 10         # probably throttled by YouTube: stop for now
DEFAULT_TRACK_SIZE = 5_000_000
BAD_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def die(msg: str, code: int = 1):
    print(f"Помилка: {msg}", file=sys.stderr)
    sys.exit(code)


def require(module: str, pip_name: str):
    try:
        return importlib.import_module(module)
    except ImportError:
        die(f"не встановлено пакет «{pip_name}». Виконайте:\n"
            f"  pip install -r requirements.txt")


def safe_name(text: str, maxlen: int = 100) -> str:
    text = BAD_FILENAME_CHARS.sub("_", text).strip().rstrip(". ")
    return text[:maxlen].rstrip(". ") or "track"


def fetch(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def split_browser(spec: str) -> tuple[str, str | None]:
    """'firefox' -> ('firefox', None); 'chrome:Profile 1' -> (..., ...)."""
    name, _, profile = spec.partition(":")
    return name.strip().lower(), (profile.strip() or None)


def parse_size(text: str) -> int:
    """'28G', '500M', '1.5T', '30' (=GB) -> bytes, decimal like on iPods."""
    m = re.fullmatch(r"\s*(\d+(?:[.,]\d+)?)\s*([KMGT]?)B?\s*", text, re.I)
    if not m:
        raise argparse.ArgumentTypeError(
            f"не розумію розмір «{text}», приклад: 28G або 500M")
    number = float(m.group(1).replace(",", "."))
    unit = m.group(2).upper() or "G"
    return int(number * 1000 ** ("KMGT".index(unit) + 1))


# --------------------------------------------------------------------------
# Authentication (cookies -> ytmusicapi browser headers)
# --------------------------------------------------------------------------

def load_cookie_jar(args):
    cookies_mod = require("yt_dlp.cookies", "yt-dlp")
    if args.cookies:
        jar = cookies_mod.YoutubeDLCookieJar(args.cookies)
        try:
            # Handles '#HttpOnly_' lines that http.cookiejar may skip.
            jar.load()
        except Exception as exc:  # noqa: BLE001 - show any parse problem
            die(f"не вдалося прочитати {args.cookies}: {exc}")
        return jar
    browser, profile = split_browser(args.browser)
    try:
        return cookies_mod.extract_cookies_from_browser(browser, profile)
    except Exception as exc:  # noqa: BLE001
        die(f"не вдалося прочитати cookies з браузера «{browser}»: {exc}\n"
            "Порада: закрийте браузер і спробуйте ще раз, або використайте "
            "Firefox, або експортуйте cookies.txt (див. README).")


def ytm_cookie_header(jar) -> str:
    now = time.time()
    picked: dict[str, str] = {}
    for cookie in jar:
        domain = (cookie.domain or "").lstrip(".")
        if domain not in ("youtube.com", "music.youtube.com"):
            continue
        if cookie.value is None:
            continue
        if cookie.expires and cookie.expires < now:
            continue
        # Prefer music.youtube.com over .youtube.com for the same name.
        if cookie.name in picked and domain != "music.youtube.com":
            continue
        picked[cookie.name] = cookie.value
    if "__Secure-3PAPISID" not in picked:
        die("у cookies немає входу в YouTube (__Secure-3PAPISID).\n"
            "Відкрийте music.youtube.com у цьому браузері, увійдіть в акаунт "
            "і запустіть скрипт знову.")
    return "; ".join(f"{k}={v}" for k, v in picked.items())


def make_ytmusic(cookie: str, authuser: int, brand_account: str | None):
    ytmusicapi = require("ytmusicapi", "ytmusicapi")
    headers = {
        "user-agent": USER_AGENT,
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.9",
        "content-type": "application/json",
        "origin": YTM_ORIGIN,
        "x-origin": YTM_ORIGIN,
        "x-goog-authuser": str(authuser),
        "cookie": cookie,
        # ytmusicapi only checks that this contains "SAPISIDHASH" to pick
        # browser auth; the real hash is recomputed for every request.
        "authorization": "SAPISIDHASH 0_0",
    }
    # A JSON string works across ytmusicapi versions (dicts only in newer).
    return ytmusicapi.YTMusic(json.dumps(headers), user=brand_account,
                              language="en")


# --------------------------------------------------------------------------
# Quick picks and radio
# --------------------------------------------------------------------------

def find_shelf(home: list[dict], wanted: str | None) -> dict | None:
    if wanted:
        needle = wanted.casefold()
        for row in home:
            if needle in (row.get("title") or "").casefold():
                return row
        return None
    for row in home:
        if (row.get("title") or "").strip().casefold() in QUICK_PICKS_TITLES:
            return row
    return None


def to_track(item: dict) -> dict | None:
    video_id = item.get("videoId")
    if not video_id:
        return None  # albums / playlists / artists are skipped
    artists = [a.get("name") for a in (item.get("artists") or [])
               if isinstance(a, dict) and a.get("name")]
    album = item.get("album") or {}
    # Home shelves use "thumbnails", watch playlists (radio) "thumbnail".
    thumbs = item.get("thumbnails") or item.get("thumbnail") or []
    if not isinstance(thumbs, list):
        thumbs = []
    return {
        "videoId": video_id,
        "title": item.get("title") or video_id,
        "artists": artists,
        "album": album.get("name") if isinstance(album, dict) else None,
        "thumb": thumbs[-1].get("url") if thumbs else None,
    }


def get_quick_picks(yt, shelf: str | None) -> list[dict]:
    try:
        home = yt.get_home(limit=10)
    except Exception as exc:  # noqa: BLE001
        die(f"YouTube Music не віддав головну сторінку: {exc}\n"
            "Можливо, cookies застаріли — увійдіть у браузері знову.")
    row = find_shelf(home, shelf)
    if row is None:
        titles = [r.get("title") or "?" for r in home]
        die("не знайшов полицю «Quick picks». Полиці на вашій головній:\n  "
            + "\n  ".join(titles)
            + "\nВкажіть потрібну через --shelf \"назва\".")
    tracks = [t for t in map(to_track, row.get("contents") or []) if t]
    if not tracks:
        die(f"полиця «{row.get('title')}» не містить треків.")
    return tracks


def track_key(track: dict) -> tuple[str, str]:
    artist = track["artists"][0] if track["artists"] else ""
    return track["title"].strip().casefold(), artist.strip().casefold()


def candidates(yt, picks: list[dict], fill: bool):
    """Quick picks first; with fill, radio from them (breadth-first).

    Radio is fetched lazily, only when more tracks are needed.
    """
    seen_ids: set[str] = set()
    seen_keys: set[tuple[str, str]] = set()

    def fresh(track: dict) -> bool:
        key = track_key(track)
        if track["videoId"] in seen_ids or key in seen_keys:
            return False  # also skips a song's music-video duplicate
        seen_ids.add(track["videoId"])
        seen_keys.add(key)
        return True

    seeds: collections.deque[str] = collections.deque()
    for track in picks:
        if fresh(track):
            seeds.append(track["videoId"])
            yield track
    while fill and seeds:
        seed = seeds.popleft()
        try:
            radio = yt.get_watch_playlist(videoId=seed, radio=True,
                                          limit=RADIO_LENGTH)
        except Exception as exc:  # noqa: BLE001 - skip this seed
            print(f"    радіо для {seed} недоступне: {exc}")
            continue
        for item in radio.get("tracks") or []:
            track = to_track(item)
            if track and fresh(track):
                seeds.append(track["videoId"])
                yield track


# --------------------------------------------------------------------------
# Download, cover art, tags
# --------------------------------------------------------------------------

def make_ydl(yt_dlp, tmpdir: Path, args):
    opts = {
        # m4a: take YouTube's AAC stream as is (no re-encoding).
        "format": ("bestaudio[ext=m4a]/bestaudio/best"
                   if args.format == "m4a" else "bestaudio/best"),
        "outtmpl": str(tmpdir / "%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "noprogress": True,
        "retries": 5,
        # Short pauses make YouTube less likely to throttle long runs.
        "sleep_interval": 1,
        "max_sleep_interval": 4,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": args.format,
            "preferredquality": str(args.bitrate),
        }],
    }
    if args.ytdlp_cookies:
        if args.cookies:
            opts["cookiefile"] = args.cookies
        else:
            browser, profile = split_browser(args.browser)
            opts["cookiesfrombrowser"] = (browser, profile, None, None)
    return yt_dlp.YoutubeDL(opts)


def download_audio(ydl, video_id: str, tmpdir: Path, fmt: str):
    info = ydl.extract_info(f"{YTM_ORIGIN}/watch?v={video_id}",
                            download=True)
    path = None
    for item in info.get("requested_downloads") or []:
        if item.get("filepath"):
            path = Path(item["filepath"])
    if path is None or not path.exists():
        found = [p for p in tmpdir.glob(f"{video_id}.*")
                 if p.suffix.lower() == f".{fmt}"]
        if not found:
            raise RuntimeError("yt-dlp не створив аудіофайл")
        path = found[0]
    return path, info


def cover_sources(track: dict) -> list[tuple[str, bool]]:
    """(url, is_video_frame) in order of preference."""
    sources = []
    thumb = track.get("thumb") or ""
    if "googleusercontent.com" in thumb:
        size = COVER_SIZE + 100
        sources.append((re.sub(r"=w\d+-h\d+.*$",
                               f"=w{size}-h{size}-l90-rj", thumb), False))
    vid = track["videoId"]
    for name in ("maxresdefault", "sddefault", "hqdefault"):
        sources.append((f"https://i.ytimg.com/vi/{vid}/{name}.jpg", True))
    return sources


def trim_black_bars(img):
    mask = img.convert("L").point(lambda p: 255 if p > 20 else 0)
    box = mask.getbbox()
    if not box:
        return img
    left, top, right, bottom = box
    if (right - left) * (bottom - top) < 0.3 * img.width * img.height:
        return img
    return img.crop(box)


def make_cover(track: dict) -> bytes | None:
    Image = require("PIL.Image", "Pillow")
    resample = getattr(Image, "Resampling", Image).LANCZOS
    for url, is_frame in cover_sources(track):
        try:
            img = Image.open(io.BytesIO(fetch(url)))
            img.load()
        except Exception:  # noqa: BLE001 - try the next source
            continue
        img = img.convert("RGB")
        if is_frame:
            img = trim_black_bars(img)
        side = min(img.size)
        left = (img.width - side) // 2
        top = (img.height - side) // 2
        img = img.crop((left, top, left + side, top + side))
        if side > COVER_SIZE:
            img = img.resize((COVER_SIZE, COVER_SIZE), resample)
        out = io.BytesIO()
        # Baseline (non-progressive) JPEG: the only kind old iPods and
        # Rockbox can show.
        img.save(out, "JPEG", quality=90, progressive=False)
        return out.getvalue()
    return None


def tag_file(path: Path, meta: dict, cover: bytes | None, comment: str):
    if path.suffix.lower() == ".m4a":
        mp4 = require("mutagen.mp4", "mutagen")
        audio = mp4.MP4(str(path))
        if audio.tags is None:
            audio.add_tags()
        tags = audio.tags
        tags["\xa9nam"] = [meta["title"]]
        tags["\xa9ART"] = [meta["artist"]]
        if meta.get("album"):
            tags["\xa9alb"] = [meta["album"]]
        if meta.get("year"):
            tags["\xa9day"] = [str(meta["year"])]
        tags["\xa9cmt"] = [comment]
        if cover:
            tags["covr"] = [mp4.MP4Cover(
                cover, imageformat=mp4.MP4Cover.FORMAT_JPEG)]
        audio.save()
        return
    id3 = require("mutagen.id3", "mutagen")
    try:
        tags = id3.ID3(str(path))
    except id3.ID3NoHeaderError:
        tags = id3.ID3()
    # encoding=1 (UTF-16) + ID3v2.3: what iPods read reliably.
    tags.setall("TIT2", [id3.TIT2(encoding=1, text=meta["title"])])
    tags.setall("TPE1", [id3.TPE1(encoding=1, text=meta["artist"])])
    if meta.get("album"):
        tags.setall("TALB", [id3.TALB(encoding=1, text=meta["album"])])
    if meta.get("year"):
        # mutagen writes TDRC as TYER when saving ID3v2.3.
        tags.setall("TDRC", [id3.TDRC(encoding=1, text=str(meta["year"]))])
    tags.setall("COMM", [id3.COMM(encoding=1, lang="eng", desc="",
                                  text=comment)])
    if cover:
        tags.setall("APIC", [id3.APIC(encoding=1, mime="image/jpeg", type=3,
                                      desc="Cover", data=cover)])
    tags.save(str(path), v2_version=3)


def artist_of(track: dict, info: dict | None) -> str:
    if track["artists"]:
        return ", ".join(track["artists"])
    info = info or {}
    artists = info.get("artists")
    if isinstance(artists, list) and artists:
        return ", ".join(str(a) for a in artists)
    return (info.get("artist") or info.get("creator")
            or info.get("uploader") or "Unknown Artist")


def unique_path(folder: Path, base: str, ext: str, video_id: str) -> Path:
    path = folder / f"{base}.{ext}"
    if path.exists():
        path = folder / f"{base} [{video_id}].{ext}"
    return path


def download_track(ydl, track: dict, tmpdir: Path, out_dir: Path, fmt: str,
                   old: dict | None, comment: str) -> dict:
    src, info = download_audio(ydl, track["videoId"], tmpdir, fmt)
    meta = {
        "title": track["title"],
        "artist": artist_of(track, info),
        "album": track["album"] or info.get("album"),
        "year": info.get("release_year"),
    }
    tag_file(src, meta, make_cover(track), comment)
    if old and old.get("file", "").endswith(f".{fmt}"):
        dest = out_dir / old["file"]  # a re-download keeps its file name
    else:
        base = safe_name(f"{meta['artist']} - {meta['title']}")
        dest = unique_path(out_dir, base, fmt, track["videoId"])
    if dest.exists():
        dest.unlink()  # Windows can't rename over an existing file
    shutil.move(str(src), str(dest))
    return {**meta, "file": dest.name, "duration": info.get("duration"),
            "videoId": track["videoId"]}


def existing_entry(manifest: dict, track: dict, out_dir: Path,
                   args) -> dict | None:
    old = manifest.get(track["videoId"])
    if (old and not args.redownload
            and old.get("file", "").endswith(f".{args.format}")
            and (out_dir / old["file"]).exists()):
        return old
    return None


def save_manifest(path: Path, manifest: dict):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    tmp.replace(path)  # atomic: Ctrl+C can't leave a half-written file


# --------------------------------------------------------------------------
# Free space
# --------------------------------------------------------------------------

class Space:
    """Decides whether one more track still fits on the player."""

    def __init__(self, max_bytes: int | None, device: Path | None,
                 reserve: int):
        self.max_bytes = max_bytes  # whole playlist budget (iTunes sync)
        self.device = device        # mounted player (Rockbox): real space
        self.reserve = reserve
        self.used = 0

    def fits(self, size: int, device_size: int) -> bool:
        if self.max_bytes is not None and self.used + size > self.max_bytes:
            return False
        if self.device is not None and device_size:
            free = shutil.disk_usage(self.device).free
            if free - device_size < self.reserve:
                return False
        return True

    def take(self, size: int):
        self.used += size


# --------------------------------------------------------------------------
# Playlists and iPod targets
# --------------------------------------------------------------------------

def write_m3u8(path: Path, entries: list[dict], prefix: str = ""):
    lines = ["#EXTM3U"]
    for e in entries:
        duration = int(e.get("duration") or -1)
        lines.append(f"#EXTINF:{duration},{e['artist']} - {e['title']}")
        lines.append(prefix + e["file"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def rockbox_subdir(subdir: str) -> str:
    return subdir.replace("\\", "/").strip("/")


def rockbox_prepare(mount: Path, subdir: str) -> Path:
    if not mount.is_dir():
        die(f"{mount} не існує або це не тека (iPod не підключено?)")
    if not (mount / ".rockbox").is_dir():
        if (mount / "iPod_Control").is_dir():
            die("на цьому iPod стандартна прошивка Apple, а не Rockbox.\n"
                "Просто скопійовані файли він не побачить — використайте "
                "--itunes (Windows/macOS) або Strawberry/Rhythmbox на Linux.")
        print("Попередження: теки .rockbox немає, копіюю як на звичайний "
              "USB-плеєр.")
    dest = mount / rockbox_subdir(subdir)
    dest.mkdir(parents=True, exist_ok=True)
    return dest


def rockbox_needs_copy(src: Path, dest_dir: Path) -> bool:
    target = dest_dir / src.name
    return not (target.exists()
                and target.stat().st_size == src.stat().st_size)


def rockbox_playlist(mount: Path, subdir: str, entries: list[dict],
                     playlist_name: str):
    playlists = mount / "Playlists"
    playlists.mkdir(exist_ok=True)
    pl_path = playlists / f"{safe_name(playlist_name)}.m3u8"
    write_m3u8(pl_path, entries, prefix=f"/{rockbox_subdir(subdir)}/")
    print(f"Плейлист Rockbox: {pl_path}")


APPLESCRIPT = r"""
on run argv
    set plName to item 1 of argv
    set listText to read (POSIX file (item 2 of argv)) as «class utf8»
    set theFiles to {}
    repeat with p in paragraphs of listText
        set s to contents of p
        if s is not "" then
            set end of theFiles to ((POSIX file s) as alias)
        end if
    end repeat
    tell application "__APP__"
        with timeout of 3600 seconds
            if not (exists user playlist plName) then
                make new user playlist with properties {name:plName}
            end if
            set pl to user playlist plName
            try
                delete every track of pl
            end try
            add theFiles to pl
        end timeout
    end tell
end run
"""


def add_to_music_macos(files: list[Path], playlist_name: str):
    version = platform.mac_ver()[0] or "10.15"
    parts = [int(x) for x in version.split(".")[:2] if x.isdigit()] + [0]
    # macOS 10.15 Catalina replaced iTunes with the Music app.
    app = "Music" if (parts[0], parts[1]) >= (10, 15) else "iTunes"
    script = APPLESCRIPT.replace("__APP__", app)
    # Paths go through a file: thousands of them would not fit in argv.
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt",
                                     delete=False) as fh:
        fh.write("\n".join(str(f.resolve()) for f in files) + "\n")
        list_path = fh.name
    try:
        res = subprocess.run(["osascript", "-e", script, playlist_name,
                              list_path], capture_output=True, text=True)
    finally:
        Path(list_path).unlink(missing_ok=True)
    if res.returncode != 0:
        die(f"{app} не прийняв треки: {res.stderr.strip()}\n"
            "Дозвольте терміналу керувати застосунком «Музика»: Системні "
            "параметри → Конфіденційність і безпека → Автоматизація.")
    print(f"Плейлист «{playlist_name}» оновлено в застосунку {app}.")
    print("Підключіть iPod → Finder → iPod → Музика → «Синхронізувати "
          "вибрані плейлисти» → позначте цей плейлист → «Синхронізувати».")


def add_to_itunes_windows(files: list[Path], playlist_name: str, sync: bool):
    try:
        dynamic = importlib.import_module("win32com.client.dynamic")
    except ImportError:
        die("для --itunes на Windows потрібен pywin32: pip install pywin32")
    itunes = dynamic.Dispatch("iTunes.Application")
    playlist = itunes.LibrarySource.Playlists.ItemByName(playlist_name)
    if playlist is not None and (playlist.Kind != 2  # 2 = user playlist
                                 or getattr(playlist, "Smart", False)):
        die(f"в iTunes вже є не-звичайний плейлист «{playlist_name}»; "
            "оберіть іншу назву через --playlist-name.")
    if playlist is None:
        playlist = itunes.CreatePlaylist(playlist_name)
    else:
        # Keep the same playlist (iPod sync settings remember it by ID),
        # only replace its contents.
        tracks = playlist.Tracks
        for idx in range(tracks.Count, 0, -1):
            tracks.Item(idx).Delete()
    for n, f in enumerate(files, 1):
        status = playlist.AddFile(str(f.resolve()))
        while status is not None and status.InProgress:
            time.sleep(0.2)
        if n % 100 == 0:
            print(f"  додано в iTunes {n}/{len(files)}")
    print(f"Плейлист «{playlist_name}» оновлено в iTunes.")
    if sync:
        itunes.UpdateIPod()
        print("Запущено синхронізацію iPod.")
    else:
        print("Для синхронізації додайте --sync або натисніть "
              "«Синхронізувати» в iTunes.")


def add_to_itunes(files: list[Path], playlist_name: str, sync: bool):
    system = platform.system()
    if system == "Darwin":
        add_to_music_macos(files, playlist_name)
    elif system == "Windows":
        add_to_itunes_windows(files, playlist_name, sync)
    else:
        die("--itunes працює лише на Windows і macOS. На Linux імпортуйте "
            "теку в Strawberry або Rhythmbox (вони пишуть на iPod через "
            "libgpod) або використайте --rockbox.")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Вивантажити «Швидкий вибір» з YouTube Music на iPod.")
    auth = p.add_mutually_exclusive_group(required=True)
    auth.add_argument("--browser", metavar="BROWSER[:PROFILE]",
                      help="взяти cookies з браузера, де ви увійшли в "
                           "YouTube Music: firefox, chrome, edge, brave, "
                           "chromium, opera, vivaldi, safari")
    auth.add_argument("--cookies", metavar="FILE",
                      help="файл cookies.txt (формат Netscape)")
    p.add_argument("--authuser", type=int, default=0,
                   help="номер Google-акаунта, якщо в браузері їх кілька "
                        "(0 — перший)")
    p.add_argument("--brand-account", metavar="ID",
                   help="ID бренд-акаунта/каналу, якщо слухаєте з нього")
    p.add_argument("--shelf", metavar="TITLE",
                   help="інша полиця головної сторінки замість Quick picks")
    p.add_argument("--list", action="store_true",
                   help="лише показати треки, нічого не завантажувати")
    p.add_argument("--fill", action="store_true",
                   help="після «Швидкого вибору» брати радіо від його "
                        "треків, поки на плеєрі є місце")
    p.add_argument("--max-size", type=parse_size, metavar="SIZE",
                   help="скільки музики записати, напр. 28G або 500M "
                        "(для --itunes: вільне місце на iPod)")
    p.add_argument("--reserve", type=parse_size, default="300M",
                   metavar="SIZE",
                   help="скільки лишити вільним на плеєрі з --rockbox "
                        "(типово 300M)")
    p.add_argument("--limit", type=int, help="не більше N треків")
    p.add_argument("--out", type=Path, default=Path("QuickPicks"),
                   help="тека для музики (типово ./QuickPicks)")
    p.add_argument("--format", choices=("m4a", "mp3"), default="m4a",
                   help="m4a (AAC, без перекодування) або mp3")
    p.add_argument("--bitrate", type=int, default=192,
                   help="кбіт/с, якщо доводиться перекодовувати")
    p.add_argument("--playlist-name", default="Quick Picks")
    p.add_argument("--dated", action="store_true",
                   help="додати дату до назви плейлиста (зберігати історію)")
    p.add_argument("--redownload", action="store_true",
                   help="завантажити заново навіть уже наявні треки")
    p.add_argument("--ytdlp-cookies", action="store_true",
                   help="передати cookies і в yt-dlp (потрібно лише для "
                        "треків 18+)")
    target = p.add_mutually_exclusive_group()
    target.add_argument("--itunes", action="store_true",
                        help="додати плейлист в iTunes (Windows) / "
                             "Музику (macOS)")
    target.add_argument("--rockbox", type=Path, metavar="MOUNT",
                        help="корінь iPod з Rockbox, напр. E:\\ або "
                             "/media/user/IPOD")
    p.add_argument("--rockbox-dir", default="Music/YouTube Music",
                   help="тека на iPod для --rockbox")
    p.add_argument("--sync", action="store_true",
                   help="з --itunes на Windows: одразу синхронізувати iPod")
    return p.parse_args(argv)


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except AttributeError:
            pass

    args = parse_args(argv)
    if args.fill and args.max_size is None and args.rockbox is None:
        die("для --fill скажіть, скільки місця заповнювати: --max-size 28G "
            "(вільне місце на iPod, яке показує iTunes/Finder) або "
            "--rockbox КОРІНЬ_IPOD (тоді місце рахується автоматично).")
    playlist_name = args.playlist_name
    if args.dated:
        playlist_name += f" {dt.date.today().isoformat()}"

    cookie = ytm_cookie_header(load_cookie_jar(args))
    yt = make_ytmusic(cookie, args.authuser, args.brand_account)
    try:
        account = yt.get_account_info().get("accountName")
        print(f"Акаунт YouTube Music: {account}")
    except Exception:  # noqa: BLE001 - older ytmusicapi / not critical
        pass

    picks = get_quick_picks(yt, args.shelf)
    print(f"«Швидкий вибір»: {len(picks)} треків:")
    for i, t in enumerate(picks, 1):
        artists = ", ".join(t["artists"]) or "?"
        print(f"  {i:2}. {artists} — {t['title']}")
    if args.list:
        return 0

    if not shutil.which("ffmpeg"):
        die("не знайдено ffmpeg. Встановіть його (див. README) і додайте "
            "в PATH.")
    yt_dlp = require("yt_dlp", "yt-dlp")

    out_dir = args.out.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / MANIFEST_NAME
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        manifest = {}

    rb_mount = args.rockbox.expanduser() if args.rockbox else None
    rb_dir = (rockbox_prepare(rb_mount, args.rockbox_dir)
              if rb_mount else None)
    space = Space(args.max_size, rb_dir, args.reserve)
    if args.fill:
        print("\nРежим --fill: після «Швидкого вибору» беру радіо від його "
              "треків, поки є місце. Це може тривати години; Ctrl+C зупиняє "
              "і зберігає вже завантажене.\n")

    comment = f"YouTube Music Quick Picks {dt.date.today().isoformat()}"
    entries: list[dict] = []
    failed: list[str] = []
    total_bytes = 0
    fails_in_row = 0
    stop_reason = None
    of_total = "" if args.fill else f"/{len(picks)}"
    with tempfile.TemporaryDirectory(prefix="quickpicks-") as tmp:
        tmpdir = Path(tmp)
        with make_ydl(yt_dlp, tmpdir, args) as ydl:
            try:
                for t in candidates(yt, picks, args.fill):
                    if args.limit and len(entries) >= args.limit:
                        stop_reason = f"досягнуто --limit {args.limit}"
                        break
                    tag = f"[{len(entries) + 1}{of_total}]"
                    label = f"{', '.join(t['artists']) or '?'} — {t['title']}"
                    entry = existing_entry(manifest, t, out_dir, args)
                    if entry is None:
                        estimate = (total_bytes // len(entries) if entries
                                    else DEFAULT_TRACK_SIZE)
                        if not space.fits(estimate,
                                          estimate if rb_dir else 0):
                            stop_reason = "закінчилося місце"
                            break
                        print(f"{tag} завантажую: {label}")
                        try:
                            entry = download_track(
                                ydl, t, tmpdir, out_dir, args.format,
                                manifest.get(t["videoId"]), comment)
                        except Exception as exc:  # noqa: BLE001
                            print(f"    не вдалося: {exc}")
                            failed.append(label)
                            fails_in_row += 1
                            if fails_in_row >= MAX_FAILS_IN_ROW:
                                stop_reason = (
                                    f"{MAX_FAILS_IN_ROW} помилок поспіль — "
                                    "схоже, YouTube тимчасово обмежив "
                                    "завантаження; запустіть пізніше, уже "
                                    "завантажене не повторюватиметься")
                                break
                            continue
                        fails_in_row = 0
                        manifest[t["videoId"]] = entry
                        save_manifest(manifest_path, manifest)
                    else:
                        print(f"{tag} вже є: {label}")
                    path = out_dir / entry["file"]
                    size = path.stat().st_size
                    copy = (rb_dir is not None
                            and rockbox_needs_copy(path, rb_dir))
                    if not space.fits(size, size if copy else 0):
                        stop_reason = "закінчилося місце"
                        break
                    if copy:
                        shutil.copyfile(path, rb_dir / path.name)
                    space.take(size)
                    total_bytes += size
                    entries.append(entry)
            except KeyboardInterrupt:
                stop_reason = "перервано (Ctrl+C)"

    if not entries:
        die("жоден трек не завантажився"
            + (f": {stop_reason}." if stop_reason else "."))

    pl_path = out_dir / f"{safe_name(playlist_name)}.m3u8"
    write_m3u8(pl_path, entries)
    files = [out_dir / e["file"] for e in entries]
    print(f"\nГотово: {len(entries)} треків, {total_bytes / 1e9:.2f} ГБ, "
          f"у {out_dir}")
    if stop_reason:
        print(f"Зупинено: {stop_reason}.")
    print(f"Плейлист: {pl_path}")
    if failed:
        shown = "; ".join(failed[:20]) + (" …" if len(failed) > 20 else "")
        print(f"Не вдалося ({len(failed)}): {shown}")

    if args.itunes:
        add_to_itunes(files, playlist_name, args.sync)
    elif rb_mount is not None:
        rockbox_playlist(rb_mount, args.rockbox_dir, entries, playlist_name)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nПерервано.", file=sys.stderr)
        sys.exit(130)
