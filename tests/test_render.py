"""Tests for render.py — HTML rendering and XSS prevention."""

import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def test_render_returns_html():
    """render() returns a string containing HTML boilerplate."""
    from render import render
    html = render("Hello world editorial content.", date="April 26, 2026")
    assert "<!DOCTYPE html>" in html
    assert "Hello world editorial content." in html


def test_render_escape():
    """Claude output containing HTML/JS must be escaped, not executed."""
    from render import render
    malicious = '<script>alert(1)</script>'
    html = render(malicious, date="April 26, 2026")

    assert "<script>" not in html
    assert "alert(1)" in html  # content preserved but tags escaped
    assert "&lt;script&gt;" in html or "&#39;" in html or "&lt;" in html


def test_render_includes_date():
    """render() includes the supplied date string in output."""
    from render import render
    html = render("Some editorial.", date="April 26, 2026")
    assert "April 26, 2026" in html


def test_render_scope_note():
    """Email template includes the GitHub-only scope note."""
    from render import render
    html = render("Editorial.", date="April 26, 2026")
    assert "GitHub" in html
