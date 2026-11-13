# Radio Bridge

Listen in Apple Music, with Spotify choosing the songs.

Radio Bridge is a small macOS menu bar app. While Spotify plays a radio (muted, if you like), it copies each song across to Apple Music: saved to a playlist, added to Up Next, or both.

It needs no Spotify Premium, no Spotify developer app, and no paid Apple developer key.

## What it saves

The official way to build this would mean paying for two things Radio Bridge does without:

| What the official route needs | US price | Per year |
|---|---|---|
| Spotify Premium, required to run a Spotify developer app | $12.99 a month | $155.88 |
| Apple Developer Program, required for an Apple Music API key | $99 a year | $99.00 |
| **Total avoided** | | **$254.88** |

Prices are US list prices as of November 2026 and will change. The one thing you still pay for is the Apple Music subscription you listen with. The free Spotify tier is enough, since Spotify only chooses the songs.

## How it works

1. A Python script asks the Spotify desktop app what is playing, every few seconds, over AppleScript.
2. Once a song has played for 20 seconds, the script passes "artist title" to an Apple Shortcut.
3. The shortcut finds the song in the store and adds it to an Apple Music playlist. A second shortcut adds it to Up Next.

Why this route: Spotify closed its recommendations API to new apps in 2024, and Apple's playlist API needs a paid developer membership. Both desktop apps, though, can be driven locally.

## Requirements

- macOS 13 or later, with the Spotify and Music desktop apps
- An Apple Music subscription
- Python 3 (the one that ships with the Xcode Command Line Tools is enough)
- Xcode Command Line Tools, to build the menu bar app (`xcode-select --install`)

## Setup

### 1. Create the playlist

In Music, create an empty playlist called `Bridge Test` (or any name; see Options).

### 2. Create two shortcuts

In the Shortcuts app, create a shortcut named exactly `Bridge Add`:

1. Add **Find iTunes Store Items**. Click the blue placeholder in its title and choose **Shortcut Input**.
2. Under Show More set Category: Music, Results: Songs, Number of Items: 1.
3. Add **Add to Playlist** and set it to add **iTunes Products** to your playlist.

Duplicate it, name the copy `Bridge Next`, and replace the last action with **Add to Playing Next**, set to **Later**.

### 3. Build and open the app

```sh
./build.sh
open "Radio Bridge.app"
```

Keep the app in this folder; it looks for `bridge.py` next to itself.

The first time, macOS asks whether Radio Bridge may control Spotify and Music and access Apple Music, and Shortcuts asks whether each shortcut may output an iTunes product. Allow them (choose **Always Allow** for the Shortcuts prompt). The price shown in that prompt is the song's store listing, not a purchase.

## Using it

Click the bridge icon in the menu bar:

- **Turn On / Turn Off** starts and stops the bridge.
- **Save songs to playlist** and **Add songs to Up Next** can be switched independently while it runs.
- **Open Log** shows everything it has added, queued, skipped or missed.

Then start a song radio in Spotify. If Apple Music is idle, the bridge starts the first song for you.

### Without the app

```sh
python3 bridge.py --queue          # save to playlist and add to Up Next
python3 bridge.py                  # save to playlist only
python3 bridge.py --no-playlist --queue
python3 bridge.py --dry-run        # log only, change nothing
```

### Options

- `--playlist NAME` must match the playlist chosen in the `Bridge Add` shortcut.
- `--min-seconds N` is how long a song must play before it counts (default 20).

## Limitations

- It copies whatever Spotify plays, one song at a time, as it plays. Apple Music runs about one song behind.
- The Mac must be on with Spotify open.
- Matching is by title and artist through the store's search, so it occasionally picks the wrong song or version. The log marks suspect ones with `CHECK MATCH`.
- Apple Music's Up Next queue can't be read by scripts, so the bridge can't verify the queue itself.
- Adverts on Spotify's free tier are filtered by track type; this has had little testing.

## Files

- `bridge.py` is the bridge itself.
- `app/` holds the menu bar app's source; `build.sh` builds it.
- `queue_test.py` is a leftover experiment for the Spotify Web API route (needs Premium and a developer app).

This is a personal project. It is not affiliated with or endorsed by Spotify or Apple.
