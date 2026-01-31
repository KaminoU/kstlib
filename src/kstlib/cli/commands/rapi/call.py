"""Make API calls from the command line."""

from __future__ import annotations

import json
from typing import Annotated, Any, cast

import typer

from kstlib.cli.common import CommandResult, CommandStatus, console, exit_error, exit_with_result
from kstlib.limits import get_rapi_render_config
from kstlib.rapi import (
    CredentialError,
    EndpointAmbiguousError,
    EndpointNotFoundError,
    RapiClient,
    RapiResponse,
    RequestError,
    ResponseTooLargeError,
    load_rapi_config,
)
from kstlib.utils.serialization import is_xml_content, to_json, to_xml


def _parse_args(
    args: list[str],
) -> tuple[list[str], dict[str, str]]:
    """Parse positional and keyword arguments.

    Args:
        args: List of arguments like ["3", "foo=bar", "count=42"].

    Returns:
        Tuple of (positional_args, keyword_args).

    Examples:
        >>> _parse_args(["3", "foo=bar", "count=42"])
        (['3'], {'foo': 'bar', 'count': '42'})
        >>> _parse_args(["value1", "value2"])
        (['value1', 'value2'], {})
    """
    positional: list[str] = []
    keyword: dict[str, str] = {}

    for arg in args:
        if "=" in arg:
            key, value = arg.split("=", 1)
            keyword[key] = value
        else:
            positional.append(arg)

    return positional, keyword


def _parse_headers(headers: list[str]) -> dict[str, str]:
    """Parse header arguments.

    Args:
        headers: List of headers like ["Accept: application/json", "X-Debug: true"].

    Returns:
        Dictionary of header name to value.

    Raises:
        typer.Exit: If header format is invalid.
    """
    result: dict[str, str] = {}
    for header in headers:
        if ":" not in header:
            exit_error(f"Invalid header format: '{header}'\nExpected: 'Header-Name: value'")
        name, value = header.split(":", 1)
        result[name.strip()] = value.strip()
    return result


def _parse_body(body: str | None) -> dict[str, Any] | list[Any] | None:
    """Parse JSON body string or load from file.

    Supports reading from file with @filename syntax (like curl).

    Args:
        body: JSON string, @filename reference, or None.

    Returns:
        Parsed JSON object or None.

    Raises:
        typer.Exit: If body is not valid JSON or file not found.

    Examples:
        >>> _parse_body('{"key": "value"}')
        {'key': 'value'}
        >>> _parse_body('@data.json')  # Reads from file
        {'key': 'value'}
    """
    if body is None:
        return None

    # Support @filename syntax (like curl)
    if body.startswith("@"):
        from pathlib import Path

        filepath = Path(body[1:])
        try:
            content = filepath.read_text(encoding="utf-8")
        except FileNotFoundError:
            exit_error(f"Body file not found: {filepath}")
        except OSError as e:
            exit_error(f"Failed to read body file '{filepath}': {e}")
    else:
        content = body

    try:
        return json.loads(content)  # type: ignore[no-any-return]
    except json.JSONDecodeError as e:
        exit_error(f"Invalid JSON body: {e}")


def _format_output(
    response: RapiResponse,
    fmt: str,
    quiet: bool,
    out_file: str | None = None,
) -> None:
    """Format and print response output.

    Args:
        response: The API response to format.
        fmt: Output format (json, text, full).
        quiet: Whether to suppress rich formatting.
        out_file: Optional file path to write output to.
    """
    # Load render config for pretty-print settings
    render_config = get_rapi_render_config()
    content_type = response.headers.get("content-type", "")

    # Build output content
    if fmt == "full":
        result_data = {
            "endpoint": response.endpoint_ref,
            "status_code": response.status_code,
            "ok": response.ok,
            "elapsed": f"{response.elapsed:.3f}s",
            "headers": dict(response.headers),
            "data": response.data,
        }
        content = to_json(result_data, indent=render_config.json_indent or 2)
    elif fmt == "text":
        # Text format: apply XML pretty-print if enabled and content is XML
        if render_config.xml_pretty and is_xml_content(response.text, content_type):
            content = to_xml(response.text)
        else:
            content = response.text
    elif response.data is not None:
        # JSON data available: format with configured indent
        content = to_json(response.data, indent=render_config.json_indent or 2)
    elif render_config.xml_pretty and is_xml_content(response.text, content_type):
        # No JSON data but XML detected: pretty-print if enabled
        content = to_xml(response.text)
    else:
        # Raw text fallback
        content = response.text

    # Write to file or print
    if out_file:
        from pathlib import Path

        Path(out_file).write_text(content, encoding="utf-8")
        if not quiet:
            console.print(f"[green]Output written to:[/green] {out_file}")
    elif quiet or fmt == "text" or (fmt == "json" and response.data is None):
        print(content)
    else:
        console.print_json(content)


def call(
    endpoint: Annotated[
        str,
        typer.Argument(help="Endpoint reference (e.g., 'github.user' or 'api.endpoint')."),
    ],
    args: Annotated[
        list[str] | None,
        typer.Argument(
            help="Path/query params: positional for path, key=value for query.",
        ),
    ] = None,
    body: Annotated[
        str | None,
        typer.Option(
            "--body",
            "-b",
            help="JSON body or @filename to read from file.",
        ),
    ] = None,
    header: Annotated[
        list[str] | None,
        typer.Option(
            "--header",
            "-H",
            help="Custom header (can be repeated). Format: 'Name: value'.",
        ),
    ] = None,
    fmt: Annotated[
        str,
        typer.Option(
            "--format",
            "-f",
            help="Output format: json, text, or full.",
        ),
    ] = "json",
    out: Annotated[
        str | None,
        typer.Option(
            "--out",
            "-o",
            help="Write output to file (for scripting).",
        ),
    ] = None,
    quiet: Annotated[
        bool,
        typer.Option(
            "--quiet",
            "-q",
            help="Suppress status messages, only output response.",
        ),
    ] = False,
) -> None:
    """Make an API call to a configured endpoint.

    Examples:
        # Simple GET (implicit call)
        kstlib rapi github.user

        # GET with path parameters
        kstlib rapi github.repos-get owner=KaminoU repo=igcv3

        # POST with JSON body from file (recommended for complex JSON)
        kstlib rapi myapi.create-item -b @data.json

        # Custom headers
        kstlib rapi github.user -H "X-Debug: true"

        # Output to file (for scripting)
        kstlib rapi github.user -o user.json

        # Full format with file output
        kstlib rapi github.user -f full -o result.json

        # Quiet mode (JSON only, no formatting)
        kstlib rapi github.rate-limit -q
    """
    # Parse arguments
    positional_args, keyword_args = _parse_args(args or [])
    headers = _parse_headers(header or [])
    parsed_body = _parse_body(body)

    # Validate output format
    if fmt not in ("json", "text", "full"):
        exit_error(f"Invalid output format: '{fmt}'\nValid formats: json, text, full")

    try:
        # Create client and make call
        config_manager = load_rapi_config()
        client = RapiClient(config_manager=config_manager)

        response = client.call(
            endpoint,
            *positional_args,
            body=parsed_body,
            headers=headers if headers else None,
            **cast("dict[str, Any]", keyword_args),
        )

        # Format and print output
        _format_output(response, fmt, quiet, out)

        # Exit with appropriate code
        if not response.ok:
            raise typer.Exit(code=1)

    except EndpointNotFoundError as e:
        exit_with_result(
            CommandResult(
                status=CommandStatus.ERROR,
                message=f"Endpoint not found: {e.endpoint_ref}",
                payload={"searched_apis": e.searched_apis} if e.searched_apis else None,
            ),
            quiet=quiet,
            exit_code=1,
            cause=e,
        )
    except EndpointAmbiguousError as e:
        exit_with_result(
            CommandResult(
                status=CommandStatus.ERROR,
                message=f"Ambiguous endpoint: '{e.endpoint_name}' exists in multiple APIs",
                payload={"matching_apis": e.matching_apis},
            ),
            quiet=quiet,
            exit_code=1,
            cause=e,
        )
    except CredentialError as e:
        exit_with_result(
            CommandResult(
                status=CommandStatus.ERROR,
                message=f"Credential error: {e}",
                payload={"credential_name": e.credential_name} if e.credential_name else None,
            ),
            quiet=quiet,
            exit_code=1,
            cause=e,
        )
    except RequestError as e:
        exit_with_result(
            CommandResult(
                status=CommandStatus.ERROR,
                message=f"Request failed: {e}",
                payload={
                    "status_code": e.status_code,
                    "retryable": e.retryable,
                },
            ),
            quiet=quiet,
            exit_code=1,
            cause=e,
        )
    except ResponseTooLargeError as e:
        exit_with_result(
            CommandResult(
                status=CommandStatus.ERROR,
                message=f"Response too large: {e.response_size} bytes (max: {e.max_size})",
            ),
            quiet=quiet,
            exit_code=1,
            cause=e,
        )


__all__ = ["call"]
