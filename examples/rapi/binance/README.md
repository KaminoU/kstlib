# Binance API with HMAC Signing

This example demonstrates how to use kstlib RAPI with HMAC-SHA256 signing for Binance authenticated endpoints.

## Setup

### 1. Get API Credentials

**For Testnet (recommended for testing):**
1. Go to https://testnet.binance.vision/
2. Log in with GitHub
3. Generate API Key and Secret

**For Production:**
1. Go to https://www.binance.com/en/my/settings/api-management
2. Create a new API key (enable Spot trading if needed)

### 2. Set Environment Variables

```bash
# Windows (PowerShell)
$env:BINANCE_API_KEY = "your_api_key"
$env:BINANCE_API_SECRET = "your_secret_key"

# Linux/macOS
export BINANCE_API_KEY="your_api_key"
export BINANCE_API_SECRET="your_secret_key"
```

### 3. Switch to Testnet (optional)

Edit `binance.rapi.yml` and uncomment the testnet URL:

```yaml
# base_url: "https://api.binance.com"  # Production
base_url: "https://testnet.binance.vision"  # Testnet
```

## Usage

Run commands from this directory:

```bash
cd examples/rapi/binance

# Public endpoints (no auth)
kstlib rapi binance.ping
kstlib rapi binance.time
kstlib rapi binance.ticker-price
kstlib rapi binance.ticker-price symbol=ETHUSDT

# Authenticated endpoints (HMAC signed)
kstlib rapi binance.balance
kstlib rapi binance.my-trades symbol=BTCUSDT limit=5
kstlib rapi binance.open-orders
kstlib rapi binance.all-orders symbol=ETHUSDT

# With verbose output (see signature generation)
kstlib -vvv rapi binance.balance

# Output to file
kstlib rapi binance.balance -o balance.json
```

## How HMAC Signing Works

For authenticated endpoints, kstlib automatically:

1. Adds `timestamp` parameter (milliseconds since epoch)
2. Builds the query string (sorted alphabetically)
3. Generates HMAC-SHA256 signature using your secret key
4. Adds `signature` parameter to the request
5. Sends `X-MBX-APIKEY` header with your API key

Example signed request:
```
GET /api/v3/account?timestamp=1700000000000&signature=abc123...
X-MBX-APIKEY: your_api_key
```

## Endpoints

| Endpoint | Auth | Description |
|----------|------|-------------|
| `binance.ping` | No | Test connectivity |
| `binance.time` | No | Server time |
| `binance.exchange-info` | No | Exchange trading rules |
| `binance.ticker-price` | No | Current price |
| `binance.balance` | Yes | Account balances |
| `binance.my-trades` | Yes | Trade history |
| `binance.open-orders` | Yes | Open orders |
| `binance.all-orders` | Yes | Order history |

## Troubleshooting

### "Invalid signature"

- Check that `BINANCE_API_SECRET` is correct
- Ensure your system clock is synchronized (NTP)

### "API key does not exist"

- Check that `BINANCE_API_KEY` is correct
- For testnet, make sure you're using the testnet URL

### "Timestamp for this request is outside of the recvWindow"

- Your system clock may be out of sync
- Try syncing with an NTP server
