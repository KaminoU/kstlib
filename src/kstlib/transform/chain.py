"""Transform chain engine for kstlib.transform.

Chains primitives (decode, decompress, parse, patch, serialize,
compress, encode) declared in YAML configuration. Supports preset
inheritance, replace/callable patching with blob/outer/all scopes,
composed patches with filters, and lossless round-trip via stored
envelopes.
"""

from __future__ import annotations

import fnmatch
import importlib
import logging
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from xml.etree.ElementTree import Element

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

from kstlib._shared.logging_helpers import log_trace
from kstlib.transform.config import (
    ComposedPatchConfig,
    FilterConfig,
    PatchConfig,
    PrimitiveConfig,
    TransformChainConfig,
    TransformConfig,
    load_transform_config,
)
from kstlib.transform.exceptions import (
    CallableError,
    CallableImportError,
    PatchError,
    TransformChainError,
    TransformConfigError,
)
from kstlib.transform.primitives import (
    BACKWARD_DISPATCH,
    FORWARD_DISPATCH,
    json_serialize,
    xml_parse,
    xml_serialize,
)
from kstlib.transform.validators import (
    CALLABLE_TIMEOUT,
    FORWARD_ONLY_PRIMITIVES,
    MAX_VARIABLE_REFS,
    VARIABLE_PATTERN,
)

#: Cached PrimitiveConfig for internal XML serialize/parse operations.
#: Avoids re-instantiation on every call.
_DEFAULT_XML_PRIM: PrimitiveConfig = PrimitiveConfig(name="xml")

log = logging.getLogger(__name__)


#: Modules that are ALWAYS rejected by callable patches, regardless of
#: the user-configured ``allowed_callable_modules`` whitelist.
#: These modules provide unrestricted OS or interpreter access and must
#: never be importable via a YAML-driven patch config.
DANGEROUS_MODULES: frozenset[str] = frozenset(
    {
        "os",
        "sys",
        "subprocess",
        "builtins",
        "ctypes",
        "posix",
        "nt",
        "shutil",
        "importlib",
        "pickle",
        "marshal",
        "code",
        "compile",
        "__main__",
    }
)

# Pattern used to auto-coerce bytes->str between zlib and json
_AUTO_COERCE_PAIRS: frozenset[tuple[str, str]] = frozenset(
    {
        ("zlib", "json"),
        ("bytes", "json"),
        ("zlib", "xml"),
        ("bytes", "xml"),
    }
)

#: Default protected paths for :func:`replace_outer_uris`.
#:
#: Each entry is a dotted-path string with ``[*]`` matching any list
#: index. The default blacklist protects ``connectors[*].hints.xpath``
#: because SAS Viya stores BIRD XPath pointers there: patching them
#: would silently corrupt the wrapper-to-content coherence.
#:
#: The set is exposed as a public constant so callers can extend it
#: (or replace it) by passing a custom ``protected_paths`` to
#: :func:`replace_outer_uris`.
PROTECTED_OUTER_PATHS: frozenset[str] = frozenset(
    {
        "connectors[*].hints.xpath",
    }
)


def _parse_path_pattern(pattern: str) -> tuple[str, ...]:
    """Parse a dotted path with ``[*]`` markers into a tuple of segments.

    The wildcard ``"*"`` is emitted in place of every ``[*]`` marker, so
    list indices in the walked path are matched against ``"*"`` for
    structural equality.

    Examples:
        >>> _parse_path_pattern("connectors[*].hints.xpath")
        ('connectors', '*', 'hints', 'xpath')
        >>> _parse_path_pattern("a.b.c")
        ('a', 'b', 'c')
        >>> _parse_path_pattern("items[*]")
        ('items', '*')

    """
    parts: list[str] = []
    for segment in pattern.split("."):
        remaining = segment
        while "[*]" in remaining:
            head, _, remaining = remaining.partition("[*]")
            if head:
                parts.append(head)
            parts.append("*")
        if remaining:
            parts.append(remaining)
    return tuple(parts)


# Pre-parsed default protected paths for replace_outer_uris.
# Avoids re-parsing on every call when using the defaults.
_PROTECTED_OUTER_PATHS_PARSED: frozenset[tuple[str, ...]] = frozenset(
    _parse_path_pattern(p) for p in PROTECTED_OUTER_PATHS
)


def _replace_in_string(value: str, replace_map: Mapping[str, str]) -> str:
    """Apply every ``(old, new)`` pair from ``replace_map`` to ``value``."""
    new = value
    for old, replacement in replace_map.items():
        if old in new:
            new = new.replace(old, replacement)
    return new


#: Maximum recursion depth for :func:`_walk_node`. Protects against
#: pathological nesting in attacker-controlled metadata.
_MAX_WALK_DEPTH: int = 64


def _walk_node(
    node: Any,
    path: tuple[str, ...],
    replace_map: Mapping[str, str],
    protected: frozenset[tuple[str, ...]],
    state: dict[str, int],
    *,
    depth: int = 0,
) -> Any:
    """Recursively walk a JSON-like node and apply replacements in place.

    Args:
        node: Current node in the JSON tree.
        path: Tuple of keys/indices leading to this node.
        replace_map: Substring replacements to apply.
        protected: Set of parsed path patterns to skip.
        state: Mutable dict with ``"counter"`` tracking modified strings.
        depth: Current recursion depth (for stack overflow protection).

    Returns:
        The (possibly modified) node.

    Raises:
        PatchError: If recursion depth exceeds ``_MAX_WALK_DEPTH``.

    """
    if depth > _MAX_WALK_DEPTH:
        raise PatchError(
            f"replace_outer_uris recursion depth exceeds {_MAX_WALK_DEPTH}",
            primitive_name="patch",
        )
    if path in protected:
        return node
    if isinstance(node, dict):
        for k, v in node.items():
            node[k] = _walk_node(v, (*path, str(k)), replace_map, protected, state, depth=depth + 1)
        return node
    if isinstance(node, list):
        new_path = (*path, "*")
        for i, v in enumerate(node):
            node[i] = _walk_node(v, new_path, replace_map, protected, state, depth=depth + 1)
        return node
    if isinstance(node, str):
        new = _replace_in_string(node, replace_map)
        if new != node:
            state["counter"] += 1
        return new
    return node


def replace_outer_uris(
    obj: Any,
    replace_map: Mapping[str, str],
    *,
    protected_paths: frozenset[str] = PROTECTED_OUTER_PATHS,
    additional_protected_paths: frozenset[str] | None = None,
) -> int:
    """Recursively patch string values in a JSON-like object, in place.

    Walks the object tree and applies ``str.replace(old, new)`` for
    every entry of ``replace_map`` to every string value, skipping any
    path that matches ``protected_paths``. The object is mutated in
    place.

    Path syntax: each protected path is a dotted string. ``[*]`` matches
    any list index. Dict keys are matched literally. For example,
    ``"connectors[*].hints.xpath"`` matches ``obj["connectors"][i]["hints"]["xpath"]``
    for every ``i``.

    .. note::

       Keys containing a literal ``"."`` cannot be expressed in the
       dotted-path syntax and are therefore not protectable via
       ``protected_paths``. This is a known limitation.

    This helper is meant to be called from caller code that knows about
    the wrapper structure (e.g. SAS Viya transfer packages where the
    BIRD XML lives inside an encoded blob but ``connectors[].uri`` and
    ``connectors[].hints.orig-uri`` live in the outer JSON wrapper).
    Use it together with ``PatchConfig(scope='outer')`` or
    ``scope='all'``.

    Args:
        obj: JSON-like nested structure (dict, list, str, int, ...).
            Mutated in place. Non-string scalars are returned unchanged.
        replace_map: Mapping of ``old -> new`` substring replacements.
            Replacements are applied in iteration order.
        protected_paths: Dotted-path patterns that must NOT be patched.
            Defaults to :data:`PROTECTED_OUTER_PATHS`.
        additional_protected_paths: Extra patterns merged with
            ``protected_paths``. Provides an additive API so callers
            can extend the defaults without accidentally wiping them.

    Returns:
        Total number of string values that were modified.

    Examples:
        >>> wrapper = {"connectors": [{"uri": "library=CASUSER", "hints": {"xpath": "/foo/CASUSER"}}]}
        >>> replace_outer_uris(wrapper, {"CASUSER": "PUBLIC"})
        1
        >>> wrapper["connectors"][0]["uri"]
        'library=PUBLIC'
        >>> wrapper["connectors"][0]["hints"]["xpath"]
        '/foo/CASUSER'

    """
    if not replace_map:
        return 0

    # Use pre-parsed cache when defaults are unchanged
    if protected_paths is PROTECTED_OUTER_PATHS and not additional_protected_paths:
        parsed = _PROTECTED_OUTER_PATHS_PARSED
    else:
        all_paths = protected_paths
        if additional_protected_paths:
            all_paths = protected_paths | additional_protected_paths
        parsed = frozenset(_parse_path_pattern(p) for p in all_paths)
    state = {"counter": 0}
    _walk_node(obj, (), replace_map, parsed, state)
    return state["counter"]


@dataclass(slots=True)
class _ChainContext:
    """Internal state kept during a forward->backward round-trip.

    Stores JSON envelopes extracted during forward for lossless
    restoration during backward.
    """

    json_envelopes: dict[str, Any] = field(default_factory=dict)


def _auto_reverse(forward: tuple[PrimitiveConfig, ...]) -> tuple[PrimitiveConfig, ...]:
    """Generate backward chain by reversing forward primitives.

    Args:
        forward: Forward primitive chain.

    Returns:
        Reversed backward chain with swapped options.

    Raises:
        TransformConfigError: If a primitive cannot be auto-reversed.

    """
    backward: list[PrimitiveConfig] = []

    for prim in reversed(forward):
        match prim.name:
            case "base64":
                backward.append(PrimitiveConfig(name="base64"))
            case "bytes":
                backward.append(PrimitiveConfig(name="bytes", options=dict(prim.options)))
            case "xml":
                backward.append(PrimitiveConfig(name="xml", options=dict(prim.options)))
            case "zlib":
                if prim.options.get("skip_bytes"):
                    raise TransformConfigError(
                        "zlib with skip_bytes requires explicit backward with prepend_bytes. "
                        "Auto-reverse cannot recover the skipped header bytes."
                    )
                backward.append(PrimitiveConfig(name="zlib"))
            case "json":
                opts: dict[str, Any] = {}
                if extract := prim.options.get("extract"):
                    opts["wrap"] = extract
                backward.append(PrimitiveConfig(name="json", options=opts))
            case _:
                raise TransformConfigError(f"Cannot auto-reverse primitive: {prim.name!r}")

    return tuple(backward)


def _has_forward_only(forward: tuple[PrimitiveConfig, ...]) -> bool:
    """Return True if any forward primitive is forward-only (lossy extractor).

    Forward-only primitives (see
    :data:`~kstlib.transform.validators.FORWARD_ONLY_PRIMITIVES`) have no
    backward implementation, so a chain that contains one cannot be
    auto-reversed and is treated as forward-only.

    Args:
        forward: Forward primitive chain.

    Returns:
        True if at least one primitive is forward-only.

    """
    return any(prim.name in FORWARD_ONLY_PRIMITIVES for prim in forward)


def _resolve_preset(
    chain_config: TransformChainConfig,
    all_chains: dict[str, TransformChainConfig],
) -> TransformChainConfig:
    """Resolve preset inheritance, returning a standalone chain config.

    Args:
        chain_config: Chain config with preset reference.
        all_chains: All available chain configs.

    Returns:
        New TransformChainConfig with forward/backward from preset and
        patch/composed_patch from child.

    """
    preset = all_chains[chain_config.preset]  # type: ignore[index]
    return TransformChainConfig(
        name=chain_config.name,
        forward=preset.forward,
        backward=preset.backward,
        patch=chain_config.patch,
        composed_patch=chain_config.composed_patch,
        preset=None,
    )


def _matches_filter(metadata: Mapping[str, Any], filter_config: FilterConfig) -> bool:
    """Check if object metadata matches a FilterConfig.

    All fields are ANDed: an object matches only if every non-wildcard
    field of the filter matches the corresponding metadata key.

    Args:
        metadata: Object metadata dict (typically with ``content_type``
            and ``name`` keys). Missing keys default to empty string.
        filter_config: Filter to evaluate.

    Returns:
        True if metadata matches the filter, False otherwise.

    Examples:
        >>> _matches_filter({"content_type": "report", "name": "R220_X"},
        ...                 FilterConfig(content_type="report", name="R220_*"))
        True
        >>> _matches_filter({"content_type": "folder", "name": "R220_X"},
        ...                 FilterConfig(content_type="report"))
        False

    """
    content_type = str(metadata.get("content_type", ""))
    name = str(metadata.get("name", ""))

    if filter_config.content_type not in ("*", content_type):
        return False

    return filter_config.name == "*" or fnmatch.fnmatchcase(name, filter_config.name)


def _resolve_variables(
    args: dict[str, Any],
    context: Mapping[str, Any],
) -> dict[str, Any]:
    """Replace {{variable}} patterns in args values from context.

    Args:
        args: Arguments dict with possible {{variable}} references.
        context: Variable store for resolution.

    Returns:
        New dict with variables resolved.

    Raises:
        TransformChainError: If variable not found in context.

    """
    resolved: dict[str, Any] = {}
    total_refs = 0

    for key, raw_value in args.items():
        result_value = raw_value
        if isinstance(result_value, str) and "{{" in result_value:
            matches = VARIABLE_PATTERN.findall(result_value)
            total_refs += len(matches)
            if total_refs > MAX_VARIABLE_REFS:
                raise TransformChainError(f"Too many variable references ({total_refs} > {MAX_VARIABLE_REFS})")
            # Validate all variables exist before substituting
            for var_name in matches:
                if var_name not in context:
                    raise TransformChainError(f"Variable '{{{{{var_name}}}}}' not found in context")

            # Single-pass substitution via re.sub callback
            def _replace_var(m: Any) -> str:
                return str(context[m.group(1)])

            result_value = VARIABLE_PATTERN.sub(_replace_var, result_value)
        resolved[key] = result_value

    return resolved


class TransformChain:
    """Execute a chain of transform primitives with optional patching.

    .. warning::

       ``TransformChain`` instances are **not reentrant**. Do not call
       ``transform()`` concurrently from multiple threads on the same
       instance. Each call resets internal state (``_chain_context``).
       Create one instance per thread if concurrent execution is needed.

    Args:
        config: Resolved chain configuration (no preset references).
        context: Optional external context for {{variable}} resolution.

    Examples:
        >>> from kstlib.transform.config import PrimitiveConfig, TransformChainConfig
        >>> chain = TransformChain(TransformChainConfig(
        ...     name="test",
        ...     forward=(PrimitiveConfig(name="base64"),),
        ... ))
        >>> chain.forward("SGVsbG8=")
        b'Hello'

    """

    def __init__(
        self,
        config: TransformChainConfig,
        *,
        context: Mapping[str, Any] | None = None,
        transform_config: TransformConfig | None = None,
        allowed_modules: frozenset[str] | None = None,
    ) -> None:
        """Initialize TransformChain.

        Args:
            config: Resolved chain configuration.
            context: External context for variable resolution.
            transform_config: Top-level config used to resolve chain
                references in ``composed_patch``. Required when
                ``config.composed_patch`` is set.
            allowed_modules: Whitelist of allowed callable module
                prefixes. When ``None`` (direct construction without
                ``from_config``), any callable patch is rejected
                (fail-closed). Pass an explicit frozenset to allow
                specific modules.

        Raises:
            TransformConfigError: If ``composed_patch`` is set but
                ``transform_config`` was not provided.

        """
        self._config = config
        self._context = context or {}
        self._transform_config = transform_config
        self._allowed_modules = allowed_modules
        self._chain_context = _ChainContext()
        self._callable_lock = threading.Lock()

        if config.composed_patch is not None and transform_config is None:
            raise TransformConfigError(
                f"Chain '{config.name}': composed_patch requires a transform_config "
                f"to resolve chain references. Use TransformChain.from_config()."
            )

        # Resolve backward if not explicit. Forward-only chains (lossy
        # extractors like split) have no backward path: the extraction is
        # terminal, so auto-reverse is skipped and backward is rejected.
        self._forward_only = False
        self._backward: tuple[PrimitiveConfig, ...]
        if config.backward is None:
            if _has_forward_only(config.forward):
                self._forward_only = True
                self._backward = ()
            else:
                self._backward = _auto_reverse(config.forward)
        else:
            self._backward = config.backward

        log.debug(
            "TransformChain '%s': %d forward, %d backward, patch=%s, composed=%s, forward_only=%s",
            config.name,
            len(config.forward),
            len(self._backward),
            "yes" if config.patch else "no",
            "yes" if config.composed_patch else "no",
            self._forward_only,
        )

    @classmethod
    def from_config(
        cls,
        name: str,
        transform_config: TransformConfig,
        *,
        context: Mapping[str, Any] | None = None,
    ) -> TransformChain:
        """Create a TransformChain from a named config entry.

        Resolves presets and returns a ready-to-use chain.

        Args:
            name: Chain name to look up in transform_config.
            transform_config: Top-level TransformConfig.
            context: External context for variable resolution.

        Returns:
            Configured TransformChain.

        Raises:
            TransformChainError: If chain name not found.

        """
        if name not in transform_config.chains:
            available = sorted(transform_config.chains)
            raise TransformChainError(
                f"Chain '{name}' not found. Available: {available}",
                chain_name=name,
            )

        chain_config = transform_config.chains[name]

        # Resolve preset if needed
        if chain_config.preset is not None:
            chain_config = _resolve_preset(chain_config, transform_config.chains)

        return cls(
            chain_config,
            context=context,
            transform_config=transform_config,
            allowed_modules=transform_config.allowed_callable_modules,
        )

    def forward(self, data: Any) -> Any:
        """Apply forward primitives in order.

        Args:
            data: Input data (typically base64 string).

        Returns:
            Decoded/parsed data ready for patching.

        Raises:
            TransformChainError: If any primitive fails.

        """
        self._chain_context = _ChainContext()
        current = data

        for i, prim in enumerate(self._config.forward):
            # Per-primitive trace (firehose-level detail). Sizes / timings
            # are intentionally not measured here : data may be a non-sized
            # object (Element tree) and computing len() defensively across
            # types would add complexity for little diagnostic value.
            log_trace(
                log,
                "Chain '%s' forward[%d]: %s",
                self._config.name,
                i,
                prim.name,
            )

            # Auto-coerce bytes -> str if needed
            if i > 0 and isinstance(current, bytes):
                prev_name = self._config.forward[i - 1].name
                if (prev_name, prim.name) in _AUTO_COERCE_PAIRS:
                    current = current.decode("utf-8")

            func = FORWARD_DISPATCH[prim.name]

            if prim.name == "json":
                # json_parse returns (value, envelope)
                value, envelope = func(current, prim)
                extract_path = prim.options.get("extract")
                if extract_path and envelope is not None:
                    self._chain_context.json_envelopes[extract_path] = envelope
                current = value
            else:
                current = func(current, prim)

        return current

    def backward(self, data: Any) -> Any:
        """Apply backward primitives in order.

        Uses stored envelopes from forward for lossless JSON restoration.

        Args:
            data: Data to re-encode (typically patched XML string or Element).

        Returns:
            Re-encoded data (same format as original input).

        Raises:
            TransformConfigError: If the chain is forward-only (lossy
                extractor) and therefore has no backward path.
            TransformChainError: If any primitive fails.

        """
        if self._forward_only:
            raise TransformConfigError(
                f"Chain '{self._config.name}' is forward-only (lossy extractor); backward is not available"
            )

        current = data

        for i, prim in enumerate(self._backward):
            log_trace(
                log,
                "Chain '%s' backward[%d]: %s",
                self._config.name,
                i,
                prim.name,
            )

            func = BACKWARD_DISPATCH[prim.name]

            if prim.name == "json":
                wrap_path = prim.options.get("wrap")
                envelope = self._chain_context.json_envelopes.get(wrap_path or "")
                current = json_serialize(current, prim, envelope=envelope)
            elif prim.name in ("zlib", "base64", "bytes"):
                # Auto-coerce str -> bytes if needed
                if isinstance(current, str) and prim.name in ("zlib", "bytes"):
                    current = current.encode("utf-8")
                current = func(current, prim)
            else:
                current = func(current, prim)

        return current

    def patch(
        self,
        data: Any,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> Any:
        """Apply patch to decoded data.

        If the chain has an inline ``patch``, applies it directly.
        If the chain has a ``composed_patch``, applies the global
        patches then the targeted patches whose filter matches
        ``metadata`` (in declaration order, last applied wins).

        Args:
            data: Decoded data from forward.
            metadata: Object metadata. Used for filter matching in
                composed patches (typical keys: ``content_type``,
                ``name``). May also carry ``"outer"`` referencing the
                JSON wrapper to mutate when the patch declares
                ``scope: outer`` or ``scope: all``.

        Returns:
            Patched data.

        Raises:
            PatchError: If patching fails.
            CallableError: If a callable patch raises.
            CallableImportError: If a callable cannot be imported.

        """
        if self._config.composed_patch is not None:
            return self._apply_composed_patch(data, metadata or {})

        if self._config.patch is None:
            return data

        return self._apply_patch_config(data, self._config.patch, metadata)

    def transform(
        self,
        data: Any,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> Any:
        """Full round-trip: forward -> patch -> backward.

        This is the main entry point for most use cases. Forward-only
        chains (lossy extractors like split) skip the backward leg: the
        patched, extracted value is returned as-is.

        Args:
            data: Raw input data.
            metadata: Object metadata used for filter matching in
                composed patches. Ignored for inline ``patch``.

        Returns:
            Transformed data (same format as input).

        Raises:
            TransformChainError: If any stage fails.

        """
        import time

        log.debug("Chain '%s': starting transform", self._config.name)
        start = time.monotonic()
        decoded = self.forward(data)
        patched = self.patch(decoded, metadata=metadata)
        # Forward-only chains have no backward leg: the patched (extracted)
        # value is terminal. patch still applies, so a declared patch is
        # never silently dropped.
        result = patched if self._forward_only else self.backward(patched)
        log.debug(
            "Chain '%s': transform complete (took=%.3fs)",
            self._config.name,
            time.monotonic() - start,
        )
        return result

    def _apply_patch_config(
        self,
        data: Any,
        patch_config: PatchConfig,
        metadata: Mapping[str, Any] | None = None,
    ) -> Any:
        """Dispatch a single PatchConfig to replace or callable.

        Args:
            data: Data to patch.
            patch_config: Patch configuration to apply.
            metadata: Object metadata. Required (with key ``"outer"``)
                when ``patch_config.scope`` is ``"outer"`` or ``"all"``.

        Returns:
            Patched data (or unchanged if patch is a no-op).

        """
        if patch_config.replace is not None:
            return self._apply_replace_with_scope(data, patch_config, metadata)
        if patch_config.callable is not None:
            return self._apply_callable(data, patch_config)
        return data

    def _apply_composed_patch(
        self,
        data: Any,
        metadata: Mapping[str, Any],
    ) -> Any:
        """Apply global_patches then matching targeted_patches in order.

        When the decoded data is an XML ``Element``, the method
        serializes it to a string once before the patch loop and
        re-parses once after all patches have been applied. This avoids
        K full XML round-trips when K patches match (performance fix).

        Args:
            data: Decoded data to patch.
            metadata: Object metadata used for filter evaluation. Also
                threaded to ``_apply_patch_config`` for ``scope: outer``
                and ``scope: all`` patches that need ``metadata['outer']``.

        Returns:
            Patched data after the full cascade.

        """
        assert self._config.composed_patch is not None
        assert self._transform_config is not None  # checked in __init__
        composed: ComposedPatchConfig = self._config.composed_patch
        all_chains = self._transform_config.chains

        # Optimization: serialize Element to string once before the
        # patch loop so that N replace patches only do string ops.
        # Re-parse to Element once at the end.
        was_element = isinstance(data, Element)
        result: Any = xml_serialize(data, _DEFAULT_XML_PRIM) if was_element else data

        # 1. global_patches - always applied
        for ref_name in composed.global_patches:
            ref_chain = all_chains[ref_name]
            if ref_chain.patch is not None:
                log.debug(
                    "Chain '%s': applying global patch '%s'",
                    self._config.name,
                    ref_name,
                )
                result = self._apply_patch_config(result, ref_chain.patch, metadata)

        # 2. targeted_patches - applied if filter matches
        for targeted in composed.targeted_patches:
            if not _matches_filter(metadata, targeted.filter):
                continue
            for ref_name in targeted.patches:
                ref_chain = all_chains[ref_name]
                if ref_chain.patch is not None:
                    log.debug(
                        "Chain '%s': applying targeted patch '%s' (matched filter)",
                        self._config.name,
                        ref_name,
                    )
                    result = self._apply_patch_config(result, ref_chain.patch, metadata)

        # Re-parse to Element if the original data was Element and
        # the result is still a string (callable patches may return
        # a different type).
        if was_element and isinstance(result, str):
            result = xml_parse(result, _DEFAULT_XML_PRIM)

        return result

    def _apply_replace_with_scope(
        self,
        data: Any,
        patch: PatchConfig,
        metadata: Mapping[str, Any] | None,
    ) -> Any:
        """Apply ``patch.replace`` according to ``patch.scope``.

        - ``scope='blob'``: patch the decoded data only (str or Element).
        - ``scope='outer'``: patch ``metadata['outer']`` in place via
          :func:`replace_outer_uris`. Data flows through unchanged.
        - ``scope='all'``: do both, outer first then blob.

        Args:
            data: Decoded data from forward (only relevant for blob/all).
            patch: PatchConfig with a non-None ``replace`` mapping.
            metadata: Object metadata. Must contain ``"outer"`` when
                scope is ``outer`` or ``all``.

        Returns:
            Patched data (unchanged if scope is ``outer`` only).

        Raises:
            PatchError: If scope requires ``metadata['outer']`` but it
                is missing, or if data type is unsupported for ``blob``
                / ``all`` scopes.

        """
        assert patch.replace is not None
        scope = patch.scope

        if scope in ("outer", "all"):
            outer = (metadata or {}).get("outer")
            if outer is None:
                raise PatchError(
                    f"PatchConfig with scope={scope!r} requires "
                    f"metadata['outer'] to be set on chain.transform() "
                    f"or chain.patch()",
                    primitive_name="patch",
                    chain_name=self._config.name,
                )
            replace_outer_uris(outer, patch.replace)

        if scope in ("blob", "all"):
            return self._apply_replace_to_data(data, patch.replace)

        # scope == "outer": data is unchanged, side effect on outer only.
        return data

    def _apply_replace_to_data(
        self,
        data: Any,
        replace_map: Mapping[str, str],
    ) -> Any:
        """Apply string replacement to decoded blob data (str or Element)."""
        if isinstance(data, str):
            return _replace_in_string(data, replace_map)

        if isinstance(data, Element):
            xml_str = xml_serialize(data, _DEFAULT_XML_PRIM)
            xml_str = _replace_in_string(xml_str, replace_map)
            return xml_parse(xml_str, _DEFAULT_XML_PRIM)

        raise PatchError(
            f"Cannot apply replace to {type(data).__name__}; expected str or Element",
            primitive_name="patch",
            chain_name=self._config.name,
        )

    def _apply_callable(self, data: Any, patch: PatchConfig) -> Any:
        """Import and call a patch function with a hard wall-clock timeout.

        Security enforcement (defense-in-depth):

        1. If ``allowed_modules`` was not provided at construction time
           (direct ``TransformChain(...)`` without ``from_config``), ALL
           callable patches are rejected (fail-closed).
        2. The module is checked against :data:`DANGEROUS_MODULES`
           regardless of the whitelist.
        3. The module must match the ``allowed_modules`` whitelist.
        """
        assert patch.callable is not None
        target = patch.callable

        module_path, _, func_name = target.rpartition(":")
        if not module_path or not func_name:
            raise CallableImportError(target, chain_name=self._config.name)

        # Fail-closed: no whitelist means no callable allowed
        if self._allowed_modules is None:
            raise CallableError(
                target,
                "Callable patches require allowed_callable_modules config. "
                "Use TransformChain.from_config() or pass allowed_modules explicitly.",
                chain_name=self._config.name,
            )

        # Hardcoded blacklist: always rejected
        root_module = module_path.split(".")[0]
        if root_module in DANGEROUS_MODULES:
            raise CallableError(
                target,
                f"Module '{module_path}' is in DANGEROUS_MODULES blacklist and cannot be used as a callable patch",
                chain_name=self._config.name,
            )

        # Whitelist check (same logic as validate_callable_module)
        if not any(
            module_path == allowed or module_path.startswith(f"{allowed}.") for allowed in self._allowed_modules
        ):
            raise CallableError(
                target,
                f"Module '{module_path}' is not in allowed_callable_modules",
                chain_name=self._config.name,
            )

        try:
            module = importlib.import_module(module_path)
            func = getattr(module, func_name)
        except (ImportError, AttributeError) as exc:
            raise CallableImportError(target, chain_name=self._config.name) from exc

        # Post-import check: verify the resolved module matches the
        # expected path. Protects against sys.modules tampering where
        # a malicious entry could redirect an import to a different module.
        actual_name = getattr(module, "__name__", "")
        if actual_name != module_path:
            raise CallableError(
                target,
                f"Module identity mismatch: expected '{module_path}', "
                f"got '{actual_name}' (possible sys.modules tampering)",
                chain_name=self._config.name,
            )

        resolved_args = _resolve_variables(patch.args, self._context)
        return self._run_callable_with_timeout(func, data, resolved_args, target)

    def _run_callable_with_timeout(
        self,
        fn: Callable[..., Any],
        data: Any,
        resolved_args: dict[str, Any],
        target_label: str,
    ) -> Any:
        """Run a callable in a daemon thread with a hard wall-clock timeout.

        The timeout enforcement uses ``threading.Thread(daemon=True)`` plus
        ``Thread.join(timeout)``. This is the only practical way to add
        wall-clock cancellation to arbitrary Python callables without
        relying on ``signal`` (main-thread only) or ``multiprocessing``
        (too heavy and incompatible with shared in-memory state).

        The timeout value is :data:`kstlib.transform.validators.CALLABLE_TIMEOUT`
        (30 seconds by default). Tests can patch the module-level constant
        with ``monkeypatch`` to use a smaller value.

        Limitations (honest disclosure):

        1. **Orphaned threads on timeout** keep running until natural
           completion or process exit. Python has no public API to kill
           a thread cleanly. The worker is marked ``daemon=True`` so it
           does not block process exit, but it still consumes resources
           (CPU, memory, file handles) until it finishes on its own.
        2. **Blocking syscalls cannot be interrupted** mid-flight. If the
           callable is stuck in ``time.sleep``, ``socket.recv``, a long
           CPython bytecode loop without GIL release, or any blocking
           OS call, the timeout fires (the join returns) but the worker
           keeps running. The timeout is wall-clock only; it does not
           cancel the work itself.
        3. **Resources held by a timed-out callable may leak** until the
           process exits. Open files, network connections, and locks
           held by the orphaned thread will not be released early.
        4. **Mutable shared state can race**: a timed-out callable that
           kept writing to shared structures may continue mutating them
           after the timeout error has been raised in the caller.

        Use callables that are short, idempotent, side-effect-free, and
        do not hold external resources. For long-running or risky
        operations, prefer running them out-of-process via a pipeline
        shell step with its own timeout supervisor.

        Args:
            fn: Resolved callable (already imported).
            data: First positional argument passed to ``fn``.
            resolved_args: Keyword arguments passed to ``fn`` after
                ``{{variable}}`` resolution.
            target_label: ``module:function`` string used in error
                messages and the worker thread name.

        Returns:
            The callable's return value.

        Raises:
            CallableError: If the callable raises an exception or if it
                does not complete within ``CALLABLE_TIMEOUT`` seconds.

        """
        # Reject reentrant calls: if a previous callable timed out and
        # its orphan thread is still accessing _chain_context, running
        # another callable risks data races.
        if not self._callable_lock.acquire(blocking=False):
            raise CallableError(
                target_label,
                "Reentrant callable call rejected (previous call still in progress)",
                chain_name=self._config.name,
            )
        try:
            result_box: list[Any] = []
            error_box: list[BaseException] = []

            def _worker() -> None:
                try:
                    result_box.append(fn(data, **resolved_args))
                except BaseException as exc:
                    error_box.append(exc)

            worker = threading.Thread(
                target=_worker,
                name=f"transform-callable-{target_label}",
                daemon=True,
            )
            worker.start()
            worker.join(CALLABLE_TIMEOUT)

            if worker.is_alive():
                # Timed out: the worker will keep running in the background
                # until it terminates on its own (or until process exit, since
                # the thread is marked daemon=True).
                log.warning(
                    "Callable '%s' timed out after %.1fs (orphaned thread continues)",
                    target_label,
                    CALLABLE_TIMEOUT,
                )
                raise CallableError(
                    target_label,
                    f"timed out after {CALLABLE_TIMEOUT}s",
                    chain_name=self._config.name,
                )

            if error_box:
                raise CallableError(
                    target_label,
                    str(error_box[0]),
                    chain_name=self._config.name,
                ) from error_box[0]
        finally:
            self._callable_lock.release()

        return result_box[0]


# ============================================================================
# Module-level convenience function
# ============================================================================


def transform(
    data: Any,
    chain_name: str,
    config: TransformConfig | None = None,
    context: dict[str, Any] | None = None,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> Any:
    """Apply a named transform chain to data.

    Convenience function for use in CallableStep pipelines.
    Loads config from kstlib.conf.yml if not provided.

    Args:
        data: Raw input data.
        chain_name: Name of the transform chain to apply.
        config: Transform config (loads from kstlib.conf.yml if None).
        context: Variables for {{variable}} resolution in callable args.
        metadata: Object metadata for filter matching in composed patches
            (typical keys: ``content_type``, ``name``).

    Returns:
        Transformed data.

    Examples:
        >>> transform("SGVsbG8=", "my_chain")  # doctest: +SKIP

    """
    if config is None:
        config = load_transform_config()

    chain = TransformChain.from_config(chain_name, config, context=context)
    return chain.transform(data, metadata=metadata)


__all__ = [
    "DANGEROUS_MODULES",
    "PROTECTED_OUTER_PATHS",
    "TransformChain",
    "replace_outer_uris",
    "transform",
]
