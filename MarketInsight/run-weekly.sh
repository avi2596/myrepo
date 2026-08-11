#!/bin/bash
#
# The Monday run: build this week's edition, commit it, push it.
#
# Driven by launchd (see com.avi.marketinsight.plist). launchd hands a job
# almost no environment — no PATH worth the name, no working directory, no ssh
# agent — so everything here is resolved from the script's own location and
# every path is absolute.
#
# The guard rails matter more than the automation. A failed scrape ends with
# "nothing matched", which on a page looks exactly like a quiet week, so a run
# that returns little or nothing must not be committed. Better a missing
# edition, which is visible, than a hollow one, which is not.
#
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"
PYTHON="$REPO/.venv/bin/python"
[ -x "$PYTHON" ] || PYTHON="$(command -v python3 || true)"

log() { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
die() { log "FAILED: $*"; exit 1; }

log "=== Market Insight weekly run ==="
[ -n "$PYTHON" ] && [ -x "$PYTHON" ] || die "no usable Python (looked for $REPO/.venv/bin/python)"
log "python: $PYTHON ($("$PYTHON" --version 2>&1))"

TODAY="$(date '+%Y-%m-%d')"
EDITION="$HERE/reports/${TODAY:0:4}/$TODAY"

# Don't commit on top of someone else's work in progress.
BRANCH="$(git -C "$REPO" rev-parse --abbrev-ref HEAD)"
if [ -n "$(git -C "$REPO" diff --cached --name-only)" ]; then
    die "something is already staged in the repo — leaving it alone"
fi

log "building edition for $TODAY"
cd "$HERE"
"$PYTHON" market_insight.py --quiet || die "market_insight.py exited non-zero"

# Did it actually produce something worth keeping?
[ -f "$EDITION/report.json" ] || die "no report.json for $TODAY — the run produced nothing"
NOTES="$("$PYTHON" -c "import json,sys; print(len(json.load(open(sys.argv[1]))['articles']))" "$EDITION/report.json")"
CHARTS="$(find "$EDITION/assets" -type f \( -name '*.png' -o -name '*.svg' \) 2>/dev/null | wc -l | tr -d ' ')"
log "produced $NOTES notes, $CHARTS charts"

[ "$NOTES" -ge 3 ] || die "only $NOTES notes — treating as a broken scrape, not committing"
[ "$CHARTS" -ge 1 ] || die "no charts extracted — treating as a broken scrape, not committing"

if [ "$BRANCH" != "main" ]; then
    log "on branch '$BRANCH', not main — edition built and left uncommitted"
    exit 0
fi

# Only the edition data and the archive index — never the source. Staging the
# whole folder would sweep up whatever happened to be sitting there unfinished
# and commit it under an edition's name.
git -C "$REPO" add MarketInsight/reports MarketInsight/index.html
STAGED="$(git -C "$REPO" diff --cached --name-only)"
if [ -z "$STAGED" ]; then
    log "no change to commit (already built today) — done"
    exit 0
fi

# Re-running on a day already built rewrites report.json's build time and
# nothing else. That is not an edition, so don't make a commit out of it.
if [ "$(echo "$STAGED" | wc -l | tr -d ' ')" = "1" ] && \
   [ "$STAGED" = "MarketInsight/reports/${TODAY:0:4}/$TODAY/report.json" ] && \
   [ "$(git -C "$REPO" diff --cached --numstat -- "$STAGED" | cut -f1-2)" = "1	1" ]; then
    log "only the build timestamp changed — already built today, nothing to commit"
    # Put the file back rather than leaving a stray one-line diff behind, or it
    # would ride along in next week's edition commit. The pages are then
    # re-rendered so what they show matches what is stored again.
    git -C "$REPO" restore --staged --worktree "$STAGED"
    "$PYTHON" market_insight.py --render-only >/dev/null
    exit 0
fi

SUBJECTS="$("$PYTHON" -c "
import json, sys
blob = json.load(open(sys.argv[1]))
seen = []
for a in blob['articles']:
    for t in a['themes']:
        if t not in seen:
            seen.append(t)
print(', '.join(seen))
" "$EDITION/report.json")"

git -C "$REPO" commit -q -m "Market Insight: edition for $(date '+%-d %B %Y')" -m \
"$NOTES notes, $CHARTS charts. Subjects covered: $SUBJECTS.

Built automatically by run-weekly.sh." || die "commit failed"

log "committed $(git -C "$REPO" rev-parse --short HEAD)"

if ! git -C "$REPO" push -q origin main 2>&1; then
    log "push rejected — rebasing on origin/main and retrying once"
    git -C "$REPO" pull --rebase -q origin main || die "rebase failed; commit is local, push it by hand"
    git -C "$REPO" push -q origin main || die "push failed twice; commit is local, push it by hand"
fi

log "pushed to origin/main — done"
