"""Tests for RapiResponse extraction accessors and the heuristic cascade."""

from __future__ import annotations

from typing import Any, NoReturn

import pytest
from box import Box
from jmespath.exceptions import JMESPathError

from kstlib.config.exceptions import ConfigNotLoadedError
from kstlib.logging import TRACE_LEVEL
from kstlib.rapi import RapiError, RapiResponse, client


def _raise_not_loaded() -> NoReturn:
    """Stand-in for get_config when no kstlib config is loaded."""
    raise ConfigNotLoadedError("no config loaded in test")


# Documented heuristic defaults, mirrored from the embedded kstlib.conf.yml
# (rapi.extraction). The resolver must surface exactly these values; tests assert
# against them rather than an in-code constant (which Opt D removed).
_EXPECTED_ID_KEYS: tuple[str, ...] = ("id", "uri", "name", "key", "objectId")
_EXPECTED_IDS_PATHS: tuple[str, ...] = (
    "items[*].id",
    "members[*].id",
    "results[*].id",
    "data[*].id",
    "value[*].id",
)
_EXPECTED_COUNT_KEYS: tuple[str, ...] = ("count", "total", "totalCount")


def _keys(
    *,
    id_keys: tuple[str, ...] | None = None,
    ids_paths: tuple[str, ...] | None = None,
    count_keys: tuple[str, ...] | None = None,
) -> client._ExtractionKeys:
    """Build an _ExtractionKeys, overriding selected lists (documented defaults otherwise)."""
    return client._ExtractionKeys(
        id_keys=id_keys if id_keys is not None else _EXPECTED_ID_KEYS,
        ids_paths=ids_paths if ids_paths is not None else _EXPECTED_IDS_PATHS,
        count_keys=count_keys if count_keys is not None else _EXPECTED_COUNT_KEYS,
    )


class TestId:
    """The .id accessor resolves a single resource identifier."""

    def test_single_dict_root(self) -> None:
        """A root id key resolves to its string value."""
        assert RapiResponse(status_code=200, data={"id": "abc"}).id == "abc"

    def test_id_key_cascade(self) -> None:
        """The first present default key wins (id > uri > name > ...)."""
        assert RapiResponse(status_code=200, data={"name": "n", "uri": "u"}).id == "u"

    def test_non_string_id_is_stringified(self) -> None:
        """A non-string id value is coerced to str."""
        assert RapiResponse(status_code=200, data={"id": 42}).id == "42"

    def test_dict_without_id_returns_none(self) -> None:
        """A dict without any id key resolves to None."""
        assert RapiResponse(status_code=200, data={"foo": "bar"}).id is None

    def test_extracted_takes_priority(self) -> None:
        """An extract:-provided id wins over the heuristic."""
        resp = RapiResponse(status_code=200, data={"id": "heuristic"}, extracted=Box({"id": "forced"}))
        assert resp.id == "forced"

    def test_custom_id_keys(self) -> None:
        """A configured id_keys list (idx/index) is honored."""
        resp = RapiResponse(status_code=200, data={"idx": "7"}, extraction_keys=_keys(id_keys=("idx", "index")))
        assert resp.id == "7"

    def test_list_returns_first_with_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """A list payload returns the first item id and warns once."""
        data = [{"id": "a"}, {"id": "b"}]
        with caplog.at_level("WARNING", logger="kstlib.rapi.client"):
            result = RapiResponse(status_code=200, data=data, endpoint_ref="x.list").id
        assert result == "a"
        assert [r for r in caplog.records if "Multiple results" in r.getMessage()]

    def test_list_warning_does_not_leak_values(self, caplog: pytest.LogCaptureFixture) -> None:
        """The multi-result warning never dumps the id values."""
        data = [{"id": "secret-aaa"}, {"id": "secret-bbb"}]
        with caplog.at_level("WARNING", logger="kstlib.rapi.client"):
            _ = RapiResponse(status_code=200, data=data, endpoint_ref="x.list").id
        assert "secret-aaa" not in caplog.text
        assert "secret-bbb" not in caplog.text

    def test_list_of_non_dict_returns_none(self) -> None:
        """A list whose first item is not a dict resolves to None."""
        assert RapiResponse(status_code=200, data=["a", "b"]).id is None

    def test_list_first_item_without_id_returns_none(self) -> None:
        """A list whose first item has no id key resolves to None."""
        assert RapiResponse(status_code=200, data=[{"foo": "bar"}]).id is None

    def test_scalar_returns_none(self) -> None:
        """A scalar JSON body resolves to None."""
        assert RapiResponse(status_code=200, data=5).id is None

    def test_non_json_returns_none_with_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """A non-JSON body resolves to None and warns."""
        with caplog.at_level("WARNING", logger="kstlib.rapi.client"):
            result = RapiResponse(status_code=200, data=None, text="plain", endpoint_ref="x.txt").id
        assert result is None
        assert [r for r in caplog.records if "non-JSON" in r.getMessage()]


class TestIds:
    """The .ids accessor always returns a list of strings."""

    def test_items_path(self) -> None:
        """items[*].id is extracted into a list of strings."""
        assert RapiResponse(status_code=200, data={"items": [{"id": "a"}, {"id": "b"}]}).ids == ["a", "b"]

    @pytest.mark.parametrize("container", ["members", "results", "data", "value"])
    def test_alternative_containers(self, container: str) -> None:
        """members / results / data / value containers are all supported."""
        resp = RapiResponse(status_code=200, data={container: [{"id": "x"}]})
        assert resp.ids == ["x"]

    def test_ids_are_stringified(self) -> None:
        """Integer ids are coerced to strings."""
        assert RapiResponse(status_code=200, data={"items": [{"id": 1}, {"id": 2}]}).ids == ["1", "2"]

    def test_empty_collection(self) -> None:
        """An empty items list yields an empty list."""
        assert RapiResponse(status_code=200, data={"items": []}).ids == []

    def test_no_container_returns_empty(self) -> None:
        """A dict without a known container yields an empty list."""
        assert RapiResponse(status_code=200, data={"foo": "bar"}).ids == []

    def test_non_json_returns_empty(self) -> None:
        """A non-JSON body yields an empty list (never None)."""
        assert RapiResponse(status_code=204, data=None).ids == []

    def test_extracted_takes_priority(self) -> None:
        """An extract:-provided ids list wins over the heuristic."""
        resp = RapiResponse(status_code=200, data={"items": [{"id": "h"}]}, extracted=Box({"ids": ["a", "b"]}))
        assert resp.ids == ["a", "b"]

    def test_custom_ids_paths(self) -> None:
        """A configured ids_paths list is honored."""
        resp = RapiResponse(
            status_code=200,
            data={"rows": [{"index": "1"}, {"index": "2"}]},
            extraction_keys=_keys(ids_paths=("rows[*].index",)),
        )
        assert resp.ids == ["1", "2"]


class TestCount:
    """The .count accessor returns an int or None."""

    @pytest.mark.parametrize("key", ["count", "total", "totalCount"])
    def test_count_keys(self, key: str) -> None:
        """count / total / totalCount are all supported."""
        assert RapiResponse(status_code=200, data={key: 7}).count == 7

    def test_bool_is_not_a_count(self) -> None:
        """A boolean value is not accepted as a count."""
        assert RapiResponse(status_code=200, data={"count": True}).count is None

    def test_non_int_ignored(self) -> None:
        """A non-integer count value resolves to None."""
        assert RapiResponse(status_code=200, data={"count": "many"}).count is None

    def test_non_json_returns_none(self) -> None:
        """A non-JSON body resolves to None."""
        assert RapiResponse(status_code=200, data=None).count is None

    def test_extracted_takes_priority(self) -> None:
        """An extract:-provided count wins over the heuristic."""
        resp = RapiResponse(status_code=200, data={"count": 1}, extracted=Box({"count": 99}))
        assert resp.count == 99


class TestNextUrl:
    """The .next_url / .has_next pagination accessors."""

    def test_next_link(self) -> None:
        """A links entry with rel=next exposes its href."""
        data = {"links": [{"rel": "self", "href": "/a"}, {"rel": "next", "href": "/b"}]}
        resp = RapiResponse(status_code=200, data=data)
        assert resp.next_url == "/b"
        assert resp.has_next is True

    def test_no_next_link(self) -> None:
        """Without a next link, next_url is None and has_next is False."""
        resp = RapiResponse(status_code=200, data={"links": [{"rel": "self", "href": "/a"}]})
        assert resp.next_url is None
        assert resp.has_next is False

    def test_non_json_has_no_next(self) -> None:
        """A non-JSON body has no next link."""
        resp = RapiResponse(status_code=200, data=None)
        assert resp.next_url is None
        assert resp.has_next is False

    def test_extracted_takes_priority(self) -> None:
        """An extract:-provided next_url wins over the heuristic."""
        resp = RapiResponse(status_code=200, data={}, extracted=Box({"next_url": "/forced"}))
        assert resp.next_url == "/forced"


class TestGet:
    """The .get JMESPath escape hatch."""

    def test_match(self) -> None:
        """A matching expression returns its value."""
        assert RapiResponse(status_code=200, data={"a": {"b": 1}}).get("a.b") == 1

    def test_no_match_returns_none(self) -> None:
        """A non-matching expression returns None."""
        assert RapiResponse(status_code=200, data={"a": 1}).get("missing") is None

    def test_non_json_returns_none(self) -> None:
        """A non-JSON body returns None."""
        assert RapiResponse(status_code=200, data=None).get("a") is None

    def test_invalid_expression_returns_none(self, caplog: pytest.LogCaptureFixture) -> None:
        """An invalid expression returns None and warns."""
        with caplog.at_level("WARNING", logger="kstlib.rapi.client"):
            result = RapiResponse(status_code=200, data={"a": 1}).get("a[")
        assert result is None
        assert [r for r in caplog.records if "Invalid JMESPath" in r.getMessage()]


class TestJson:
    """The .json strict accessor."""

    def test_dict(self) -> None:
        """A dict body is returned as-is."""
        assert RapiResponse(status_code=200, data={"a": 1}).json() == {"a": 1}

    def test_list(self) -> None:
        """A list body is returned as-is."""
        assert RapiResponse(status_code=200, data=[1, 2]).json() == [1, 2]

    def test_non_json_raises(self) -> None:
        """A non-JSON (None) body raises RapiError."""
        with pytest.raises(RapiError, match="not JSON"):
            RapiResponse(status_code=200, data=None, endpoint_ref="x.txt").json()

    def test_scalar_raises(self) -> None:
        """A scalar JSON body raises RapiError."""
        with pytest.raises(RapiError, match="not JSON"):
            RapiResponse(status_code=200, data=5).json()


class TestResolveExtractionKeys:
    """Extraction key resolution: embedded defaults, user override, degraded path."""

    @staticmethod
    def _embedded(cfg_loader: Any) -> Box:
        """Return the embedded package config (the single source of the defaults)."""
        return Box(cfg_loader._load_default_config(), default_box=True, default_box_attr=None)

    def test_defaults_from_embedded_conf(self, monkeypatch: pytest.MonkeyPatch, cfg_loader: Any) -> None:
        """The defaults are sourced from the embedded kstlib.conf.yml, not from code."""
        embedded = self._embedded(cfg_loader)
        monkeypatch.setattr("kstlib.config.get_config", lambda: embedded)
        keys = client._resolve_extraction_keys()
        assert keys.id_keys == _EXPECTED_ID_KEYS
        assert keys.ids_paths == _EXPECTED_IDS_PATHS
        assert keys.count_keys == _EXPECTED_COUNT_KEYS

    def test_degraded_config_yields_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When config loading fails, every list degrades to empty (no in-code copy)."""
        monkeypatch.setattr("kstlib.config.get_config", _raise_not_loaded)
        keys = client._resolve_extraction_keys()
        assert keys.id_keys == ()
        assert keys.ids_paths == ()
        assert keys.count_keys == ()

    def test_user_override_keeps_embedded_defaults(self, monkeypatch: pytest.MonkeyPatch, cfg_loader: Any) -> None:
        """Overriding one list keeps the embedded defaults for the others.

        Simulates get_config's embedded-base merge: the user replaces id_keys
        while ids_paths and count_keys remain the embedded defaults.
        """
        embedded = self._embedded(cfg_loader)["rapi"]["extraction"]
        section = {
            "id_keys": ["idx", "index"],
            "ids_paths": list(embedded["ids_paths"]),
            "count_keys": list(embedded["count_keys"]),
        }
        monkeypatch.setattr("kstlib.config.get_config", lambda: {"rapi": {"extraction": section}})
        keys = client._resolve_extraction_keys()
        assert keys.id_keys == ("idx", "index")
        assert keys.ids_paths == _EXPECTED_IDS_PATHS
        assert keys.count_keys == _EXPECTED_COUNT_KEYS

    def test_override_all_lists(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """All three lists can be overridden together."""
        monkeypatch.setattr(
            "kstlib.config.get_config",
            lambda: {"rapi": {"extraction": {"id_keys": ["idx"], "ids_paths": ["rows[*].idx"], "count_keys": ["n"]}}},
        )
        keys = client._resolve_extraction_keys()
        assert keys.id_keys == ("idx",)
        assert keys.ids_paths == ("rows[*].idx",)
        assert keys.count_keys == ("n",)

    def test_absent_list_yields_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A list missing from the section resolves to empty (no in-code default)."""
        monkeypatch.setattr("kstlib.config.get_config", lambda: {"rapi": {"extraction": {"id_keys": ["x"]}}})
        keys = client._resolve_extraction_keys()
        assert keys.id_keys == ("x",)
        assert keys.ids_paths == ()
        assert keys.count_keys == ()


class TestExtractionHardening:
    """rapi.extraction.* is an external input: invalid overrides are rejected (defense in depth)."""

    @staticmethod
    def _resolve_with(monkeypatch: pytest.MonkeyPatch, section: dict[str, Any]) -> client._ExtractionKeys:
        """Resolve extraction keys from a single injected rapi.extraction section."""
        monkeypatch.setattr("kstlib.config.get_config", lambda: {"rapi": {"extraction": section}})
        return client._resolve_extraction_keys()

    @staticmethod
    def _security_records(caplog: pytest.LogCaptureFixture) -> list[Any]:
        """Return the captured [SECURITY] warning records."""
        return [r for r in caplog.records if "[SECURITY]" in r.getMessage()]

    def test_too_many_keys_rejected(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        """A list exceeding the max entry count is rejected and disabled."""
        with caplog.at_level("WARNING", logger="kstlib.rapi.client"):
            keys = self._resolve_with(monkeypatch, {"id_keys": [f"k{i}" for i in range(33)]})
        assert keys.id_keys == ()
        assert any("rapi.extraction.id_keys" in r.getMessage() for r in self._security_records(caplog))

    def test_empty_list_rejected(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        """An empty override list is rejected and the heuristic disabled."""
        with caplog.at_level("WARNING", logger="kstlib.rapi.client"):
            keys = self._resolve_with(monkeypatch, {"id_keys": []})
        assert keys.id_keys == ()
        assert any(
            "rapi.extraction.id_keys" in r.getMessage() and "empty list" in r.getMessage()
            for r in self._security_records(caplog)
        )

    def test_field_name_too_long_rejected(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """An id_keys entry over the field-name length limit is rejected; value not logged."""
        long_name = "x" * 65
        with caplog.at_level("WARNING", logger="kstlib.rapi.client"):
            keys = self._resolve_with(monkeypatch, {"id_keys": [long_name]})
        assert keys.id_keys == ()
        assert self._security_records(caplog)
        assert long_name not in caplog.text

    def test_jmespath_expr_too_long_rejected(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """An ids_paths entry over the expression length limit is rejected; value not logged."""
        long_expr = "a" * 513
        with caplog.at_level("WARNING", logger="kstlib.rapi.client"):
            keys = self._resolve_with(monkeypatch, {"ids_paths": [long_expr]})
        assert keys.ids_paths == ()
        assert self._security_records(caplog)
        assert long_expr not in caplog.text

    def test_invalid_jmespath_rejected(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """An ids_paths entry that is not valid JMESPath is rejected; value not logged."""
        bad_expr = "items[*."
        with caplog.at_level("WARNING", logger="kstlib.rapi.client"):
            keys = self._resolve_with(monkeypatch, {"ids_paths": [bad_expr]})
        assert keys.ids_paths == ()
        assert self._security_records(caplog)
        assert bad_expr not in caplog.text

    def test_non_string_entry_rejected(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A non-string entry is rejected for a field-name list."""
        with caplog.at_level("WARNING", logger="kstlib.rapi.client"):
            keys = self._resolve_with(monkeypatch, {"count_keys": [1, 2]})
        assert keys.count_keys == ()
        assert any("rapi.extraction.count_keys" in r.getMessage() for r in self._security_records(caplog))

    def test_non_list_rejected(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        """A non-list value (e.g. a bare string) is rejected; value not logged."""
        with caplog.at_level("WARNING", logger="kstlib.rapi.client"):
            keys = self._resolve_with(monkeypatch, {"id_keys": "nope"})
        assert keys.id_keys == ()
        assert self._security_records(caplog)
        assert "nope" not in caplog.text

    def test_valid_jmespath_accepted_no_warning(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A valid JMESPath ids_paths override is accepted with no security warning."""
        with caplog.at_level("WARNING", logger="kstlib.rapi.client"):
            keys = self._resolve_with(monkeypatch, {"ids_paths": ["data[*].uuid", "items[?ok].id"]})
        assert keys.ids_paths == ("data[*].uuid", "items[?ok].id")
        assert not self._security_records(caplog)


class TestLoadRapiExtractionConfig:
    """The config loader degrades gracefully to an empty section."""

    def test_empty_when_not_loaded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A missing config yields an empty section."""
        monkeypatch.setattr("kstlib.config.get_config", _raise_not_loaded)
        assert client._load_rapi_extraction_config() == {}

    def test_empty_on_loader_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A loader failure yields an empty section."""

        def _boom() -> NoReturn:
            """Raise to simulate a corrupt-config loader failure."""
            raise RuntimeError("corrupt config")

        monkeypatch.setattr("kstlib.config.get_config", _boom)
        assert client._load_rapi_extraction_config() == {}

    def test_empty_when_cfg_not_mapping(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A non-mapping config object yields an empty section."""
        monkeypatch.setattr("kstlib.config.get_config", lambda: 42)
        assert client._load_rapi_extraction_config() == {}

    def test_empty_when_rapi_not_mapping(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A non-mapping rapi section yields an empty section."""
        monkeypatch.setattr("kstlib.config.get_config", lambda: {"rapi": 5})
        assert client._load_rapi_extraction_config() == {}

    def test_empty_when_extraction_not_mapping(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A non-mapping extraction section yields an empty section."""
        monkeypatch.setattr("kstlib.config.get_config", lambda: {"rapi": {"extraction": 5}})
        assert client._load_rapi_extraction_config() == {}

    def test_returns_section(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A well-formed extraction section is returned as-is."""
        monkeypatch.setattr("kstlib.config.get_config", lambda: {"rapi": {"extraction": {"id_keys": ["x"]}}})
        assert client._load_rapi_extraction_config() == {"id_keys": ["x"]}


class TestPublicApi:
    """RapiResponse default field wiring and public re-exports."""

    def test_bare_response_resolves_embedded_defaults(
        self,
        monkeypatch: pytest.MonkeyPatch,
        cfg_loader: Any,
    ) -> None:
        """A bare RapiResponse resolves its keys from the embedded conf defaults."""
        embedded = Box(cfg_loader._load_default_config(), default_box=True, default_box_attr=None)
        monkeypatch.setattr("kstlib.config.get_config", lambda: embedded)
        keys = RapiResponse(status_code=200).extraction_keys
        assert keys.id_keys == _EXPECTED_ID_KEYS
        assert keys.ids_paths == _EXPECTED_IDS_PATHS
        assert keys.count_keys == _EXPECTED_COUNT_KEYS

    def test_extracted_defaults_empty(self) -> None:
        """A bare RapiResponse starts with an empty extracted box."""
        assert dict(RapiResponse(status_code=200).extracted) == {}

    def test_reexported_from_rapi(self) -> None:
        """RapiResponse is part of the public kstlib.rapi API."""
        import kstlib.rapi as rapi_pkg

        assert rapi_pkg.RapiResponse is RapiResponse
        assert "RapiResponse" in rapi_pkg.__all__


class TestEvalExtract:
    """The endpoint extract: evaluation into a result Box."""

    def test_no_extract_returns_empty_box(self) -> None:
        """A None or empty extract map yields an empty Box."""
        assert dict(client._eval_extract(None, {"id": "x"}, "")) == {}
        assert dict(client._eval_extract({}, {"id": "x"}, "")) == {}

    def test_body_keyword_yields_text(self) -> None:
        """The $body keyword yields the raw response text."""
        assert dict(client._eval_extract({"state": "$body"}, None, "RUNNING")) == {"state": "RUNNING"}

    def test_simple_expression(self) -> None:
        """A simple JMESPath expression extracts the matched value."""
        assert dict(client._eval_extract({"region": "meta.region"}, {"meta": {"region": "eu"}}, "")) == {"region": "eu"}

    def test_filter_expression(self) -> None:
        """A JMESPath filter expression extracts a filtered list."""
        data = {"items": [{"id": "a", "ok": True}, {"id": "b", "ok": False}]}
        assert dict(client._eval_extract({"good": "items[?ok].id"}, data, "")) == {"good": ["a"]}

    def test_missing_key_yields_none(self) -> None:
        """An expression matching nothing yields None."""
        assert dict(client._eval_extract({"x": "missing.key"}, {"a": 1}, "")) == {"x": None}

    def test_non_json_yields_none(self) -> None:
        """A non-JSON body yields None for a normal expression."""
        assert dict(client._eval_extract({"x": "a.b"}, None, "plain text")) == {"x": None}

    def test_eval_error_yields_none_with_sanitized_warning(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A runtime JMESPath error stores None and never logs the body value."""

        def _boom(*args: object, **kwargs: object) -> NoReturn:
            """Simulate a runtime JMESPath evaluation error."""
            raise JMESPathError("boom")

        monkeypatch.setattr("jmespath.search", _boom)
        with caplog.at_level("WARNING", logger="kstlib.rapi.client"):
            extracted = dict(client._eval_extract({"v": "a.b"}, {"a": {"b": "secret-value"}}, ""))
        assert extracted["v"] is None
        assert [r for r in caplog.records if "failed to evaluate" in r.getMessage()]
        assert "secret-value" not in caplog.text


class TestExtractIntegration:
    """extract: results feed RapiResponse accessors (cascade extracted > heuristic)."""

    def test_extract_overrides_id_heuristic(self) -> None:
        """An extracted id wins over the heuristic in .id."""
        extracted = client._eval_extract({"id": "userId"}, {"userId": "u-42", "id": "ignored"}, "")
        resp = RapiResponse(status_code=200, data={"id": "ignored"}, extracted=extracted)
        assert resp.id == "u-42"

    def test_custom_extract_key_accessible(self) -> None:
        """A custom extract key is accessible via response.extracted."""
        extracted = client._eval_extract({"region": "meta.region"}, {"meta": {"region": "eu"}}, "")
        resp = RapiResponse(status_code=200, data={"meta": {"region": "eu"}}, extracted=extracted)
        assert dict(resp.extracted)["region"] == "eu"


class TestExtractionTrace:
    """Source-of-cascade TRACE seeding on the extraction layer (code-logging.md Section C)."""

    def test_keys_absent_from_config_trace(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """When config loading fails, each key list TRACEs that it is absent."""
        monkeypatch.setattr("kstlib.config.get_config", _raise_not_loaded)
        with caplog.at_level(TRACE_LEVEL, logger="kstlib.rapi.client"):
            client._resolve_extraction_keys()
        messages = [record.getMessage() for record in caplog.records]
        assert any("extraction id_keys absent from config" in m for m in messages), messages
        assert any("extraction ids_paths absent from config" in m for m in messages), messages
        assert any("extraction count_keys absent from config" in m for m in messages), messages

    def test_keys_resolved_from_config_trace(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A configured key list TRACEs that it resolved from config (absent ones too)."""
        monkeypatch.setattr(
            "kstlib.config.get_config",
            lambda: {"rapi": {"extraction": {"id_keys": ["idx", "index"]}}},
        )
        with caplog.at_level(TRACE_LEVEL, logger="kstlib.rapi.client"):
            client._resolve_extraction_keys()
        messages = [record.getMessage() for record in caplog.records]
        assert any("extraction id_keys resolved from config" in m for m in messages), messages
        assert any("extraction ids_paths absent from config" in m for m in messages), messages

    def test_id_from_field_trace(self, caplog: pytest.LogCaptureFixture) -> None:
        """The .id accessor TRACEs which root id_keys field matched."""
        with caplog.at_level(TRACE_LEVEL, logger="kstlib.rapi.client"):
            _ = RapiResponse(status_code=200, data={"name": "n", "uri": "u"}).id
        messages = [record.getMessage() for record in caplog.records]
        assert any("resolved .id from field 'uri'" in m for m in messages), messages

    def test_id_no_match_trace(self, caplog: pytest.LogCaptureFixture) -> None:
        """The .id accessor TRACEs when no id_keys field matched on a dict."""
        with caplog.at_level(TRACE_LEVEL, logger="kstlib.rapi.client"):
            _ = RapiResponse(status_code=200, data={"foo": "bar"}).id
        messages = [record.getMessage() for record in caplog.records]
        assert any(".id: no id_keys field matched" in m for m in messages), messages

    def test_id_from_list_item_field_trace(self, caplog: pytest.LogCaptureFixture) -> None:
        """A list payload TRACEs the first-item field used for .id."""
        with caplog.at_level(TRACE_LEVEL, logger="kstlib.rapi.client"):
            _ = RapiResponse(status_code=200, data=[{"id": "a"}, {"id": "b"}], endpoint_ref="x.list").id
        messages = [record.getMessage() for record in caplog.records]
        assert any("resolved .id from first list item field 'id'" in m for m in messages), messages

    def test_id_from_extract_trace(self, caplog: pytest.LogCaptureFixture) -> None:
        """An extract:-provided id TRACEs its source as the directive."""
        with caplog.at_level(TRACE_LEVEL, logger="kstlib.rapi.client"):
            _ = RapiResponse(status_code=200, data={"id": "h"}, extracted=Box({"id": "forced"})).id
        messages = [record.getMessage() for record in caplog.records]
        assert any("resolved .id from extract: directive" in m for m in messages), messages

    def test_ids_from_extract_trace(self, caplog: pytest.LogCaptureFixture) -> None:
        """An extract:-provided ids list TRACEs source and item count."""
        with caplog.at_level(TRACE_LEVEL, logger="kstlib.rapi.client"):
            _ = RapiResponse(status_code=200, data={}, extracted=Box({"ids": ["a", "b"]})).ids
        messages = [record.getMessage() for record in caplog.records]
        assert any("resolved .ids from extract: directive (2 items)" in m for m in messages), messages

    def test_ids_from_path_trace(self, caplog: pytest.LogCaptureFixture) -> None:
        """The .ids accessor TRACEs the JMESPath and item count that matched."""
        with caplog.at_level(TRACE_LEVEL, logger="kstlib.rapi.client"):
            _ = RapiResponse(status_code=200, data={"items": [{"id": "a"}, {"id": "b"}]}).ids
        messages = [record.getMessage() for record in caplog.records]
        assert any("resolved .ids from 'items[*].id' (2 items)" in m for m in messages), messages

    def test_ids_none_trace(self, caplog: pytest.LogCaptureFixture) -> None:
        """The .ids accessor TRACEs when no ids_paths matched."""
        with caplog.at_level(TRACE_LEVEL, logger="kstlib.rapi.client"):
            _ = RapiResponse(status_code=200, data={"foo": "bar"}).ids
        messages = [record.getMessage() for record in caplog.records]
        assert any(".ids: no ids_paths matched" in m for m in messages), messages

    def test_count_from_extract_trace(self, caplog: pytest.LogCaptureFixture) -> None:
        """An extract:-provided count TRACEs source and value."""
        with caplog.at_level(TRACE_LEVEL, logger="kstlib.rapi.client"):
            _ = RapiResponse(status_code=200, data={}, extracted=Box({"count": 99})).count
        messages = [record.getMessage() for record in caplog.records]
        assert any("resolved .count from extract: directive -> 99" in m for m in messages), messages

    def test_count_from_field_trace(self, caplog: pytest.LogCaptureFixture) -> None:
        """The .count accessor TRACEs the matched field and value."""
        with caplog.at_level(TRACE_LEVEL, logger="kstlib.rapi.client"):
            _ = RapiResponse(status_code=200, data={"total": 7}).count
        messages = [record.getMessage() for record in caplog.records]
        assert any("resolved .count from field 'total' -> 7" in m for m in messages), messages

    def test_count_none_trace(self, caplog: pytest.LogCaptureFixture) -> None:
        """The .count accessor TRACEs when no count_keys field matched."""
        with caplog.at_level(TRACE_LEVEL, logger="kstlib.rapi.client"):
            _ = RapiResponse(status_code=200, data={"foo": "bar"}).count
        messages = [record.getMessage() for record in caplog.records]
        assert any(".count: no count_keys field matched" in m for m in messages), messages

    def test_next_url_from_extract_trace_hides_url(self, caplog: pytest.LogCaptureFixture) -> None:
        """The .next_url accessor TRACEs the source but never the URL value."""
        with caplog.at_level(TRACE_LEVEL, logger="kstlib.rapi.client"):
            _ = RapiResponse(status_code=200, data={}, extracted=Box({"next_url": "/secret-token-xyz"})).next_url
        messages = [record.getMessage() for record in caplog.records]
        assert any("resolved .next_url from extract: directive" in m for m in messages), messages
        assert "/secret-token-xyz" not in caplog.text

    def test_next_url_from_jmespath_trace_hides_url(self, caplog: pytest.LogCaptureFixture) -> None:
        """The .next_url JMESPath branch TRACEs the source but never the URL value."""
        data = {"links": [{"rel": "next", "href": "/page-secret-xyz"}]}
        with caplog.at_level(TRACE_LEVEL, logger="kstlib.rapi.client"):
            _ = RapiResponse(status_code=200, data=data).next_url
        messages = [record.getMessage() for record in caplog.records]
        assert any("resolved .next_url from JMESPath" in m for m in messages), messages
        assert "/page-secret-xyz" not in caplog.text

    def test_eval_extract_body_keyword_trace_hides_text(self, caplog: pytest.LogCaptureFixture) -> None:
        """The $body keyword TRACEs type and length but never the body text."""
        with caplog.at_level(TRACE_LEVEL, logger="kstlib.rapi.client"):
            client._eval_extract({"state": "$body"}, None, "RUNNING")
        messages = [record.getMessage() for record in caplog.records]
        assert any("extract 'state' resolved from $body keyword (type=str, len=7)" in m for m in messages), messages
        assert "RUNNING" not in caplog.text

    def test_eval_extract_jmespath_trace_present(self, caplog: pytest.LogCaptureFixture) -> None:
        """A JMESPath hit TRACEs the expression, type, and presence flag."""
        with caplog.at_level(TRACE_LEVEL, logger="kstlib.rapi.client"):
            client._eval_extract({"region": "meta.region"}, {"meta": {"region": "eu"}}, "")
        messages = [record.getMessage() for record in caplog.records]
        assert any("extract 'region' resolved from JMESPath 'meta.region'" in m for m in messages), messages
        assert any("type=str, present=True" in m for m in messages), messages

    def test_eval_extract_jmespath_trace_absent(self, caplog: pytest.LogCaptureFixture) -> None:
        """A JMESPath miss TRACEs present=False and a NoneType result."""
        with caplog.at_level(TRACE_LEVEL, logger="kstlib.rapi.client"):
            client._eval_extract({"x": "missing.key"}, {"a": 1}, "")
        messages = [record.getMessage() for record in caplog.records]
        assert any("present=False" in m and "type=NoneType" in m for m in messages), messages

    def test_eval_extract_body_not_json_trace(self, caplog: pytest.LogCaptureFixture) -> None:
        """A non-JSON body TRACEs that the key stored None."""
        with caplog.at_level(TRACE_LEVEL, logger="kstlib.rapi.client"):
            client._eval_extract({"x": "a.b"}, None, "plain text")
        messages = [record.getMessage() for record in caplog.records]
        assert any("extract 'x': body not JSON, storing None" in m for m in messages), messages

    def test_eval_extract_trace_does_not_leak_value(self, caplog: pytest.LogCaptureFixture) -> None:
        """The _eval_extract TRACE logs source and type but never the extracted value."""
        with caplog.at_level(TRACE_LEVEL, logger="kstlib.rapi.client"):
            client._eval_extract({"token": "creds.secret"}, {"creds": {"secret": "super-secret-xyz"}}, "")
        messages = [record.getMessage() for record in caplog.records]
        assert any("extract 'token' resolved from JMESPath 'creds.secret'" in m for m in messages), messages
        assert "super-secret-xyz" not in caplog.text
