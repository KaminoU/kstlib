"""Tests for kstlib.transform.config dataclasses and validation."""

from __future__ import annotations

import pytest

from kstlib.transform.config import (
    ComposedPatchConfig,
    FilterConfig,
    PatchConfig,
    PrimitiveConfig,
    TargetedPatchConfig,
    TransformChainConfig,
    TransformConfig,
    _parse_chain,
    _parse_patch,
)
from kstlib.transform.exceptions import TransformConfigError

# ============================================================================
# PrimitiveConfig
# ============================================================================


class TestPrimitiveConfig:
    """Tests for PrimitiveConfig validation."""

    def test_valid_base64(self) -> None:
        """Valid base64 primitive."""
        cfg = PrimitiveConfig(name="base64")
        assert cfg.name == "base64"

    def test_valid_zlib_with_options(self) -> None:
        """Valid zlib primitive with skip_bytes."""
        cfg = PrimitiveConfig(name="zlib", options={"skip_bytes": 3})
        assert cfg.options["skip_bytes"] == 3

    def test_valid_json_with_extract(self) -> None:
        """Valid json primitive with extract path."""
        cfg = PrimitiveConfig(name="json", options={"extract": "a.b"})
        assert cfg.options["extract"] == "a.b"

    def test_invalid_primitive_name(self) -> None:
        """Unknown primitive name raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="Unknown primitive"):
            PrimitiveConfig(name="rot13")

    def test_too_many_options(self) -> None:
        """Too many options raises TransformConfigError."""
        opts = {f"key{i}": i for i in range(15)}
        with pytest.raises(TransformConfigError, match="too many options"):
            PrimitiveConfig(name="base64", options=opts)

    def test_zlib_skip_bytes_negative(self) -> None:
        """Negative skip_bytes raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="skip_bytes"):
            PrimitiveConfig(name="zlib", options={"skip_bytes": -1})

    def test_zlib_skip_bytes_too_large(self) -> None:
        """skip_bytes exceeding limit raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="skip_bytes"):
            PrimitiveConfig(name="zlib", options={"skip_bytes": 99})

    def test_zlib_prepend_invalid_hex(self) -> None:
        """Invalid hex in prepend_bytes raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="prepend_bytes"):
            PrimitiveConfig(name="zlib", options={"prepend_bytes": "xyz"})

    def test_json_extract_invalid_path(self) -> None:
        """Invalid dot-path raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="json extract"):
            PrimitiveConfig(name="json", options={"extract": "a..b"})

    def test_frozen(self) -> None:
        """PrimitiveConfig is frozen."""
        cfg = PrimitiveConfig(name="base64")
        with pytest.raises(AttributeError):
            cfg.name = "other"  # type: ignore[misc]

    # ------------------------------------------------------------------
    # Phase 1: new YAML options validation (base64 strict/strip_prefix/prefix,
    # json minify/ensure_ascii, zlib level)
    # ------------------------------------------------------------------

    def test_base64_strict_must_be_bool(self) -> None:
        """base64 strict must be bool, not string."""
        with pytest.raises(TransformConfigError, match="strict must be bool"):
            PrimitiveConfig(name="base64", options={"strict": "yes"})

    def test_base64_strip_prefix_too_long(self) -> None:
        """strip_prefix exceeding 32 chars raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="strip_prefix too long"):
            PrimitiveConfig(name="base64", options={"strip_prefix": "x" * 33})

    def test_base64_strip_prefix_wrong_type(self) -> None:
        """strip_prefix as int raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="strip_prefix must be string"):
            PrimitiveConfig(name="base64", options={"strip_prefix": 42})

    def test_base64_prefix_too_long(self) -> None:
        """prefix exceeding 32 chars raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="prefix too long"):
            PrimitiveConfig(name="base64", options={"prefix": "y" * 33})

    def test_base64_valid_strip_prefix(self) -> None:
        """Valid strip_prefix passes validation."""
        cfg = PrimitiveConfig(
            name="base64",
            options={"strip_prefix": "TRUE###", "strict": False},
        )
        assert cfg.options["strip_prefix"] == "TRUE###"

    def test_base64_valid_prefix(self) -> None:
        """Valid prefix passes validation."""
        cfg = PrimitiveConfig(name="base64", options={"prefix": "TRUE###"})
        assert cfg.options["prefix"] == "TRUE###"

    def test_json_minify_must_be_bool(self) -> None:
        """json minify must be bool, not int."""
        with pytest.raises(TransformConfigError, match="minify must be bool"):
            PrimitiveConfig(name="json", options={"minify": 1})

    def test_json_ensure_ascii_must_be_bool(self) -> None:
        """json ensure_ascii must be bool, not string."""
        with pytest.raises(TransformConfigError, match="ensure_ascii must be bool"):
            PrimitiveConfig(name="json", options={"ensure_ascii": "true"})

    def test_json_valid_minify_and_ensure_ascii(self) -> None:
        """Valid minify + ensure_ascii combo passes validation."""
        cfg = PrimitiveConfig(
            name="json",
            options={"minify": True, "ensure_ascii": False},
        )
        assert cfg.options["minify"] is True
        assert cfg.options["ensure_ascii"] is False

    def test_zlib_level_out_of_range_high(self) -> None:
        """zlib level > 9 raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match=r"level must be in range"):
            PrimitiveConfig(name="zlib", options={"level": 10})

    def test_zlib_level_out_of_range_low(self) -> None:
        """zlib level < -1 raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match=r"level must be in range"):
            PrimitiveConfig(name="zlib", options={"level": -2})

    def test_zlib_level_wrong_type(self) -> None:
        """zlib level as string raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="level must be int"):
            PrimitiveConfig(name="zlib", options={"level": "9"})

    def test_zlib_level_bool_rejected(self) -> None:
        """bool is rejected even though it subclasses int."""
        with pytest.raises(TransformConfigError, match="level must be int"):
            PrimitiveConfig(name="zlib", options={"level": True})

    def test_zlib_level_valid_range(self) -> None:
        """Valid level values in [-1, 9] pass validation."""
        for lvl in (-1, 0, 1, 6, 9):
            cfg = PrimitiveConfig(name="zlib", options={"level": lvl})
            assert cfg.options["level"] == lvl


# ============================================================================
# PatchConfig
# ============================================================================


class TestPatchConfig:
    """Tests for PatchConfig validation."""

    def test_replace_only(self) -> None:
        """Valid replace-only patch."""
        cfg = PatchConfig(replace={"old": "new"})
        assert cfg.replace == {"old": "new"}
        assert cfg.scope == "blob"

    def test_callable_only(self) -> None:
        """Valid callable-only patch."""
        cfg = PatchConfig(callable="mymod:func")
        assert cfg.callable == "mymod:func"

    def test_no_replace_no_callable(self) -> None:
        """Neither replace nor callable is valid (no-op patch)."""
        cfg = PatchConfig()
        assert cfg.replace is None
        assert cfg.callable is None

    def test_both_replace_and_callable(self) -> None:
        """Both replace and callable raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="mutually exclusive"):
            PatchConfig(replace={"a": "b"}, callable="mod:fn")

    def test_default_scope_is_blob(self) -> None:
        """The default scope is 'blob' when omitted."""
        cfg = PatchConfig(replace={"a": "b"})
        assert cfg.scope == "blob"

    def test_scope_outer(self) -> None:
        """scope='outer' is accepted."""
        cfg = PatchConfig(replace={"a": "b"}, scope="outer")
        assert cfg.scope == "outer"

    def test_scope_all(self) -> None:
        """scope='all' is accepted."""
        cfg = PatchConfig(replace={"a": "b"}, scope="all")
        assert cfg.scope == "all"

    def test_scope_invalid(self) -> None:
        """An unknown scope raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="scope must be one of"):
            PatchConfig(replace={"a": "b"}, scope="deep")  # type: ignore[arg-type]

    def test_mapping_alias_emits_deprecation_warning(self) -> None:
        """The deprecated 'mapping' alias copies to 'replace' with a warning."""
        with pytest.warns(DeprecationWarning, match="mapping.*deprecated"):
            cfg = PatchConfig(mapping={"old": "new"})
        # The alias is copied to replace and validated like the new field.
        assert cfg.replace == {"old": "new"}

    def test_mapping_and_replace_both_set_raises(self) -> None:
        """Setting both mapping and replace is ambiguous and raises."""
        with pytest.raises(TransformConfigError, match="both set"):
            PatchConfig(replace={"a": "b"}, mapping={"c": "d"})

    def test_replace_empty_key(self) -> None:
        """Empty replace key raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="key must not be empty"):
            PatchConfig(replace={"": "value"})

    def test_replace_key_too_long(self) -> None:
        """Oversized replace key raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="key too long"):
            PatchConfig(replace={"x" * 5000: "value"})

    def test_replace_too_many_entries(self) -> None:
        """Too many replace entries raises TransformConfigError."""
        replace = {f"key{i}": f"val{i}" for i in range(150)}
        with pytest.raises(TransformConfigError, match="too many entries"):
            PatchConfig(replace=replace)

    def test_callable_invalid_target(self) -> None:
        """Invalid callable target raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="Invalid callable target"):
            PatchConfig(callable="no-colon-here")

    def test_args_too_many(self) -> None:
        """Too many args raises TransformConfigError."""
        args = {f"k{i}": f"v{i}" for i in range(25)}
        with pytest.raises(TransformConfigError, match="too many entries"):
            PatchConfig(args=args)

    def test_yaml_depth_rejected_with_migration_message(self) -> None:
        """The legacy YAML 'depth:' key is rejected with a migration hint."""
        with pytest.raises(TransformConfigError, match="no longer supported"):
            _parse_patch({"depth": 3, "replace": {"a": "b"}})

    def test_yaml_depth_string_also_rejected(self) -> None:
        """The legacy YAML 'depth: all' string form is also rejected."""
        with pytest.raises(TransformConfigError, match="scope.*instead"):
            _parse_patch({"depth": "all", "replace": {"a": "b"}})

    def test_yaml_replace_and_scope_parsed(self) -> None:
        """The new 'replace:' and 'scope:' keys are parsed correctly."""
        cfg = _parse_patch({"replace": {"a": "b"}, "scope": "all"})
        assert cfg.replace == {"a": "b"}
        assert cfg.scope == "all"

    def test_yaml_mapping_alias_still_parsed_with_warning(self) -> None:
        """The deprecated YAML 'mapping:' alias still parses (with warning)."""
        with pytest.warns(DeprecationWarning, match="deprecated"):
            cfg = _parse_patch({"mapping": {"a": "b"}})
        assert cfg.replace == {"a": "b"}


# ============================================================================
# TransformChainConfig
# ============================================================================


class TestTransformChainConfig:
    """Tests for TransformChainConfig validation."""

    def test_valid_with_forward(self) -> None:
        """Valid chain with forward primitives."""
        cfg = TransformChainConfig(
            name="test",
            forward=(PrimitiveConfig(name="base64"),),
        )
        assert cfg.name == "test"

    def test_valid_with_preset(self) -> None:
        """Valid chain with preset reference."""
        cfg = TransformChainConfig(name="child", preset="parent")
        assert cfg.preset == "parent"

    def test_empty_forward_no_preset(self) -> None:
        """Empty forward without preset/patch raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="must declare at least one"):
            TransformChainConfig(name="bad")

    def test_preset_and_forward(self) -> None:
        """Both preset and forward raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="mutually exclusive"):
            TransformChainConfig(
                name="bad",
                forward=(PrimitiveConfig(name="base64"),),
                preset="parent",
            )

    def test_invalid_name(self) -> None:
        """Invalid chain name raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="Invalid chain name"):
            TransformChainConfig(name="bad name!", forward=(PrimitiveConfig(name="base64"),))

    def test_forward_too_long(self) -> None:
        """Too many forward primitives raises TransformConfigError."""
        prims = tuple(PrimitiveConfig(name="base64") for _ in range(25))
        with pytest.raises(TransformConfigError, match="forward chain too long"):
            TransformChainConfig(name="long", forward=prims)


# ============================================================================
# TransformConfig
# ============================================================================


class TestTransformConfig:
    """Tests for TransformConfig validation."""

    def test_valid_config(self) -> None:
        """Valid config with one chain."""
        cfg = TransformConfig(
            chains={
                "decode": TransformChainConfig(
                    name="decode",
                    forward=(PrimitiveConfig(name="base64"),),
                ),
            }
        )
        assert "decode" in cfg.chains

    def test_too_many_chains(self) -> None:
        """Too many chains raises TransformConfigError."""
        chains = {
            f"chain{i}": TransformChainConfig(
                name=f"chain{i}",
                forward=(PrimitiveConfig(name="base64"),),
            )
            for i in range(60)
        }
        with pytest.raises(TransformConfigError, match="Too many named chains"):
            TransformConfig(chains=chains)

    def test_unknown_preset_reference(self) -> None:
        """Preset referencing unknown chain raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="unknown preset"):
            TransformConfig(
                chains={
                    "child": TransformChainConfig(name="child", preset="nonexistent"),
                }
            )

    def test_circular_preset(self) -> None:
        """Self-referencing preset raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="circular"):
            TransformConfig(
                chains={
                    "loop": TransformChainConfig(name="loop", preset="loop"),
                }
            )

    def test_chained_presets_rejected(self) -> None:
        """Preset referencing another preset raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="Chained presets"):
            TransformConfig(
                chains={
                    "base": TransformChainConfig(
                        name="base",
                        forward=(PrimitiveConfig(name="base64"),),
                    ),
                    "mid": TransformChainConfig(name="mid", preset="base"),
                    "leaf": TransformChainConfig(name="leaf", preset="mid"),
                }
            )

    def test_callable_not_in_whitelist(self) -> None:
        """Callable module not in whitelist raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="not in allowed_callable_modules"):
            TransformConfig(
                chains={
                    "patched": TransformChainConfig(
                        name="patched",
                        forward=(PrimitiveConfig(name="base64"),),
                        patch=PatchConfig(callable="evil.module:hack"),
                    ),
                },
                allowed_callable_modules=frozenset({"safe.module"}),
            )

    def test_callable_in_whitelist_passes(self) -> None:
        """Callable module in whitelist passes validation."""
        cfg = TransformConfig(
            chains={
                "patched": TransformChainConfig(
                    name="patched",
                    forward=(PrimitiveConfig(name="base64"),),
                    patch=PatchConfig(callable="myproject.viya:patch_fn"),
                ),
            },
            allowed_callable_modules=frozenset({"myproject.viya"}),
        )
        assert cfg.chains["patched"].patch is not None


# ============================================================================
# FilterConfig
# ============================================================================


class TestFilterConfig:
    """Tests for FilterConfig validation."""

    def test_default_wildcards(self) -> None:
        """Default FilterConfig matches everything."""
        cfg = FilterConfig()
        assert cfg.content_type == "*"
        assert cfg.name == "*"

    def test_valid_explicit(self) -> None:
        """Explicit content_type and name pass validation."""
        cfg = FilterConfig(content_type="report", name="R220_*")
        assert cfg.content_type == "report"
        assert cfg.name == "R220_*"

    def test_all_allowed_types(self) -> None:
        """All allowed content_type values pass validation."""
        for ct in ("report", "folder", "file", "*"):
            cfg = FilterConfig(content_type=ct)
            assert cfg.content_type == ct

    def test_invalid_content_type(self) -> None:
        """Unknown content_type raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="content_type"):
            FilterConfig(content_type="dataset")

    def test_empty_name(self) -> None:
        """Empty name raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="filter name"):
            FilterConfig(name="")

    def test_name_too_long(self) -> None:
        """Oversized name raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="too long"):
            FilterConfig(name="x" * 300)

    def test_name_with_control_char(self) -> None:
        """Control characters in name raise TransformConfigError."""
        with pytest.raises(TransformConfigError, match="control characters"):
            FilterConfig(name="bad\x00pattern")

    def test_frozen(self) -> None:
        """FilterConfig is frozen."""
        cfg = FilterConfig()
        with pytest.raises(AttributeError):
            cfg.name = "other"  # type: ignore[misc]


# ============================================================================
# TargetedPatchConfig
# ============================================================================


class TestTargetedPatchConfig:
    """Tests for TargetedPatchConfig validation."""

    def test_valid(self) -> None:
        """Valid targeted patch config."""
        cfg = TargetedPatchConfig(
            filter=FilterConfig(name="R220_*"),
            patches=("remap_caslib_r220",),
        )
        assert cfg.patches == ("remap_caslib_r220",)

    def test_empty_patches(self) -> None:
        """Empty patches tuple raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="must not be empty"):
            TargetedPatchConfig(filter=FilterConfig(), patches=())

    def test_too_many_patches(self) -> None:
        """Too many patches raises TransformConfigError."""
        patches = tuple(f"chain{i}" for i in range(15))
        with pytest.raises(TransformConfigError, match="too many patches"):
            TargetedPatchConfig(filter=FilterConfig(), patches=patches)

    def test_invalid_patch_name(self) -> None:
        """Invalid chain name in patches raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="Invalid chain name"):
            TargetedPatchConfig(filter=FilterConfig(), patches=("bad name!",))


# ============================================================================
# ComposedPatchConfig
# ============================================================================


class TestComposedPatchConfig:
    """Tests for ComposedPatchConfig validation."""

    def test_global_only(self) -> None:
        """Composed config with only global_patches is valid."""
        cfg = ComposedPatchConfig(global_patches=("remap_host",))
        assert cfg.global_patches == ("remap_host",)
        assert cfg.targeted_patches == ()

    def test_targeted_only(self) -> None:
        """Composed config with only targeted_patches is valid."""
        cfg = ComposedPatchConfig(
            targeted_patches=(
                TargetedPatchConfig(
                    filter=FilterConfig(name="R220_*"),
                    patches=("remap_r220",),
                ),
            )
        )
        assert len(cfg.targeted_patches) == 1

    def test_both_global_and_targeted(self) -> None:
        """Composed config with both global and targeted is valid."""
        cfg = ComposedPatchConfig(
            global_patches=("remap_host",),
            targeted_patches=(
                TargetedPatchConfig(
                    filter=FilterConfig(name="*"),
                    patches=("remap_default",),
                ),
            ),
        )
        assert cfg.global_patches == ("remap_host",)
        assert len(cfg.targeted_patches) == 1

    def test_empty_raises(self) -> None:
        """Composed config with no global and no targeted raises."""
        with pytest.raises(TransformConfigError, match="at least one"):
            ComposedPatchConfig()

    def test_too_many_global(self) -> None:
        """Too many global_patches raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="too many global_patches"):
            ComposedPatchConfig(global_patches=tuple(f"c{i}" for i in range(15)))

    def test_too_many_targeted(self) -> None:
        """Too many targeted_patches raises TransformConfigError."""
        targeted = tuple(TargetedPatchConfig(filter=FilterConfig(), patches=("ref",)) for _ in range(60))
        with pytest.raises(TransformConfigError, match="too many targeted_patches"):
            ComposedPatchConfig(targeted_patches=targeted)

    def test_invalid_global_chain_name(self) -> None:
        """Invalid chain name in global_patches raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="Invalid chain name"):
            ComposedPatchConfig(global_patches=("bad name!",))


# ============================================================================
# TransformChainConfig - composed_patch + patch-only
# ============================================================================


class TestTransformChainConfigComposed:
    """Tests for TransformChainConfig with composed_patch and patch-only."""

    def test_patch_only_chain(self) -> None:
        """Patch-only chain (no forward, no preset) is valid."""
        cfg = TransformChainConfig(
            name="remap_host",
            patch=PatchConfig(replace={"old": "new"}),
        )
        assert cfg.patch is not None
        assert cfg.forward == ()
        assert cfg.preset is None

    def test_composed_patch_chain(self) -> None:
        """Chain with composed_patch (no inline patch) is valid."""
        cfg = TransformChainConfig(
            name="orchestrator",
            preset="sas_report",
            composed_patch=ComposedPatchConfig(global_patches=("remap_host",)),
        )
        assert cfg.composed_patch is not None
        assert cfg.patch is None

    def test_patch_and_composed_mutex(self) -> None:
        """Both patch and composed_patch raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="mutually exclusive"):
            TransformChainConfig(
                name="bad",
                preset="other",
                patch=PatchConfig(replace={"a": "b"}),
                composed_patch=ComposedPatchConfig(global_patches=("ref",)),
            )

    def test_no_forward_no_preset_no_patch_raises(self) -> None:
        """Truly empty chain raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="must declare at least one"):
            TransformChainConfig(name="empty")


# ============================================================================
# TransformConfig - composed_patch reference validation
# ============================================================================


class TestTransformConfigComposedReferences:
    """Tests for TransformConfig validation of composed_patch references."""

    def test_valid_composed_references(self) -> None:
        """Composed patches referencing existing patch-only chains pass."""
        cfg = TransformConfig(
            chains={
                "remap_host": TransformChainConfig(
                    name="remap_host",
                    patch=PatchConfig(replace={"a": "b"}),
                ),
                "orchestrator": TransformChainConfig(
                    name="orchestrator",
                    forward=(PrimitiveConfig(name="base64"),),
                    composed_patch=ComposedPatchConfig(global_patches=("remap_host",)),
                ),
            }
        )
        assert "orchestrator" in cfg.chains

    def test_unknown_global_reference(self) -> None:
        """Composed global_patches referencing unknown chain raises."""
        with pytest.raises(TransformConfigError, match="unknown chain"):
            TransformConfig(
                chains={
                    "orchestrator": TransformChainConfig(
                        name="orchestrator",
                        forward=(PrimitiveConfig(name="base64"),),
                        composed_patch=ComposedPatchConfig(global_patches=("missing",)),
                    ),
                }
            )

    def test_unknown_targeted_reference(self) -> None:
        """Composed targeted_patches referencing unknown chain raises."""
        with pytest.raises(TransformConfigError, match="unknown chain"):
            TransformConfig(
                chains={
                    "orchestrator": TransformChainConfig(
                        name="orchestrator",
                        forward=(PrimitiveConfig(name="base64"),),
                        composed_patch=ComposedPatchConfig(
                            targeted_patches=(
                                TargetedPatchConfig(
                                    filter=FilterConfig(),
                                    patches=("missing",),
                                ),
                            )
                        ),
                    ),
                }
            )

    def test_self_reference_raises(self) -> None:
        """Composed patch referencing its own chain raises."""
        with pytest.raises(TransformConfigError, match="references itself"):
            TransformConfig(
                chains={
                    "loop": TransformChainConfig(
                        name="loop",
                        forward=(PrimitiveConfig(name="base64"),),
                        composed_patch=ComposedPatchConfig(global_patches=("loop",)),
                    ),
                }
            )

    def test_nested_composition_rejected(self) -> None:
        """Composed patch referencing another composed chain raises."""
        with pytest.raises(TransformConfigError, match="Nested composition"):
            TransformConfig(
                chains={
                    "leaf": TransformChainConfig(
                        name="leaf",
                        patch=PatchConfig(replace={"a": "b"}),
                    ),
                    "mid": TransformChainConfig(
                        name="mid",
                        forward=(PrimitiveConfig(name="base64"),),
                        composed_patch=ComposedPatchConfig(global_patches=("leaf",)),
                    ),
                    "root": TransformChainConfig(
                        name="root",
                        forward=(PrimitiveConfig(name="base64"),),
                        composed_patch=ComposedPatchConfig(global_patches=("mid",)),
                    ),
                }
            )

    def test_reference_without_patch_rejected(self) -> None:
        """Composed patch referencing a chain without .patch raises."""
        with pytest.raises(TransformConfigError, match="has no 'patch'"):
            TransformConfig(
                chains={
                    "no_patch": TransformChainConfig(
                        name="no_patch",
                        forward=(PrimitiveConfig(name="base64"),),
                    ),
                    "orchestrator": TransformChainConfig(
                        name="orchestrator",
                        forward=(PrimitiveConfig(name="base64"),),
                        composed_patch=ComposedPatchConfig(global_patches=("no_patch",)),
                    ),
                }
            )


# ============================================================================
# YAML parsing - _parse_chain with composed_patch
# ============================================================================


class TestParseChainComposed:
    """Tests for _parse_chain with global_patches and targeted_patches."""

    def test_parse_global_patches(self) -> None:
        """global_patches list is parsed into composed_patch."""
        raw = {
            "preset": "sas_report",
            "global_patches": ["remap_host"],
        }
        chain = _parse_chain("orchestrator", raw)
        assert chain.composed_patch is not None
        assert chain.composed_patch.global_patches == ("remap_host",)
        assert chain.composed_patch.targeted_patches == ()

    def test_parse_targeted_patches(self) -> None:
        """targeted_patches list is parsed into composed_patch."""
        raw = {
            "preset": "sas_report",
            "targeted_patches": [
                {
                    "filter": {"content_type": "report", "name": "R220_*"},
                    "patches": ["remap_r220"],
                },
            ],
        }
        chain = _parse_chain("orchestrator", raw)
        assert chain.composed_patch is not None
        assert len(chain.composed_patch.targeted_patches) == 1
        targeted = chain.composed_patch.targeted_patches[0]
        assert targeted.filter.content_type == "report"
        assert targeted.filter.name == "R220_*"
        assert targeted.patches == ("remap_r220",)

    def test_parse_both(self) -> None:
        """Both global and targeted parse together."""
        raw = {
            "preset": "sas_report",
            "global_patches": ["remap_host"],
            "targeted_patches": [
                {"filter": {"name": "*"}, "patches": ["remap_default"]},
            ],
        }
        chain = _parse_chain("orchestrator", raw)
        assert chain.composed_patch is not None
        assert chain.composed_patch.global_patches == ("remap_host",)
        assert len(chain.composed_patch.targeted_patches) == 1

    def test_parse_no_filter_defaults_to_wildcards(self) -> None:
        """Targeted patch without filter uses wildcard FilterConfig."""
        raw = {
            "preset": "sas_report",
            "targeted_patches": [
                {"patches": ["remap_default"]},
            ],
        }
        chain = _parse_chain("orchestrator", raw)
        assert chain.composed_patch is not None
        targeted = chain.composed_patch.targeted_patches[0]
        assert targeted.filter.content_type == "*"
        assert targeted.filter.name == "*"

    def test_parse_global_patches_must_be_list(self) -> None:
        """global_patches as non-list raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="must be a list"):
            _parse_chain("bad", {"preset": "x", "global_patches": "remap_host"})

    def test_parse_targeted_patches_must_be_list(self) -> None:
        """targeted_patches as non-list raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="must be a list"):
            _parse_chain("bad", {"preset": "x", "targeted_patches": {}})

    def test_parse_global_entry_must_be_string(self) -> None:
        """global_patches entry not a string raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="must be strings"):
            _parse_chain("bad", {"preset": "x", "global_patches": [42]})

    def test_parse_targeted_patches_entries_must_be_strings(self) -> None:
        """targeted_patches.patches entry not a string raises."""
        with pytest.raises(TransformConfigError, match="must be strings"):
            _parse_chain(
                "bad",
                {
                    "preset": "x",
                    "targeted_patches": [{"patches": [42]}],
                },
            )
