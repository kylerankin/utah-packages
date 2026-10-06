#!/usr/bin/env python3
"""Source-lock coverage for every recipe plus bootstrap merge/selection behavior."""

import json
from pathlib import Path
import unittest

from tools.bootstrap_upstream_sources import (
    generated_candidate,
    merge_candidates,
    plan_targets,
)
from tools.package_inventory import inventory
from tools.upstream_bump import manifest_pin


ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "upstream-sources.json"


def normalized(data: dict) -> str:
    return json.dumps(data, indent=2) + "\n"


class SourceCoverageTests(unittest.TestCase):
    def test_every_recipe_has_a_source_lock(self):
        records = inventory(ROOT)
        self.assertEqual(
            [record.name for record in records if not record.source_locked],
            [],
        )


class MergeCandidatesTests(unittest.TestCase):
    def setUp(self):
        self.existing = json.loads(CONFIG.read_text())

    def test_merge_without_candidates_preserves_existing_entries(self):
        merged = merge_candidates(self.existing, [])
        self.assertEqual(normalized(merged), normalized(self.existing))

    def test_merge_appends_new_entries_after_existing_ones(self):
        candidate = {
            "name": "brand-new-package",
            "version": "1.0",
            "url": "https://example.org/brand-new-package-1.0.tar.gz",
            "filename": "brand-new-package-1.0.tar.gz",
            "sha512": "ab" * 64,
        }
        merged = merge_candidates(self.existing, [candidate])
        self.assertEqual(merged["packages"][:-1], self.existing["packages"])
        self.assertEqual(merged["packages"][-1], candidate)

    def test_merge_refuses_to_replace_an_existing_lock(self):
        existing_entry = dict(self.existing["packages"][0])
        existing_entry["sha512"] = "ff" * 64
        with self.assertRaisesRegex(ValueError, "already exists"):
            merge_candidates(self.existing, [existing_entry])

    def test_merge_refuses_duplicate_candidates(self):
        candidate = dict(self.existing["packages"][0])
        candidate["name"] = "brand-new-package"
        with self.assertRaisesRegex(ValueError, "duplicate candidate"):
            merge_candidates(self.existing, [candidate, dict(candidate)])


class TargetSelectionTests(unittest.TestCase):
    def test_hummingbird_supplied_packages_are_skipped_by_default(self):
        targets = plan_targets(ROOT / "packages", {"mesa": ["mesa"]})
        self.assertNotIn("mesa", [path.name for path in targets])
        self.assertEqual(len(targets), 404)

    def test_explicit_selection_processes_a_hummingbird_supplied_package(self):
        targets = plan_targets(ROOT / "packages", {"mesa": ["mesa"]}, only="mesa")
        self.assertEqual([path.name for path in targets], ["mesa"])

    def test_explicit_selection_requires_an_existing_recipe(self):
        with self.assertRaisesRegex(ValueError, "no package recipe"):
            plan_targets(ROOT / "packages", {}, only="not-a-package")


class GeneratedSourceTests(unittest.TestCase):
    """Generated Source0 locks: first-party input, deterministic rebuild.

    The payload contract forbids fetching primary source payloads from Fedora
    infrastructure, so generated entries carry no ``url`` at all -- they name
    the factory script that deterministically rebuilds the archive from
    pinned upstream input, and source_pipeline re-runs it on verification.
    """

    def manifest_hash(self, package: str, filename: str) -> str:
        prefix = f"SHA512 ({filename}) = "
        for line in (ROOT / "packages" / package / "sources").read_text().splitlines():
            if line.startswith(prefix):
                return line[len(prefix):]
        raise AssertionError(f"{filename} is not pinned in packages/{package}/sources")

    def lock(self, package: str) -> dict:
        config = json.loads(CONFIG.read_text())
        matches = [entry for entry in config["packages"] if entry["name"] == package]
        self.assertEqual(len(matches), 1)
        return matches[0]

    def assert_first_party_generated(self, entry: dict) -> None:
        self.assertIn("generate", entry)
        self.assertNotIn("url", entry)
        self.assertNotIn("url_template", entry)
        self.assertNotIn("fallback_urls", entry)
        self.assertEqual(entry["generate"]["script"], "tools/generated_sources.py")
        self.assertTrue((ROOT / entry["generate"]["script"]).is_file())
        self.assertNotIn("fedoraproject.org", json.dumps(entry))
        # verify_staged_sources enforces the manifest pin over the lock, so a
        # pinned Source0 filename must agree with the lock's digest.
        self.assertEqual(entry["sha512"], self.manifest_hash(entry["name"], entry["filename"]))

    def test_intel_media_driver_free_lock_regenerates_the_stripped_archive(self):
        candidate = generated_candidate(ROOT / "packages" / "intel-media-driver-free")
        self.assertEqual(candidate["name"], "intel-media-driver-free")
        self.assertEqual(candidate["version"], "26.2.4")
        # The recipe consumes the stripped -free archive; the unstripped
        # upstream tag archive must not be locked in its place.
        self.assertEqual(candidate["filename"], "intel-media-26.2.4-free.tar.gz")
        self.assertIn("intel-media-26.2.4.tar.gz", candidate["generate"]["input"])
        self.assert_first_party_generated(self.lock("intel-media-driver-free"))

    def test_tailscale_lock_remains_lookaside_pinned_pending_go_fsdk_image(self):
        # BLOCKED: tailscale's vendored Source0 can be regenerated
        # deterministically (generated_candidate below stays ready), but the
        # FSDK catalog has no Go-capable image, so the remote-cluster
        # verification the execution-environment policy requires cannot run.
        # The pre-existing lock stays untouched until projectbluefin/fsdk-containers
        # ships a Go image; see the Task 2 report's Pre-review correction.
        candidate = generated_candidate(ROOT / "packages" / "tailscale")
        self.assertEqual(candidate["filename"], "tailscale-1.98.8-vendored.tar.xz")
        self.assertIn("05a91829316e055517a1e84f7b00016846ef4107", candidate["generate"]["input"])
        self.assertIn("go mod vendor", candidate["generate"]["method"])
        self.assertNotIn("generate", self.lock("tailscale"))

    def test_recipe_without_generated_source0_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "no generated source resolver"):
            generated_candidate(ROOT / "packages" / "zsh")


class LockManifestConsistencyTests(unittest.TestCase):
    # Recipes whose manifest pin uses an algorithm the lock records no digest
    # for. Empty: every md5-pinned recipe carries an `md5` lock field (#393).
    # A new entry here must name why its pin cannot be compared.
    MISSING_ALGORITHM_ALLOWED: frozenset[str] = frozenset()

    def manifest_pins(self, text: str) -> dict[str, tuple[str, str]]:
        """Map each pinned filename to its (algorithm, digest) from a manifest.

        Parsing is shared with tools/upstream_bump.py (manifest_pin), which
        reads both the BSD form (`SHA512 (file) = <hex>`, any algorithm) and
        the legacy md5sum form (`<32 hex>  file`). Malformed lines are ignored.
        """
        pins: dict[str, tuple[str, str]] = {}
        for line in text.splitlines():
            pin = manifest_pin(line)
            if pin is not None:
                filename, algorithm, digest = pin
                pins[filename] = (algorithm, digest)
        return pins

    def test_manifest_pins_parses_legacy_md5_lines(self):
        pins = self.manifest_pins(
            "b304bbe8ab63373924a744eac9ebc652  cdparanoia-III-10.2.src.tgz\n"
        )
        self.assertEqual(
            pins,
            {"cdparanoia-III-10.2.src.tgz": ("md5", "b304bbe8ab63373924a744eac9ebc652")},
        )

    def test_manifest_pins_handles_a_mixed_manifest(self):
        text = (
            "SHA512 (a.tar.xz) = " + "a" * 128 + "\n"
            "b304bbe8ab63373924a744eac9ebc652  b.tar.gz\n"
        )
        pins = self.manifest_pins(text)
        self.assertEqual(pins["a.tar.xz"], ("sha512", "a" * 128))
        self.assertEqual(
            pins["b.tar.gz"],
            ("md5", "b304bbe8ab63373924a744eac9ebc652"),
        )

    def test_lock_hash_matches_manifest_pin_when_pinned(self):
        config = json.loads(CONFIG.read_text())
        mismatched = []
        unchecked: list[tuple[str, str]] = []
        for entry in config["packages"]:
            manifest = ROOT / "packages" / entry.get("dist_git_name", entry["name"]) / "sources"
            if not manifest.is_file():
                continue
            pins = self.manifest_pins(manifest.read_text())
            filename = entry.get("filename", "")
            if filename not in pins:
                continue
            algorithm, digest = pins[filename]
            lock_digest = entry.get(algorithm)
            if lock_digest is None:
                # Nothing to compare against: report it rather than letting
                # the pin go unchecked, unless explicitly allowlisted.
                unchecked.append((entry["name"], algorithm))
                continue
            if digest != lock_digest.lower():
                mismatched.append(entry["name"])
        self.assertEqual(mismatched, [])
        self.assertEqual(
            [item for item in unchecked if item[0] not in self.MISSING_ALGORITHM_ALLOWED],
            [],
            "lock entries lack a digest for their manifest pin's algorithm; "
            "add the field to config/upstream-sources.json",
        )
        self.assertEqual(
            sorted(self.MISSING_ALGORITHM_ALLOWED - {name for name, _ in unchecked}),
            [],
            "stale MISSING_ALGORITHM_ALLOWED entries",
        )


if __name__ == "__main__":
    unittest.main()
