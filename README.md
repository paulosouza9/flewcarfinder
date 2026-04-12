# Car Deal Bot

Sends you a daily digest of the best car deals from **AutoScout24** (and optionally mobile.de)
every morning — **for free**, no API key required.

## Quick start

```powershell
# 1. Create virtual environment and install dependencies
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt

# 2. Copy and edit the config
copy config.example.yaml config.yaml
# Edit config.yaml: set make, model, price, year, mileage filters

# 3. (Optional) Telegram notifications
copy .env.example .env
# Edit .env: set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID
# Without Telegram, results are printed to the console.

# 4. Test it right now
.\.venv\Scripts\python.exe -m car_deal_bot run-once

# 5. Run the scheduler (stays open, triggers at the time set in config.yaml)
.\.venv\Scripts\python.exe -m car_deal_bot schedule
```

## Configuration (`config.yaml`)

```yaml
schedule:
  hour: 7        # send at 07:00
  minute: 0
  timezone: Europe/Berlin

search:
  make: BMW
  model: "3 Series"
  price_max_eur: 28000
  year_min: 2018
  mileage_max_km: 150000
  country: DE

  # Exact URL slugs used by each site — auto-derived from make/model if omitted.
  # Tip: do a search on the site and copy the slug from the URL bar.
  autoscout_make_slug: bmw
  autoscout_model_slug: 3-series
  mobilede_make_id: BMW
  mobilede_model_id: 3ER

sources:
  autoscout:
    enabled: true   # works out of the box
    max_pages: 5
    country_code: D # D=Germany, A=Austria, CH=Switzerland
  mobile_de:
    enabled: false  # see note below

ranking:
  top_n: 15
  strategy: cheapest_first   # or: lowest_price_per_km

notification:
  telegram:
    enabled: true  # false → print to console
```

## Sources

| Source | Status | Notes |
|---|---|---|
| **AutoScout24** | ✅ works | Reads `__NEXT_DATA__` JSON embedded in each search page |
| **mobile.de** | ⚠️ 403 by default | Their Akamai bot layer blocks plain HTTP clients based on TLS fingerprinting |

### Enabling mobile.de (optional)

mobile.de uses Akamai Bot Manager which checks the SSL handshake, not just headers.
To bypass it, install `curl_cffi` which impersonates Chrome's TLS fingerprint:

```powershell
.\.venv\Scripts\pip install curl_cffi
```

Then set `mobile_de.enabled: true` in `config.yaml`.
The bot will automatically use `curl_cffi` when it is installed.

> **Note**: `curl_cffi` may not have a pre-built wheel for the very latest Python releases.
> If it fails to install, stay on AutoScout24 only — it alone covers 2 million+ European listings.

## Telegram setup

1. Message [@BotFather](https://t.me/BotFather) → `/newbot` → copy the token.
2. Get your chat ID: message [@userinfobot](https://t.me/userinfobot).
3. Put both in `.env`.

## Run daily with Windows Task Scheduler (recommended)

Instead of keeping a terminal open, schedule `run-once` to run every morning:

1. Open **Task Scheduler** → Create Basic Task
2. Trigger: **Daily** at your preferred time
3. Action: **Start a program**
   - Program: `D:\projects\Car deal bot\.venv\Scripts\python.exe`
   - Arguments: `-m car_deal_bot run-once`
   - Start in: `D:\projects\Car deal bot`

## Project layout

```
car_deal_bot/
  __main__.py       # CLI entry point (run-once / schedule)
  run.py            # orchestrates fetch → rank → notify
  scheduler.py      # APScheduler wrapper
  config_loader.py  # loads config.yaml via Pydantic
  settings.py       # loads .env secrets
  models.py         # VehicleListing, SearchParams
  ranker.py         # deduplication + sorting
  notify.py         # Telegram + plain-text output
  sources/
    base.py         # ListingSource ABC
    autoscout.py    # AutoScout24 scraper (__NEXT_DATA__)
    mobile_de.py    # mobile.de scraper (HTML / curl_cffi)
```
