# Monthly seasonality heatmap

Average percentage change of every calendar month, over the last 25 years plus
the year to date. The static PNG covers one symbol (`^GSPC` by default); the
interactive page carries thirteen and switches between them in the browser.

## Refresh

```bash
pip install -r requirements-seasonality.txt
python sp500_seasonality_heatmap.py \
    --html sp500_seasonality.html \
    --json sp500_seasonality_data.json
```

That single command re-fetches from Yahoo Finance and rewrites all three outputs:

| File | What it is |
|---|---|
| `sp500_seasonality.png` | static heatmap for one symbol — year grid, average/median strip, win rate, observation count |
| `sp500_seasonality.html` | interactive page, all bundled symbols; `--html` swaps its embedded data block in place |
| `sp500_seasonality_data.json` | the numbers on their own, every symbol |

## Choosing symbols

A published artifact runs under a strict CSP and **cannot call Yahoo**, so the
page can only offer symbols that were fetched at build time and embedded. The
picker is populated from whatever this script bundled.

```bash
# the PNG symbol
python sp500_seasonality_heatmap.py --ticker ^IXIC

# what the page offers (the --ticker symbol is always included, and leads)
python sp500_seasonality_heatmap.py --tickers '^GSPC,^FTSE,TSLA,^HSI' --html sp500_seasonality.html
```

Default bundle: `^GSPC ^IXIC ^DJI ^RUT ^FTSE ^N225 ^GDAXI GC=F CL=F BTC-USD
AAPL MSFT NVDA`. A symbol that fails to fetch is skipped with a warning rather
than sinking the run; if *none* resolve, the script exits without writing.

Colour scales are per symbol — crude oil's grid spans ±89%, the FTSE's ±14% —
because one shared scale would flatten the calmer instruments to a single tone.

## Method

Monthly bars, `auto_adjust=True`, percentage change month over month. The sample
is every month from January of the first year through today. **All of it counts
toward the averages, the year to date included**, and the month in progress is
carried at its month-to-date return (marked `*`). So months already past in the
current year hold one more observation than those still ahead of it — the
`Months` row reports which is which.

Price return only: `^GSPC` excludes dividends, so these are not total returns.

## After a refresh

Nothing to check by hand. Every word of the page that carries a number —
headline, tiles, average strip, tooltips, method note, and the findings under
**"What the grid says"** — is generated from the embedded data at render time.
The findings in particular are written per symbol and branch on what the numbers
actually say: whether one year is carrying the best month, whether a weak month
is a habit or a few disasters, whether the half-year gap is real or noise. Prose
about the S&P would otherwise become a quiet lie about bitcoin the moment
someone changed the picker.