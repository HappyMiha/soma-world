#!/usr/bin/env python3
"""Вивантажує «Швидкий вибір» (Quick picks) з YouTube Music на iPod.

Що робить скрипт:
  1. Читає вашу головну сторінку YouTube Music (через ytmusicapi і cookies
     з браузера, де ви увійшли в акаунт) і бере полицю «Quick picks».
  2. Завантажує кожен трек через yt-dlp у формат, який розуміє iPod
     (m4a/AAC за замовчуванням, або mp3).
  3. Записує теги (назва, виконавець, альбом) і квадратну обкладинку.
  4. Створює плейлист .m3u8 і, за бажанням:
       --itunes   додає треки в плейлист iTunes (Windows) або Музики (macOS),
                  звідки iPod зі стандартною прошивкою синхронізується;
       --rockbox  копіює файли й плейлист прямо на iPod з прошивкою Rockbox.

Приклади:
  python quickpicks_to_ipod.py --browser firefox --list
  python quickpicks_to_ipod.py --browser firefox --itunes --sync
  python quickpicks_to_ipod.py --cookies cookies.txt --rockbox /media/IPOD

Детальніше: README.md поруч зі скриптом.
"""

from __future__ import annotations

import argparse
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
# Quick picks
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
    thumbs = item.get("thumbnails") or []
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


# --------------------------------------------------------------------------
# Download, cover art, tags
# --------------------------------------------------------------------------

def make_ydl(yt_dlp, tmpdir: Path, fmt: str, bitrate: int, args):
    opts = {
        # m4a: take YouTube's AAC stream as is (no re-encoding).
        "format": ("bestaudio[ext=m4a]/bestaudio/best" if fmt == "m4a"
                   else "bestaudio/best"),
        "outtmpl": str(tmpdir / "%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "noprogress": True,
        "retries": 5,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": fmt,
            "preferredquality": str(bitrate),
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


def copy_to_rockbox(mount: Path, files: list[Path], entries: list[dict],
                    subdir: str, playlist_name: str):
    if not mount.is_dir():
        die(f"{mount} не існує або це не тека (iPod не підключено?)")
    if not (mount / ".rockbox").is_dir():
        if (mount / "iPod_Control").is_dir():
            die("на цьому iPod стандартна прошивка Apple, а не Rockbox.\n"
                "Просто скопійовані файли він не побачить — використайте "
                "--itunes (Windows/macOS) або Strawberry/Rhythmbox на Linux.")
        print("Попередження: теки .rockbox немає, копіюю як на звичайний "
              "USB-плеєр.")
    subdir = subdir.replace("\\", "/").strip("/")
    dest = mount / subdir
    dest.mkdir(parents=True, exist_ok=True)
    for src in files:
        target = dest / src.name
        if target.exists() and target.stat().st_size == src.stat().st_size:
            continue
        shutil.copyfile(src, target)  # copyfile: FAT32 dislikes chmod
    playlists = mount / "Playlists"
    playlists.mkdir(exist_ok=True)
    pl_path = playlists / f"{safe_name(playlist_name)}.m3u8"
    write_m3u8(pl_path, entries, prefix=f"/{subdir}/")
    print(f"Скопійовано {len(files)} треків у {dest}")
    print(f"Плейлист Rockbox: {pl_path}")


APPLESCRIPT = r"""
on run argv
    set plName to item 1 of argv
    set theFiles to {}
    repeat with i from 2 to (count of argv)
        set end of theFiles to ((POSIX file (item i of argv)) as alias)
    end repeat
    tell application "__APP__"
        if not (exists user playlist plName) then
            make new user playlist with properties {name:plName}
        end if
        set pl to user playlist plName
        try
            delete every track of pl
        end try
        add theFiles to pl
    end tell
end run
"""


def add_to_music_macos(files: list[Path], playlist_name: str):
    version = platform.mac_ver()[0] or "10.15"
    parts = [int(x) for x in version.split(".")[:2] if x.isdigit()] + [0]
    # macOS 10.15 Catalina replaced iTunes with the Music app.
    app = "Music" if (parts[0], parts[1]) >= (10, 15) else "iTunes"
    script = APPLESCRIPT.replace("__APP__", app)
    cmd = ["osascript", "-e", script, playlist_name,
           *[str(f.resolve()) for f in files]]
    res = subprocess.run(cmd, capture_output=True, text=True)
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
    for f in files:
        status = playlist.AddFile(str(f.resolve()))
        while status is not None and status.InProgress:
            time.sleep(0.2)
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
    p.add_argument("--limit", type=int, help="взяти лише перші N треків")
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

    tracks = get_quick_picks(yt, args.shelf)
    if args.limit:
        tracks = tracks[:args.limit]
    print(f"Знайдено {len(tracks)} треків:")
    for i, t in enumerate(tracks, 1):
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

    comment = f"YouTube Music Quick Picks {dt.date.today().isoformat()}"
    entries: list[dict] = []
    failed: list[str] = []
    with tempfile.TemporaryDirectory(prefix="quickpicks-") as tmp:
        tmpdir = Path(tmp)
        with make_ydl(yt_dlp, tmpdir, args.format, args.bitrate,
                      args) as ydl:
            for i, t in enumerate(tracks, 1):
                label = f"{', '.join(t['artists']) or '?'} — {t['title']}"
                prefix = f"[{i}/{len(tracks)}]"
                old = manifest.get(t["videoId"])
                if (old and not args.redownload
                        and old.get("file", "").endswith(f".{args.format}")
                        and (out_dir / old["file"]).exists()):
                    print(f"{prefix} вже є: {label}")
                    entries.append(old)
                    continue
                print(f"{prefix} завантажую: {label}")
                try:
                    src, info = download_audio(ydl, t["videoId"], tmpdir,
                                               args.format)
                    meta = {
                        "title": t["title"],
                        "artist": artist_of(t, info),
                        "album": t["album"] or info.get("album"),
                        "year": info.get("release_year"),
                    }
                    tag_file(src, meta, make_cover(t), comment)
                    if (old and old.get("file", "").endswith(
                            f".{args.format}")):
                        dest = out_dir / old["file"]  # --redownload
                    else:
                        base = safe_name(
                            f"{meta['artist']} - {meta['title']}")
                        dest = unique_path(out_dir, base, args.format,
                                           t["videoId"])
                    if dest.exists():
                        dest.unlink()  # Windows can't rename over a file
                    shutil.move(str(src), str(dest))
                except KeyboardInterrupt:
                    raise
                except Exception as exc:  # noqa: BLE001 - keep going
                    print(f"    не вдалося: {exc}")
                    failed.append(label)
                    continue
                entry = {**meta, "file": dest.name,
                         "duration": info.get("duration"),
                         "videoId": t["videoId"]}
                manifest[t["videoId"]] = entry
                entries.append(entry)
                manifest_path.write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=1),
                    encoding="utf-8")

    if not entries:
        die("жоден трек не завантажився.")

    pl_path = out_dir / f"{safe_name(playlist_name)}.m3u8"
    write_m3u8(pl_path, entries)
    files = [out_dir / e["file"] for e in entries]
    print(f"\nГотово: {len(entries)} треків у {out_dir}")
    print(f"Плейлист: {pl_path}")
    if failed:
        print(f"Не вдалося ({len(failed)}): " + "; ".join(failed))

    if args.itunes:
        add_to_itunes(files, playlist_name, args.sync)
    elif args.rockbox:
        copy_to_rockbox(args.rockbox.expanduser(), files, entries,
                        args.rockbox_dir, playlist_name)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nПерервано.", file=sys.stderr)
        sys.exit(130)
