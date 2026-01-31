"""Authenticate with an OAuth2/OIDC provider."""

# pylint: disable=too-many-branches,too-many-statements
# Justification: OAuth2 login flow with multiple user-facing modes (quiet/verbose,
# browser/no-browser/manual, PKCE/standard) and comprehensive error handling. Each
# branch handles a distinct case - decomposing would obscure the linear auth flow.

from __future__ import annotations

import re
import webbrowser
from typing import TYPE_CHECKING

# Note: parse_qs not used - it converts + to space, breaking base64 codes
import typer
from rich.panel import Panel
from rich.prompt import Prompt

from kstlib.auth.callback import CallbackServer
from kstlib.auth.config import get_callback_server_config
from kstlib.auth.errors import AuthError, CallbackServerError, TokenExchangeError
from kstlib.cli.common import CommandResult, CommandStatus, console, exit_error, render_result

from .common import PROVIDER_ARGUMENT, QUIET_OPTION, TIMEOUT_OPTION, get_provider, resolve_provider_name

if TYPE_CHECKING:
    from kstlib.auth.providers.base import AbstractAuthProvider


# Defense in depth: limits for manual input
_MAX_INPUT_LENGTH = 8192  # Max URL/code input length (increased for long base64 codes)
_MAX_CODE_LENGTH = 2048  # Max authorization code length (some IdPs use long base64 codes)
_CODE_PATTERN = re.compile(r"^[a-zA-Z0-9._~+/=-]+$")  # RFC 6749 safe chars + base64


def _extract_code_from_input(user_input: str) -> tuple[str | None, str | None]:
    """Extract authorization code and state from user input.

    Handles both full redirect URLs and raw code values.
    Applies defense-in-depth validation on extracted values.

    Args:
        user_input: URL with code parameter or raw code value.

    Returns:
        Tuple of (code, state) where state may be None.
    """
    user_input = user_input.strip()

    # Defense: limit input length to prevent DoS
    if len(user_input) > _MAX_INPUT_LENGTH:
        return None, None

    code: str | None = None
    state: str | None = None

    # Extract code and state via regex (preserves + and / in base64 codes)
    # Note: parse_qs converts + to space, breaking base64-encoded codes
    code_match = re.search(r"[?&]code=([^&\s]+)", user_input)
    if code_match:
        code = code_match.group(1)
        state_match = re.search(r"[?&]state=([^&\s]+)", user_input)
        state = state_match.group(1) if state_match else None

    # Assume raw code value (no URL structure)
    if not code and user_input and not user_input.startswith(("?", "&", "=")):
        code = user_input

    # Defense: validate code format and length
    if code:
        if len(code) > _MAX_CODE_LENGTH:
            return None, None
        if not _CODE_PATTERN.match(code):
            return None, None

    return code, state


def _login_manual(
    auth_provider: AbstractAuthProvider,
    provider_name: str,
    quiet: bool,
) -> None:
    """Perform manual login without callback server.

    Displays the authorization URL and prompts for the redirect URL or code.

    Args:
        auth_provider: The authentication provider instance.
        provider_name: Name of the provider for display.
        quiet: Suppress verbose output.
    """
    # Generate authorization URL (with PKCE if supported)
    if hasattr(auth_provider, "get_authorization_url_with_pkce"):
        auth_url, state, code_verifier = auth_provider.get_authorization_url_with_pkce()
    else:
        auth_url, state = auth_provider.get_authorization_url()
        code_verifier = None

    # Display instructions and URL
    console.print(
        Panel(
            "[bold]Manual authentication mode[/]\n\n"
            "1. Copy the URL below and open it in your browser\n"
            "2. Complete the authentication\n"
            "3. Copy the redirect URL from your browser (even if it shows an error)\n"
            "4. Paste it below",
            title="Manual Login",
            style="cyan",
        )
    )
    console.print()
    console.print("[bold]Authorization URL:[/]")
    console.print(f"\n{auth_url}\n", soft_wrap=True, highlight=False)

    # Prompt for redirect URL or code
    console.print("[bold]After authentication, paste the redirect URL or code:[/]")
    user_input = Prompt.ask("[dim](paste URL or code)[/]")

    if not user_input:
        exit_error("No input provided.")

    # Extract code from input
    code, returned_state = _extract_code_from_input(user_input)

    if not code:
        exit_error(
            "Could not extract authorization code from input.\nExpected a URL with ?code=... or the raw code value."
        )

    # Validate state if returned
    if returned_state and returned_state != state:
        exit_error("State mismatch - possible CSRF attack.")

    # Exchange code for token
    if not quiet:
        console.print("[dim]Exchanging authorization code for token...[/]")

    try:
        token = auth_provider.exchange_code(
            code=code,
            state=state,
            code_verifier=code_verifier,
        )
    except TokenExchangeError as e:
        exit_error(f"Token exchange failed: {e}")

    # Success
    render_result(
        CommandResult(
            status=CommandStatus.OK,
            message=f"Successfully authenticated with {provider_name}.",
            payload={
                "provider": provider_name,
                "token_type": token.token_type.value if hasattr(token.token_type, "value") else str(token.token_type),
                "expires_in": token.expires_in,
                "scopes": token.scope,
            }
            if not quiet
            else None,
        )
    )


def _login_with_callback(
    auth_provider: AbstractAuthProvider,
    provider_name: str,
    quiet: bool,
    timeout: int,
    no_browser: bool,
) -> None:
    """Perform login using local callback server.

    Args:
        auth_provider: The authentication provider instance.
        provider_name: Name of the provider for display.
        quiet: Suppress verbose output.
        timeout: Callback timeout in seconds.
        no_browser: Print URL instead of opening browser.
    """
    callback_cfg = get_callback_server_config()

    with CallbackServer(
        host=callback_cfg["host"],
        port=callback_cfg["port"],
    ) as server:
        # Generate authorization URL
        if hasattr(auth_provider, "get_authorization_url_with_pkce"):
            auth_url, state, code_verifier = auth_provider.get_authorization_url_with_pkce()
        else:
            auth_url, state = auth_provider.get_authorization_url()
            code_verifier = None

        if no_browser:
            console.print(
                Panel(
                    "Open this URL in your browser:",
                    title="Authorization URL",
                    style="cyan",
                )
            )
            console.print(f"\n{auth_url}\n", soft_wrap=True, highlight=False)
        else:
            if not quiet:
                console.print(f"[dim]Opening browser for {provider_name} authentication...[/]")
            webbrowser.open(auth_url)

        if not quiet:
            console.print(f"[dim]Waiting for callback (timeout: {timeout}s)...[/]")

        # Wait for callback
        result = server.wait_for_callback(timeout=timeout)

        if result.error:
            exit_error(f"Authorization failed: {result.error_description or result.error}")

        if result.code is None:
            exit_error("No authorization code received.")

        # Validate state
        if result.state != state:
            exit_error("State mismatch - possible CSRF attack.")

        # Exchange code for token
        if not quiet:
            console.print("[dim]Exchanging authorization code for token...[/]")

        token = auth_provider.exchange_code(
            code=result.code,
            state=state,
            code_verifier=code_verifier,
        )

        # Success
        render_result(
            CommandResult(
                status=CommandStatus.OK,
                message=f"Successfully authenticated with {provider_name}.",
                payload={
                    "provider": provider_name,
                    "token_type": token.token_type.value
                    if hasattr(token.token_type, "value")
                    else str(token.token_type),
                    "expires_in": token.expires_in,
                    "scopes": token.scope,
                }
                if not quiet
                else None,
            )
        )


def login(  # noqa: PLR0913
    provider: str | None = PROVIDER_ARGUMENT,
    quiet: bool = QUIET_OPTION,
    timeout: int = TIMEOUT_OPTION,
    no_browser: bool = typer.Option(
        False,
        "--no-browser",
        help="Print authorization URL instead of opening browser.",
    ),
    manual: bool = typer.Option(
        False,
        "--manual",
        "-m",
        help="Manual mode: display URL and prompt for code (no callback server).",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Force re-authentication even if already authenticated.",
    ),
) -> None:
    """Authenticate with an OAuth2/OIDC provider.

    Opens the system browser to complete the OAuth2 authorization flow.
    Use --manual when the callback server cannot bind (e.g., port 443 in corporate environments).
    """
    provider_name = resolve_provider_name(provider)
    auth_provider = get_provider(provider_name)

    # Check if already authenticated
    if not force and auth_provider.is_authenticated:
        if quiet:
            console.print(f"[green]{provider_name}: already authenticated[/]")
        else:
            console.print(
                Panel(
                    f"Already authenticated with [cyan]{provider_name}[/].\nUse [bold]--force[/] to re-authenticate.",
                    title="Auth Status",
                    style="green",
                )
            )
        return

    try:
        if manual:
            _login_manual(auth_provider, provider_name, quiet)
        else:
            _login_with_callback(auth_provider, provider_name, quiet, timeout, no_browser)

    except CallbackServerError as e:
        # Suggest manual mode if callback server fails
        console.print(
            Panel(
                f"[red]{e}[/]\n\n"
                "[yellow]Tip:[/] Use [bold]--manual[/] mode to authenticate without a callback server:\n"
                f"  kstlib auth login --manual {provider_name}",
                title="Callback Server Error",
                style="red",
            )
        )
        raise typer.Exit(1) from None
    except TokenExchangeError as e:
        exit_error(f"Token exchange failed: {e}")
    except AuthError as e:
        exit_error(f"Authentication failed: {e}")
    except TimeoutError:
        exit_error(f"Authentication timed out after {timeout} seconds.")
    except KeyboardInterrupt:
        exit_error("Authentication cancelled by user.")


__all__ = ["login"]
