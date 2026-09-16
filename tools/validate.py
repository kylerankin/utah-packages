#!/usr/bin/env python3
"""Validate package-factory configuration."""
import json
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.package_inventory import inventory

for path in Path("packages").glob("*/.hummingbird-upstream.json"):
    data = json.loads(path.read_text())
    required = {"package", "branch", "remote", "commit", "tree", "imported_at"}
    if set(data) != required:
        raise SystemExit(f"invalid upstream provenance: {path}")
    if data["branch"] not in ("rawhide", "upstream"):
        raise SystemExit(f"only rawhide or upstream imports are supported: {path}")
    if data["branch"] == "upstream":
        # Direct-upstream recipes (e.g. liblc3plus, libfreeaptx,
        # pipewire-libs-extra) are imported from the project's own release
        # repository rather than Fedora dist-git. They carry a remote and
        # imported_at but no dist-git commit/tree; the verified source lock
        # lives in config/upstream-sources.json instead.
        for key in ("commit", "tree"):
            if data[key]:
                raise SystemExit(f"upstream import must not carry {key}: {path}")
    else:
        # Fedora dist-git imports pin the exact rawhide snapshot.
        for key in ("commit", "tree"):
            if not data[key]:
                raise SystemExit(f"rawhide import must carry {key}: {path}")
records = inventory(Path("."))
missing_locks = sorted(record.name for record in records if not record.source_locked)
missing_packit = sorted(record.name for record in records if not record.packit_configured)
if missing_locks or missing_packit:
    if missing_locks:
        print(f"packages missing source locks: {', '.join(missing_locks)}")
    if missing_packit:
        print(f"packages missing Packit config: {', '.join(missing_packit)}")
    raise SystemExit(1)

# Upstream provenance: every direct-source entry in config/upstream-sources.json
# must fetch its payload from upstream; a Fedora host must never sit in the
# primary ``url`` position. Fedora's lookaside is still allowed as a
# ``fallback_urls`` entry. The exceptions below are packages that cannot be
# re-pinned to a verbatim upstream artifact: they are built from vendored/
# Go source (containerd, runc, mozc, alsa-firmware, alsa-tools), ship no
# tarball at all (kde-filesystem, kf5), are blocked on the FSDK Go image
# (tailscale), or are patched by Fedora so the upstream sdist no longer
# matches the locked hash (python-psutil, python-argcomplete,
# python-dbus-next, python-pydantic-core). The remaining Fedora-primary
# entries (fwupd, graphene, lcms2, livesys-scripts, samba, xmlrpc-c) could
# not be resolved to a verbatim artifact during the re-pin pass.
FEDORA_HOSTS = ("src.fedoraproject.org", "fedoraproject.org")
FEDORA_PRIMARY_EXCEPTIONS = {
    "containerd": "built from vendored Go source (gosource), no upstream tarball",
    "runc": "built from vendored Go source (gosource), no upstream tarball",
    "mozc": "built from vendored Go source (gosource), no upstream tarball",
    "alsa-firmware": "built from ftp.fedoraproject.org source, no upstream tarball",
    "alsa-tools": "built from ftp.fedoraproject.org source, no upstream tarball",
    "kde-filesystem": "no upstream tarball; ships a recipe file (teamnames)",
    "kf5": "no upstream tarball; ships a recipe file (macros.kf5)",
    "tailscale": "blocked on projectbluefin/fsdk-containers Go image; lookaside still required",
    "python-psutil": "Fedora patches the sdist; upstream sdist sha does not match the lock",
    "python-argcomplete": "Fedora patches the sdist; upstream sdist sha does not match the lock",
    "python-dbus-next": "Fedora patches the sdist; upstream sdist sha does not match the lock",
    "python-pydantic-core": "Fedora patches the sdist; upstream sdist sha does not match the lock",
    "fwupd": "upstream release URL could not be resolved to a verbatim artifact",
    "graphene": "upstream release URL could not be resolved to a verbatim artifact",
    "lcms2": "upstream release URL could not be resolved to a verbatim artifact",
    "livesys-scripts": "upstream archive sha does not match the lock",
    "samba": "upstream release URL could not be resolved to a verbatim artifact",
    "xmlrpc-c": "upstream release URL could not be resolved to a verbatim artifact",
}


def _primary_url(entry: dict) -> str | None:
    if "url" in entry:
        return entry["url"]
    if "url_template" in entry and "version" in entry:
        return entry["url_template"].format(version=entry["version"])
    return None


config_path = Path("config/upstream-sources.json")
if config_path.is_file():
    config = json.loads(config_path.read_text())
    violations = []
    for entry in config.get("packages", []):
        url = _primary_url(entry)
        if not url:
            continue  # generated-source entries have no primary url
        if any(host in url for host in FEDORA_HOSTS) and entry["name"] not in FEDORA_PRIMARY_EXCEPTIONS:
            violations.append(entry["name"])
    if violations:
        raise SystemExit(
            "fedora-primary source url not allowed (exceptions are documented in tools/validate.py): "
            + ", ".join(sorted(violations))
        )

print(f"validated {len(records)} source RPMs")
