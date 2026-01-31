"""Tests for validation utilities."""

from __future__ import annotations

import pytest

from kstlib.utils import EmailAddress, ValidationError, normalize_address_list, parse_email_address


class TestParseEmailAddress:
    """Validate parsing behaviour."""

    def test_parses_plain_address(self) -> None:
        """Parse simple email addresses without display names."""
        address = parse_email_address("user@example.com")
        assert address.name == ""
        assert address.address == "user@example.com"
        assert address.formatted == "user@example.com"

    def test_parses_address_with_display_name(self) -> None:
        """Extract display names alongside the mailbox."""
        address = parse_email_address("Grace Hopper <grace.hopper@example.org>")
        assert address.name == "Grace Hopper"
        assert address.address == "grace.hopper@example.org"
        assert address.formatted == "Grace Hopper <grace.hopper@example.org>"

    def test_rejects_invalid_address(self) -> None:
        """Reject malformed email addresses."""
        with pytest.raises(ValidationError):
            parse_email_address("invalid-address")

    def test_rejects_empty_strings(self) -> None:
        """Reject empty strings as email addresses."""
        with pytest.raises(ValidationError):
            parse_email_address("")

    def test_rejects_local_part_too_long(self) -> None:
        """Enforce length limits on the local part of the address."""
        long_local = "a" * 65
        with pytest.raises(ValidationError):
            parse_email_address(f"{long_local}@example.com")

    def test_rejects_domain_part_too_long(self) -> None:
        """Enforce length limits on the domain portion."""
        domain = "a" * 256 + ".com"
        with pytest.raises(ValidationError):
            parse_email_address(f"user@{domain}")

    def test_rejects_short_tld(self) -> None:
        """Require top-level domain segments to have a minimum length."""
        with pytest.raises(ValidationError):
            parse_email_address("user@example.c")

    def test_rejects_domains_with_empty_labels(self) -> None:
        """Disallow domains containing empty labels (e.g. consecutive dots)."""

        with pytest.raises(ValidationError):
            parse_email_address("user@example..com")


class TestNormalizeAddressList:
    """Validate collection handling."""

    def test_normalizes_multiple_addresses(self) -> None:
        """Normalize a collection of addresses."""
        addresses = normalize_address_list(["Ada <ada@example.org>", "alan@example.org"])
        assert [addr.address for addr in addresses] == [
            "ada@example.org",
            "alan@example.org",
        ]

    def test_propagates_validation_errors(self) -> None:
        """Propagate validation errors from individual addresses."""
        with pytest.raises(ValidationError):
            normalize_address_list(["valid@example.org", "broken @example.org"])


class TestEmailAddress:
    """Direct EmailAddress behaviour."""

    def test_formatted_property_uses_display_name(self) -> None:
        """Render formatted string with display name."""
        address = EmailAddress(name="Test User", address="test@example.org")
        assert address.formatted == "Test User <test@example.org>"

    def test_formatted_property_without_name(self) -> None:
        """Render formatted string without display name."""
        address = EmailAddress(name="", address="user@example.org")
        assert address.formatted == "user@example.org"

    def test_formatted_property_sanitizes_display_name(self) -> None:
        """Strip control characters and escape quotes in display names."""
        raw_name = 'User\r\nBcc: "evil"'
        address = EmailAddress(name=raw_name, address="user@example.org")
        formatted = address.formatted
        assert "\r" not in formatted and "\n" not in formatted
        assert "'" in formatted

    def test_formatted_property_ignores_blank_display_name(self) -> None:
        """Return the raw address when sanitization leaves an empty name."""

        address = EmailAddress(name="  \r\n  ", address="blank@example.org")

        assert address.formatted == "blank@example.org"
