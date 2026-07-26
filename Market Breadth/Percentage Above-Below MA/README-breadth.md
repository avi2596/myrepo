# Percentage above and below the moving average

How much of the S&P 500 is above its own 20- and 50-day mean, one row per
trading day. Breadth asks a different question from the index level: not
whether the market went up, but how many of its members went with it. A rally
carried by five names and one carried by four hundred draw the same line on a
price chart — this table tells them apart.

March 2026 is the case for keeping it. Over five weeks the share of members
above their 20-day average fell from 67% on 10 February to **12.8%** on 20
March — nearly the whole index underwater at once, a washout the price chart
states far more mildly.

## Refresh

```bash
pip install -r requirements-breadth.txt
python sp500_breadth_ma.py
```

That downloads the current year, appends any sessions it is missing, and
rewrites the charts, the page and the index. Run it after any close.

| File | What it is |
|---|---|
| `breadth_YYYY.csv` | the table — `date`, `above_20`, `below_20`, `above_50`, `below_50`, plus how many members each figure counted |
| `breadth_YYYY.html` | that year's page: both charts, then every session behind them |
| `breadth_YYYY_20ma.png` / `_50ma.png` | the line charts, above in blue, below in red |
| `breadth_YYYY.json` | the same numbers on their own |
| `index.html` | one link per year, newest first |
| `sp500_constituents.txt` | the member list, cached so a run without a network still has a universe |

Outputs default to this folder regardless of where the script is invoked from.

```bash
python sp500_breadth_ma.py --year 2025        # a past year
python sp500_breadth_ma.py --pages-only       # re-render, download nothing
python sp500_breadth_ma.py --rebuild          # recompute rows already stored
python sp500_breadth_ma.py --refresh-members  # re-read the member list
```

## Adding a year

Nothing to edit. A year's table is created the first time the script is run
inside it, and the year strip on every existing page picks up the new link on
the next run — so last year's archive is never a dead end. The index reports
each year as **complete** or **in progress**, which is read from the data
rather than set by hand: a year is complete once it is behind us and its
December is on the table.

## Frozen years

Rows are kept once written. Membership of the index changes, so recomputing
2026 in 2028 would measure a different 500 companies and quietly rewrite
settled history — the stored row is what the index of the day actually did. A
rerun therefore adds only the sessions it is missing. `--rebuild` is there for
when you want the recomputation anyway.

The bias worth stating: members are read **today** and applied backwards across
the year being built, so a company that left the index in June is missing from
January too. Over a single year the drift is small, but it is real, and it is
the reason completed years are frozen rather than refreshed.

## Method

Adjusted daily closes from Yahoo Finance; members from Wikipedia's current S&P
500 list, with class shares respelled for Yahoo (`BRK.B` → `BRK-B`). The
lookback starts 110 calendar days before January so the 50-day average is
already full on the year's first session — January is not blank.

A member counts toward a figure only once it has **both** a price and a
complete moving average that day, so a company with three months of listing
history is absent from the 50-day count rather than counted as below it. Each
row records the count it used; in 2026 that has been 501–503 on the 20-day and
499–501 on the 50-day.

Above and below are both measured **strictly**, which leaves a stock sitting
exactly on its average in neither column. That is why a row can come to 99.9
rather than 100 — the alternative is defining one side as "not the other" and
silently parking the ties there.

### Partly-published sessions

Yahoo opens a row for the current session before it has filled in the closes:
the volumes are there and the prices are still empty. A day like that arrives
with a few dozen prices out of five hundred, and reading breadth off them says
something confident and wrong — the first run here put 24 July at **0% above**
the 20-day on the strength of the handful that had reported. A session now
counts only once 80% of the index has printed. The rest wait for the next run,
by which time Yahoo has caught up, so an evening run costs you nothing but the
last few hours.

## Colour

Above is blue, below is red, the same pair in the charts and in the table. Not
green and red: this is a share of a universe, not a gain and a loss, and
nothing here is good or bad on its own — 90% above the 20-day is as often the
top of a run as the middle of one.

Both hues are stepped for dark mode on the page, and the two series never rely
on colour alone to be told apart — each is labelled in the legend, and they are
near-mirror images, so above is the line that rises when the market does.

## What the two lines will not tell you

The pair is close to a mirror around 50% by construction — above plus below is
100 minus the ties. Plotting both is a readability choice, not two independent
signals; the information is in the level and how fast it moves, not in the gap
between the lines.
