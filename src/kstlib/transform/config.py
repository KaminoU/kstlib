"""Configuration models for kstlib.transform module.

Frozen dataclasses for transform chain configuration, parsed from
the ``transforms:`` section of ``kstlib.conf.yml``.

YAML schema::

    transforms:
      security:
        allowed_callable_modules:    # Whitelist (default: empty)
          - myproject.viya
      chains:
        my_chain:
          forward:                   # Required (or preset/patch must be set)
            - base64
            - zlib:
                skip_bytes: 3
            - json:
                extract: "path.to.field"
            - xml
          backward:                  # Optional (auto-reversed if absent)
            - xml
            - json:
                wrap: "path.to.field"
            - zlib:
                prepend_bytes: "4d1504"
            - base64
          preset: other_chain        # Mutually exclusive with forward
          patch:                     # Mutually exclusive with composed_patch
            scope: blob              # blob | outer | all (default: blob)
            replace:                 # Mutually exclusive with callable
              "old": "new"
            callable: mod.path:fn    # Mutually exclusive with replace
            args:
              key: "{{var}}"

        # Composed patches: reference other chains and apply their patches
        # with optional filters. Mutually exclusive with patch:.
        composed_chain:
          preset: other_chain
          global_patches:            # Preset names, applied to all objects
            - remap_host
          targeted_patches:          # Conditional patches (filter + patches)
            - filter:
                content_type: report
                name: "R220_*"
              patches:
                - remap_caslib_r220
            - filter:
                name: "*"            # Fallback for other objects
              patches:
                - remap_caslib_global
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from kstlib.transform.exceptions import TransformConfigError
from kstlib.transform.validators import (
    MAX_ARG_KEY_LENGTH,
    MAX_CALLABLE_ARGS,
    MAX_CHAIN_PRIMITIVES,
    MAX_ENCODING_LENGTH,
    MAX_GLOBAL_PATCHES,
    MAX_MAPPING_ENTRIES,
    MAX_MAPPING_STRING_LENGTH,
    MAX_NAMED_CHAINS,
    MAX_PATCHES_PER_TARGETED,
    MAX_PREFIX_LENGTH,
    MAX_PRIMITIVE_OPTIONS,
    MAX_SKIP_BYTES,
    MAX_TARGETED_PATCHES,
    ZLIB_LEVEL_MAX,
    ZLIB_LEVEL_MIN,
    validate_callable_module,
    validate_callable_target,
    validate_chain_name,
    validate_dot_path,
    validate_filter_type,
    validate_glob_pattern,
    validate_hex_string,
    validate_primitive_name,
)

log = logging.getLogger(__name__)


# ============================================================================
# Dataclasses
# ============================================================================


@dataclass(frozen=True, slots=True)
class PrimitiveConfig:
    """Configuration for a single transform primitive.

    Attributes:
        name: Primitive name (base64, zlib, json, xml, bytes).
        options: Primitive-specific options dict.

    Examples:
        >>> PrimitiveConfig(name="base64")
        PrimitiveConfig(name='base64', options={})
        >>> PrimitiveConfig(name="zlib", options={"skip_bytes": 3})
        PrimitiveConfig(name='zlib', options={'skip_bytes': 3})

    """

    name: str
    options: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate primitive configuration.

        Raises:
            TransformConfigError: If configuration is invalid.

        """
        validate_primitive_name(self.name)

        if len(self.options) > MAX_PRIMITIVE_OPTIONS:
            raise TransformConfigError(
                f"Primitive '{self.name}' has too many options: {len(self.options)} > {MAX_PRIMITIVE_OPTIONS}"
            )

        if self.name == "zlib":
            self._validate_zlib_options()
        elif self.name == "json":
            self._validate_json_options()
        elif self.name in ("base64", "bytes"):
            self._validate_encoding_option()

    def _validate_bool_option(self, key: str) -> None:
        """Validate that an option, if present, is a strict bool.

        Helper used by zlib/json/base64 validators for bool flags.
        """
        value = self.options.get(key)
        if value is not None and not isinstance(value, bool):
            raise TransformConfigError(f"{self.name} {key} must be bool, got: {type(value).__name__}")

    def _validate_string_option_with_max_length(
        self,
        key: str,
        max_length: int,
    ) -> None:
        """Validate that an option, if present, is a string within length.

        Helper used by base64 strip_prefix and prefix validators.
        """
        value = self.options.get(key)
        if value is None:
            return
        if not isinstance(value, str):
            raise TransformConfigError(f"{self.name} {key} must be string, got: {type(value).__name__}")
        if len(value) > max_length:
            raise TransformConfigError(f"{self.name} {key} too long: {len(value)} > {max_length}")

    def _validate_zlib_options(self) -> None:
        """Validate zlib-specific options."""
        skip = self.options.get("skip_bytes")
        if skip is not None and (not isinstance(skip, int) or skip < 0 or skip > MAX_SKIP_BYTES):
            raise TransformConfigError(f"zlib skip_bytes must be int 0-{MAX_SKIP_BYTES}, got: {skip!r}")

        prepend = self.options.get("prepend_bytes")
        if prepend is not None:
            if not isinstance(prepend, str):
                raise TransformConfigError(f"zlib prepend_bytes must be hex string, got: {type(prepend).__name__}")
            validate_hex_string(prepend, label="zlib prepend_bytes")

        level = self.options.get("level")
        if level is not None:
            # Reject bools explicitly: bool is a subclass of int in Python.
            if not isinstance(level, int) or isinstance(level, bool):
                raise TransformConfigError(f"zlib level must be int, got: {type(level).__name__}")
            if level < ZLIB_LEVEL_MIN or level > ZLIB_LEVEL_MAX:
                raise TransformConfigError(
                    f"zlib level must be in range [{ZLIB_LEVEL_MIN}, {ZLIB_LEVEL_MAX}], got: {level}"
                )

    def _validate_json_options(self) -> None:
        """Validate json-specific options."""
        extract = self.options.get("extract")
        if extract is not None:
            if not isinstance(extract, str):
                raise TransformConfigError(f"json extract must be string, got: {type(extract).__name__}")
            validate_dot_path(extract, label="json extract")

        wrap = self.options.get("wrap")
        if wrap is not None:
            if not isinstance(wrap, str):
                raise TransformConfigError(f"json wrap must be string, got: {type(wrap).__name__}")
            validate_dot_path(wrap, label="json wrap")

        self._validate_bool_option("minify")
        self._validate_bool_option("ensure_ascii")

    def _validate_encoding_option(self) -> None:
        """Validate encoding option for base64/bytes primitives."""
        encoding = self.options.get("encoding")
        if encoding is not None:
            if not isinstance(encoding, str):
                raise TransformConfigError(f"{self.name} encoding must be string, got: {type(encoding).__name__}")
            if len(encoding) > MAX_ENCODING_LENGTH:
                raise TransformConfigError(f"{self.name} encoding too long: {len(encoding)} > {MAX_ENCODING_LENGTH}")

        # base64-specific options (do not apply to bytes primitive)
        if self.name == "base64":
            self._validate_bool_option("strict")
            self._validate_string_option_with_max_length("strip_prefix", MAX_PREFIX_LENGTH)
            self._validate_string_option_with_max_length("prefix", MAX_PREFIX_LENGTH)


#: Allowed values for PatchConfig.scope.
PATCH_SCOPE_VALUES: frozenset[str] = frozenset({"blob", "outer", "all"})


@dataclass(frozen=True, slots=True)
class PatchConfig:
    """Configuration for the patch stage between forward and backward.

    A patch operates either as a string-replacement mapping (``replace``)
    or as a Python callable (``callable``). The two modes are mutually
    exclusive.

    The ``scope`` field controls WHERE replacements apply:

    - ``"blob"`` (default): patch the data decoded by the forward chain
      (e.g. the BIRD XML extracted from a SAS Viya report blob).
      Preserves the historical behavior.
    - ``"outer"``: patch the wrapper dict passed in
      ``metadata["outer"]`` to ``chain.transform()``. The wrapper is
      mutated in place; the blob itself is not modified beyond the
      normal forward+backward round-trip. Useful for fields like
      ``connectors[].uri`` that live outside the encoded blob.
    - ``"all"``: do both, blob first then outer.

    Attributes:
        replace: String replacement mapping ``{old: new}``. Mutually
            exclusive with ``callable``.
        scope: Where to apply the replace mapping. One of
            ``"blob"`` (default), ``"outer"``, ``"all"``.
        callable: Import target ``module.path:function`` for complex
            patch logic. Mutually exclusive with ``replace``.
        args: Keyword arguments passed to the callable as ``**kwargs``.
        mapping: **Deprecated alias for ``replace``**. Setting it
            triggers a ``DeprecationWarning`` and is silently copied
            to ``replace``. Will be removed in a future version. Do
            not set both ``mapping`` and ``replace`` (raises).

    Examples:
        >>> PatchConfig(replace={"old": "new"})
        PatchConfig(replace={'old': 'new'}, scope='blob', callable=None, args={}, mapping=None)
        >>> PatchConfig(replace={"a": "b"}, scope="all")
        PatchConfig(replace={'a': 'b'}, scope='all', callable=None, args={}, mapping=None)

    """

    replace: dict[str, str] | None = None
    scope: Literal["blob", "outer", "all"] = "blob"
    callable: str | None = None
    args: dict[str, Any] = field(default_factory=dict)
    mapping: dict[str, str] | None = None  # DEPRECATED: use 'replace' instead

    def __post_init__(self) -> None:
        """Validate patch configuration.

        Raises:
            TransformConfigError: If configuration is invalid.

        """
        # Handle the deprecated 'mapping' alias: copy to 'replace' if
        # only 'mapping' is set, error if both are set (ambiguous).
        if self.mapping is not None:
            if self.replace is not None:
                raise TransformConfigError(
                    "PatchConfig: 'mapping' and 'replace' are both set. "
                    "'mapping' is the deprecated alias of 'replace' - use only one."
                )
            import warnings

            warnings.warn(
                "PatchConfig 'mapping' field is deprecated - use 'replace' instead. "
                "The behavior is identical; this is a pure rename.",
                DeprecationWarning,
                stacklevel=3,
            )
            # Frozen dataclass: use object.__setattr__ to copy the alias.
            object.__setattr__(self, "replace", self.mapping)

        if self.replace is not None and self.callable is not None:
            raise TransformConfigError("PatchConfig: 'replace' and 'callable' are mutually exclusive")

        self._validate_scope()
        self._validate_replace()
        self._validate_callable_and_args()

    def _validate_scope(self) -> None:
        """Validate scope value (must be one of blob/outer/all)."""
        if self.scope not in PATCH_SCOPE_VALUES:
            raise TransformConfigError(
                f"PatchConfig scope must be one of {sorted(PATCH_SCOPE_VALUES)}, got: {self.scope!r}"
            )

    def _validate_replace(self) -> None:
        """Validate replace entries (length and key non-emptiness)."""
        if self.replace is None:
            return
        if len(self.replace) > MAX_MAPPING_ENTRIES:
            raise TransformConfigError(
                f"PatchConfig replace has too many entries: {len(self.replace)} > {MAX_MAPPING_ENTRIES}"
            )
        for key, value in self.replace.items():
            if not key:
                raise TransformConfigError("PatchConfig replace key must not be empty")
            if len(key) > MAX_MAPPING_STRING_LENGTH:
                raise TransformConfigError(
                    f"PatchConfig replace key too long: {len(key)} > {MAX_MAPPING_STRING_LENGTH}"
                )
            if len(value) > MAX_MAPPING_STRING_LENGTH:
                raise TransformConfigError(
                    f"PatchConfig replace value too long: {len(value)} > {MAX_MAPPING_STRING_LENGTH}"
                )

    def _validate_callable_and_args(self) -> None:
        """Validate callable target and args."""
        if self.callable is not None:
            validate_callable_target(self.callable)
        if len(self.args) > MAX_CALLABLE_ARGS:
            raise TransformConfigError(f"PatchConfig args has too many entries: {len(self.args)} > {MAX_CALLABLE_ARGS}")
        for key in self.args:
            if len(key) > MAX_ARG_KEY_LENGTH:
                raise TransformConfigError(f"PatchConfig args key too long: {len(key)} > {MAX_ARG_KEY_LENGTH}")


@dataclass(frozen=True, slots=True)
class FilterConfig:
    """Filter used by TargetedPatchConfig to select matching objects.

    All fields are ANDed: an object matches only if every field matches.
    A value of ``"*"`` means "any value".

    Attributes:
        content_type: Object content type ("report", "folder", "file", or "*").
        name: fnmatch glob pattern on the object name (e.g. ``"R220_*"``).

    Examples:
        >>> FilterConfig(content_type="report", name="R220_*")
        FilterConfig(content_type='report', name='R220_*')
        >>> FilterConfig()
        FilterConfig(content_type='*', name='*')

    """

    content_type: str = "*"
    name: str = "*"

    def __post_init__(self) -> None:
        """Validate filter configuration.

        Raises:
            TransformConfigError: If configuration is invalid.

        """
        validate_filter_type(self.content_type)
        validate_glob_pattern(self.name, label="filter name")


@dataclass(frozen=True, slots=True)
class TargetedPatchConfig:
    """A filter plus a list of patch chain names to apply when it matches.

    Attributes:
        filter: Filter describing which objects this entry applies to.
        patches: Ordered tuple of chain names whose ``.patch`` is applied.

    Examples:
        >>> TargetedPatchConfig(
        ...     filter=FilterConfig(content_type="report", name="R220_*"),
        ...     patches=("remap_caslib_r220",),
        ... )
        TargetedPatchConfig(filter=FilterConfig(...), patches=('remap_caslib_r220',))

    """

    filter: FilterConfig
    patches: tuple[str, ...]

    def __post_init__(self) -> None:
        """Validate targeted patch configuration.

        Raises:
            TransformConfigError: If configuration is invalid.

        """
        if not self.patches:
            raise TransformConfigError("TargetedPatchConfig.patches must not be empty")
        if len(self.patches) > MAX_PATCHES_PER_TARGETED:
            raise TransformConfigError(
                f"TargetedPatchConfig has too many patches: {len(self.patches)} > {MAX_PATCHES_PER_TARGETED}"
            )
        for patch_name in self.patches:
            validate_chain_name(patch_name)


@dataclass(frozen=True, slots=True)
class ComposedPatchConfig:
    """Composition of global and targeted patch chain references.

    Execution order (per object):

    1. ``global_patches``: applied to every object, in declaration order.
    2. ``targeted_patches``: for each entry in declaration order, if the
       filter matches the object metadata, apply all its patches in order.

    **Last applied wins on conflict**, following kstlib cascade philosophy
    (``kwargs > user config > preset > defaults``). Ordering is by
    declaration, not by filter specificity. Order your targeted_patches
    from most general to most specific.

    Attributes:
        global_patches: Chain names applied to every object.
        targeted_patches: Conditional entries applied when their filter matches.

    Examples:
        >>> ComposedPatchConfig(
        ...     global_patches=("remap_host",),
        ...     targeted_patches=(
        ...         TargetedPatchConfig(
        ...             filter=FilterConfig(name="R220_*"),
        ...             patches=("remap_caslib_r220",),
        ...         ),
        ...     ),
        ... )
        ComposedPatchConfig(global_patches=('remap_host',), targeted_patches=(...))

    """

    global_patches: tuple[str, ...] = ()
    targeted_patches: tuple[TargetedPatchConfig, ...] = ()

    def __post_init__(self) -> None:
        """Validate composed patch configuration.

        Raises:
            TransformConfigError: If configuration is invalid.

        """
        if not self.global_patches and not self.targeted_patches:
            raise TransformConfigError(
                "ComposedPatchConfig must declare at least one global_patches or targeted_patches entry"
            )
        if len(self.global_patches) > MAX_GLOBAL_PATCHES:
            raise TransformConfigError(
                f"ComposedPatchConfig has too many global_patches: {len(self.global_patches)} > {MAX_GLOBAL_PATCHES}"
            )
        if len(self.targeted_patches) > MAX_TARGETED_PATCHES:
            raise TransformConfigError(
                f"ComposedPatchConfig has too many targeted_patches: "
                f"{len(self.targeted_patches)} > {MAX_TARGETED_PATCHES}"
            )
        for patch_name in self.global_patches:
            validate_chain_name(patch_name)


@dataclass(frozen=True, slots=True)
class TransformChainConfig:
    """Configuration for a named transform chain.

    A chain declares how to transform data. It must provide at least one of:

    - ``forward``: explicit forward primitive chain
    - ``preset``: inherit forward/backward from another chain
    - ``patch`` or ``composed_patch``: patch-only chain (no forward/backward).
      Such chains are meant to be referenced by a ``composed_patch`` of
      another chain, not instantiated directly.

    Attributes:
        name: Chain name (for logging and error messages).
        forward: Ordered tuple of forward primitives.
        backward: Ordered list of backward primitives (None = auto-reverse).
        patch: Patch configuration (None = no inline patching).
        composed_patch: Composed patches referencing other chains (None = absent).
        preset: Name of preset to inherit from (None = standalone).

    Examples:
        >>> TransformChainConfig(
        ...     name="decode",
        ...     forward=(PrimitiveConfig(name="base64"),),
        ... )
        TransformChainConfig(name='decode', forward=(...), backward=None, patch=None, composed_patch=None, preset=None)

    """

    name: str
    forward: tuple[PrimitiveConfig, ...] = ()
    backward: tuple[PrimitiveConfig, ...] | None = None
    patch: PatchConfig | None = None
    composed_patch: ComposedPatchConfig | None = None
    preset: str | None = None

    def __post_init__(self) -> None:
        """Validate chain configuration.

        Raises:
            TransformConfigError: If configuration is invalid.

        """
        validate_chain_name(self.name)

        # Preset and forward are mutually exclusive
        if self.preset is not None and self.forward:
            raise TransformConfigError(
                f"Chain '{self.name}': 'preset' and 'forward' are mutually exclusive. "
                f"A preset inherits forward/backward from the referenced chain."
            )

        # patch and composed_patch are mutually exclusive
        if self.patch is not None and self.composed_patch is not None:
            raise TransformConfigError(f"Chain '{self.name}': 'patch' and 'composed_patch' are mutually exclusive")

        # Must have forward, preset, patch, or composed_patch
        # (patch-only chains are allowed as reference targets for composed_patch).
        if self.preset is None and not self.forward and self.patch is None and self.composed_patch is None:
            raise TransformConfigError(
                f"Chain '{self.name}': must declare at least one of 'forward', 'preset', 'patch', or 'composed_patch'"
            )

        # Validate preset name
        if self.preset is not None:
            validate_chain_name(self.preset)

        # Validate chain lengths
        if len(self.forward) > MAX_CHAIN_PRIMITIVES:
            raise TransformConfigError(
                f"Chain '{self.name}': forward chain too long: {len(self.forward)} > {MAX_CHAIN_PRIMITIVES}"
            )
        if self.backward is not None and len(self.backward) > MAX_CHAIN_PRIMITIVES:
            raise TransformConfigError(
                f"Chain '{self.name}': backward chain too long: {len(self.backward)} > {MAX_CHAIN_PRIMITIVES}"
            )


@dataclass(frozen=True, slots=True)
class TransformConfig:
    """Top-level transform configuration from kstlib.conf.yml.

    Attributes:
        chains: Named transform chain configurations.
        allowed_callable_modules: Whitelist of allowed callable module prefixes.

    Examples:
        >>> TransformConfig(chains={"decode": TransformChainConfig(name="decode", forward=(PrimitiveConfig(name="base64"),))})
        TransformConfig(chains={...}, allowed_callable_modules=frozenset())

    """

    chains: dict[str, TransformChainConfig] = field(default_factory=dict)
    allowed_callable_modules: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        """Validate top-level configuration.

        Raises:
            TransformConfigError: If configuration is invalid.

        """
        if len(self.chains) > MAX_NAMED_CHAINS:
            raise TransformConfigError(f"Too many named chains: {len(self.chains)} > {MAX_NAMED_CHAINS}")

        for name, chain in self.chains.items():
            if chain.preset is not None:
                self._validate_preset_reference(name, chain.preset)
            if chain.patch and chain.patch.callable:
                validate_callable_module(
                    chain.patch.callable,
                    self.allowed_callable_modules,
                )
            if chain.composed_patch is not None:
                self._validate_composed_references(name, chain.composed_patch)

    def _validate_preset_reference(self, chain_name: str, preset: str) -> None:
        """Validate a single preset reference (existence + cycle detection).

        Args:
            chain_name: Name of the chain holding the preset reference.
            preset: Preset name to validate.

        Raises:
            TransformConfigError: If the preset reference is invalid.

        """
        if preset not in self.chains:
            raise TransformConfigError(f"Chain '{chain_name}' references unknown preset: '{preset}'")
        if preset == chain_name:
            raise TransformConfigError(f"Chain '{chain_name}' references itself as preset (circular)")
        target = self.chains[preset]
        if target.preset is not None:
            raise TransformConfigError(
                f"Chain '{chain_name}' preset '{preset}' itself has a preset "
                f"('{target.preset}'). Chained presets are not supported."
            )

    def _validate_composed_references(
        self,
        chain_name: str,
        composed: ComposedPatchConfig,
    ) -> None:
        """Validate that composed_patch references exist and are patch-only.

        Args:
            chain_name: Name of the parent chain (for error messages).
            composed: ComposedPatchConfig to validate.

        Raises:
            TransformConfigError: If a referenced chain is unknown, references
                a composed_patch itself, or has no patch to apply.

        """
        referenced: list[str] = list(composed.global_patches)
        for targeted in composed.targeted_patches:
            referenced.extend(targeted.patches)

        for ref_name in referenced:
            if ref_name not in self.chains:
                raise TransformConfigError(
                    f"Chain '{chain_name}' composed_patch references unknown chain: '{ref_name}'"
                )
            if ref_name == chain_name:
                raise TransformConfigError(f"Chain '{chain_name}' composed_patch references itself")
            target = self.chains[ref_name]
            if target.composed_patch is not None:
                raise TransformConfigError(
                    f"Chain '{chain_name}' composed_patch references "
                    f"'{ref_name}' which itself has a composed_patch. "
                    f"Nested composition is not supported."
                )
            if target.patch is None:
                raise TransformConfigError(
                    f"Chain '{chain_name}' composed_patch references '{ref_name}' which has no 'patch' to apply"
                )


# ============================================================================
# Config loading
# ============================================================================


def _parse_primitive(raw: str | dict[str, Any]) -> PrimitiveConfig:
    """Parse a primitive from YAML (string or dict with options).

    Args:
        raw: Either a string ("base64") or dict ({"zlib": {"skip_bytes": 3}}).

    Returns:
        Parsed PrimitiveConfig.

    Raises:
        TransformConfigError: If format is invalid.

    """
    if isinstance(raw, str):
        return PrimitiveConfig(name=raw)

    if isinstance(raw, dict):
        if len(raw) != 1:
            raise TransformConfigError(f"Primitive dict must have exactly 1 key, got: {list(raw.keys())}")
        name = next(iter(raw))
        options = raw[name]
        if options is None:
            options = {}
        if not isinstance(options, dict):
            raise TransformConfigError(f"Primitive '{name}' options must be dict, got: {type(options).__name__}")
        return PrimitiveConfig(name=name, options=options)

    raise TransformConfigError(f"Primitive must be str or dict, got: {type(raw).__name__}")


def _parse_primitives(raw_list: list[Any]) -> tuple[PrimitiveConfig, ...]:
    """Parse a list of primitives from YAML.

    Args:
        raw_list: List of raw primitive definitions.

    Returns:
        Tuple of PrimitiveConfig.

    """
    return tuple(_parse_primitive(item) for item in raw_list)


def _parse_patch(raw: dict[str, Any]) -> PatchConfig:
    """Parse a PatchConfig from YAML dict.

    Accepts both the new ``replace:`` field and the deprecated ``mapping:``
    alias. If ``mapping:`` is set, the PatchConfig dataclass will emit a
    DeprecationWarning at construction time.

    The legacy ``depth:`` key is no longer supported and is rejected
    with a clear migration message: it was never implemented and
    ``scope:`` covers the original intent.

    Args:
        raw: Raw patch configuration dict.

    Returns:
        Parsed PatchConfig.

    Raises:
        TransformConfigError: If ``depth:`` is present in the raw dict.

    """
    if "depth" in raw:
        raise TransformConfigError(
            "PatchConfig 'depth:' is no longer supported. The field was "
            "never implemented; use 'scope: blob | outer | all' instead "
            "to control where replacements apply."
        )
    return PatchConfig(
        replace=raw.get("replace"),
        scope=raw.get("scope", "blob"),
        callable=raw.get("callable"),
        args=raw.get("args", {}),
        mapping=raw.get("mapping"),
    )


def _parse_filter(raw: dict[str, Any]) -> FilterConfig:
    """Parse a FilterConfig from YAML dict.

    Args:
        raw: Raw filter configuration dict.

    Returns:
        Parsed FilterConfig.

    Raises:
        TransformConfigError: If raw is not a dict.

    """
    if not isinstance(raw, dict):
        raise TransformConfigError(f"Filter must be a dict, got: {type(raw).__name__}")
    return FilterConfig(
        content_type=raw.get("content_type", "*"),
        name=raw.get("name", "*"),
    )


def _parse_targeted_patch(raw: dict[str, Any]) -> TargetedPatchConfig:
    """Parse a TargetedPatchConfig from YAML dict.

    Args:
        raw: Raw targeted patch configuration dict.

    Returns:
        Parsed TargetedPatchConfig.

    Raises:
        TransformConfigError: If format is invalid.

    """
    if not isinstance(raw, dict):
        raise TransformConfigError(f"Targeted patch must be a dict, got: {type(raw).__name__}")

    filter_raw = raw.get("filter", {})
    filter_config = _parse_filter(filter_raw) if filter_raw else FilterConfig()

    patches_raw = raw.get("patches", [])
    if not isinstance(patches_raw, list):
        raise TransformConfigError(f"Targeted patch 'patches' must be a list, got: {type(patches_raw).__name__}")
    for item in patches_raw:
        if not isinstance(item, str):
            raise TransformConfigError(f"Targeted patch 'patches' entries must be strings, got: {type(item).__name__}")

    return TargetedPatchConfig(
        filter=filter_config,
        patches=tuple(patches_raw),
    )


def _parse_composed_patch(
    global_raw: list[Any] | None,
    targeted_raw: list[Any] | None,
) -> ComposedPatchConfig:
    """Parse a ComposedPatchConfig from YAML lists.

    Args:
        global_raw: Raw global_patches list from YAML.
        targeted_raw: Raw targeted_patches list from YAML.

    Returns:
        Parsed ComposedPatchConfig.

    Raises:
        TransformConfigError: If format is invalid.

    """
    if global_raw is not None and not isinstance(global_raw, list):
        raise TransformConfigError(f"'global_patches' must be a list, got: {type(global_raw).__name__}")
    if targeted_raw is not None and not isinstance(targeted_raw, list):
        raise TransformConfigError(f"'targeted_patches' must be a list, got: {type(targeted_raw).__name__}")

    global_patches: tuple[str, ...] = ()
    if global_raw:
        for item in global_raw:
            if not isinstance(item, str):
                raise TransformConfigError(f"'global_patches' entries must be strings, got: {type(item).__name__}")
        global_patches = tuple(global_raw)

    targeted_patches: tuple[TargetedPatchConfig, ...] = ()
    if targeted_raw:
        targeted_patches = tuple(_parse_targeted_patch(item) for item in targeted_raw)

    return ComposedPatchConfig(
        global_patches=global_patches,
        targeted_patches=targeted_patches,
    )


def _parse_chain(name: str, raw: dict[str, Any]) -> TransformChainConfig:
    """Parse a TransformChainConfig from YAML dict.

    Args:
        name: Chain name.
        raw: Raw chain configuration dict.

    Returns:
        Parsed TransformChainConfig.

    """
    forward_raw = raw.get("forward")
    backward_raw = raw.get("backward")
    patch_raw = raw.get("patch")
    preset = raw.get("preset")
    global_patches_raw = raw.get("global_patches")
    targeted_patches_raw = raw.get("targeted_patches")

    forward = _parse_primitives(forward_raw) if forward_raw else ()
    backward = _parse_primitives(backward_raw) if backward_raw else None
    patch = _parse_patch(patch_raw) if patch_raw else None

    composed_patch: ComposedPatchConfig | None = None
    if global_patches_raw is not None or targeted_patches_raw is not None:
        composed_patch = _parse_composed_patch(global_patches_raw, targeted_patches_raw)

    return TransformChainConfig(
        name=name,
        forward=forward,
        backward=backward,
        patch=patch,
        composed_patch=composed_patch,
        preset=preset,
    )


def load_transform_config() -> TransformConfig:
    """Load transform configuration from kstlib.conf.yml.

    Reads the ``transforms:`` section from the global config.

    Returns:
        Parsed TransformConfig, or empty config if section absent.

    Examples:
        >>> config = load_transform_config()  # doctest: +SKIP

    """
    from kstlib.config import get_config

    config = get_config()
    transforms_section = config.get("transforms", {})  # type: ignore[no-untyped-call]

    if not transforms_section:
        log.debug("No transforms section found in config")
        return TransformConfig()

    # Parse security settings
    security = transforms_section.get("security", {})
    allowed_modules_raw = security.get("allowed_callable_modules", [])
    allowed_modules = frozenset(allowed_modules_raw) if allowed_modules_raw else frozenset()

    # Parse chains
    chains_raw = transforms_section.get("chains", {})
    if not isinstance(chains_raw, dict):
        raise TransformConfigError(f"transforms.chains must be a dict, got: {type(chains_raw).__name__}")

    chains: dict[str, TransformChainConfig] = {}
    for name, chain_data in chains_raw.items():
        if not isinstance(chain_data, dict):
            raise TransformConfigError(f"Chain '{name}' must be a dict, got: {type(chain_data).__name__}")
        chains[name] = _parse_chain(name, chain_data)

    return TransformConfig(
        chains=chains,
        allowed_callable_modules=allowed_modules,
    )


__all__ = [
    "PATCH_SCOPE_VALUES",
    "ComposedPatchConfig",
    "FilterConfig",
    "PatchConfig",
    "PrimitiveConfig",
    "TargetedPatchConfig",
    "TransformChainConfig",
    "TransformConfig",
    "load_transform_config",
]
