"""
Tests for the stderr sanitizer in kraken_cli.

Resolves docs/tech-debt.md MEDIO: "stderr do Kraken CLI exposto sem sanitizacao".
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from execution.kraken_cli import _MAX_STDERR_CHARS, _sanitize_stderr


def test_empty_returns_empty():
    assert _sanitize_stderr("") == ""
    assert _sanitize_stderr(None) == ""


def test_normal_message_unchanged():
    msg = "Connection refused on port 7777"
    assert _sanitize_stderr(msg) == msg


def test_windows_path_redacted():
    msg = r"Error reading C:\Users\alice\.kraken\private.pem"
    out = _sanitize_stderr(msg)
    assert "C:\\Users" not in out
    assert "<path>" in out


def test_posix_home_redacted():
    msg = "Cannot open /home/bob/secrets/key.json"
    out = _sanitize_stderr(msg)
    assert "/home/bob" not in out
    assert "<path>" in out


def test_macos_home_redacted():
    msg = "Failed: /Users/charlie/.kraken/api.key not found"
    out = _sanitize_stderr(msg)
    assert "/Users/charlie" not in out
    assert "<path>" in out


def test_long_hex_redacted():
    # 40+ char hex strings (potential keys/hashes/sigs)
    msg = "Signature 0x1234567890abcdef1234567890abcdef12345678ab failed"  # pragma: allowlist secret
    out = _sanitize_stderr(msg)
    assert "1234567890abcdef1234567890abcdef12345678ab" not in out  # pragma: allowlist secret
    assert "<hex>" in out


def test_short_hex_kept():
    # Short hex like exit codes or small ids should not be redacted
    msg = "exit code 0xff"
    out = _sanitize_stderr(msg)
    assert "0xff" in out


def test_truncation_at_max_chars():
    long_msg = "x" * (_MAX_STDERR_CHARS + 500)
    out = _sanitize_stderr(long_msg)
    assert len(out) <= _MAX_STDERR_CHARS


def test_strips_whitespace():
    msg = "   error message   \n\n"
    out = _sanitize_stderr(msg)
    assert out == "error message"


def test_combined_path_and_hex():
    msg = (
        r"FATAL: cannot decrypt /home/dave/.kraken/key with sig "
        "abcdef0123456789abcdef0123456789abcdef0123"  # pragma: allowlist secret
    )
    out = _sanitize_stderr(msg)
    assert "/home/dave" not in out
    assert "abcdef0123456789abcdef0123456789abcdef0123" not in out  # pragma: allowlist secret
    assert "<path>" in out
    assert "<hex>" in out
