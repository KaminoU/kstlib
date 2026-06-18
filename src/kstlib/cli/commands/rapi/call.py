"""Make API calls from the command line."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Annotated, Any, cast

import typer
from typer.core import TyperCommand

from kstlib.auth import AuthExpiredError
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
    ServerNotFoundError,
)
from kstlib.utils.serialization import is_xml_content, to_json, to_xml

if TYPE_CHECKING:
    from collections.abc import Mapping

    import click


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


def _validate_format(fmt: str) -> None:
    """Reject output formats outside the supported set with a friendly error.

    Extracted from the ``call`` command body so the cyclomatic
    complexity budget keeps room for the exception handlers that
    cover the runtime error paths (auth expiration, HTTP errors,
    safeguard checks, etc.).

    Args:
        fmt: Format value passed by the user via ``--format`` / ``-f``.

    Raises:
        typer.Exit: Exit code 1 if ``fmt`` is not one of ``json``,
            ``text``, or ``full``.

    """
    if fmt not in ("json", "text", "full"):
        exit_error(f"Invalid output format: '{fmt}'\nValid formats: json, text, full")


def _is_multipart_file_body(endpoint_config: Any, body: str | None) -> bool:
    """Return True when the call targets a multipart endpoint with a ``@file`` body.

    Extracted from the ``call`` command body to keep its cyclomatic
    complexity in check. The compound check is pulled out so each
    short-circuit (``and``) does not count as a separate branch
    against the caller's complexity budget.
    """
    return endpoint_config.is_multipart and body is not None and body.startswith("@")


def _handle_auth_expired_error(error: AuthExpiredError, *, quiet: bool) -> None:
    """Render an :class:`AuthExpiredError` and exit with code 4.

    Distinct exit code lets shell scripts detect token expiration
    specifically and trigger an automated re-login flow (decision
    D5 in the v3.0.0 roadmap). The message body is built from the
    exception attributes : ``Error: <message>``, optionally
    ``Source: <token_source>``, optionally ``Hint: <suggested_action>``.

    Args:
        error: The caught :class:`AuthExpiredError`.
        quiet: Whether the user passed ``--quiet`` / ``-q``.

    Raises:
        typer.Exit: Always exits with code 4.

    """
    message_lines = [f"Error: {error.message}"]
    if error.token_source:
        message_lines.append(f"Source: {error.token_source}")
    if error.suggested_action:
        message_lines.append(f"Hint: {error.suggested_action}")
    exit_with_result(
        CommandResult(
            status=CommandStatus.ERROR,
            message="\n".join(message_lines),
            payload={
                "token_source": error.token_source,
                "suggested_action": error.suggested_action,
            },
        ),
        quiet=quiet,
        exit_code=4,
        cause=error,
    )


def _validate_output_flags(raw: bool, minify: bool) -> None:
    """Reject ``--minify`` without ``--raw`` at command entry.

    Rich console rendering reformats output regardless of compact JSON
    flags, so ``--minify`` without ``--raw`` is silently ineffective.
    Fail fast with a hint instead of swallowing the user intent.

    Args:
        raw: True if the user passed ``--raw``.
        minify: True if the user passed ``--minify``.

    Raises:
        typer.BadParameter: If ``minify`` is True and ``raw`` is False.
            The message contains the hint ``--raw --minify``.

    """
    if minify and not raw:
        raise typer.BadParameter(
            "--minify requires --raw (Rich rendering ignores compact JSON formatting). Hint: use --raw --minify.",
        )


def _serialize_json(data: Any, *, minify: bool = False, indent: int = 2) -> str:
    """Serialize data to JSON string.

    Args:
        data: Data to serialize.
        minify: If True, output compact single-line JSON.
        indent: Indentation level for pretty-print.

    Returns:
        JSON string.

    """
    if minify:
        return json.dumps(data, separators=(",", ":"), default=str)
    return to_json(data, indent=indent)


def _build_content(
    response: RapiResponse,
    fmt: str,
    minify: bool,
) -> str:
    """Build formatted content string from response.

    Args:
        response: The API response to format.
        fmt: Output format (json, text, full).
        minify: Output compact single-line JSON.

    Returns:
        Formatted content string.

    """
    render_config = get_rapi_render_config()
    content_type = response.headers.get("content-type", "")
    indent = render_config.json_indent or 2

    if fmt == "full":
        result_data = {
            "endpoint": response.endpoint_ref,
            "status_code": response.status_code,
            "ok": response.ok,
            "elapsed": f"{response.elapsed:.3f}s",
            "headers": dict(response.headers),
            "data": response.data,
        }
        return _serialize_json(result_data, minify=minify, indent=indent)

    if fmt == "text":
        if render_config.xml_pretty and is_xml_content(response.text, content_type):
            return to_xml(response.text)
        return response.text

    # fmt == "json" (default)
    if response.data is not None:
        return _serialize_json(response.data, minify=minify, indent=indent)
    if render_config.xml_pretty and is_xml_content(response.text, content_type):
        return to_xml(response.text)
    return response.text


def _format_output(
    response: RapiResponse,
    fmt: str,
    quiet: bool,
    out_file: str | None = None,
    *,
    raw: bool = False,
    minify: bool = False,
) -> None:
    """Format and print response output.

    Args:
        response: The API response to format.
        fmt: Output format (json, text, full).
        quiet: Whether to suppress rich formatting.
        out_file: Optional file path to write output to.
        raw: Output raw JSON without Rich formatting (pipeable).
        minify: Output compact single-line JSON.

    """
    content = _build_content(response, fmt, minify)

    # Write to file or print
    if out_file:
        from pathlib import Path

        Path(out_file).write_text(content, encoding="utf-8")
        if not quiet:
            console.print(f"[green]Output written to:[/green] {out_file}")
    elif quiet or raw or fmt == "text" or (fmt == "json" and response.data is None):
        print(content)
    else:
        console.print_json(content)


def _normalize_show_extracted(args: list[str]) -> list[str]:
    """Rewrite bare ``--show-extracted`` tokens into ``--show-extracted=``.

    A bare flag is one at the end of the argument list, or followed by a
    token that cannot be an extracted key name: another option (leading
    ``-``) or a ``key=value`` query argument (contains ``=``). The rewrite
    gives the flag an explicit empty value (empty string selects all keys)
    so click never consumes the next token as the key.

    Args:
        args: Raw CLI tokens for the call command.

    Returns:
        The token list with bare ``--show-extracted`` occurrences rewritten.

    Examples:
        >>> _normalize_show_extracted(["ep", "--show-extracted"])
        ['ep', '--show-extracted=']
        >>> _normalize_show_extracted(["ep", "--show-extracted", "object_ids"])
        ['ep', '--show-extracted', 'object_ids']
        >>> _normalize_show_extracted(["ep", "--show-extracted", "limit=5"])
        ['ep', '--show-extracted=', 'limit=5']

    """
    result: list[str] = []
    for index, token in enumerate(args):
        if token == "--show-extracted":
            nxt = args[index + 1] if index + 1 < len(args) else None
            if nxt is None or nxt.startswith("-") or "=" in nxt:
                result.append("--show-extracted=")
                continue
        result.append(token)
    return result


class _CallCommand(TyperCommand):
    """Click command giving ``--show-extracted`` an optional value.

    Typer cannot express click's optional-value options (``is_flag=False``
    plus ``flag_value`` are explicitly unsupported), so a bare
    ``--show-extracted`` is rewritten to ``--show-extracted=`` (empty value
    selects all keys) before parsing. The next token is treated as the KEY
    only when it looks like one (no leading dash, no ``=``), so
    ``--show-extracted limit=5`` keeps ``limit=5`` as a query argument.
    """

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        """Normalize bare ``--show-extracted`` tokens, then parse as usual."""
        return super().parse_args(ctx, _normalize_show_extracted(args))


def _parse_extract_specs(specs: list[str]) -> dict[str, str]:
    """Parse ``key=jmespath`` extraction specs into an ordered mapping.

    Args:
        specs: Raw ``--extract`` values like ``["id=data.id", "name=user.name"]``.

    Returns:
        Mapping of output key to JMESPath expression, preserving input order.

    Raises:
        typer.BadParameter: If a spec lacks ``=`` or has an empty key.

    Examples:
        >>> _parse_extract_specs(["id=data.id", "name=user.name"])
        {'id': 'data.id', 'name': 'user.name'}

    """
    result: dict[str, str] = {}
    for spec in specs:
        if "=" not in spec:
            raise typer.BadParameter(f"Invalid --extract spec '{spec}'. Expected format: key=jmespath.")
        key, expr = spec.split("=", 1)
        key = key.strip()
        if not key:
            raise typer.BadParameter(f"Invalid --extract spec '{spec}'. Key must not be empty.")
        result[key] = expr
    return result


def _validate_extraction_flags(
    pick: str | None,
    extract: list[str] | None,
    show_id: bool,
    show_ids: bool,
    show_extracted: str | None,
) -> None:
    """Reject more than one extraction mode and malformed ``--extract`` specs.

    The five extraction flags are mutually exclusive: at most one may be active
    per call (``--extract`` may repeat with itself). ``--extract`` specs are
    validated up front so a malformed ``key=jmespath`` fails before any network
    request is issued.

    Args:
        pick: Value passed via ``--pick`` / ``-p`` (None when absent).
        extract: Values passed via repeated ``--extract`` (None when absent).
        show_id: Whether ``--show-id`` was set.
        show_ids: Whether ``--show-ids`` was set.
        show_extracted: Value passed via ``--show-extracted`` (None when
            absent; empty string selects all extracted keys).

    Raises:
        typer.BadParameter: If more than one extraction mode is active, or an
            ``--extract`` spec is not a valid ``key=jmespath`` pair.

    """
    active = [
        name
        for name, on in (
            ("--pick", pick is not None),
            ("--extract", bool(extract)),
            ("--show-id", show_id),
            ("--show-ids", show_ids),
            ("--show-extracted", show_extracted is not None),
        )
        if on
    ]
    if len(active) > 1:
        raise typer.BadParameter(
            "Only one of --pick / --extract / --show-id / --show-ids / --show-extracted "
            f"may be used at once (got: {', '.join(active)}).",
        )
    if extract:
        _parse_extract_specs(extract)


def _is_extraction_requested(
    pick: str | None,
    extract: list[str] | None,
    show_id: bool,
    show_ids: bool,
    show_extracted: str | None,
) -> bool:
    """Return True when any extraction flag is active.

    Args:
        pick: Value passed via ``--pick`` (None when absent).
        extract: Values passed via ``--extract`` (None when absent).
        show_id: Whether ``--show-id`` was set.
        show_ids: Whether ``--show-ids`` was set.
        show_extracted: Value passed via ``--show-extracted`` (None when
            absent).

    Returns:
        True if at least one extraction flag selects extraction output.

    """
    return pick is not None or bool(extract) or show_id or show_ids or show_extracted is not None


def _render_extracted_content(value: Any, *, raw: bool, minify: bool, indent: int) -> str:
    """Render an extracted value to a plain (pipeable) stdout string.

    Extraction output is never Rich-formatted: the feature targets scripting and
    piping. Scalars render bare (no quotes), lists render as a JSON array by
    default or one item per line with ``--raw``, and dicts (or any other shape)
    render as JSON.

    Args:
        value: The extracted value (scalar, list, dict, or None).
        raw: Whether ``--raw`` was set (newline-delimited list items).
        minify: Whether ``--minify`` was set (compact JSON).
        indent: JSON indentation for the pretty (non-minified) form.

    Returns:
        The string to write to stdout (empty string for an empty raw list).

    """
    if value is None or isinstance(value, (str, int, float)):
        return str(value)
    if isinstance(value, list) and raw and not minify:
        return "\n".join("" if item is None else str(item) for item in value)
    return _serialize_json(value, minify=minify, indent=indent)


def _emit_extracted_value(
    value: Any,
    *,
    out: str | None,
    quiet: bool,
    raw: bool,
    minify: bool,
    indent: int,
    empty_hint: str | None,
) -> None:
    """Write an extracted value to stdout or a file, honoring the empty policy.

    Args:
        value: The extracted value to emit.
        out: Optional file path to write to instead of stdout.
        quiet: Whether to suppress the "Output written to" confirmation.
        raw: Whether ``--raw`` was set.
        minify: Whether ``--minify`` was set.
        indent: JSON indentation for the pretty form.
        empty_hint: When set and ``value`` is None, write this hint to stderr and
            exit with code 1 (``--show-id`` / ``--pick``). When None, an empty
            value is a legitimate result (``--show-ids`` / ``--extract``).

    Raises:
        typer.Exit: Exit code 1 when ``empty_hint`` is set and ``value`` is None.

    """
    if empty_hint is not None and value is None:
        typer.echo(empty_hint, err=True)
        raise typer.Exit(code=1)
    content = _render_extracted_content(value, raw=raw, minify=minify, indent=indent)
    suppress_empty_line = raw and isinstance(value, list) and not value
    if out is not None:
        from pathlib import Path

        Path(out).write_text(content, encoding="utf-8")
        if not quiet:
            console.print(f"[green]Output written to:[/green] {out}")
    elif not suppress_empty_line:
        print(content)


def _split_extracted_keys(spec: str) -> list[str]:
    """Split a ``--show-extracted`` spec on commas/whitespace, dropping empties.

    Examples:
        >>> _split_extracted_keys("v1,v2")
        ['v1', 'v2']
        >>> _split_extracted_keys("v1 v2")
        ['v1', 'v2']
        >>> _split_extracted_keys("v1, ,v2")
        ['v1', 'v2']
        >>> _split_extracted_keys("")
        []

    """
    return [key for key in re.split(r"[,\s]+", spec) if key]


def _resolve_show_extracted(response: RapiResponse, spec: str) -> tuple[Any, str | None]:
    """Resolve the ``--show-extracted`` value and its empty-policy hint.

    The failure semantics follow the output form:

    - No ``spec`` (bare flag): the whole ``extracted`` mapping is returned as a
      dict (exit 0; a missing ``extract:`` directive still fails).
    - A single key: the raw value is returned and a None value fails (exit 1),
      mirroring ``--pick``. This keeps backward compatibility with v3.2.0
      scripts that read one key.
    - Several keys (comma/space-separated): a JSON object subset is returned
      (exit 0). A declared key whose expression matched nothing appears as
      ``null``; only an unknown key fails.

    An endpoint without an ``extract:`` directive, or an unknown key, is a
    usage failure (exit 1 via the hint). Hints name keys only, never values.

    Args:
        response: The API response whose ``extracted`` mapping is read.
        spec: The requested keys (comma/space-separated), or an empty string
            to select all keys.

    Returns:
        Tuple of (value to emit, empty hint). The hint is consumed by
        :func:`_emit_extracted_value` only when the value is None.

    """
    extracted: Mapping[str, Any] = response.extracted
    if not extracted:
        return None, "No extract: directive declared for this endpoint."
    keys = _split_extracted_keys(spec)
    if not keys:
        return dict(extracted), None
    if len(keys) == 1:
        key = keys[0]
        if key not in extracted:
            available = ", ".join(sorted(extracted))
            return None, f"No extracted key '{key}'. Available: {available}."
        return extracted.get(key), f"Extracted key '{key}' matched nothing."
    missing = [key for key in keys if key not in extracted]
    if missing:
        available = ", ".join(sorted(extracted))
        noun = "key" if len(missing) == 1 else "keys"
        names = ", ".join(f"'{key}'" for key in missing)
        return None, f"No extracted {noun} {names}. Available: {available}."
    return {key: extracted[key] for key in keys}, None


def _handle_extraction_output(
    response: RapiResponse,
    *,
    pick: str | None,
    extract: list[str] | None,
    show_id: bool,
    show_ids: bool,
    show_extracted: str | None,
    out: str | None,
    quiet: bool,
    raw: bool,
    minify: bool,
) -> None:
    """Emit the value selected by the active extraction flag.

    Exactly one extraction flag is active here (validated upstream by
    :func:`_validate_extraction_flags`). ``--show-id`` / ``--pick`` treat a None
    result as a failure (exit 1 via ``empty_hint``); ``--show-ids`` /
    ``--extract`` accept empty results as legitimate. ``--show-extracted``
    follows the declared-vs-not-declared policy of
    :func:`_resolve_show_extracted`.

    Args:
        response: The API response to extract from.
        pick: JMESPath expression from ``--pick`` (None when absent).
        extract: ``key=jmespath`` specs from ``--extract`` (None when absent).
        show_id: Whether ``--show-id`` was set.
        show_ids: Whether ``--show-ids`` was set.
        show_extracted: Key from ``--show-extracted`` (None when absent;
            empty string selects all extracted keys).
        out: Optional output file path.
        quiet: Whether to suppress the file-write confirmation.
        raw: Whether ``--raw`` was set.
        minify: Whether ``--minify`` was set.

    """
    indent = get_rapi_render_config().json_indent or 2
    if show_extracted is not None:
        value, hint = _resolve_show_extracted(response, show_extracted)
        _emit_extracted_value(
            value,
            out=out,
            quiet=quiet,
            raw=raw,
            minify=minify,
            indent=indent,
            empty_hint=hint,
        )
    elif show_id:
        _emit_extracted_value(
            response.id,
            out=out,
            quiet=quiet,
            raw=raw,
            minify=minify,
            indent=indent,
            empty_hint="No id could be resolved from the response.",
        )
    elif show_ids:
        _emit_extracted_value(
            response.ids,
            out=out,
            quiet=quiet,
            raw=raw,
            minify=minify,
            indent=indent,
            empty_hint=None,
        )
    elif pick is not None:
        _emit_extracted_value(
            response.get(pick),
            out=out,
            quiet=quiet,
            raw=raw,
            minify=minify,
            indent=indent,
            empty_hint=f"JMESPath expression matched nothing: {pick}",
        )
    else:
        specs = _parse_extract_specs(extract or [])
        result = {key: response.get(expr) for key, expr in specs.items()}
        _emit_extracted_value(
            result,
            out=out,
            quiet=quiet,
            raw=raw,
            minify=minify,
            indent=indent,
            empty_hint=None,
        )


def _render_response(
    response: RapiResponse,
    *,
    fmt: str,
    quiet: bool,
    out: str | None,
    raw: bool,
    minify: bool,
    pick: str | None,
    extract: list[str] | None,
    show_id: bool,
    show_ids: bool,
    show_extracted: str | None,
) -> None:
    """Dispatch response rendering to extraction output or the default formatter.

    When any extraction flag is active, ``--format`` is ignored and the extracted
    value is emitted as plain (pipeable) stdout. Otherwise the standard
    :func:`_format_output` path renders the full response.

    Args:
        response: The API response to render.
        fmt: Output format for the default path (json, text, full).
        quiet: Whether ``--quiet`` was set.
        out: Optional output file path.
        raw: Whether ``--raw`` was set.
        minify: Whether ``--minify`` was set.
        pick: JMESPath expression from ``--pick``.
        extract: ``key=jmespath`` specs from ``--extract``.
        show_id: Whether ``--show-id`` was set.
        show_ids: Whether ``--show-ids`` was set.
        show_extracted: Key from ``--show-extracted`` (None when absent).

    """
    if _is_extraction_requested(pick, extract, show_id, show_ids, show_extracted):
        _handle_extraction_output(
            response,
            pick=pick,
            extract=extract,
            show_id=show_id,
            show_ids=show_ids,
            show_extracted=show_extracted,
            out=out,
            quiet=quiet,
            raw=raw,
            minify=minify,
        )
    else:
        _format_output(response, fmt, quiet, out, raw=raw, minify=minify)


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
    server: Annotated[
        str | None,
        typer.Option(
            "--server",
            "-s",
            help=(
                "Named server profile from rapi.servers config. Overrides any server: directive in *.rapi.yml files."
            ),
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
    raw: Annotated[
        bool,
        typer.Option(
            "--raw",
            help="Output raw JSON without Rich formatting (pipeable).",
        ),
    ] = False,
    minify: Annotated[
        bool,
        typer.Option(
            "--minify",
            help="Output compact single-line JSON.",
        ),
    ] = False,
    pick: Annotated[
        str | None,
        typer.Option(
            "--pick",
            "-p",
            help="Extract a single value via JMESPath (ad-hoc). Example: --pick data.id",
        ),
    ] = None,
    extract: Annotated[
        list[str] | None,
        typer.Option(
            "--extract",
            help="Extract named values: key=jmespath (repeatable). Example: --extract id=data.id --extract name=user.name",
        ),
    ] = None,
    show_id: Annotated[
        bool,
        typer.Option(
            "--show-id",
            help="Print the resolved resource id (config-driven heuristic).",
        ),
    ] = False,
    show_ids: Annotated[
        bool,
        typer.Option(
            "--show-ids",
            help="Print all resolved resource ids (config-driven heuristic).",
        ),
    ] = False,
    show_extracted: Annotated[
        str | None,
        typer.Option(
            "--show-extracted",
            metavar="[KEY[,KEY...]]",
            help=(
                "Print values declared by the endpoint extract: directive. "
                "One KEY prints that value; several comma/space-separated keys "
                "print a JSON object subset; without a value, print all keys as JSON. "
                'Quote keys with spaces ("v1 v2") or join with commas (v1,v2) so the shell does not split them.'
            ),
        ),
    ] = None,
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

        # Raw output (no Rich, pipeable to jq)
        kstlib rapi github.user --raw | jq '.login'

        # Minified JSON (compact single-line)
        kstlib rapi github.user --minify --out user.json

        # Named server profile (heterogeneous APIs from rapi.servers config)
        kstlib rapi --server github github.repos-list
        kstlib rapi -s jira jira.issues-search

        # Extract a single value via JMESPath (ad-hoc, pipeable)
        kstlib rapi github.user --pick login

        # Extract named values into a JSON object
        kstlib rapi github.user --extract login=login --extract uid=id

        # Show the resolved resource id / ids (config-driven heuristic)
        kstlib rapi jira.issues-get ISSUE-1 --show-id
        kstlib rapi github.repos-list --show-ids

        # Show values declared by the endpoint extract: directive
        kstlib rapi myapi.item-get abc-123 --show-extracted object_ids
        kstlib rapi myapi.item-get abc-123 --show-extracted

    """
    # Parse arguments
    positional_args, keyword_args = _parse_args(args or [])
    headers = _parse_headers(header or [])

    # Validate output format
    _validate_format(fmt)

    # Reject --minify without --raw before any work is done.
    _validate_output_flags(raw=raw, minify=minify)

    # Reject conflicting extraction flags / malformed --extract specs early.
    _validate_extraction_flags(pick, extract, show_id, show_ids, show_extracted)

    from kstlib.cli.commands.rapi import _load_config_or_exit

    config_manager = _load_config_or_exit()
    try:
        # Create client and resolve endpoint before body parsing
        client = RapiClient(config_manager=config_manager)

        # Resolve endpoint to check if multipart
        _, endpoint_config = config_manager.resolve(endpoint)

        # For multipart endpoints with @file body, pass raw string to client
        # (client reads file as binary instead of CLI parsing as JSON)
        if _is_multipart_file_body(endpoint_config, body):
            parsed_body: Any = body
        else:
            parsed_body = _parse_body(body)

        response = client.call(
            endpoint,
            *positional_args,
            body=parsed_body,
            headers=headers if headers else None,
            server=server,
            **cast("dict[str, Any]", keyword_args),
        )

        # Format and print output. Extraction flags override --format with
        # plain, pipeable stdout; otherwise the standard formatter is used.
        _render_response(
            response,
            fmt=fmt,
            quiet=quiet,
            out=out,
            raw=raw,
            minify=minify,
            pick=pick,
            extract=extract,
            show_id=show_id,
            show_ids=show_ids,
            show_extracted=show_extracted,
        )

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
    except ServerNotFoundError as e:
        exit_with_result(
            CommandResult(
                status=CommandStatus.ERROR,
                message=(
                    f"Server profile not found: '{e.server_name}'. Available: {e.available or '(none configured)'}"
                ),
                payload={"available_servers": e.available} if e.available else None,
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
    except AuthExpiredError as e:
        _handle_auth_expired_error(e, quiet=quiet)
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
