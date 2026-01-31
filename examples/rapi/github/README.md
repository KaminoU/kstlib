# GitHub API Example

This example demonstrates the **config-driven RAPI** pattern: define your API once in YAML, use it everywhere.

## Structure

```
github/
├── github.rapi.yml      # API definition (endpoints, auth, headers)
├── kstlib.conf.yml      # Auto-include via glob pattern
├── demo.py              # Example script
├── tokens/
│   └── github.sops.json # SOPS-encrypted GitHub token
└── README.md
```

## Setup

### 1. Create GitHub Token

1. Go to [GitHub Settings > Tokens](https://github.com/settings/tokens)
2. Generate a **Personal Access Token (classic)** with scopes:
   - `public_repo` - Read public repositories
   - `read:user` - Read user profile
   - `repo:status` - Read commit statuses (optional)

### 2. Store Token in SOPS

```bash
cd examples/rapi/github/tokens

# Create the JSON file
echo '{"access_token": "ghp_YOUR_TOKEN_HERE"}' > github.json

# Encrypt with SOPS (requires age key configured)
sops -e -i github.json
mv github.json github.sops.json
```

### 3. Run the Demo

```bash
cd examples/rapi/github
python demo.py
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `github.user` | GET | Authenticated user info |
| `github.user-repos` | GET | User's repositories |
| `github.users-get` | GET | Public user by username |
| `github.repos-get` | GET | Repository details |
| `github.repos-commits` | GET | Recent commits |
| `github.repos-issues` | GET | Open issues |
| `github.rate-limit` | GET | API rate limit status |

## Usage Examples

### Python

```python
from kstlib.rapi import RapiClient

# Load from file
client = RapiClient.from_file("github.rapi.yml")

# Or auto-discover
client = RapiClient.discover()

# Call endpoints
response = client.call("github.user")
print(response.data["login"])

# With path parameters
response = client.call("github.repos-get", owner="KaminoU", repo="igcv3")
print(response.data["stargazers_count"])
```

### Include in Main Config

In your project's `kstlib.conf.yml`:

```yaml
rapi:
  include:
    - "./apis/*.rapi.yml"  # Include all API definitions
```

## YAML Format Reference

```yaml
name: github                          # API name (used as prefix)
base_url: "https://api.github.com"    # Base URL

credentials:                          # Inline credential config
  type: sops                          # sops, file, env, provider
  path: "./tokens/github.sops.json"
  token_path: ".access_token"

auth: bearer                          # bearer, basic, api_key, hmac

headers:                              # Default headers for all endpoints
  Accept: "application/vnd.github+json"

endpoints:
  user:                               # Endpoint name
    path: "/user"                     # URL path (supports {param})
    method: GET                       # HTTP method
    query:                            # Default query parameters
      per_page: "10"
```
