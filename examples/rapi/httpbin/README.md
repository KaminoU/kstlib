# httpbin API Example

This example demonstrates the **config-driven RAPI** pattern with [httpbin.org](https://httpbin.org), a simple HTTP testing service.

## Structure

```
httpbin/
├── httpbin.rapi.yml     # API definition (endpoints, no auth)
├── kstlib.conf.yml      # Auto-include via glob pattern
└── README.md
```

## Usage

### CLI

```bash
cd examples/rapi/httpbin

# List available endpoints
kstlib rapi list

# Make API calls
kstlib rapi httpbin.get_ip
kstlib rapi httpbin.echo_headers
kstlib rapi httpbin.delayed 3
kstlib rapi httpbin.get_status 418
kstlib rapi httpbin.post_data --body '{"foo": "bar"}'
```

### Python

```python
from kstlib.rapi import RapiClient

# Load from specific file
client = RapiClient.from_file("httpbin.rapi.yml")

# Or auto-discover
client = RapiClient.discover()

# Call endpoints
response = client.call("httpbin.get_ip")
print(response.data["origin"])

# With path parameters
response = client.call("httpbin.delayed", 2)

# With body (POST)
response = client.call("httpbin.post_data", body={"user": "alice"})
print(response.data["json"])
```

## Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `httpbin.get_ip` | GET | Returns client IP |
| `httpbin.echo_headers` | GET | Returns request headers |
| `httpbin.get_uuid` | GET | Returns a random UUID |
| `httpbin.delayed` | GET | Delays response by N seconds |
| `httpbin.get_status` | GET | Returns specified HTTP status |
| `httpbin.post_data` | POST | Echoes POST data |
| `httpbin.bearer_auth` | GET | Test bearer authentication |

## Notes

- No credentials required for httpbin
- Useful for testing and development
- See `examples/rapi/github/` for a real API example with SOPS credentials
