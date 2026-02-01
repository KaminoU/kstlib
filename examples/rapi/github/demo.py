#!/usr/bin/env python3
"""GitHub API demo using kstlib.rapi config-driven client.

This example demonstrates the "describe once, use everywhere" pattern:
- API defined in github.rapi.yml
- Credentials stored in SOPS-encrypted file
- Auto-discovery via kstlib.conf.yml include

Usage:
    cd examples/rapi/github
    python demo.py

Requirements:
    - SOPS configured with age key
    - GitHub token in tokens/github.sops.json
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure we use local kstlib
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from kstlib.rapi import RapiClient
from kstlib.rapi.exceptions import ConfirmationRequiredError


def safe_print(text: str) -> None:
    """Print text safely, replacing unencodable characters."""
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", errors="replace").decode("ascii"))


def main() -> None:
    """Run GitHub API demo."""
    safe_print("=" * 60)
    safe_print("GitHub API Demo - kstlib.rapi config-driven")
    safe_print("=" * 60)

    # Method 1: Load from specific file
    print("\n[1] Loading from github.rapi.yml...")
    client = RapiClient.from_file("github.rapi.yml")

    # List available endpoints
    print(f"\nAvailable APIs: {client.list_apis()}")
    print(f"Endpoints: {client.list_endpoints()}")

    # Get authenticated user info
    safe_print("\n[2] Fetching authenticated user...")
    response = client.call("github.user")
    if response.ok:
        user = response.data
        safe_print(f"    Login: {user['login']}")
        safe_print(f"    Name: {user.get('name', 'N/A')}")
        safe_print(f"    Public repos: {user['public_repos']}")
    else:
        safe_print(f"    Error: {response.status_code}")

    # Get user's repos
    safe_print("\n[3] Fetching user repos (last 5 updated)...")
    response = client.call("github.user-repos")
    if response.ok:
        for repo in response.data[:5]:
            stars = repo.get("stargazers_count", 0)
            safe_print(f"    - {repo['name']} ({stars} stars)")
    else:
        safe_print(f"    Error: {response.status_code}")

    # Get rate limit status
    safe_print("\n[4] Checking rate limit...")
    response = client.call("github.rate-limit")
    if response.ok:
        core = response.data["resources"]["core"]
        safe_print(f"    Remaining: {core['remaining']}/{core['limit']}")
    else:
        safe_print(f"    Error: {response.status_code}")

    # Example with path parameters
    safe_print("\n[5] Fetching KaminoU/igcv3 repo info...")
    response = client.call("github.repos-get", owner="KaminoU", repo="igcv3")
    if response.ok:
        repo = response.data
        safe_print(f"    Full name: {repo['full_name']}")
        safe_print(f"    Stars: {repo['stargazers_count']}")
        safe_print(f"    Forks: {repo['forks_count']}")
        safe_print(f"    Open issues: {repo['open_issues_count']}")
    else:
        safe_print(f"    Error: {response.status_code} - {response.text[:100]}")

    # Get recent commits
    safe_print("\n[6] Fetching recent commits...")
    response = client.call("github.repos-commits", owner="KaminoU", repo="igcv3")
    if response.ok:
        for commit in response.data[:3]:
            sha = commit["sha"][:7]
            msg = commit["commit"]["message"].split("\n")[0][:50]
            safe_print(f"    - {sha}: {msg}")
    else:
        safe_print(f"    Error: {response.status_code}")

    # Demonstrate safeguard feature (dangerous endpoint protection)
    safe_print("\n[7] Safeguard demo (dangerous endpoint protection)...")
    safe_print("    Trying to delete a repo WITHOUT confirmation...")
    try:
        # This will fail because repos-delete has a safeguard
        client.call("github.repos-delete", owner="test", repo="fake-repo")
    except ConfirmationRequiredError as e:
        safe_print(f"    Blocked! {e.message}")
        safe_print(f'    Expected confirmation: "{e.expected}"')

    safe_print("\n    To actually delete, you would need:")
    safe_print('    client.call("github.repos-delete", owner="X", repo="Y",')
    safe_print('                confirm="DELETE REPO X/Y")')

    safe_print("\n" + "=" * 60)
    safe_print("Demo complete!")
    safe_print("=" * 60)


if __name__ == "__main__":
    main()
