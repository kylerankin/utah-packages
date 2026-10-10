#!/usr/bin/env python3
"""Regression: pcsc-lite-ccid must not disable pcscd.service on erase.

pcsc-lite-ccid is a USB CCID *driver*; pcscd.service is owned by the separate
pcsc-lite package. On erase ($1 == 0), %systemd_preun runs remove-system-units
and stops and disables the unit, so removing the driver took down the shared
smartcard daemon this package does not manage (projectbluefin/utah-packages#430).
This pins that the %preun no longer manages pcscd.service.
"""

from __future__ import annotations

from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "packages" / "pcsc-lite-ccid" / "pcsc-lite-ccid.spec"


def section_body(text: str, name: str) -> str:
    """Return the body of the %<name> scriptlet section (up to the next section).

    Macro lines (%systemd_*, %meson_*, ...) are not section headers; only a
    bare %name line starts a new section.
    """
    match = re.search(rf"^%{name}\s*$", text, re.MULTILINE)
    if not match:
        # A driver needs no teardown on erase; an absent %preun is valid.
        return ""
    tail = text[match.end():]
    nxt = re.search(r"^%(?!systemd_)[a-z]+\s*$", tail, re.MULTILINE)
    return tail[:nxt.start() if nxt else None]


class PreunScriptletTests(unittest.TestCase):
    def test_preun_does_not_disable_pcscd(self):
        body = section_body(SPEC.read_text(), "preun")
        self.assertNotRegex(body, r"%systemd_preun\s+pcscd\.service")
        self.assertNotRegex(body, r"systemctl\s+(disable|stop)\b")

    def test_preun_explains_the_noop(self):
        body = section_body(SPEC.read_text(), "preun")
        # The deliberate no-op is documented so a re-import cannot reintroduce it.
        self.assertIn("pcsc-lite", body)
        # RPM macro-expands lines in comments; unescaped macro tokens in comments break scriptlets
        self.assertNotRegex(body, r"^#[^\n]*%(?!%)[a-z_]+")


if __name__ == "__main__":
    unittest.main()
