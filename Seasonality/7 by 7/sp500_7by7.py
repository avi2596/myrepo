"""
Years the S&P 500 was up more than 7% through July — and what August to
December did next.

The question behind the table: when the first seven months have already
delivered a strong gain, does the rest of the year keep going or give it back?
Every year from 1985 is tested; the ones clearing the threshold are listed with
both halves side by side, positive cells green and negative cells red.

    python sp500_7by7.py                       # table + PNG for ^GSPC
    python sp500_7by7.py --html --json         # also refresh the page beside it
    python sp500_7by7.py --threshold 10        # a stricter first half
    python sp500_7by7.py --ticker ^IXIC        # another symbol
    python sp500_7by7.py --show                # interactive window

Re-running is the whole maintenance story. The qualifying years are recomputed
from scratch every time, so a year that has just cleared the threshold appears
as a new row on its own, with Jan-Jul filled as July closes and Aug-Dec filling
in as the rest of the year happens. Nothing on the page is hand-written.

Both periods are measured from their own FIRST OPEN to their LAST CLOSE:
Jan-Jul from January's opening print to July's final close, Aug-Dec from
August's opening print to the last close of the year. This matches how the
sibling seasonality tool measures year to date, so the two agree with each
other. It does leave the Jul-close-to-Aug-open gap in neither column, which is
the price of having each half stand on its own rather than one half's endpoint
defining the other's baseline.

Requires: yfinance, pandas, matplotlib
"""

import argparse
import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import yfinance as yf
from matplotlib.patches import Rectangle

TICKER = "^GSPC"
START_YEAR = 1985
THRESHOLD = 7.0

FIRST_HALF = [1, 2, 3, 4, 5, 6, 7]        # January through July
SECOND_HALF = [8, 9, 10, 11, 12]          # August through December

# Outputs belong beside the script, not in whatever directory it was invoked
# from — this folder is the deliverable.
HERE = Path(__file__).resolve().parent

GREEN, RED = "#157f3c", "#c0392b"          # cell fills: gained / lost
INK, PAPER = "#22211f", "#ffffff"
HEADER_BG, YEAR_BG, GRID = "#33322f", "#f2f1ee", "#ffffff"


# ---------------------------------------------------------------- data layer

def fetch_daily(ticker: str, start_year: int) -> tuple[pd.Series, pd.Series]:
    """Daily opens and closes for `ticker`, from Jan 1 of `start_year` to today.

    auto_adjust=True, so both series are split- and dividend-adjusted. Daily
    bars rather than monthly because the period boundaries are what matter
    here: a monthly bar is stamped with the 1st and cannot say which session
    actually opened January or closed July.
    """
    today = pd.Timestamp.today().normalize()
    raw = yf.download(
        ticker,
        start=f"{start_year}-01-01",
        end=(today + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
        interval="1d",
        auto_adjust=True,
        progress=False,
    )
    if raw.empty:
        raise SystemExit(f"No data returned for {ticker} — check the ticker or your connection.")

    def column(field: str) -> pd.Series:
        col = raw[field]
        # yfinance returns MultiIndex columns (Price, Ticker) even for one symbol.
        if isinstance(col, pd.DataFrame):
            col = col.iloc[:, 0]
        # Yahoo pads the range with empty rows for sessions it has no print for
        # yet; drop those or the table claims to be more current than the data.
        return col.dropna()

    return column("Open"), column("Close")


def period_change(opens: pd.Series, closes: pd.Series,
                  year: int, months: list[int]) -> dict | None:
    """% change from the first open to the last close of `months` in `year`.

    Returns the prices and dates behind the figure too, so the caller can show
    its working instead of asserting a number. None when the period has no
    sessions yet — an August that has not arrived is absent, not zero.
    """
    in_period = lambda s: s[(s.index.year == year) & (s.index.month.isin(months))]
    period_opens, period_closes = in_period(opens), in_period(closes)
    if period_opens.empty or period_closes.empty:
        return None

    first_open, last_close = float(period_opens.iloc[0]), float(period_closes.iloc[-1])
    if first_open <= 0:
        return None
    return {
        "pct": (last_close / first_open - 1) * 100,
        "open": first_open,
        "close": last_close,
        "start": period_opens.index[0],
        "end": period_closes.index[-1],
    }


def build_table(opens: pd.Series, closes: pd.Series, threshold: float) -> pd.DataFrame:
    """One row per year clearing `threshold` over Jan-Jul, with its Aug-Dec.

    The current year is included when it qualifies, but its halves are flagged:
    July may still be running, and August to December has not happened. Marking
    it beats dropping it — the year the question is being asked about is
    usually the reason for asking.
    """
    last_close_date = closes.index[-1]
    rows = []

    def complete(year: int, months: list[int]) -> bool:
        """True once the data runs past the period's final month.

        Asked of the series, not of the period: the last close *inside* Jan-Jul
        is always in July, so it can never testify that July has ended.
        """
        end_month = months[-1]
        return (last_close_date.year > year
                or (last_close_date.year == year and last_close_date.month > end_month))

    for year in range(opens.index.year.min(), last_close_date.year + 1):
        first = period_change(opens, closes, year, FIRST_HALF)
        if first is None or first["pct"] <= threshold:
            continue
        second = period_change(opens, closes, year, SECOND_HALF)

        row = {
            "year": year,
            "jan_jul": first["pct"],
            "jan_jul_final": complete(year, FIRST_HALF),
            "jan_jul_through": first["end"],
            "aug_dec": second["pct"] if second else None,
            "aug_dec_final": second is not None and complete(year, SECOND_HALF),
            "aug_dec_through": second["end"] if second else None,
        }
        # The prices behind each figure, so the page can show its working in a
        # tooltip rather than asking the reader to trust the percentage.
        for half, period in (("jan_jul", first), ("aug_dec", second)):
            row[f"{half}_open"] = period["open"] if period else None
            row[f"{half}_close"] = period["close"] if period else None
            row[f"{half}_from"] = period["start"] if period else None
        rows.append(row)

    return pd.DataFrame(rows)


# --------------------------------------------------------------- plot layer

def cell_colour(value: float | None) -> str:
    """Green for a gain, red for a loss, neutral paper for nothing to show."""
    if value is None or pd.isna(value):
        return YEAR_BG
    return GREEN if value > 0 else RED


def format_pct(value: float | None, final: bool) -> str:
    """Signed two-decimal percent; * marks a figure that is not final yet."""
    if value is None or pd.isna(value):
        return "—"
    return f"{value:+.2f}%" + ("" if final else "*")


def plot_table(table: pd.DataFrame, ticker: str, name: str,
               threshold: float, asof: pd.Timestamp) -> plt.Figure:
    """Render the three columns as a coloured table."""
    columns = ["Year", "Jan-Jul", "Aug-Dec"]
    widths = [1.0, 1.35, 1.35]
    x_edges = [sum(widths[:i]) for i in range(len(widths) + 1)]
    total_width, n_rows = x_edges[-1], len(table)

    row_h, header_h = 0.46, 0.58
    fig_h = 0.46 * n_rows + 1.5
    fig, ax = plt.subplots(figsize=(6.4, fig_h))

    ax.set_xlim(0, total_width)
    ax.set_ylim(0, n_rows * row_h + header_h)
    ax.invert_yaxis()
    ax.axis("off")

    def cell(x0, x1, y0, height, text, bg, fg, weight="normal", size=10.5):
        ax.add_patch(Rectangle((x0, y0), x1 - x0, height,
                               facecolor=bg, edgecolor=GRID, linewidth=1.4))
        ax.text((x0 + x1) / 2, y0 + height / 2, text, ha="center", va="center",
                color=fg, fontsize=size, fontweight=weight)

    for i, label in enumerate(columns):
        cell(x_edges[i], x_edges[i + 1], 0, header_h, label,
             HEADER_BG, PAPER, weight="bold")

    for r, row in enumerate(table.itertuples(index=False)):
        y = header_h + r * row_h
        # No * on the year: the cell that is actually unfinished carries its own.
        cell(x_edges[0], x_edges[1], y, row_h, str(row.year), YEAR_BG, INK, weight="bold")

        for i, (value, final) in enumerate([(row.jan_jul, row.jan_jul_final),
                                            (row.aug_dec, row.aug_dec_final)], start=1):
            bg = cell_colour(value)
            fg = PAPER if bg in (GREEN, RED) else "#8a8781"
            cell(x_edges[i], x_edges[i + 1], y, row_h,
                 format_pct(value, final), bg, fg, weight="bold")

    # Header block laid out in inches, then converted: a figure whose height
    # grows with the row count would otherwise stretch the gap under the title.
    fig.suptitle(f"{name}: years up more than {threshold:g}% through July",
                 x=0.02, ha="left", y=(fig_h - 0.30) / fig_h,
                 fontsize=13.5, fontweight="bold")
    fig.text(0.02, (fig_h - 0.58) / fig_h,
             f"{ticker} · each half measured from its own first open to its last close · "
             f"adjusted prices\n"
             f"green = gained, red = lost · * = not final, through {asof:%d %b %Y}",
             ha="left", va="top", fontsize=8.5, color="#52514e")
    fig.subplots_adjust(left=0.06, right=0.94,
                        top=(fig_h - 1.10) / fig_h, bottom=0.3 / fig_h)
    return fig


# --------------------------------------------------------------- text output

def print_table(table: pd.DataFrame, threshold: float) -> None:
    """The same three columns in the terminal, coloured when it is a tty."""
    tty = sys.stdout.isatty()
    green, red, dim, reset = (
        ("\033[32m", "\033[31m", "\033[2m", "\033[0m") if tty else ("", "", "", "")
    )

    print(f"\n{'Year':<8}{'Jan-Jul':>10}{'Aug-Dec':>12}")
    print("-" * 30)
    for row in table.itertuples(index=False):
        cells = []
        for value, final in [(row.jan_jul, row.jan_jul_final),
                             (row.aug_dec, row.aug_dec_final)]:
            text = format_pct(value, final)
            tint = dim if value is None or pd.isna(value) else (green if value > 0 else red)
            # Pad before colouring: escape codes have width in str.format but not on screen.
            cells.append(f"{tint}{text:>10}{reset}" if len(cells) == 0
                         else f"{tint}{text:>12}{reset}")
        print(f"{row.year:<8}{cells[0]}{cells[1]}")


def baseline_stats(opens: pd.Series, closes: pd.Series) -> dict:
    """August-December over EVERY year in the sample, qualifying or not.

    A hit rate means nothing on its own: if August to December is usually
    positive anyway, a strong first half has told us nothing. This is the
    yardstick the qualifying years get measured against.
    """
    last_year = closes.index[-1].year
    every = []
    for year in range(opens.index.year.min(), last_year + 1):
        period = period_change(opens, closes, year, SECOND_HALF)
        # December must be closed for the year to count toward the baseline.
        if period and period["end"].month == 12 and year < last_year:
            every.append(period["pct"])
    if not every:
        return {}

    series = pd.Series(every)
    return {
        "years": len(series),
        "first_year": int(opens.index.year.min()),
        "last_year": int(last_year - 1),
        "hit_rate": round(float((series > 0).mean() * 100), 1),
        "avg": round(float(series.mean()), 2),
        "median": round(float(series.median()), 2),
    }


def print_summary(table: pd.DataFrame, threshold: float, baseline: dict) -> None:
    """What the table adds up to, against the all-years baseline."""
    settled = table[table["aug_dec_final"] & table["jan_jul_final"]]
    if settled.empty:
        print("\nNo year in the sample has both halves complete yet.")
        return

    second = settled["aug_dec"]
    print(f"\nOf the {len(settled)} completed years up more than {threshold:g}% through July, "
          f"August-December was positive {int((second > 0).sum())} times "
          f"({(second > 0).mean() * 100:.0f}%).")
    print(f"  average {second.mean():+.2f}%   median {second.median():+.2f}%   "
          f"range {second.min():+.2f}% to {second.max():+.2f}%")
    if baseline:
        print(f"Every year {baseline['first_year']}-{baseline['last_year']} for comparison: "
              f"positive {baseline['hit_rate']:.0f}% of {baseline['years']}, "
              f"average {baseline['avg']:+.2f}%, median {baseline['median']:+.2f}%")


# ------------------------------------------------------- interactive page

HTML_TAG = '<script type="application/json" id="data">'


def build_payload(table: pd.DataFrame, ticker: str, name: str, threshold: float,
                  asof: pd.Timestamp, first_year: int, baseline: dict) -> dict:
    """Everything the HTML page needs, so nothing on it is hand-written.

    Rows carry their own completeness flags and the prices behind them. A year
    that starts qualifying appears here on the next run with no page edit — the
    page renders the rows it is given rather than a fixed list.
    """
    def date(value) -> str | None:
        return None if pd.isna(value) else pd.Timestamp(value).strftime("%Y-%m-%d")

    def number(value, digits=2):
        return None if value is None or pd.isna(value) else round(float(value), digits)

    rows = []
    for row in table.itertuples(index=False):
        rows.append({
            "year": int(row.year),
            "halves": {
                half: {
                    "pct": number(getattr(row, half)),
                    "final": bool(getattr(row, f"{half}_final")),
                    "open": number(getattr(row, f"{half}_open")),
                    "close": number(getattr(row, f"{half}_close")),
                    "from": date(getattr(row, f"{half}_from")),
                    "through": date(getattr(row, f"{half}_through")),
                }
                for half in ("jan_jul", "aug_dec")
            },
        })

    settled = table[table["jan_jul_final"] & table["aug_dec_final"]]
    second = settled["aug_dec"]
    return {
        "ticker": ticker,
        "name": name,
        "threshold": threshold,
        "asof": asof.strftime("%Y-%m-%d"),
        "first_year": int(first_year),
        "last_year": int(asof.year),
        "rows": rows,
        # The summary the page leads with, computed here so the prose cannot
        # drift from the table underneath it.
        "summary": {
            "qualifying": int(len(table)),
            "settled": int(len(settled)),
            "up": int((second > 0).sum()) if len(settled) else 0,
            "hit_rate": number((second > 0).mean() * 100, 1) if len(settled) else None,
            "avg": number(second.mean()) if len(settled) else None,
            "median": number(second.median()) if len(settled) else None,
            "best": number(second.max()) if len(settled) else None,
            "worst": number(second.min()) if len(settled) else None,
        },
        "baseline": baseline,
    }


def embed_in_html(path: str, blob: str) -> str:
    """Swap the data block inside the page for fresh numbers.

    Every number, the headline and the method note are derived from that block,
    so they all restate themselves — including a year that has just qualified.
    """
    with open(path) as fh:
        page = fh.read()

    try:
        start = page.index(HTML_TAG)
    except ValueError:
        raise SystemExit(f"{path} has no {HTML_TAG} block to update.")
    open_end = page.index(">", start) + 1
    close = page.index("</script>", open_end)

    with open(path, "w") as fh:
        fh.write(page[:open_end] + "\n" + blob + "\n" + page[close:])
    return f"{close - open_end} bytes of data replaced with {len(blob)}"


def display_name(ticker: str) -> str:
    """Human-readable name for a symbol; a missing name must not sink the run."""
    pinned = {"^GSPC": "S&P 500", "^IXIC": "Nasdaq Composite",
              "^DJI": "Dow Jones Industrial Average", "^RUT": "Russell 2000"}
    if ticker in pinned:
        return pinned[ticker]
    try:
        info = yf.Ticker(ticker).info
        return info.get("longName") or info.get("shortName") or ticker
    except Exception:
        return ticker


# -------------------------------------------------------------------- main

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ticker", default=TICKER)
    parser.add_argument("--start-year", type=int, default=START_YEAR)
    parser.add_argument("--threshold", type=float, default=THRESHOLD,
                        help="minimum Jan-Jul %% gain for a year to qualify (default: 7)")
    parser.add_argument("--out", default=None,
                        help="PNG path (default: sp500_7by7.png beside this script)")
    parser.add_argument("--csv", help="also write the table to this CSV file")
    parser.add_argument("--json", nargs="?", const="", default=None,
                        help="write the data block to this JSON file "
                             "(bare flag: sp500_7by7_data.json beside this script)")
    parser.add_argument("--html", nargs="?", const="", default=None,
                        help="re-embed fresh data into this HTML page, in place "
                             "(bare flag: sp500_7by7.html beside this script)")
    parser.add_argument("--show", action="store_true")
    args = parser.parse_args()

    opens, closes = fetch_daily(args.ticker, args.start_year)
    asof = closes.index[-1]
    table = build_table(opens, closes, args.threshold)

    name = display_name(args.ticker)
    print(f"\n{name} ({args.ticker}) — years up more than {args.threshold:g}% "
          f"from January through July, {args.start_year}-{asof.year}")
    print(f"Data through {asof:%d %b %Y}. Each half runs from its own first open "
          f"to its last close.")

    if table.empty:
        raise SystemExit(f"\nNo year since {args.start_year} gained more than "
                         f"{args.threshold:g}% through July.")

    baseline = baseline_stats(opens, closes)
    print_table(table, args.threshold)
    if not table["jan_jul_final"].all() or not table["aug_dec_final"].all():
        print("\n* not final: the period is still running or has not started.")
    print_summary(table, args.threshold, baseline)

    if args.csv:
        out_csv = Path(args.csv)
        table[["year", "jan_jul", "aug_dec"]] \
            .rename(columns={"year": "Year", "jan_jul": "Jan-Jul", "aug_dec": "Aug-Dec"}) \
            .round({"Jan-Jul": 2, "Aug-Dec": 2}) \
            .to_csv(out_csv, index=False)
        print(f"\nWrote {out_csv}")

    if args.json is not None or args.html is not None:
        payload = build_payload(table, args.ticker, name, args.threshold,
                               asof, args.start_year, baseline)
        blob = json.dumps(payload, separators=(",", ":"))

        if args.json is not None:
            out_json = Path(args.json) if args.json else HERE / "sp500_7by7_data.json"
            out_json.write_text(blob)
            print(f"Wrote {out_json}")

        if args.html is not None:
            out_html = Path(args.html) if args.html else HERE / "sp500_7by7.html"
            print(f"Updated {out_html}: {embed_in_html(str(out_html), blob)}")

    out_png = Path(args.out) if args.out else HERE / "sp500_7by7.png"
    fig = plot_table(table, args.ticker, name, args.threshold, asof)
    fig.savefig(out_png, dpi=160, bbox_inches="tight", facecolor="white")
    print(f"Saved {out_png}")
    if args.show:
        plt.show()


if __name__ == "__main__":
    main()