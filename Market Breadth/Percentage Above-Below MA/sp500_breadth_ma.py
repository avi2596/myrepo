"""
How much of the S&P 500 is above its moving average — one row per trading day.

Breadth asks a different question from the index level: not "did the market go
up" but "how many of its members went with it". A rally carried by five names
looks the same on the chart as one carried by four hundred; this table tells
them apart. Each session gets the share of members trading above their own
20-day mean, the share below it, and the same pair for the 50-day.

    python sp500_breadth_ma.py                 # today's session onto this year
    python sp500_breadth_ma.py --rebuild       # recompute the whole year
    python sp500_breadth_ma.py --year 2025     # a past year
    python sp500_breadth_ma.py --pages-only    # re-render, download nothing

Running it after the close is the whole maintenance story. Rows already stored
are left alone and only the missing sessions are added, so the year's table
grows a line a day. When the year ends its file stops changing and its page
becomes the archive for that year; the next run starts a new table and the
index picks up a new link on its own. Nothing is hand-written and no page needs
editing to gain a year.

Rows are kept once written on purpose. Membership of the index changes, so
recomputing 2026 in 2028 would measure a different 500 companies and quietly
rewrite settled history. The stored row is what the index of the day actually
did — `--rebuild` is there when you want the recomputation anyway.

The one bias worth stating: the members are read today and applied backwards
across the year being built, so a company that left the index mid-year is
missing from January too. Over a single year the drift is small, but it is
real, and it is the reason completed years are frozen rather than refreshed.

Requires: yfinance, pandas, matplotlib, requests
"""

import argparse
import json
import sys
from datetime import date
from io import StringIO
from pathlib import Path

import matplotlib
import pandas as pd
import requests
import yfinance as yf

matplotlib.use("Agg")
import matplotlib.dates as mdates          # noqa: E402
import matplotlib.pyplot as plt            # noqa: E402

WINDOWS = (20, 50)                          # the two moving averages, in sessions
CHUNK = 100                                 # tickers per download request
MIN_COVERAGE = 0.80                         # share of members that must have printed
WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"

# Outputs belong beside the script, not in whatever directory it was invoked
# from — this folder is the deliverable.
HERE = Path(__file__).resolve().parent
MEMBERS_FILE = HERE / "sp500_constituents.txt"

BLUE, RED = "#1f5fbf", "#c0392b"            # above the average / below it
INK, INK_2, RULE, PAPER = "#22211f", "#52514e", "#e1e0d9", "#ffffff"


# ---------------------------------------------------------------- data layer

def fetch_members(refresh: bool) -> list[str]:
    """The current S&P 500 tickers, in Yahoo's spelling.

    Wikipedia is the source; the answer is cached beside the script so a run
    without a network — or a day when the page moves — still has a universe to
    work with. Wikipedia refuses a bare urllib fetch, hence requests with a
    real user agent.
    """
    if not refresh and MEMBERS_FILE.exists():
        cached = [line.strip() for line in MEMBERS_FILE.read_text().splitlines()
                  if line.strip() and not line.startswith("#")]
        if cached:
            return cached

    try:
        page = requests.get(
            WIKI_URL, timeout=30,
            headers={"User-Agent": "sp500-breadth/1.0 (personal research script)"},
        )
        page.raise_for_status()
        # Wrapped rather than passed as text: pandas 3 reads only paths and
        # file-like objects, and takes a bare string for a filename.
        table = pd.read_html(StringIO(page.text), match="Symbol")[0]
        # Class shares are written BRK.B on Wikipedia and BRK-B at Yahoo.
        members = sorted(str(s).strip().replace(".", "-") for s in table["Symbol"])
    except Exception as exc:
        # Truncated: a parse failure carries the whole page in its message.
        why = f"{type(exc).__name__}: {str(exc).splitlines()[0][:160]}"
        if MEMBERS_FILE.exists():
            print(f"Could not refresh the member list ({why}); using the cached one.")
            return fetch_members(refresh=False)
        raise SystemExit(
            f"Could not read the S&P 500 members from Wikipedia: {why}\n"
            f"Write one ticker per line into {MEMBERS_FILE} to run offline."
        )

    MEMBERS_FILE.write_text(
        "# S&P 500 members, one ticker per line, Yahoo spelling.\n"
        f"# Refreshed from Wikipedia on {date.today():%Y-%m-%d}.\n"
        + "\n".join(members) + "\n"
    )
    return members


def fetch_closes(tickers: list[str], start: str, end: str) -> pd.DataFrame:
    """Daily adjusted closes for every ticker, one column each.

    Downloaded in chunks rather than one 500-symbol request: Yahoo throttles
    the big ones, and a chunk that fails costs a hundred names instead of the
    whole universe.
    """
    frames = []
    for i in range(0, len(tickers), CHUNK):
        batch = tickers[i:i + CHUNK]
        raw = yf.download(batch, start=start, end=end, interval="1d",
                          auto_adjust=True, progress=False, threads=True)
        if raw.empty:
            print(f"  no data for tickers {i + 1}-{i + len(batch)}", file=sys.stderr)
            continue
        closes = raw["Close"]
        if isinstance(closes, pd.Series):        # a one-symbol batch
            closes = closes.to_frame(batch[0])
        frames.append(closes)
        print(f"  {min(i + CHUNK, len(tickers))}/{len(tickers)} tickers", end="\r")

    if not frames:
        raise SystemExit("No price data came back at all — check your connection.")
    print(" " * 40, end="\r")

    closes = pd.concat(frames, axis=1).sort_index().dropna(axis=1, how="all")

    # Yahoo opens a row for a session before it has filled it in: the volumes
    # are there and the closes are still empty. A day like that arrives with a
    # few dozen prices out of five hundred, and reading breadth off them says
    # something confident and wrong — the first run here put 24 Jul at 0%
    # above, on the strength of the handful that had reported. So a session
    # only counts once most of the index has printed; the rest wait for the
    # next run, by which time Yahoo has caught up.
    coverage = closes.notna().mean(axis=1)
    thin = coverage[coverage < MIN_COVERAGE]
    if len(thin):
        print(f"  set aside {len(thin)} partly-published session(s), latest "
              f"{thin.index[-1]:%d %b %Y} at {thin.iloc[-1] * 100:.0f}% of tickers")
    return closes[coverage >= MIN_COVERAGE]


def compute_breadth(closes: pd.DataFrame, year: int) -> pd.DataFrame:
    """Share of members above and below each moving average, per session.

    The percentages are taken over the members that have a price *and* a full
    moving average that day, so a company with three months of listing history
    is absent from the 50-day figure rather than counted as below it. Above and
    below are both measured strictly, which leaves a stock sitting exactly on
    its average in neither column — rare, but it is why a row can come to 99.9
    rather than 100.
    """
    rows = {}
    for window in WINDOWS:
        mean = closes.rolling(window).mean()
        counted = closes.notna() & mean.notna()
        universe = counted.sum(axis=1)
        # An index with no members counted yet would divide by zero; those
        # sessions are dropped below, once for both windows.
        share = lambda mask: (mask & counted).sum(axis=1) / universe * 100
        rows[f"above_{window}"] = share(closes > mean)
        rows[f"below_{window}"] = share(closes < mean)
        rows[f"counted_{window}"] = universe

    frame = pd.DataFrame(rows)
    frame = frame[frame[[f"counted_{w}" for w in WINDOWS]].min(axis=1) > 0]
    frame = frame[frame.index.year == year]
    frame.index.name = "date"
    return frame.round(
        {f"{side}_{w}": 2 for w in WINDOWS for side in ("above", "below")}
    )


# ------------------------------------------------------------- stored tables

def csv_path(year: int) -> Path:
    return HERE / f"breadth_{year}.csv"


def load_year(year: int) -> pd.DataFrame:
    """Rows already stored for `year`, empty when the year has not started."""
    path = csv_path(year)
    if not path.exists():
        return pd.DataFrame()
    frame = pd.read_csv(path, index_col="date", parse_dates=["date"])
    return frame.sort_index()


def merge_year(stored: pd.DataFrame, fresh: pd.DataFrame, rebuild: bool) -> pd.DataFrame:
    """Fold the freshly computed sessions into what is already on disk.

    Stored rows win unless `--rebuild` says otherwise: a session measured on
    the day it happened was measured against that day's index membership, and
    that is the number worth keeping.
    """
    if stored.empty:
        return fresh
    if rebuild:
        return fresh.combine_first(stored).sort_index()
    return stored.combine_first(fresh).sort_index()


def year_is_complete(frame: pd.DataFrame, year: int) -> bool:
    """True once the year is behind us and its December is on the table."""
    if frame.empty:
        return False
    return year < date.today().year and frame.index[-1].month == 12


def stored_years() -> list[int]:
    """Every year that has a table, oldest first."""
    return sorted(int(p.stem.split("_")[1]) for p in HERE.glob("breadth_*.csv"))


# --------------------------------------------------------------- plot layer

def plot_window(frame: pd.DataFrame, year: int, window: int, path: Path) -> None:
    """One year of the pair for a single moving average: above blue, below red."""
    fig, ax = plt.subplots(figsize=(10, 4.4))

    ax.plot(frame.index, frame[f"above_{window}"], color=BLUE, lw=1.7,
            label=f"Above the {window}-day average")
    ax.plot(frame.index, frame[f"below_{window}"], color=RED, lw=1.7,
            label=f"Below the {window}-day average")
    # The line the two series cross at: above it, most of the index is on the
    # same side as the average.
    ax.axhline(50, color=INK_2, lw=0.8, ls=(0, (4, 4)), alpha=0.55, zorder=0)

    ax.set_ylim(0, 100)
    ax.set_yticks(range(0, 101, 20))
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
    # A part-finished year should not stretch to fill the axis as though it
    # were complete — the empty right-hand side is the point.
    ax.set_xlim(pd.Timestamp(f"{year}-01-01"), pd.Timestamp(f"{year}-12-31"))
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))

    ax.grid(axis="y", color=RULE, lw=0.9)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(RULE)
    ax.tick_params(colors=INK_2, labelsize=9.5, length=0)

    ax.set_title(f"S&P 500 members above and below their {window}-day moving average, "
                 f"{year}", color=INK, fontsize=12.5, fontweight="bold",
                 loc="left", pad=12)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.09), ncols=2,
              frameon=False, fontsize=9.5, labelcolor=INK_2)

    fig.savefig(path, dpi=160, bbox_inches="tight", facecolor=PAPER)
    plt.close(fig)


def png_name(year: int, window: int) -> str:
    return f"breadth_{year}_{window}ma.png"


# ------------------------------------------------------------- page building

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{
    color-scheme: light;
    --page: #f9f9f7; --surface: #fcfcfb; --ink: #0b0b0b; --ink-2: #52514e;
    --ink-3: #898781; --rule: #e1e0d9; --chip: #eeede8;
    --above: #1f5fbf; --below: #c0392b;
    --shadow: 0 1px 2px rgba(11,11,11,.06), 0 8px 24px rgba(11,11,11,.07);
  }}
  @media (prefers-color-scheme: dark) {{
    :root:where(:not([data-theme="light"])) {{
      color-scheme: dark;
      --page: #0d0d0d; --surface: #1a1a19; --ink: #ffffff; --ink-2: #c3c2b7;
      --ink-3: #898781; --rule: #2c2c2a; --chip: #2c2c2a;
      --above: #7aa9f0; --below: #ef7d6d;
      --shadow: 0 1px 2px rgba(0,0,0,.4), 0 8px 24px rgba(0,0,0,.5);
    }}
  }}
  :root[data-theme="dark"] {{
    color-scheme: dark;
    --page: #0d0d0d; --surface: #1a1a19; --ink: #ffffff; --ink-2: #c3c2b7;
    --ink-3: #898781; --rule: #2c2c2a; --chip: #2c2c2a;
    --above: #7aa9f0; --below: #ef7d6d;
    --shadow: 0 1px 2px rgba(0,0,0,.4), 0 8px 24px rgba(0,0,0,.5);
  }}

  *, *::before, *::after {{ box-sizing: border-box; }}
  html, body {{ margin: 0; background: var(--page); }}
  body {{
    padding: 34px 22px 56px; color: var(--ink);
    font: 15px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif;
    -webkit-font-smoothing: antialiased;
  }}
  .inner {{ max-width: 900px; margin: 0 auto; }}
  h1 {{ margin: 0 0 6px; font-size: 26px; letter-spacing: -.015em; }}
  .sub {{ margin: 0 0 22px; color: var(--ink-2); font-size: 13.5px; }}
  .years {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 0 0 26px; }}
  .years a, .years span {{
    padding: 4px 11px; border-radius: 999px; font-size: 13px;
    text-decoration: none; background: var(--chip); color: var(--ink-2);
    border: 1px solid transparent;
  }}
  .years a:hover {{ color: var(--ink); border-color: var(--rule); }}
  .years .here {{ background: var(--ink); color: var(--page); font-weight: 600; }}

  figure {{
    margin: 0 0 22px; padding: 14px; border-radius: 12px;
    background: var(--surface); border: 1px solid var(--rule);
    box-shadow: var(--shadow);
  }}
  figure img {{ display: block; width: 100%; height: auto; border-radius: 6px; }}

  .scroll {{
    max-height: 620px; overflow: auto; border: 1px solid var(--rule);
    border-radius: 12px; background: var(--surface); box-shadow: var(--shadow);
  }}
  table {{ width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }}
  th, td {{ padding: 7px 14px; text-align: right; white-space: nowrap; }}
  th {{
    position: sticky; top: 0; z-index: 1; background: var(--surface);
    font-size: 11.5px; letter-spacing: .04em; text-transform: uppercase;
    color: var(--ink-3); font-weight: 600; box-shadow: inset 0 -1px var(--rule);
  }}
  td {{ border-top: 1px solid var(--rule); font-size: 13.5px; }}
  tbody tr:first-child td {{ border-top: 0; }}
  th:first-child, td:first-child {{ text-align: left; }}
  td.date {{ color: var(--ink-2); }}
  td.above {{ color: var(--above); }}
  td.below {{ color: var(--below); }}
  tbody tr:hover td {{ background: var(--chip); }}

  footer {{ margin: 24px 0 0; color: var(--ink-3); font-size: 12.5px; }}
  footer a {{ color: var(--ink-2); }}
</style>
</head>
<body>
<div class="inner">
{body}
</div>
</body>
</html>
"""


def year_links(years: list[int], current: int | None) -> str:
    """The row of year chips — this is the per-year link the archive hangs on."""
    chips = ['<a href="index.html">All years</a>' if current is not None
             else '<span class="here">All years</span>']
    for year in years:
        chips.append(f'<span class="here">{year}</span>' if year == current
                     else f'<a href="breadth_{year}.html">{year}</a>')
    return '<nav class="years">' + "".join(chips) + "</nav>"


def year_page(frame: pd.DataFrame, year: int, years: list[int], complete: bool) -> str:
    """The whole year: both charts, then every session that made them."""
    asof = frame.index[-1]
    state = ("complete" if complete
             else f"in progress — {len(frame)} sessions through {asof:%d %b %Y}")

    figures = "".join(
        f'<figure><img src="{png_name(year, w)}" '
        f'alt="S&P 500 members above and below their {w}-day moving average in {year}">'
        f"</figure>"
        for w in WINDOWS
    )

    header = (
        "<tr><th>Date</th>"
        + "".join(f"<th>Above {w}-day MA</th><th>Below {w}-day MA</th>" for w in WINDOWS)
        + "</tr>"
    )
    body_rows = []
    for stamp, row in frame.iterrows():
        cells = "".join(
            f'<td class="above">{row[f"above_{w}"]:.1f}%</td>'
            f'<td class="below">{row[f"below_{w}"]:.1f}%</td>'
            for w in WINDOWS
        )
        body_rows.append(f'<tr><td class="date">{stamp:%d %b %Y}</td>{cells}</tr>')

    counted = ", ".join(f"{int(frame[f'counted_{w}'].iloc[-1])} on the {w}-day"
                        for w in WINDOWS)
    body = f"""<h1>S&amp;P 500 market breadth, {year}</h1>
<p class="sub">Share of index members trading above and below their own moving
average, one row per session · {state}</p>
{year_links(years, year)}
{figures}
<div class="scroll"><table><thead>{header}</thead><tbody>
{chr(10).join(body_rows)}
</tbody></table></div>
<footer>Adjusted closes from Yahoo Finance; members read from Wikipedia's
current S&amp;P 500 list. A member counts only once it has a full moving
average, so the last session weighed {counted}. Above and below are both
strict, which leaves a stock sitting exactly on its average in neither column —
that is why a row can fall a shade short of 100%. Generated
{date.today():%d %b %Y}.</footer>"""

    return PAGE.format(title=f"S&P 500 market breadth, {year}", body=body)


def index_page(years: list[int]) -> str:
    """One link per year, newest first, with where each year finished."""
    rows = []
    for year in reversed(years):
        frame = load_year(year)
        if frame.empty:
            continue
        last = frame.iloc[-1]
        state = ("complete" if year_is_complete(frame, year)
                 else f"through {frame.index[-1]:%d %b}")
        rows.append(
            f'<tr><td class="date"><a href="breadth_{year}.html">{year}</a></td>'
            f"<td>{len(frame)} sessions</td><td>{state}</td>"
            f'<td class="above">{last["above_20"]:.1f}%</td>'
            f'<td class="above">{last["above_50"]:.1f}%</td></tr>'
        )

    body = f"""<h1>S&amp;P 500 market breadth</h1>
<p class="sub">How much of the index is above its own moving average, a year at
a time. Each year keeps its own table and charts.</p>
{year_links(years, None)}
<div class="scroll"><table><thead><tr><th>Year</th><th>Sessions</th>
<th>Status</th><th>Last above 20-day</th><th>Last above 50-day</th></tr></thead>
<tbody>
{chr(10).join(rows)}
</tbody></table></div>
<footer>Generated {date.today():%d %b %Y}.</footer>"""

    return PAGE.format(title="S&P 500 market breadth", body=body)


def write_year_outputs(year: int, frame: pd.DataFrame, years: list[int]) -> None:
    """Charts, JSON and the year's page — everything downstream of the table."""
    for window in WINDOWS:
        plot_window(frame, year, window, HERE / png_name(year, window))
        print(f"Saved {HERE / png_name(year, window)}")

    complete = year_is_complete(frame, year)
    payload = {
        "year": year,
        "complete": complete,
        "asof": frame.index[-1].strftime("%Y-%m-%d"),
        "sessions": len(frame),
        "windows": list(WINDOWS),
        "rows": [
            {"date": stamp.strftime("%Y-%m-%d"),
             **{f"{side}_{w}": round(float(row[f"{side}_{w}"]), 2)
                for w in WINDOWS for side in ("above", "below")},
             **{f"counted_{w}": int(row[f"counted_{w}"]) for w in WINDOWS}}
            for stamp, row in frame.iterrows()
        ],
    }
    out_json = HERE / f"breadth_{year}.json"
    out_json.write_text(json.dumps(payload, separators=(",", ":")))
    print(f"Wrote {out_json}")

    out_html = HERE / f"breadth_{year}.html"
    out_html.write_text(year_page(frame, year, years, complete))
    print(f"Wrote {out_html}")


# --------------------------------------------------------------- text output

def print_tail(frame: pd.DataFrame, rows: int) -> None:
    """The most recent sessions, coloured when it is a tty."""
    tty = sys.stdout.isatty()
    blue, red, reset = ("\033[34m", "\033[31m", "\033[0m") if tty else ("", "", "")

    print(f"\n{'Date':<14}{'>20MA':>9}{'<20MA':>9}{'>50MA':>9}{'<50MA':>9}")
    print("-" * 50)
    for stamp, row in frame.tail(rows).iterrows():
        cells = "".join(
            f"{tint}{row[f'{side}_{w}']:>8.1f}%{reset}"
            for w in WINDOWS for side, tint in (("above", blue), ("below", red))
        )
        print(f"{stamp:%d %b %Y}  {cells}")


# -------------------------------------------------------------------- main

def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--year", type=int, default=date.today().year,
                        help="the year to build (default: this one)")
    parser.add_argument("--rebuild", action="store_true",
                        help="recompute sessions already stored instead of keeping them")
    parser.add_argument("--pages-only", action="store_true",
                        help="re-render charts and pages from the stored tables")
    parser.add_argument("--refresh-members", action="store_true",
                        help="re-read the member list from Wikipedia")
    parser.add_argument("--rows", type=int, default=10,
                        help="how many recent sessions to print (default: 10)")
    args = parser.parse_args()

    year = args.year
    stored = load_year(year)

    if args.pages_only:
        if stored.empty:
            raise SystemExit(f"No stored table for {year} — run without --pages-only first.")
        frame = stored
    else:
        members = fetch_members(args.refresh_members)
        print(f"S&P 500 breadth for {year} — {len(members)} members")

        # The 50-day average needs 50 sessions of runway before the year's first
        # one, or January would be blank; ~110 calendar days covers it with room
        # for holidays.
        start = (pd.Timestamp(f"{year}-01-01") - pd.Timedelta(days=110)).strftime("%Y-%m-%d")
        end = min(pd.Timestamp(f"{year + 1}-01-01"),
                  pd.Timestamp.today().normalize() + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

        closes = fetch_closes(members, start, end)
        print(f"  {closes.shape[1]} tickers returned prices "
              f"through {closes.index[-1]:%d %b %Y}")

        fresh = compute_breadth(closes, year)
        if fresh.empty:
            raise SystemExit(f"No sessions in {year} to measure yet.")

        added = len(fresh.index.difference(stored.index)) if not stored.empty else len(fresh)
        frame = merge_year(stored, fresh, args.rebuild)
        frame.to_csv(csv_path(year), float_format="%.2f")
        print(f"Wrote {csv_path(year)} — {len(frame)} sessions, {added} new")

    print_tail(frame, args.rows)

    years = stored_years()
    write_year_outputs(year, frame, years)

    # Every page carries the same strip of year links, so the years already
    # archived have to be told about a new one — otherwise last year's page is
    # a dead end and only the index knows this year exists. Re-rendering them
    # is a read of each CSV; the charts, which are the slow part, stay put.
    for other in years:
        if other == year:
            continue
        archived = load_year(other)
        if not archived.empty:
            (HERE / f"breadth_{other}.html").write_text(
                year_page(archived, other, years, year_is_complete(archived, other)))
    print(f"Refreshed the year links on {len(years)} page(s)")

    (HERE / "index.html").write_text(index_page(years))
    print(f"Wrote {HERE / 'index.html'}")


if __name__ == "__main__":
    main()