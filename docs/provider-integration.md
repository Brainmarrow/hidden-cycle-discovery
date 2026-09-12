# Broker & Data Provider Integration

The platform talks to every data source — Indian brokers and global feeds — through
one unified `DataProvider` interface. Cycle-discovery code never knows or cares where
the candles came from; it just gets a normalized OHLCV DataFrame.

```
                    ┌─────────────────────────────┐
   your request →   │      ProviderRegistry        │
   (symbol,         │   .get_ohlcv(...)            │
    interval)       │   • auto-routes              │
                    │   • falls back on failure    │
                    └──────────────┬───────────────┘
                                   │
         ┌─────────────────────────┼─────────────────────────┐
         ▼                                                     ▼
   Indian brokers                                       Global sources
   ┌──────────────┐                                   ┌──────────────┐
   │ Zerodha      │  request_token → access_token     │ Yahoo        │  no key
   │ Upstox       │  OAuth2 bearer                    │ Stooq        │  no key
   │ Angel One    │  TOTP → JWT                       │ Alpha Vantage│  api key
   │ Dhan         │  static token                     │ Twelve Data  │  api key
   │ Fyers        │  OAuth2 auth-code                 │ CCXT (crypto)│  no key
   └──────────────┘                                   └──────────────┘
```

## Why this design

- **Indian + global stay interchangeable.** Ask for `NIFTY` through Zerodha for
  authenticated intraday, or through Yahoo with no login — same call, same output.
- **Add a broker in ~80 lines.** Subclass `DataProvider`, implement `fetch_ohlcv`,
  register it in `registry.py`. Nothing downstream changes.
- **Never dies on one feed.** If a broker token expired at 6am, the request falls
  back to a global source automatically (configurable per call).

## Provider capability matrix

| Provider | Region | Auth | Historical | Intraday | Live | Stream | Orders |
|----------|--------|------|:---:|:---:|:---:|:---:|:---:|
| Zerodha Kite | India | request_token | ✅ | ✅ | ✅ | ✅ | ✅ |
| Upstox v3 | India | OAuth2 bearer | ✅ | ✅ | ✅ | ✅ | ✅ |
| Angel One | India | TOTP→JWT | ✅ | ✅ | ✅ | ✅ | ✅ |
| Dhan | India | static token | ✅ | ✅ | ✅ | ✅ | ✅ |
| Fyers | India | OAuth2 code | ✅ | ✅ | ✅ | ✅ | ✅ |
| Yahoo | Global | none | ✅ | ⚠️ 60d | ✅ | ❌ | ❌ |
| Stooq | Global | none | ✅ daily | ❌ | ❌ | ❌ | ❌ |
| Alpha Vantage | Global | api key | ✅ | ✅ | ✅ | ❌ | ❌ |
| Twelve Data | Global | api key | ✅ | ✅ | ✅ | ❌ | ❌ |
| CCXT | Global (crypto) | none | ✅ | ✅ | ✅ | ❌ | ❌ |

## Connecting a broker (API)

### Zerodha (request-token flow)
```bash
# 1. Get the login URL
curl -X POST .../providers/zerodha/login-url \
  -H "Authorization: Bearer $JWT" \
  -d '{"api_key":"your_kite_api_key"}'
# → open the returned URL, log in, copy request_token from the redirect

# 2. Complete the handshake
curl -X POST .../providers/zerodha/connect \
  -H "Authorization: Bearer $JWT" \
  -d '{"api_key":"...","api_secret":"...","request_token":"..."}'
# → {"connected": true, "expires_at": "..."}
```

### Angel One (TOTP — no redirect)
```bash
curl -X POST .../providers/angelone/connect \
  -H "Authorization: Bearer $JWT" \
  -d '{"api_key":"smartapi_key","client_code":"A12345","pin":"1234","totp":"678901"}'
```

### Dhan (paste long-lived token)
```bash
curl -X POST .../providers/dhan/connect \
  -H "Authorization: Bearer $JWT" \
  -d '{"access_token":"your_dhan_token","client_id":"1000000001"}'
```

Upstox and Fyers use the same two-step pattern as Zerodha but with an OAuth
`auth_code` and a `redirect_uri`.

## Fetching data (broker or global, same call)

```bash
# Through a connected broker (uses your stored session)
curl -X POST .../providers/fetch \
  -d '{"symbol":"NIFTY","interval":"5m","provider":"zerodha"}'

# Auto-route (no provider named → picks a global source)
curl -X POST .../providers/fetch \
  -d '{"symbol":"AAPL","interval":"1d"}'

# Crypto
curl -X POST .../providers/fetch \
  -d '{"symbol":"BTC/USDT","interval":"1h"}'
```

Response tells you what actually served the data and whether it fell back:
```json
{
  "symbol": "NIFTY",
  "provider_used": "zerodha",
  "fell_back": false,
  "attempts": ["zerodha"],
  "n_bars": 4500
}
```

## A note on Google Finance & Investing.com

Neither offers a stable public OHLCV API:

- **Google Finance** is a Google Sheets function (`GOOGLEFINANCE(...)`), not a REST
  endpoint. There's no supported programmatic feed.
- **Investing.com** has no public API and its terms prohibit scraping.

For the same global instruments those sites cover, the registry routes to **Yahoo**
and **Stooq**, which are reliable and permit programmatic access. If you specifically
want Google-Sheets-sourced data, the clean path is a Sheets-side `GOOGLEFINANCE`
export to CSV, then upload via the existing CSV path — no scraping involved.

## Adding your own provider

```python
# app/providers/my_broker.py
from app.providers.base import DataProvider, ProviderInfo, ProviderRegion, ProviderCapability

class MyBrokerProvider(DataProvider):
    info = ProviderInfo(
        key="mybroker", name="My Broker", region=ProviderRegion.INDIA,
        capabilities=[ProviderCapability.HISTORICAL],
        requires_auth=True, auth_type="api_key",
        supported_intervals=["1m","5m","1d"],
    )
    INTERVAL_MAP = {"1m":"1","5m":"5","1d":"D"}

    async def fetch_ohlcv(self, symbol, interval, start=None, end=None):
        native = self._map_interval(interval, self.INTERVAL_MAP)
        # ... call your broker's REST API ...
        # df = pd.DataFrame(candles, columns=[...])
        return self._normalize_df(df)   # one call handles all normalization
```

Then register it in `registry.py`:
```python
PROVIDER_CLASSES["mybroker"] = MyBrokerProvider
```

Done — it now appears in `/providers`, participates in routing, and is callable
through `/providers/fetch`.

## Security notes

- **Secrets never get logged.** `api_secret`, `pin`, and `totp` are used only to
  complete the handshake and are dropped immediately.
- **Sessions are in-memory by default** (`_SESSIONS` in `providers.py`). For
  production, encrypt and persist them (DB column or a secrets manager like AWS
  Secrets Manager / Vault), keyed by user.
- **Token expiry is tracked.** Most Indian broker tokens die ~6am IST; `AuthSession`
  carries `expires_at`, and the registry treats an expired session as a failed
  primary and falls back automatically.
- **Static IP for orders (Zerodha).** Since April 2025, Zerodha requires a registered
  static IP to *place orders* — data endpoints are unaffected. This platform's data
  paths work from any IP.
