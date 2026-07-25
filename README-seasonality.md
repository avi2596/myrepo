# S&P 500 monthly seasonality

Average percentage change of every calendar month for the S&P 500 (`^GSPC`),
over the last 25 years plus the year to date.

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
| `sp500_seasonality.png` | static heatmap — year grid, average/median strip, win rate, observation count |
| `sp500_seasonality.html` | interactive page; `--html` swaps its embedded data block in place |
| `sp500_seasonality_data.json` | the numbers on their own |

## Method

Monthly bars, `auto_adjust=True`, percentage change month over month. The sample
is every month from January of the first year through today. **All of it counts
toward the averages, the year to date included**, and the month in progress is
carried at its month-to-date return (marked `*`). So months already past in the
current year hold one more observation than those still ahead of it — the
`Months` row reports which is which.

Price return only: `^GSPC` excludes dividends, so these are not total returns.

## After a refresh

The interactive page derives its headline, tiles, strip, tooltips and method
note from the embedded data, so those restate themselves. The prose under
**"What the grid says"** is hand-written and does *not* update — re-read it after
any refresh that moves a ranking.