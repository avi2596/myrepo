# The 7-by-7 table

Every year since 1985 that gained more than 7% over January to July, and what
August to December did next. The question is whether a strong first half is
followed by a giveback — it mostly isn't.

## Refresh

```bash
pip install -r requirements-7by7.txt
python sp500_7by7.py --html --json --csv sp500_7by7.csv
```

That re-fetches from Yahoo Finance and rewrites every output:

| File | What it is |
|---|---|
| `sp500_7by7.png` | the coloured table as a static image |
| `sp500_7by7.html` | interactive page; `--html` swaps its embedded data block in place |
| `sp500_7by7_data.json` | the numbers on their own |
| `sp500_7by7.csv` | three columns — `Year`, `Jan-Jul`, `Aug-Dec` |

Outputs default to this folder regardless of where the script is invoked from.
Run it with no flags for the PNG and terminal table alone.

## Adding a year

Nothing to edit. The qualifying years are recomputed from scratch on every run,
so a year that has just cleared the threshold appears as a new row on its own:

| State | Jan-Jul | Aug-Dec |
|---|---|---|
| July still open | running total, marked `*` | empty — hasn't started |
| August onward | final | running total, marked `*` |
| December closed | final | final, and joins the averages |

The page tags the running year **in progress** and hatches its unfinished
cells. Unfinished figures are excluded from every average, so a year in flight
never pads the hit rate.

## Choosing the cut

```bash
python sp500_7by7.py --threshold 10        # a stricter first half
python sp500_7by7.py --ticker ^IXIC        # another symbol
python sp500_7by7.py --start-year 1950     # a longer sample
```

The threshold matters at the edges: 2025 (+7.39%) and 2026 (+7.71%) are the
thinnest qualifiers in the current set, and `--threshold 8` drops both.

## Method

Each half is measured from its **own first open to its last close** — January's
opening print to July's final close, then August's opening print to the last
close of the year. This matches how the sibling seasonality tool measures year
to date, so the two agree with each other. The cost is that the gap between
July's close and August's open falls in neither column; the benefit is that each
half stands on its own rather than one half's endpoint defining the other's
baseline.

Daily bars, `auto_adjust=True`. `^GSPC` is a price index with no dividend
stream, so these are price returns either way and exclude dividends.

The all-years baseline — August to December for *every* year in the sample,
qualifying or not — is reported alongside. Without it a hit rate says nothing:
if the back half of the year is usually positive anyway, a strong first half has
told you nothing.

## Colour

Positive cells green, negative red, as the fills the PNG and the page share.
Both were checked rather than eyeballed: white text clears 4.5:1 on each fill,
and each fill clears 3:1 against both the light and dark page surfaces.

Red against green is the one pair roughly 8% of men cannot separate, so colour
is never the only channel — every cell carries its sign, unfinished cells are
hatched so the state survives greyscale and print, and the page has a
**colour-blind safe** toggle that swaps gains to blue. Same reasoning as the
sibling tool's `--cvd-safe` flag.

## After a refresh

Nothing to check by hand. Every number, heading, tile and method note on the
page is derived from the embedded data block, so a refresh restates all of it —
including the headline hit rate and the in-progress row.