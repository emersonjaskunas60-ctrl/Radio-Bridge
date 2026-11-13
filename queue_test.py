#!/usr/bin/env python3
"""Live test: does Spotify's queue endpoint expose upcoming radio tracks?

Usage:  python3 queue_test.py <SPOTIFY_CLIENT_ID>

Before running: start a song radio in the Spotify app and leave it playing.
The app's redirect URI must be exactly http://127.0.0.1:8888/callback.
Uses PKCE, so no client secret is needed. The token stays in memory only.
"""
import base64
import hashlib
import http.server
import json
import os
import secrets
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

REDIRECT = "http://127.0.0.1:8888/callback"
SCOPES = "user-read-playback-state user-read-currently-playing"

try:
    import certifi
    CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    cafile = "/etc/ssl/cert.pem" if os.path.exists("/etc/ssl/cert.pem") else None
    CTX = ssl.create_default_context(cafile=cafile)


def call(url, token=None, data=None):
    req = urllib.request.Request(url, data=data)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, context=CTX, timeout=20) as r:
            body = r.read()
            return r.status, json.loads(body) if body else None
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")


def authorize(client_id):
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    result = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if q.get("state", [""])[0] == state:
                result.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Done. You can close this tab.")

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 8888), Handler)
    url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode({
        "client_id": client_id, "response_type": "code",
        "redirect_uri": REDIRECT, "scope": SCOPES, "state": state,
        "code_challenge_method": "S256", "code_challenge": challenge})
    print("Opening Spotify sign-in in your browser...")
    webbrowser.open(url)
    while "code" not in result and "error" not in result:
        server.handle_request()
    server.server_close()
    if "error" in result:
        sys.exit(f"Authorization failed: {result['error']}")

    status, tok = call("https://accounts.spotify.com/api/token", data=urllib.parse.urlencode({
        "grant_type": "authorization_code", "code": result["code"],
        "redirect_uri": REDIRECT, "client_id": client_id,
        "code_verifier": verifier}).encode())
    if status != 200:
        sys.exit(f"Token exchange failed ({status}): {tok}")
    return tok["access_token"]


def describe(t):
    artists = ", ".join(a["name"] for a in t.get("artists", []))
    return f"{t.get('name')} - {artists}  [{t.get('uri')}]"


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    token = authorize(sys.argv[1])

    status, player = call("https://api.spotify.com/v1/me/player", token)
    if status == 200 and player:
        ctx = player.get("context") or {}
        print(f"\nPlayback context: {ctx.get('type')}  {ctx.get('uri')}")
    else:
        print(f"\nPlayer state: HTTP {status} (204 means nothing is playing)")

    status, q = call("https://api.spotify.com/v1/me/player/queue", token)
    if status != 200:
        sys.exit(f"Queue endpoint failed: HTTP {status}\n{q}")
    now = q.get("currently_playing")
    print("Now playing:", describe(now) if now else "nothing")
    upcoming = q.get("queue", [])
    print(f"\nUpcoming tracks returned: {len(upcoming)}")
    for i, t in enumerate(upcoming, 1):
        print(f"{i:2}. {describe(t)}")

    if upcoming:
        status, track = call(f"https://api.spotify.com/v1/tracks/{upcoming[0]['id']}", token)
        isrc = (track.get("external_ids") or {}).get("isrc") if status == 200 else None
        print(f"\nISRC lookup for first upcoming track: HTTP {status}, isrc={isrc}")


if __name__ == "__main__":
    main()
