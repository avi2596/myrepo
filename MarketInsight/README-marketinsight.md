# Market Insight

A daily brief, built at **07:00 ET**, of everything a fixed list of X accounts
posted in the previous 24 hours, sorted under six subjects — the US stock
market, US macroeconomics, the US dollar, oil, metals and global markets — plus
an *Other* section for anything off-topic, with each post's charts inlined. No
post or chart is printed twice.

```
python x_collect.py                          # fill x_inbox.json from the X API (last 24h)
python market_insight.py --hours 24          # build today's brief from it
python market_insight.py --days 60           # or: a date window instead of an hour window
python market_insight.py --render-only       # rebuild every page from stored data
python market_insight.py --reindex           # rebuild x_seen.json from the editions on disk
```

Requires Python 3.9+ and `pip install -r requirements-marketinsight.txt`.

Collection uses the official X API v2 and needs a bearer token from
developer.x.com with read access to user timelines (a paid tier). It is read
from `X_BEARER_TOKEN`, or from the login keychain, which is where the launchd
job finds it:

```
security add-generic-password -s marketinsight-x -a bearer -w '<token>'
```

Before 11 November 2026 the brief also scraped J.P. Morgan Global Research and
the Bank of America Institute; those editions still render as they were built.

## What it produces

```
index.html                          the archive — one link per edition, newest first
reports/2026/2026-07-29/
    index.html                      the brief for that date, charts inlined
    artifact.html                   the same page without the outer document
    report.json                     the same thing as data
    assets/                         each chart as a file, if you want to reuse one
x_inbox.json                        posts collected from X, waiting to be used
x_seen.json                         every X post and figure already printed
```

Editions are filed under their year. Both the folder and the page's own **Log**
group by year, so a few hundred editions stay navigable rather than becoming one
long list. Editions written before the year folders existed are moved into place
automatically on the next run.

Every run writes today's folder and leaves earlier days untouched, so the folder
becomes an archive. Older editions get their date rail rewritten so they can
still navigate to the new one; nothing else about them changes. Run it twice in
a day and the day's edition is rebuilt in place.

## What is kept, and what is regenerated

The two HTML files are **not** in version control. Each inlines every chart as
base64, and the artifact copy inlines them a second time, so an edition weighs
about 5MB of which almost all is duplication — committing one a day would add a
couple of gigabytes a year.

What is kept is what an edition is made of:

| file | size | why it is kept |
| --- | --- | --- |
| `report.json` | ~25KB | the words: headlines, summaries, dates, subjects, links |
| `assets/` | ~1MB | the figures, exactly as they came out of the source |
| `x_seen.json` | ~15KB | what has already been printed, so nothing is printed twice |

Both HTML files are rebuilt from those two, byte for byte, by

```
python market_insight.py --render-only
```

which also re-renders the archive index and every past edition — so it is the
command to run after changing the layout, not just after a fresh checkout. The
build timestamp shown on a page comes from `report.json` rather than the clock,
which is what makes a regenerated edition identical to the original and stops it
claiming to have been built months after it was.

Keeping the figures matters more than it looks: a source PDF can be revised or
withdrawn, and once it is, a chart that was not saved cannot be recovered.

## The daily run

`run-daily.sh` collects the last 24 hours from X, builds that day's edition,
commits it and pushes it. It is driven by launchd:

```
cp com.avi.marketinsight.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.avi.marketinsight.plist
launchctl kickstart -p gui/$UID/com.avi.marketinsight   # run it now
launchctl bootout gui/$UID/com.avi.marketinsight        # stop scheduling it
```

Output goes to `~/Library/Logs/marketinsight-daily.log`.

The Mac keeps London time, and the US and UK change clocks on different
weekends, so 07:00 ET is 12:00 in London most of the year and 11:00 for a few
weeks in spring and autumn. launchd fires at both, and the script decides in ET:
before 07:00 it exits, and once today's edition is committed every later call
exits too. If the Mac is asleep, launchd runs the job when it next wakes; the
window is still the 24 hours before that moment, and the ledger stops anything
from the previous edition reappearing. A Mac that stays shut all day misses
that edition.

Anything that stops the run raises a macOS notification as well as logging it:
no token, an X API error, or a build that finds nothing. A silent failure is the
worst outcome here — the page simply goes on showing yesterday's edition. A
missed day leaves no trace of its own, so the next run that works reports a gap
of more than two days.

The job refuses to commit a hollow edition: fewer than three posts, or no charts
at all, and it logs the failure and stops. It stages the edition data, the
archive index and `x_seen.json` — the ledger that prevents repeats — never
source, and a second run on a day already built is skipped rather than
committed again.

## The published pages

Every edition is published at a permanent URL of its own, and keeps it. Which
edition lives where is recorded in `published.json`, committed alongside the
data, so a later run republishes to the same address instead of minting a
second copy of the same day.

The archive is the standing page: it is the one address that never changes and
always lists everything, newest first. Each edition links back to it, which is
the only cross-link that cannot go stale — listing sibling editions inside a
published page would be wrong the moment another one appeared.

A scheduled cloud agent does this every day at 13:00 UTC, an hour or two after
the Mac has pushed. It renders the pages from stored data, mints a URL for the
new edition, commits that URL to `published.json`, and republishes the archive.
It never collects: it needs only GitHub and PyPI.

Artifacts are private until shared from the page's own share menu.

## Where the charts come from

This is the part worth explaining, because the two desks publish nothing alike.

**J.P. Morgan** puts its exhibits in the article page as SVGs, so they transfer
as vectors and stay sharp at any size. The difficulty is telling an exhibit from
the staff portraits and related-story headers sharing the page: a file counts as
a chart when its name says so (`OECD_Graph.svg`, `2027_Projection_Table.svg`) or
when it carries the long alt text the accessibility team writes for figures —
which doubles as the caption. Files named `..._Graphic.svg` are the decorative
icon strips on outlook pages, and are skipped.

**The Bank of America Institute** publishes a short summary on the web and keeps
every exhibit in the "full analysis" PDF. So the PDF is opened and each figure
cropped out of it, anchored on the two lines that reliably bracket one exhibit:
the `Exhibit N:` caption above it, and the `Source:` / `BANK OF AMERICA
INSTITUTE` line below. Anchoring on the text rather than on the drawing matters
— the vector clusters that make up a chart sometimes merge with the rest of the
page and swallow it whole. Column width comes from the layout: two captions on
one line means a two-column page and half-width figures.

Captions wrap across lines, and the wrap is found by font: the Institute sets
captions in a bold cut and the chart's subtitle in a light one, so the caption
is the run of lines sharing the first line's face. The bold *flag* is not usable
for this — several of these templates mark neither line as bold.

## The X accounts

Since 11 November 2026 the brief reads **only** these X accounts — the J.P.
Morgan and Bank of America Institute scrapers have been removed. The list lives
in `X_ACCOUNTS` in `market_insight.py`; a post in the inbox from anyone else is
skipped.

| account |
| --- |
| `@dailychartbook` |
| `@Bluekurtic` |
| `@KobeissiLetter` |
| `@TedHZhang` |
| `@Mayhem4Markets` |
| `@RyanDetrick` |
| `@FactSet` |
| `@RenMacLLC` |

Editions built before the switch still hold desk notes in their `report.json`
and render exactly as before.

Every post from these accounts in the window is shown — nothing is capped per
subject or per account. Reposts and replies are not collected; quote posts are.

### How posts are collected

`x_collect.py` looks the accounts up once per run, then reads each timeline
since the start of the window through the API (`/2/users/:id/tweets`, reposts
and replies excluded) and writes `x_inbox.json`: id, ET timestamp, full text
(long posts included) and the key of each attached photo.

The figures are not in the inbox. `pbs.twimg.com` serves them to anyone, so the
build fetches them by key through the same cached `Fetcher` it uses for
everything else, and they land in the edition's `assets/`.

`x_inbox.json` is not in version control. It is a staging area rather than a
record: what was actually printed is in the edition, and what has been spent is
in `x_seen.json`.

### Nothing is printed twice

`x_seen.json` is the ledger, and it is committed, because it is the only thing
standing between a weekly brief and a great deal of repetition. The recency
window is far wider than the gap between runs, so a chart that led last Monday
is still well inside the window this Monday. Measured on the first two editions
to carry both sources, **17 of the 22 figures on 5 October had already appeared
on 1 October**.

The rule is the same whatever the source: **a figure is printed once.** A chart
says nothing the second time, so once it has appeared it does not come back.

What *is* allowed to carry over is a note's words. A note from either desk
still appears each week with its headline, summary and link, because the
standing picture for each subject is what the brief is for — it simply loses
the figures the reader has already seen. A note in its third week is text and a
link; a note that is new shows everything it came with. A post from X is
different again: a post is its chart, so once the chart is spent the post goes
with it.

### The five disguises a repeat arrives in

A repeat is rarely bit-identical to what it repeats, so five kinds of token are
retired, not one:

| token | catches |
| --- | --- |
| `post:<id>` | the post itself, reposted or re-collected |
| `media:<key>` | X's own id for an upload, shared by a quote-repost |
| `sha:<digest>` | the exact bytes, when one upload is re-served under a second key |
| `phash:<hex>` | the *picture*, when the same chart is re-encoded, rescaled or re-cropped on its way to a second upload and so shares neither key nor bytes |
| `text:<words>` | the *claim*, when two accounts report one number in different words, or an account restates its own chart in a weekly round-up |

The first three are exact lookups. The last two are comparisons, because a
re-encoded chart and a reworded sentence are never identical to what they
repeat:

- **The picture.** A difference hash: the figure is reduced to 9×8 greyscale
  and what is recorded is which way the brightness steps between neighbouring
  pixels. That throws away everything re-encoding changes and keeps the shape
  of the plot. Re-encoding one of these charts at 50% scale and quality 35
  moves the hash by **1 bit**; two different charts sit **30 bits** apart. The
  threshold is 6, which is comfortably inside that gap.
- **The claim.** Not a hash of the text, which changes completely when one word
  does, but the *set* of content words, compared by how much of it two posts
  share. One PCE print reported by two accounts in different sentences overlaps
  a little over **half**; two unrelated posts overlap **almost nothing**. The
  threshold is 0.45. Each word is kept as a short hash, so an entry stays on
  one line and the ledger is a record of what was printed rather than a
  readable copy of it.

Every figure an edition prints is fingerprinted, not only the ones from X.
Several of these accounts republish sell-side exhibits and two of the desks the
brief reads directly are on that list, so the same J.P. Morgan figure can
arrive twice — once from `jpmorgan.com`, once via `@dailychartbook`. Recording
what the desks supplied is what lets the X side recognise it coming round
again.

The run also checks against itself, not only against the ledger. Two of these
accounts posting one chart on the same morning is the ordinary case, and
neither is in the ledger yet when the other is considered.

### What the ledger is, and what it is not

Only what an edition actually printed is retired. A post that was collected but
crowded out of its subject stays in the inbox and is a candidate again next
week, so a busy Monday does not burn a fortnight of material. Figures are read
off the charts still attached at the end rather than off everything fetched —
the budget trimmer drops surplus figures *after* selection, and a figure
retired without having been printed would be lost from every future brief
without ever having appeared in one. Retirement happens after the edition is
safely on disk, so a post spent against a run that then failed to write is not
lost either.

Running twice in a day rebuilds that day's edition in place, so the day being
built is **rewritten in the ledger, not merged into**. This matters more than
it sounds. Merging is what the first version did, and because selection shifts
between runs, rebuilding one day's edition three times left the ledger holding
the union of all three runs' picks — six posts were retired having never
appeared on a page.

That bug is the reason the ledger is derivable rather than merely accumulated:

```
python market_insight.py --reindex
```

rebuilds `x_seen.json` from the editions on disk. The editions are the record
of what was printed; the ledger is a convenience kept alongside them, and
anything kept alongside can drift. Deriving it from the archive makes the drift
answerable — whatever the ledger claims can be checked against, and replaced
by, what the pages actually show. Worth running after a ledger is lost, after
editing an edition by hand, or to confirm the two still agree.

Tokens are stamped with the edition that printed them **first**, which is what
"already seen" has to mean. Stamped with the last one instead, a figure carried
for weeks would look newer every week, and rebuilding the day it was last seen
would let it straight back in.

Media keys are not restored by `--reindex`, because an edition does not keep
them and does not need to: the figure's bytes and its appearance are both
recorded, and either catches a repeat the key would have caught.

### Scoring a post

Posts are scored against the same six-subject vocabulary as a research note,
but not at the same threshold. A post is terse by construction — a sentence and
a chart, where a note has nine paragraphs — and would almost never reach the
score a note has to. The bar for a post is therefore the theme floor it has
already cleared. The gap between the two floors exists to keep the Institute's
consumer-lifestyle research out of the brief, and none of these accounts
publishes that.

Posts are also selected separately from the notes, rather than thrown into one
ranking. A post always outranks a note on recency — these accounts publish
within the hour, the desks within the month — so a shared ranking would hand
every subject to X and bury the research the brief is built on. Each subject
takes its three best posts and no more.

A post has no headline, because nobody wrote one: the first sentence becomes
the headline and the rest becomes the standfirst. Where there is no sentence to
break on, a colon will do — these accounts write *"The Tech x Energy barbell is
chugging along: …"* — and where there is neither, the headline is cut short and
the standfirst carries the post in full.

## How notes are chosen

Each note is scored against a weighted vocabulary for the six subjects. Where a
word appears counts for more than how often: the headline and the URL slug are
the desk telling you what a piece is about, so body hits are capped and a single
mention of China cannot drag a US wage note into Global Markets.

- A note **joins a subject** at a score of 5, and **enters the brief** at 10.
  The gap is deliberate. The Institute publishes a lot of consumer-lifestyle
  research that brushes against macro vocabulary — a study of wedding budgets
  genuinely is about spending — and the higher bar keeps it out.
- A **second subject** must reach 40% of the note's strongest score, which lets
  a wide-ranging outlook file under everything it covers without letting a Fed
  note that mentions copper once appear under Metals.
- Selection runs **per subject**, not globally, or a busy week of macro copy
  would crowd out the only oil note. Within a subject, a note actually filed
  there outranks a broad outlook that merely touches it, however recent that
  outlook is — otherwise the dollar section fills with pieces about everything
  and the one real currency note never appears.
- If a subject has both desks writing, **both are shown**, since they answer the
  same question differently: J.P. Morgan from the forecast side, the Institute
  from its own card and payroll data.

Notes are filed on the page under their strongest subject only, so a chart-heavy
outlook is not printed six times. The other subjects it covers are listed as
tags on the card.

## What is new this week

Run weekly, consecutive editions overlap heavily — the recency window is far
wider than the gap between runs, so most of each subject's standing picture
repeats from one Monday to the next. Measured across the first two editions,
6 of 10 notes were carried over.

Dropping the older notes would lose the context, which is the point of the
page, so instead each note that was not in the previous edition is marked
**New**, sorted to the top of its section, and counted in the masthead
("4 new since 29 Jul"). What a carried-over note does *not* bring with it is
its figures — see *Nothing is printed twice* — so the **New** flag is also the
answer to why one note has charts and the one below it does not. The flag is stored in `report.json`, so a page rebuilt
with `--render-only` months later still shows what was new at the time rather
than recomputing it against whatever is on disk now.

The first edition has nothing to compare against, so nothing is marked.

## Getting around the page

The **Log** in the left rail lists every edition, newest first, grouped under
its year, with the one you are reading marked. It is how you get back to any
previous date.

The six counters across the top are the table of contents: each one jumps to
its section. They are plain fragment links, so the jump is instant and works
with JavaScript off — the page ships with no script at all. A subject nobody
wrote about in the window has no section to jump to, so its counter is dimmed
and inert rather than being a link that goes nowhere.

## Dates

Discovery goes through each site's sitemap rather than the homepage, because
both homepages render their cards in the browser and arrive empty. The sitemap's
`lastmod` finds candidates, but it also moves when a template is retouched, so
the publication date is taken from the document itself wherever one exists —
J.P. Morgan stamps a timestamp in a meta tag, and the Institute prints the date
on the front page of the PDF. Anything whose real date falls outside the window
is dropped, which is what keeps last December's holiday-shopping note out of a
July brief.

## Known limits

- **Public tier only.** Both desks put their deep research behind a login. This
  reads what is open, which is more than it sounds.
- **Bank of America Daily Insights** has no article pages — each headline links
  straight to a tracked PDF — so those are carried as a dated one-line list
  rather than as notes.
- **Transcripts are quoted from sparingly.** Some J.P. Morgan pages are webcast
  transcripts; picking the least chatty paragraphs out of a conversation still
  reads as a conversation, so when a page is mostly dialogue the card falls back
  to the desk's own summary line.
- **Keyword scoring is not comprehension.** It is tuned against what these two
  desks actually publish and will need revisiting if either changes its house
  style. `--hours` and `--days` are the dials. The vocabulary carries each
  subject twice over, because the desks and the accounts do not write alike: a
  desk writes "the stock market" and "emerging markets", while an account
  writes SPX, XLK, FTSE, Ibovespa. Terms match on word boundaries — without
  that, "Goldman Sachs" contains "gold" and files a note about equity
  positioning under Metals, which these accounts quote often enough for it to
  matter.
- **The picture hash is not comprehension either.** It recognises the same
  figure re-encoded, rescaled or lightly re-cropped. It will not recognise the
  same *data* redrawn — a desk's chart and an account's own plot of the same
  series are two different pictures, and both can appear. Pillow is what
  computes it; without Pillow installed that check is skipped and the other
  four still apply.
- **X needs a browser.** The build itself is unattended, but the inbox it reads
  is not — see *The X accounts*. An account can also simply go quiet, and a
  quiet account is indistinguishable from a collection that failed: on
  1 October 2026 `@SubuTrade` had not posted since 16 April. The collector
  records a note per account when it finds nothing, so a silent week says which
  it was.
- **Charts are reproduced, not interpreted.** A figure posted to X carries
  whatever its original publisher put on it, and several arrive second-hand —
  `@dailychartbook` reposting a Strategas or NDR exhibit. The post is linked so
  the chain is followable, but the brief does not check the underlying data.

Headlines, summaries and charts belong to their publishers and are reproduced
for reference, each linked back to the note or post it came from. Nothing here is
investment advice.
