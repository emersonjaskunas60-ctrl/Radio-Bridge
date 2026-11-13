#!/usr/bin/env python3
"""Spotify radio -> Apple Music bridge (keyless prototype).

Watches the Spotify desktop app, and hands each new track to the
"Bridge Add" shortcut, which finds it in the store and adds it to the
Apple Music playlist chosen inside that shortcut.

    python3 bridge.py              watch until Ctrl+C
    python3 bridge.py --once       handle the current track, then exit
    python3 bridge.py --dry-run    log what would be added, add nothing
"""
import argparse
import datetime
import fcntl
import json
import os
import pathlib
import re
import ssl
import subprocess
import sys
import time
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
SEEN_FILE = HERE / "seen.json"
LOG_FILE = HERE / "bridge.log"
SEP = "\x1f"

SPOTIFY_SCRIPT = f'''
tell application "Spotify"
    if player state is stopped then return "stopped"
    set t to current track
    return (player state as string) & "{SEP}" & (id of t) & "{SEP}" & (name of t) & "{SEP}" & (artist of t) & "{SEP}" & (player position as string)
end tell
'''

PLAYLIST_SCRIPT = f'''
tell application "Music"
    if not (exists user playlist "%s") then return ""
    set out to ""
    repeat with t in tracks of user playlist "%s"
        set out to out & (name of t) & "{SEP}" & (artist of t) & linefeed
    end repeat
    return out
end tell
'''


def log(msg):
    line = f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S}  {msg}"
    print(line, flush=True)
    with LOG_FILE.open("a") as f:
        f.write(line + "\n")


def osa(script):
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip())
    return r.stdout.rstrip("\n")


def spotify_running():
    return subprocess.run(["pgrep", "-x", "Spotify"], capture_output=True).returncode == 0


def now_playing():
    """Return dict for the current Spotify item, or None if nothing usable."""
    if not spotify_running():
        return None
    out = osa(SPOTIFY_SCRIPT)
    if out == "stopped":
        return None
    state, uri, name, artist, pos = out.split(SEP)
    return {"state": state, "uri": uri, "name": name, "artist": artist,
            "position": float(pos.replace(",", "."))}


def norm(s):
    """Loose form for comparing titles/artists across the two services."""
    s = s.lower()
    s = re.sub(r"\s+-\s+.*$", "", s)          # " - Remastered 2011", " - Radio Edit"
    s = re.sub(r"[\(\[].*?[\)\]]", "", s)     # "(feat. X)", "[Live]"
    s = re.split(r",|&| feat\.? | with ", s)[0]
    return re.sub(r"[^a-z0-9]+", "", s)


def playlist_keys(playlist):
    """Map of loose (title, artist) key -> the title as Apple Music shows it."""
    out = osa(PLAYLIST_SCRIPT % (playlist, playlist))
    keys = {}
    for line in out.splitlines():
        if SEP in line:
            n, a = line.split(SEP, 1)
            keys[key_of(n, a)] = n
    return keys


# Suffixes that describe the same recording, so are left out of the search.
NOISE = re.compile(r"remaster|single version|album version|mono|stereo|bonus track|^original mix$", re.I)
FILLER = {"mix", "remix", "version", "edit", "original", "the", "a"}


def version_text(name):
    """The ' - VIP Mix' or '(VIP Mix)' part of a title, or '' if absent or meaningless."""
    m = re.match(r"^.*?\s+-\s+(.*)$", name)
    if m:
        v = m.group(1)
    else:
        parts = [x for x in re.findall(r"[\(\[](.*?)[\)\]]", name)
                 if not re.match(r"(feat|with)\b", x, re.I)]
        v = parts[-1] if parts else ""
    return "" if NOISE.search(v) else v


def version_words(version):
    return sorted(w for w in re.findall(r"[a-z0-9]+", version.lower()) if w not in FILLER)


def key_of(name, artist):
    """Loose identity for a recording: title, lead artist, and which version it is."""
    return (norm(name), norm(artist), " ".join(version_words(version_text(name))))


def queries_for(track):
    """Searches to try in order: with the version suffix first, then without."""
    title = re.sub(r"\s+-\s+.*$", "", track["name"])
    title = re.sub(r"\s*[\(\[](feat|with)[^\)\]]*[\)\]]", "", title, flags=re.I)
    artist = track["artist"].split(",")[0]
    base = f"{artist} {title}".strip()
    version = version_text(track["name"])
    return [f"{base} {version}", base] if version else [base]


def add_to_apple(query, shortcut, timeout=120):
    r = subprocess.run(["shortcuts", "run", shortcut, "-i", "-"],
                       input=query, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0 or r.stderr.strip():
        log(f"  [{shortcut} exit {r.returncode}] {r.stderr.strip()[:300]}")
    # The shortcut's own result is not needed. When macOS cannot hand it back to
    # the command line it reports this error even though the actions ran.
    if r.returncode != 0 and "output of the shortcut could not be processed" not in r.stderr:
        raise RuntimeError(r.stderr.strip() or f"shortcut exited {r.returncode}")


def load_seen():
    if SEEN_FILE.exists():
        return json.loads(SEEN_FILE.read_text())
    return {}


def store_has(query):
    """True if the store search finds a song for this query (True on network trouble)."""
    try:
        cafile = "/etc/ssl/cert.pem" if pathlib.Path("/etc/ssl/cert.pem").exists() else None
        ctx = ssl.create_default_context(cafile=cafile)
        url = "https://itunes.apple.com/search?" + urllib.parse.urlencode(
            {"term": query, "entity": "song", "limit": 1, "country": "us"})
        with urllib.request.urlopen(url, context=ctx, timeout=10) as r:
            return json.load(r).get("resultCount", 0) > 0
    except Exception:
        return True


def apply_settings(args):
    """Re-read the settings file (written by the menu bar app) so toggles apply live."""
    if not args.settings:
        return
    try:
        cfg = json.loads(pathlib.Path(args.settings).read_text())
    except Exception:
        return
    new = (bool(cfg.get("playlist", True)), bool(cfg.get("queue", True)))
    if new != (args.save, args.queue):
        args.save, args.queue = new
        log(f"settings: save to playlist {'on' if args.save else 'off'}, add to queue {'on' if args.queue else 'off'}")


def music_state():
    try:
        return osa('tell application "Music" to get player state as string')
    except Exception:
        return "unknown"


def queue_up(query, label, args, apple_title=None):
    """Put the song at the end of Apple Music's Playing Next queue.

    If Music is idle there is no queue to join, so the song is started instead.
    """
    if not args.queue:
        return
    try:
        idle = music_state() == "stopped"
        if idle and args.save and apple_title:
            safe = apple_title.replace("\\", "\\\\").replace('"', '\\"')
            osa(f'tell application "Music" to play (last track of user playlist "{args.playlist}" whose name is "{safe}")')
            log(f"playing now (Music was idle): {label}")
            return
        add_to_apple(query, args.queue_shortcut, timeout=30)
        log(f"queued: {label}")
        if idle:
            time.sleep(2)
            if music_state() == "stopped":
                osa('tell application "Music" to play')
            log(f"  Music was idle; after starting it the player is: {music_state()}")
    except Exception as e:
        log(f"could not queue {label}: {e}")


def handle(track, seen, args):
    """Try to add one track. Returns a short status word."""
    key = key_of(track["name"], track["artist"])
    label = f'{track["name"]} - {track["artist"]}'
    if not args.save:
        queries = queries_for(track)
        query = next((q for q in queries if store_has(q)), None)
        if query is None:
            seen[track["uri"]] = "not found"
            log(f"MISS (not in store): {label}   [searches: {queries}]")
            return "miss"
        if args.dry_run:
            log(f'dry run, would queue: {label}   [search: "{query}"]')
            return "dry"
        queue_up(query, label, args)
        seen[track["uri"]] = "queued only"
        return "queued"
    before = playlist_keys(args.playlist)
    if key in before:
        seen[track["uri"]] = "already in playlist"
        log(f"skip (already in playlist): {label}")
        if not args.dry_run:
            queue_up(f'{track["artist"].split(",")[0]} {before[key]}', label, args, before[key])
        return "skip"
    queries = queries_for(track)
    if args.dry_run:
        log(f"dry run, would add: {label}   [searches: {queries}]")
        return "dry"
    added = {}
    for query in queries:
        add_to_apple(query, args.shortcut)
        for _ in range(5):
            time.sleep(2)
            now = playlist_keys(args.playlist)
            added = {k: v for k, v in now.items() if k not in before}
            if added:
                break
        if added:
            break
    if not added:
        seen[track["uri"]] = "not found"
        log(f"MISS (nothing added): {label}   [searches: {queries}]")
        return "miss"
    got = "; ".join(added.values())
    if key not in added:
        seen[track["uri"]] = "added, check match"
        log(f"added, but CHECK MATCH (wrong song or version?): wanted {label}; Apple Music added: {got}")
        queue_up(query, label, args, next(iter(added.values())))
        return "check"
    seen[track["uri"]] = "added"
    log(f"added: {label}  ->  {got}")
    queue_up(query, label, args, added[key])
    return "added"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--once", action="store_true", help="handle the current track and exit")
    p.add_argument("--dry-run", action="store_true", help="log only, add nothing")
    p.add_argument("--playlist", default="Bridge Test", help="must match the playlist set in the shortcut")
    p.add_argument("--shortcut", default="Bridge Add")
    p.add_argument("--queue", action="store_true",
                   help="also add each song to Apple Music's Playing Next queue")
    p.add_argument("--queue-shortcut", default="Bridge Next")
    p.add_argument("--no-playlist", action="store_true", help="do not save songs to the playlist")
    p.add_argument("--settings", help="JSON file with playlist/queue switches, re-read while running")
    p.add_argument("--min-seconds", type=float, default=20,
                   help="only add a track once it has played this long (skipped songs are ignored)")
    p.add_argument("--interval", type=float, default=5, help="seconds between checks")
    args = p.parse_args()
    args.save = not args.no_playlist

    if not (args.once or args.dry_run):
        # Two copies running at once would add and queue every song twice.
        lock = open(HERE / ".bridge.lock", "w")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            log("another copy of the bridge is already running; not starting a second one")
            return 1
        args._lock = lock

    seen = load_seen()   # record of every track handled, kept across runs
    session = set()      # tracks handled since this run started
    apply_settings(args)
    log(f"watching Spotify: save to playlist '{args.playlist}' {'on' if args.save else 'off'}, "
        f"add to queue {'on' if args.queue else 'off'}" + ("  (dry run)" if args.dry_run else ""))
    waiting_noted = False
    try:
        while True:
            if args.settings and os.getppid() == 1:
                log("the app that started the bridge has gone; stopping")
                return 0
            apply_settings(args)
            try:
                track = now_playing()
            except Exception as e:
                log(f"could not read Spotify: {e}")
                track = None
            if track is None:
                if args.once:
                    log("Spotify is not running or nothing is loaded")
                    return
                if not waiting_noted:
                    log("waiting for Spotify to play something...")
                    waiting_noted = True
            else:
                waiting_noted = False
                uri = track["uri"]
                is_song = uri.startswith("spotify:track:")
                ready = args.once or (track["state"] == "playing" and track["position"] >= args.min_seconds)
                if not is_song:
                    if args.once:
                        log(f"current item is not a song ({uri.split(':')[1]}), ignoring")
                elif uri not in session and ready and (args.save or args.queue):
                    session.add(uri)
                    try:
                        status = handle(track, seen, args)
                    except Exception as e:
                        status = "error"
                        log(f'error adding {track["name"]} - {track["artist"]}: {e}')
                    if status not in ("dry", "error"):
                        SEEN_FILE.write_text(json.dumps(seen, indent=1))
            if args.once:
                return
            time.sleep(args.interval)
    except KeyboardInterrupt:
        log("stopped")


if __name__ == "__main__":
    sys.exit(main())
