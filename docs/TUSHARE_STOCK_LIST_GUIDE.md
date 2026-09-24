# Tushare Stock List Fetch Tool Guide

## Overview

Fetches the A-share, Hong Kong, and US stock lists from Tushare Pro and saves them locally as CSV files.

## Quick Start

### 1. Configure the token

Add your Tushare token to the `.env` file in the project root:

```bash
TUSHARE_TOKEN=你的tushare_token
```

> Getting a token: register at [Tushare Pro](https://tushare.pro/weborder/#/login) and obtain one there.

### 2. Run the script

```bash
python3 scripts/fetch_tushare_stock_list.py
```

To correct A-share name states, add `--a-rk`. The script keeps `stock_basic` as the base source, then uses `rt_k` to back-fill names carrying an `XD`, `XR`, `DR`, `N`, or `C` prefix, and overwrites `data/stock_list_a.csv` with the result:

```bash
python3 scripts/fetch_tushare_stock_list.py --a-rk
```

### 3. Check the output

The data is saved under `data/`:

```
data/
├── stock_list_a.csv       # A-share list (corrected names when --a-rk is used)
├── stock_list_hk.csv      # Hong Kong list
├── stock_list_us.csv      # US list
└── README_stock_list.md   # Data description document
```

## Features

✅ **Automatic pagination**: US data is read page by page (5,000 rows per page)
✅ **Adaptive rate limiting**: a random 5-10 second pause between requests
✅ **Error handling**: one market failing does not affect the others
✅ **Progress reporting**: read progress is shown live
✅ **Automatic documentation**: a detailed data description document is generated

## Market notes

| Market | Endpoint | Credit requirement | Volume |
|------|------|----------|--------|
| A-shares | stock_basic | 2,000 credits | ~5,000 symbols |
| Hong Kong | hk_basic | 2,000 credits | ~2,000 symbols |
| US | us_basic | 120 trial / 5,000 full | ~10,000 symbols |

## Output file formats

### A-shares (stock_list_a.csv)

With `--a-rk`, this file receives the corrected A-share names.

```csv
ts_code,symbol,name,area,industry,market,exchange,list_date,...
000001.SZ,000001,平安银行,深圳,银行,主板,SZSE,19910403,...
600519.SH,600519,贵州茅台,贵州,白酒,主板,SSE,20010827,...
```

### Hong Kong (stock_list_hk.csv)

```csv
ts_code,name,fullname,market,list_date,trade_unit,curr_type,...
00700.HK,腾讯控股,腾讯控股有限公司,主板,20040616,100,HKD,...
00005.HK,汇丰控股,汇丰控股有限公司,主板,19750401,100,HKD,...
```

### US (stock_list_us.csv)

```csv
ts_code,name,enname,classify,list_date,...
AAPL,苹果,Apple Inc.,EQT,19801212,...
TSLA,特斯拉,Tesla Inc.,EQT,20100629,...
BABA,阿里巴巴,Alibaba Group,ADR,20140919,...
```

## Usage examples

### Reading the data from Python

```python
import pandas as pd

# Read the A-share list
a_stocks = pd.read_csv('data/stock_list_a.csv')
print(f"A-share count: {len(a_stocks)}")

# Filter main-board stocks
main_board = a_stocks[a_stocks['market'] == '主板']
print(f"Main-board count: {len(main_board)}")

# Look up one stock
stock = a_stocks[a_stocks['ts_code'] == '600519.SH']
print(stock[['name', 'industry', 'list_date']])
```

### Refreshing the stock autocomplete index

Use the one-shot refresh script. It defaults to `--a-rk` when fetching A-shares, then generates and syncs the autocomplete index:

```bash
pip install -r requirements.txt
python3 scripts/refresh_stock_index.py
```

Generating the autocomplete index depends on `pypinyin` to write the full-pinyin and pinyin-initial fields for Chinese stock names. If that dependency is missing the script fails outright, rather than producing a degraded index that cannot support pinyin search.

To update only the CSV files, fetch the data on its own:

```bash
python3 scripts/fetch_tushare_stock_list.py --a-rk
```

If you already have fresh CSV files and only want to rebuild the index:

```bash
python3 scripts/generate_index_from_csv.py --test  # dry run first
python3 scripts/generate_index_from_csv.py         # generate once confirmed
```

### Automatic index updates on the local client

By default the current client reads the latest `apps/dsa-web/public/stocks.index.json` from the project's GitHub `main` branch and caches it locally at `data/cache/stocks.index.json`. The frontend still requests the local `/stocks.index.json`, so no cross-origin request to GitHub is needed.

The remote index URL, check frequency, and network timeout are built-in system values with no user-facing configuration. The only decision left to the user is whether to enable the feature:

```bash
STOCK_INDEX_REMOTE_UPDATE_ENABLED=true
```

When enabled, the system checks for updates at most once every 48 hours. If the runtime cannot reach GitHub raw, the request times out, or the response is not a valid stock index, the application keeps the existing cache; with no remote cache it falls back to the built-in index shipped with the application. A failed remote update never blocks WebUI startup, stock autocomplete, or the analysis flow. After a built-in threshold of consecutive failures, retries are paused within the process until the next 48-hour window.

## Notes

1. **Credit requirement**: make sure the account has enough credits (2,000 for A-shares and Hong Kong, 120 for the US trial)
2. **Request limits**: mind the API's per-minute request cap
3. **Data refresh**: maintainers are advised to refresh every three days and commit the result to the repository; local clients check GitHub `main` for index updates at most once every 48 hours. Refresh and PR submission can later be automated with a GitHub Actions workflow
4. **Network connectivity**: a stable network connection is required

## FAQ

### Q: It reports "TUSHARE_TOKEN not found"
**A**: Set `TUSHARE_TOKEN=你的token` in the `.env` file.

### Q: It reports "insufficient account credits"
**A**:
- A-shares and Hong Kong require 2,000 credits
- The US endpoint offers a 120-credit trial; full access requires 5,000 credits
- See https://tushare.pro for how to earn credits

### Q: What should I do when a read fails?
**A**:
1. Check the network connection
2. Check that the token is correct
3. Check whether the account has enough credits
4. The current script does not retry automatically. A failed request prints an error and ends the run, so diagnose the cause and run it again

### Q: How often should the data be refreshed?
**A**: For a maintainer's local CSV files and the repository index, refresh every three days and commit the result. High-impact events such as an ST-tag removal or a rename justify an ad-hoc refresh. This can later be automated with a GitHub Actions workflow that refreshes and opens a PR. Ordinary local clients check GitHub `main` for the latest index at most once every 48 hours by default.

### Q: Does being unable to reach GitHub raw break anything?
**A**: No. The remote index update is best-effort: on failure the client keeps using the existing remote cache or the built-in index shipped with the application. If the index is entirely unavailable, web autocomplete falls back to the existing path and stock codes can still be entered by hand.

## Related links

- [Tushare home page](https://tushare.pro)
- [Tushare documentation](https://tushare.pro/document/2)
- [How to earn credits](https://tushare.pro/document/1)
- [API data console](https://tushare.pro/document/2)
