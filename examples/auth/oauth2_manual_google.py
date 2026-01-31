#!/usr/bin/env python3
"""Manual OAuth2 Authorization Code flow with Google - no abstractions.

This example demonstrates the OAuth2 Authorization Code flow "from scratch"
using only httpx and standard library. No kstlib.auth wrappers are used,
making it educational for understanding OAuth2 internals.

The example:
    1. Starts a local callback server to receive the authorization code
    2. Opens browser for Google OAuth consent
    3. Exchanges the code for tokens using httpx
    4. Calls Gmail API to prove the token works

Setup:
    1. Create OAuth2 credentials in Google Cloud Console
    2. Add http://localhost:8400/callback to authorized redirect URIs
    3. Store credentials in examples/auth/google.secrets.yml (will be encrypted)
    4. Run: kstlib secrets encrypt google.secrets.yml -o google.secrets.sops.yml

Usage:
    cd examples/auth
    python oauth2_manual_google.py your-email@gmail.com

Educational value:
    - See exactly what HTTP requests OAuth2 requires
    - Understand state parameter for CSRF protection
    - Learn token response structure
    - No magic - just HTTP calls
"""

from __future__ import annotations

import argparse
import base64
import secrets
import sys
import webbrowser
from email.message import EmailMessage
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

# Add src to path for development (only for config loading)
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

# =============================================================================
# Configuration Loading (uses kstlib.config for SOPS auto-decrypt)
# =============================================================================


def load_google_credentials() -> dict[str, Any]:
    """Load Google OAuth2 credentials from SOPS-encrypted config.

    Returns:
        Dict with client_id, client_secret, scopes, and redirect_uri.

    Raises:
        SystemExit: If credentials not found.
    """
    try:
        from kstlib.config import load_config

        config = load_config()
        google = config.auth.providers.google

        return {
            "client_id": google.client_id,
            "client_secret": google.client_secret,
            "authorize_url": google.authorize_url,
            "token_url": google.token_url,
            "scopes": list(google.scopes) if google.scopes else "",
            "redirect_uri": google.redirect_uri,
        }
    except Exception as e:
        print("=" * 60)
        print("ERROR: Could not load Google credentials!")
        print("=" * 60)
        print()
        print(f"Details: {e}")
        print()
        print("Make sure you're running from examples/auth/ directory")
        print("and have configured auth.providers.google in kstlib.conf.yml")
        print()
        sys.exit(1)


# =============================================================================
# Manual Callback Server (no kstlib.auth.callback)
# =============================================================================


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """Simple HTTP handler to receive OAuth2 callback."""

    # Class-level storage
    authorization_code: str | None = None
    received_state: str | None = None
    error: str | None = None

    def log_message(self, format: str, *args: object) -> None:
        """Suppress default logging."""
        pass

    def do_GET(self) -> None:
        """Handle OAuth2 callback GET request."""
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        # Extract OAuth2 response parameters
        OAuthCallbackHandler.authorization_code = params.get("code", [None])[0]
        OAuthCallbackHandler.received_state = params.get("state", [None])[0]
        OAuthCallbackHandler.error = params.get("error", [None])[0]

        # Send response to browser
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()

        if OAuthCallbackHandler.error:
            html = f"<h1>Authorization Failed</h1><p>{OAuthCallbackHandler.error}</p>"
        else:
            html = "<h1>Authorization Successful</h1><p>You can close this window.</p>"

        self.wfile.write(html.encode())


def start_callback_server(port: int = 8400) -> HTTPServer:
    """Start a simple HTTP server for OAuth2 callback.

    Args:
        port: Port to listen on.

    Returns:
        HTTPServer instance (not yet serving).
    """
    server = HTTPServer(("127.0.0.1", port), OAuthCallbackHandler)
    server.timeout = 1.0  # Allow checking for shutdown

    # Reset class state
    OAuthCallbackHandler.authorization_code = None
    OAuthCallbackHandler.received_state = None
    OAuthCallbackHandler.error = None

    return server


def wait_for_callback(server: HTTPServer, timeout: float = 120.0) -> tuple[str, str]:
    """Wait for OAuth2 callback with authorization code.

    Args:
        server: HTTPServer instance.
        timeout: Maximum wait time in seconds.

    Returns:
        Tuple of (authorization_code, state).

    Raises:
        SystemExit: On timeout or error.
    """
    import time

    start = time.time()

    while time.time() - start < timeout:
        server.handle_request()

        if OAuthCallbackHandler.error:
            print(f"ERROR: OAuth2 error: {OAuthCallbackHandler.error}")
            sys.exit(1)

        if OAuthCallbackHandler.authorization_code:
            return (
                OAuthCallbackHandler.authorization_code,
                OAuthCallbackHandler.received_state or "",
            )

    print("ERROR: Timeout waiting for OAuth2 callback")
    sys.exit(1)


# =============================================================================
# Manual OAuth2 Flow (no kstlib.auth.OAuth2Provider)
# =============================================================================


def build_authorization_url(
    credentials: dict[str, Any],
    redirect_uri: str,
    state: str,
) -> str:
    """Build the OAuth2 authorization URL.

    This is what the user visits in their browser to grant consent.

    Args:
        credentials: OAuth2 credentials dict.
        redirect_uri: Where Google redirects after consent.
        state: Random state for CSRF protection.

    Returns:
        Full authorization URL.
    """
    params = {
        "client_id": credentials["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(credentials["scopes"]),
        "state": state,
        "access_type": "offline",  # Request refresh token
        "prompt": "consent",  # Force consent to get refresh token
    }

    return f"{credentials['authorize_url']}?{urlencode(params)}"


def exchange_code_for_tokens(
    credentials: dict[str, Any],
    code: str,
    redirect_uri: str,
) -> dict[str, Any]:
    """Exchange authorization code for access and refresh tokens.

    This is the token endpoint POST request.

    Args:
        credentials: OAuth2 credentials dict.
        code: Authorization code from callback.
        redirect_uri: Must match the one used in authorization request.

    Returns:
        Token response dict with access_token, refresh_token, etc.

    Raises:
        SystemExit: On error.
    """
    print("\n--- TOKEN EXCHANGE REQUEST ---")
    print(f"POST {credentials['token_url']}")

    data = {
        "client_id": credentials["client_id"],
        "client_secret": credentials["client_secret"],
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }

    print(f"Body: grant_type=authorization_code, code={code[:20]}...")

    with httpx.Client() as client:
        response = client.post(
            credentials["token_url"],
            data=data,
            headers={"Accept": "application/json"},
        )

    print(f"Response: {response.status_code}")

    if response.status_code != 200:
        print(f"ERROR: Token exchange failed: {response.text}")
        sys.exit(1)

    tokens: dict[str, Any] = response.json()

    print("\n--- TOKEN RESPONSE ---")
    print(f"access_token: {str(tokens.get('access_token', ''))[:30]}...")
    print(f"token_type: {tokens.get('token_type')}")
    print(f"expires_in: {tokens.get('expires_in')} seconds")
    print(f"refresh_token: {'present' if tokens.get('refresh_token') else 'none'}")
    print(f"scope: {tokens.get('scope')}")

    return tokens


def refresh_access_token(
    credentials: dict[str, Any],
    refresh_token: str,
) -> dict[str, Any]:
    """Refresh an expired access token using the refresh token.

    Args:
        credentials: OAuth2 credentials dict.
        refresh_token: The refresh token from initial authorization.

    Returns:
        New token response dict with fresh access_token.

    Raises:
        SystemExit: On error.
    """
    print("\n--- TOKEN REFRESH REQUEST ---")
    print(f"POST {credentials['token_url']}")

    data = {
        "client_id": credentials["client_id"],
        "client_secret": credentials["client_secret"],
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }

    print("Body: grant_type=refresh_token")

    with httpx.Client() as client:
        response = client.post(
            str(credentials["token_url"]),
            data=data,
            headers={"Accept": "application/json"},
        )

    print(f"Response: {response.status_code}")

    if response.status_code != 200:
        print(f"ERROR: Token refresh failed: {response.text}")
        sys.exit(1)

    tokens: dict[str, Any] = response.json()

    print("\n--- REFRESHED TOKEN ---")
    print(f"access_token: {str(tokens.get('access_token', ''))[:30]}...")
    print(f"expires_in: {tokens.get('expires_in')} seconds")

    return tokens


# =============================================================================
# Token Storage (SOPS-encrypted for security)
# =============================================================================


def get_token_path() -> Path:
    """Get the path to the token file."""
    # Use the tokens directory from config (relative to examples/auth/)
    return Path(__file__).parent / "tokens" / "google.token.sops.json"


def load_cached_token() -> dict[str, Any] | None:
    """Load cached token from SOPS-encrypted file.

    Returns:
        Token dict if exists and decryptable, None otherwise.
    """
    import json
    import shutil
    import subprocess

    token_path = get_token_path()

    if not token_path.exists():
        return None

    # Decrypt with SOPS
    sops_bin = shutil.which("sops")
    if sops_bin is None:
        print("WARNING: SOPS not found, cannot load cached token")
        return None

    result = subprocess.run(
        [sops_bin, "--decrypt", str(token_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        print(f"WARNING: Failed to decrypt token: {result.stderr.strip()}")
        return None

    try:
        token: dict[str, Any] = json.loads(result.stdout)
        return token
    except json.JSONDecodeError:
        return None


def save_token(tokens: dict[str, Any]) -> None:
    """Save token to SOPS-encrypted file.

    Args:
        tokens: Token dict to save.
    """
    import json
    import shutil
    import subprocess
    import tempfile

    token_path = get_token_path()
    token_path.parent.mkdir(parents=True, exist_ok=True)

    sops_bin = shutil.which("sops")
    if sops_bin is None:
        print("WARNING: SOPS not found, cannot save token securely")
        return

    # Write to temp file first, then encrypt with SOPS
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
        json.dump(tokens, tmp, indent=2)
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            [sops_bin, "--encrypt", "--input-type", "json", "--output-type", "json", tmp_path],
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode != 0:
            print(f"WARNING: Failed to encrypt token: {result.stderr.strip()}")
            return

        # Write encrypted content
        token_path.write_text(result.stdout)
        print(f"Token saved to: {token_path}")

    finally:
        Path(tmp_path).unlink(missing_ok=True)


def is_token_expired(tokens: dict[str, Any]) -> bool:
    """Check if the access token is expired.

    Args:
        tokens: Token dict with 'expires_at' ISO timestamp.

    Returns:
        True if expired or no expiry info, False otherwise.
    """
    from datetime import datetime, timezone

    expires_at_str = tokens.get("expires_at")
    if expires_at_str is None:
        # No expiry info, assume expired to be safe
        return True

    try:
        expires_at = datetime.fromisoformat(str(expires_at_str))
        # Add 60 second buffer
        now = datetime.now(timezone.utc)
        return now > expires_at
    except ValueError:
        return True


def add_expiry_timestamp(tokens: dict[str, Any]) -> dict[str, Any]:
    """Add expires_at ISO timestamp to token dict.

    Uses same format as kstlib.auth for compatibility.

    Args:
        tokens: Token dict with 'expires_in' seconds.

    Returns:
        Token dict with added 'expires_at' ISO timestamp.
    """
    from datetime import datetime, timedelta, timezone

    expires_in = tokens.get("expires_in")
    if expires_in is not None:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
        tokens["expires_at"] = expires_at.isoformat()

    # Also add issued_at for compatibility with kstlib.auth
    tokens["issued_at"] = datetime.now(timezone.utc).isoformat()

    return tokens


# =============================================================================
# Gmail API Call (proves the token works)
# =============================================================================


def send_test_email(
    access_token: str,
    sender: str,
    recipient: str,
) -> None:
    """Send a test email via Gmail API to prove OAuth2 works.

    Args:
        access_token: OAuth2 access token with gmail.send scope.
        sender: Sender email (must be authenticated user).
        recipient: Recipient email.
    """
    print("\n--- GMAIL API REQUEST ---")
    print("POST https://gmail.googleapis.com/gmail/v1/users/me/messages/send")

    # Build email message
    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = "Test from kstlib - Manual OAuth2"
    message.set_content(
        "Hello!\n\n"
        "This email was sent using manual OAuth2 flow (no wrappers).\n\n"
        "The example demonstrates:\n"
        "  - Authorization code flow\n"
        "  - Token exchange with httpx\n"
        "  - Gmail API call to prove it works\n\n"
        "See examples/auth/oauth2_manual_google.py for the full code."
    )

    # Encode as base64url (Gmail API format)
    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    raw_message = raw_message.rstrip("=")  # Remove padding

    # Call Gmail API
    with httpx.Client() as client:
        response = client.post(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            json={"raw": raw_message},
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
        )

    print(f"Response: {response.status_code}")

    if response.status_code == 200:
        data = response.json()
        print(f"Message ID: {data.get('id')}")
        print(f"Thread ID: {data.get('threadId')}")
        print("\nEmail sent successfully!")
    else:
        print(f"ERROR: Gmail API failed: {response.text}")
        sys.exit(1)


# =============================================================================
# Main
# =============================================================================


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Manual OAuth2 flow with Google (educational example)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example:
    python oauth2_manual_google.py your-email@gmail.com
        """,
    )
    parser.add_argument(
        "email",
        help="Your Gmail address (sender and recipient for test)",
    )
    return parser.parse_args()


def do_full_oauth_flow(credentials: dict[str, Any]) -> dict[str, Any]:
    """Execute the full OAuth2 authorization code flow.

    Args:
        credentials: OAuth2 credentials dict.

    Returns:
        Token dict with access_token, refresh_token, etc.
    """
    # Extract port from redirect_uri in config
    redirect_uri = str(credentials["redirect_uri"])
    parsed_uri = urlparse(redirect_uri)
    port = parsed_uri.port or 8400

    print(f"  redirect_uri: {redirect_uri}")
    print(f"  port: {port}")
    print()

    # Generate state for CSRF protection
    print("Generating state parameter for CSRF protection...")
    state = secrets.token_urlsafe(32)
    print(f"  state: {state[:20]}...")
    print()

    # Start callback server
    print(f"Starting callback server on port {port}...")
    server = start_callback_server(port)
    print(f"  listening on: http://localhost:{port}/callback")
    print()

    # Build and open authorization URL
    print("Building authorization URL...")
    auth_url = build_authorization_url(credentials, redirect_uri, state)
    print(f"  URL: {auth_url[:80]}...")
    print()

    print("Opening browser for user consent...")
    webbrowser.open(auth_url)
    print("  Waiting for callback (authorize in browser)...")
    print()

    # Wait for callback
    code, received_state = wait_for_callback(server, timeout=120)
    server.server_close()

    # Validate state
    print("Validating state parameter...")
    if received_state != state:
        print("ERROR: State mismatch - possible CSRF attack!")
        sys.exit(1)
    print("  State validated OK")
    print()

    # Exchange code for tokens
    print("Exchanging authorization code for tokens...")
    tokens = exchange_code_for_tokens(credentials, code, redirect_uri)

    return tokens


def main() -> None:
    """Run the manual OAuth2 flow demonstration."""
    args = parse_args()

    print("=" * 60)
    print("MANUAL OAUTH2 FLOW - Google (Educational Example)")
    print("=" * 60)
    print()
    print("This example shows OAuth2 'under the hood' - no wrappers!")
    print()

    # Step 1: Load credentials
    print("Step 1: Loading credentials from SOPS config...")
    credentials = load_google_credentials()
    print(f"  client_id: {str(credentials['client_id'])[:30]}...")
    print(f"  scopes: {credentials['scopes']}")
    print()

    # Step 2: Check for cached token
    print("Step 2: Checking for cached token (SOPS-encrypted)...")
    cached_token = load_cached_token()
    tokens: dict[str, Any] | None = None

    if cached_token:
        print(f"  Found cached token: {get_token_path()}")

        if not is_token_expired(cached_token):
            # Token still valid
            print("  Token is still valid!")
            tokens = cached_token
        else:
            # Token expired, try refresh
            print("  Token expired, attempting refresh...")
            refresh_token = cached_token.get("refresh_token")

            if refresh_token:
                try:
                    tokens = refresh_access_token(credentials, str(refresh_token))
                    # Preserve refresh_token (not always returned on refresh)
                    if "refresh_token" not in tokens:
                        tokens["refresh_token"] = refresh_token
                    tokens = add_expiry_timestamp(tokens)
                    save_token(tokens)
                    print("  Token refreshed successfully!")
                except SystemExit:
                    print("  Refresh failed, will do full flow...")
                    tokens = None
            else:
                print("  No refresh token available, will do full flow...")
    else:
        print("  No cached token found")

    # Step 3: Full OAuth flow if needed
    if tokens is None:
        print()
        print("Step 3: Starting full OAuth2 authorization flow...")
        tokens = do_full_oauth_flow(credentials)
        tokens = add_expiry_timestamp(tokens)
        save_token(tokens)
    else:
        print()
        print("Step 3: Skipped (using cached/refreshed token)")

    print()

    # Step 4: Use the token to call Gmail API
    print("Step 4: Testing token with Gmail API...")
    access_token = str(tokens["access_token"])
    send_test_email(access_token, args.email, args.email)
    print()

    print("=" * 60)
    print("SUCCESS! Manual OAuth2 flow completed.")
    print("=" * 60)
    print()
    print("Summary:")
    print("  - Authorization code obtained via browser redirect")
    print("  - Tokens exchanged using direct HTTP POST")
    print("  - Gmail API called to prove token works")
    print()
    print("Check your inbox for the test email!")


if __name__ == "__main__":
    main()
