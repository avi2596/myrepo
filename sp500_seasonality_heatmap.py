"""
S&P 500 (^GSPC) monthly seasonality heatmap.

Builds a Year x Month matrix of percentage returns and a summary panel holding
the average, median, win rate and observation count for each calendar month.

The sample runs from the first year of the window through *today*: the year to
date counts toward every average, and the month in progress is included as a
month-to-date return (marked with * in the grid). Re-run the script after any
month closes and that month's partial figure becomes its final one, so the
averages stay current with no code change.

    python sp500_seasonality_heatmap.py            # writes sp500_seasonality.png
    python sp500_seasonality_heatmap.py --cvd-safe # red<->blue instead of red/green
    python sp500_seasonality_heatmap.py --json out.json   # dump the numbers
    python sp500_seasonality_heatmap.py --show     # open an interactive window

Requires: yfinance, pandas, numpy, matplotlib, seaborn
"""

import argparse
import json

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
import yfinance as yf
from matplotlib.colors import TwoSlopeNorm

TICKER = "^GSPC"
N_YEARS = 25
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# ---------------------------------------------------------------- data layer

def fetch_monthly_returns(ticker: str, first_year: int) -> tuple[pd.Series, pd.Timestamp]:
    """Monthly % returns for `ticker` from Jan(first_year) through today.

    Downloads monthly bars with auto_adjust=True, so 'Close' is the adjusted
    close (split- and dividend-adjusted). We start one month early so that the
    January return of the first year has a prior close to compare against.

    Returns the series plus the date its last value is good through. yfinance
    stamps each monthly bar with the first day of the month, and the bar for the
    month in progress carries the latest close — so that last entry is a
    month-to-date return. It is kept, not dropped; the caller marks it partial.
    """
    today = pd.Timestamp.today().normalize()
    raw = yf.download(
        ticker,
        start=f"{first_year - 1}-12-01",
        end=(today + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
        interval="1mo",
        auto_adjust=True,
        progress=False,
    )
    if raw.empty:
        raise SystemExit(f"No data returned for {ticker} — check the ticker or your connection.")

    # yfinance returns MultiIndex columns (Price, Ticker) even for one symbol.
    close = raw["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]

    returns = close.pct_change().mul(100).dropna()

    # The monthly bar is stamped with the 1st, which would misreport how current
    # the partial month is — ask for recent daily bars to get the real last close.
    daily = yf.download(ticker, start=(today - pd.Timedelta(days=10)).strftime("%Y-%m-%d"),
                        interval="1d", auto_adjust=True, progress=False)
    asof = daily.index[-1] if not daily.empty else returns.index[-1]
    return returns, pd.Timestamp(asof)


def to_year_month_matrix(returns: pd.Series) -> pd.DataFrame:
    """Reshape a monthly return series into a Year (rows) x Month (cols) grid."""
    frame = pd.DataFrame({
        "year": returns.index.year,
        "month": returns.index.month,
        "ret": returns.to_numpy(),
    })
    matrix = frame.pivot(index="year", columns="month", values="ret")
    matrix = matrix.reindex(columns=range(1, 13))     # keep Jan..Dec even if sparse
    matrix.columns = MONTHS
    return matrix


def summarise(matrix: pd.DataFrame) -> pd.DataFrame:
    """Per-calendar-month summary over every observation in the matrix.

    Months already past in the current year carry one more observation than
    those still ahead of it, so the count is reported rather than assumed.
    """
    return pd.DataFrame(
        [matrix.mean(), matrix.median(), (matrix > 0).mean() * 100, matrix.count()],
        index=["Average", "Median", "Win rate", "Months"],
    )


# --------------------------------------------------------------- plot layer

def _annotations(matrix: pd.DataFrame, partial: tuple[int, str] | None = None) -> np.ndarray:
    """Signed, one-decimal percent labels; blank for missing months.

    The month in progress is suffixed with * — it is a month-to-date figure
    sitting in a grid of completed ones.
    """
    out = matrix.map(lambda v: f"{v:+.1f}" if pd.notna(v) else "").to_numpy(dtype=object)
    if partial is not None:
        year, month = partial
        if year in matrix.index and month in matrix.columns:
            r = matrix.index.get_loc(year)
            c = matrix.columns.get_loc(month)
            if out[r][c]:
                out[r][c] += "*"
    return out


def plot_seasonality(matrix: pd.DataFrame, summary: pd.DataFrame,
                     partial: tuple[int, str], asof: pd.Timestamp,
                     cvd_safe: bool = False) -> plt.Figure:
    """Year x Month heatmap above a summary panel of the calendar-month record."""
    # Diverging scale centred on zero: red = negative, yellow = flat, green =
    # positive. --cvd-safe swaps green for blue, which stays legible for
    # red-green colour blindness (~8% of men) at no cost in meaning.
    cmap = "RdBu" if cvd_safe else "RdYlGn"
    limit = np.nanmax(np.abs(matrix.to_numpy()))
    norm = TwoSlopeNorm(vmin=-limit, vcenter=0.0, vmax=limit)

    # Averaging tens of years shrinks the spread to a couple of per cent, so the
    # summary panel gets its own tighter scale — on the main matrix's range every
    # average would render as the same pale midpoint and the signal would vanish.
    avg_limit = np.nanmax(np.abs(summary.loc[["Average", "Median"]].to_numpy()))
    avg_norm = TwoSlopeNorm(vmin=-avg_limit, vcenter=0.0, vmax=avg_limit)

    fig, (ax_main, ax_avg, ax_meta) = plt.subplots(
        3, 1,
        figsize=(13, 0.42 * len(matrix) + 5.0),
        gridspec_kw={"height_ratios": [len(matrix), 2, 2], "hspace": 0.18},
    )
    cbar_ax = fig.add_axes((0.92, 0.40, 0.015, 0.40))
    avg_cbar_ax = fig.add_axes((0.92, 0.11, 0.015, 0.12))

    common = dict(fmt="", annot_kws={"size": 8.5}, linewidths=1.2,
                  linecolor="white", xticklabels=False, cbar=False)
    returns_cells = dict(cmap=cmap, norm=norm, **common)

    # --- main matrix: one row per year, current year included --------------
    sns.heatmap(matrix, ax=ax_main, annot=_annotations(matrix, partial),
                **{**returns_cells,
                   "xticklabels": True, "cbar": True, "cbar_ax": cbar_ax,
                   "cbar_kws": {"label": "Monthly return (%)"}})
    ax_main.tick_params(axis="x", length=0, top=True, labeltop=True,
                        bottom=False, labelbottom=False)

    # --- summary panel: the seasonality signal itself ----------------------
    returns_rows = summary.loc[["Average", "Median"]]
    sns.heatmap(returns_rows, ax=ax_avg, annot=_annotations(returns_rows),
                **{**returns_cells, "norm": avg_norm, "cbar": True,
                   "cbar_ax": avg_cbar_ax,
                   "cbar_kws": {"label": "Avg return (%)"}})
    ax_avg.set_title(
        f"Seasonality, {matrix.index.min()}–{matrix.index.max()} incl. year to date"
        "  ·  own colour scale, see lower bar",
        fontsize=10, fontweight="bold", loc="left", pad=6)

    # Win rate and the observation count are not returns, so they get their own
    # grey ramp — colouring them on the return scale would be a unit error.
    meta = summary.loc[["Win rate", "Months"]]
    labels = np.array([[f"{v:.0f}%" for v in summary.loc["Win rate"]],
                       [f"{v:.0f}" for v in summary.loc["Months"]]], dtype=object)
    # Win rate is shaded against its own range; the count is held flat because
    # 25-vs-26 is a footnote, not a magnitude anyone should read off a colour.
    shaded = meta.copy()
    shaded.loc["Win rate"] = meta.loc["Win rate"] / meta.loc["Win rate"].max() * 100
    shaded.loc["Months"] = 18
    sns.heatmap(shaded, ax=ax_meta, cmap="Greys", vmin=0, vmax=230,
                annot=labels, **{**common, "xticklabels": True})
    ax_meta.tick_params(axis="x", length=0, labelbottom=True)

    for ax in (ax_main, ax_avg, ax_meta):
        ax.set_xlabel("")
        ax.set_ylabel("")
        ax.tick_params(axis="both", length=0)
        ax.tick_params(axis="y", rotation=0)
    for ax in (ax_avg, ax_meta):
        for label in ax.get_yticklabels():
            label.set_fontweight("bold")

    fig.suptitle(
        f"S&P 500 monthly returns, {matrix.index.min()}–{matrix.index.max()}",
        x=0.125, ha="left", y=0.975, fontsize=15, fontweight="bold")
    fig.text(0.125, 0.951,
             "Percentage change in adjusted monthly close. Green = positive, red = negative. "
             f"* = month to date, through {asof:%d %b %Y}; it counts toward the averages.",
             ha="left", fontsize=9.5, color="#52514e")
    fig.subplots_adjust(left=0.06, right=0.90, top=0.93, bottom=0.05)
    return fig


# ------------------------------------------------------------- html refresh

HTML_TAG = '<script type="application/json" id="data">'


def embed_in_html(path: str, blob: str) -> str:
    """Swap the data block inside the interactive page for fresh numbers.

    The page derives its headline, tiles, strip, tooltips and method note from
    that block, so they all restate themselves. The hand-written prose under
    "What the grid says" is NOT derived — re-read it after a refresh that moves
    a ranking, because it will happily keep asserting last month's story.
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


# -------------------------------------------------------------------- main

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticker", default=TICKER)
    parser.add_argument("--years", type=int, default=N_YEARS,
                        help="complete calendar years to include, before the year to date")
    parser.add_argument("--cvd-safe", action="store_true",
                        help="use red<->blue instead of red/green")
    parser.add_argument("--out", default="sp500_seasonality.png")
    parser.add_argument("--json", help="also write the matrix and summary to this JSON file")
    parser.add_argument("--html", help="re-embed the fresh data into this HTML page, in place")
    parser.add_argument("--show", action="store_true")
    args = parser.parse_args()

    # The window is the N most recent complete calendar years plus the year to
    # date. Every month of the current year that has data counts toward the
    # averages, so months already past carry one more observation than the rest.
    this_year = pd.Timestamp.today().year
    first_year = this_year - args.years

    returns, asof = fetch_monthly_returns(args.ticker, first_year)
    matrix = to_year_month_matrix(returns).loc[first_year:]
    summary = summarise(matrix)
    partial = (asof.year, MONTHS[asof.month - 1])

    pd.set_option("display.width", 200)
    print(f"\n{args.ticker} monthly returns (%), {first_year}–{this_year} "
          f"(through {asof:%b %Y}, month to date)\n")
    print(matrix.round(2).to_string(na_rep="—"))
    print("\nCalendar-month summary — year to date included\n")
    print(summary.round(2).to_string())

    best, worst = summary.loc["Average"].idxmax(), summary.loc["Average"].idxmin()
    print(f"\nBest month:  {best} ({summary.loc['Average', best]:+.2f}% avg, "
          f"{summary.loc['Win rate', best]:.0f}% of {summary.loc['Months', best]:.0f} positive)")
    print(f"Worst month: {worst} ({summary.loc['Average', worst]:+.2f}% avg, "
          f"{summary.loc['Win rate', worst]:.0f}% of {summary.loc['Months', worst]:.0f} positive)")
    print(f"{partial[0]} {partial[1]} is month-to-date through {asof:%d %b %Y} "
          f"and is included in the averages above.")

    if args.json or args.html:
        payload = {
            "ticker": args.ticker,
            "asof": asof.strftime("%Y-%m-%d"),
            "partial": {"year": partial[0], "month": partial[1]},
            "months": MONTHS,
            "years": {str(y): [None if pd.isna(v) else round(float(v), 2)
                               for v in matrix.loc[y]] for y in matrix.index},
            # Explicit keys — a "Months" summary row would otherwise collide
            # with the "months" name list above.
            "avg": [round(float(v), 2) for v in summary.loc["Average"]],
            "median": [round(float(v), 2) for v in summary.loc["Median"]],
            "win": [round(float(v), 1) for v in summary.loc["Win rate"]],
            "n": [int(v) for v in summary.loc["Months"]],
            "std": [round(float(v), 2) for v in matrix.std()],
            "best": [round(float(v), 2) for v in matrix.max()],
            "worst": [round(float(v), 2) for v in matrix.min()],
            "best_year": [int(matrix[c].idxmax()) for c in MONTHS],
            "worst_year": [int(matrix[c].idxmin()) for c in MONTHS],
        }
        blob = json.dumps(payload, separators=(",", ":"))

        if args.json:
            with open(args.json, "w") as fh:
                fh.write(blob)
            print(f"Wrote {args.json}")

        if args.html:
            print(f"Updated {args.html}: {embed_in_html(args.html, blob)}")

    fig = plot_seasonality(matrix, summary, partial, asof, cvd_safe=args.cvd_safe)
    fig.savefig(args.out, dpi=160, bbox_inches="tight", facecolor="white")
    print(f"Saved {args.out}")
    if args.show:
        plt.show()


if __name__ == "__main__":
    main()