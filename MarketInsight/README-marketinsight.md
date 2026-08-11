# Market Insight

A dated brief built from the public research of **J.P. Morgan Global Research**
and the **Bank of America Institute**, filtered to six subjects — the US stock
market, US macroeconomics, the US dollar, oil, metals and global markets — with
the charts lifted out of the source documents.

```
python market_insight.py                 # build today's brief
python market_insight.py --days 60       # widen the recency window (default 45)
python market_insight.py --per-theme 6   # more notes per subject (default 4)
python market_insight.py --no-cache      # ignore cached pages
python market_insight.py --render-only   # rebuild every page from stored data
```

Requires Python 3.9+ and `pip install -r requirements-marketinsight.txt`.

It also needs to reach `www.jpmorgan.com` and `institute.bankofamerica.com`
directly. Behind a proxy that filters outbound hosts, both must be allowlisted —
otherwise every fetch fails and the run ends with `nothing matched`, which looks
identical to a quiet week.

## What it produces

```
index.html                          the archive — one link per edition, newest first
reports/2026/2026-07-29/
    index.html                      the brief for that date, charts inlined
    artifact.html                   the same page without the outer document
    report.json                     the same thing as data
    assets/                         each chart as a file, if you want to reuse one
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
  style. `--days` and `--per-theme` are the dials.

Headlines, summaries and charts belong to their publishers and are reproduced
for reference, each linked back to the note it came from. Nothing here is
investment advice.
