"""
Fill x_inbox.json with the followed accounts' recent posts, from the X API.

    python x_collect.py              # the last 24 hours
    python x_collect.py --hours 48   # a wider window

The accounts are X_ACCOUNTS in market_insight.py. Each one's timeline is read
through the official v2 API — no browser, no login session — which is what lets
the daily job run unattended. Reposts and replies are left out: a repost is
someone else's post, and the brief is about what these accounts publish.

The bearer token is read from the X_BEARER_TOKEN environment variable, or else
from the macOS login keychain, where launchd jobs can reach it:

    security add-generic-password -s marketinsight-x -a bearer -w '<token>'

The inbox is rewritten on every run. It is a staging area: what was printed is
in the edition, and what has been spent is in x_seen.json, so a post collected
twice is still printed once.

Requires: requests
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from market_insight import ET, X_ACCOUNTS, X_INBOX

API = "https://api.x.com/2"
KEYCHAIN_SERVICE = "marketinsight-x"
# The t.co link X appends for attached media; the figure itself is carried
# separately, so the link is just noise at the end of the text.
TRAILING_TCO = re.compile(r"(\s*https://t\.co/\w+)+\s*$")
MEDIA_URL = re.compile(r"/media/([\w-]+)\.(jpg|jpeg|png)", re.I)


def bearer_token() -> str:
    token = os.environ.get("X_BEARER_TOKEN", "").strip()
    if token:
        return token
    try:
        out = subprocess.run(
            ["/usr/bin/security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True, text=True, timeout=10)
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


class XClient:
    def __init__(self, token: str):
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {token}"

    def get(self, path: str, **params) -> dict:
        r = self.session.get(f"{API}{path}", params=params, timeout=30)
        if r.status_code == 429:
            reset = r.headers.get("x-rate-limit-reset", "?")
            raise SystemExit(f"X API rate limit hit on {path} (resets at {reset})")
        if r.status_code != 200:
            raise SystemExit(f"X API {r.status_code} on {path}: {r.text[:300]}")
        return r.json()


def lookup_users(api: XClient) -> dict[str, dict]:
    """{lowercased handle: {id, username, name}} for every followed account."""
    blob = api.get("/users/by", usernames=",".join(X_ACCOUNTS), **{"user.fields": "name"})
    for err in blob.get("errors", []):
        print(f"  ! {err.get('value', '?')}: {err.get('detail', err)}", file=sys.stderr)
    return {u["username"].lower(): u for u in blob.get("data", [])}


def timeline(api: XClient, user: dict, start: datetime) -> list[dict]:
    """One account's own posts since `start`, newest first, as inbox records."""
    posts, token = [], None
    while True:
        params = {
            "start_time": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "max_results": 100,
            "exclude": "retweets,replies",
            "tweet.fields": "created_at,note_tweet,attachments",
            "expansions": "attachments.media_keys",
            "media.fields": "type,url",
        }
        if token:
            params["pagination_token"] = token
        blob = api.get(f"/users/{user['id']}/tweets", **params)
        media = {m["media_key"]: m for m in blob.get("includes", {}).get("media", [])}
        for tweet in blob.get("data", []):
            # Long posts arrive truncated in `text`; the full body is in note_tweet.
            text = (tweet.get("note_tweet") or {}).get("text") or tweet.get("text", "")
            figures = []
            for key in tweet.get("attachments", {}).get("media_keys", []):
                item = media.get(key, {})
                hit = MEDIA_URL.search(item.get("url", "")) if item.get("type") == "photo" else None
                if hit:
                    figures.append({"key": hit.group(1), "fmt": hit.group(2).lower()})
            created = datetime.fromisoformat(tweet["created_at"].replace("Z", "+00:00"))
            posts.append({
                "id": tweet["id"],
                "handle": user["username"],
                "name": user.get("name", user["username"]),
                # In ET, which is what the build's --hours window is measured in.
                "ts": created.astimezone(ET).strftime("%Y-%m-%dT%H:%M"),
                "url": f"https://x.com/{user['username']}/status/{tweet['id']}",
                "text": TRAILING_TCO.sub("", text).strip(),
                "media": figures,
            })
        token = blob.get("meta", {}).get("next_token")
        if not token:
            return posts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--hours", type=int, default=24, help="how far back to read (default 24)")
    args = ap.parse_args()

    token = bearer_token()
    if not token:
        print("no X bearer token: set X_BEARER_TOKEN or add it to the keychain with\n"
              f"  security add-generic-password -s {KEYCHAIN_SERVICE} -a bearer -w '<token>'",
              file=sys.stderr)
        return 2

    api = XClient(token)
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=args.hours)
    users = lookup_users(api)

    posts, notes = [], {}
    for handle in X_ACCOUNTS:
        user = users.get(handle.lower())
        if not user:
            notes[handle] = "account not found"
            continue
        got = timeline(api, user, start)
        posts.extend(got)
        if not got:
            notes[handle] = f"no posts in the last {args.hours}h"
        print(f"  @{user['username']}: {len(got)} post(s), "
              f"{sum(len(p['media']) for p in got)} figure(s)", file=sys.stderr)

    X_INBOX.write_text(json.dumps({
        "collected": now.astimezone(ET).strftime("%Y-%m-%dT%H:%M"),
        "window": f"{start.astimezone(ET):%Y-%m-%d %H:%M} to {now.astimezone(ET):%Y-%m-%d %H:%M} ET",
        "accounts": list(X_ACCOUNTS),
        "notes": notes,
        "posts": sorted(posts, key=lambda p: p["ts"], reverse=True),
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"X: {len(posts)} post(s) from {len(users)} of {len(X_ACCOUNTS)} account(s) "
          f"→ {X_INBOX.name}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
