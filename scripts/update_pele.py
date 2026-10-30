#!/usr/bin/env python
"""Download a pinned build of Pele and store it as ``core/assets/pele.js``.

Pele (https://github.com/obsidianmd/pele) renders Mermaid diagrams to SVG.
ope runs its browser build (``dist/pele.global.js``) in the embedded V8 of
mini-racer, so no Node.js is needed at export time. The build is stored in
the package, like Luxon for DataviewJS.

The script fetches the npm tarball of :data:`VERSION`, checks it against the
``integrity`` hash the npm registry publishes, and writes the build with the
full text of Pele's ``LICENSE`` (MIT, plus the ISC notice of the Lucide icon
it contains) in a comment at the top. Run from the repository root:

    uv run python scripts/update_pele.py             # write the asset
    uv run python scripts/update_pele.py --check     # exit 1 if it is not the pinned build

After changing :data:`VERSION`, also change ``PELE_VERSION`` in
``obsidian_pdf_exporter/core/mermaid_pele.py``.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import sys
import tarfile
import urllib.request
from pathlib import Path

VERSION = "1.12.0"
REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "obsidian_pdf_exporter" / "core" / "assets" / "pele.js"
REGISTRY = "https://registry.npmjs.org/pele"


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310 - fixed https URL
        return response.read()


def build() -> str:
    """Return the asset text: license comment plus the browser build."""
    meta = json.loads(fetch(f"{REGISTRY}/{VERSION}"))
    tarball = fetch(meta["dist"]["tarball"])
    algorithm, _, expected = meta["dist"]["integrity"].partition("-")
    digest = base64.b64encode(hashlib.new(algorithm, tarball).digest()).decode("ascii")
    if digest != expected:
        sys.exit(f"pele {VERSION}: tarball does not match the registry integrity hash")
    with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as archive:
        license_text = _member(archive, "package/LICENSE")
        code = _member(archive, "package/dist/pele.global.js")
    notice = license_text.strip().replace("*/", "* /")
    header = f"/*! Pele {VERSION} | https://github.com/obsidianmd/pele\n\n{notice}\n*/\n"
    return header + code


def _member(archive: tarfile.TarFile, name: str) -> str:
    member = archive.extractfile(name)
    if member is None:
        sys.exit(f"pele {VERSION}: {name} missing from the tarball")
    return member.read().decode("utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="only compare, do not write")
    args = parser.parse_args()
    text = build()
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            sys.exit(f"{OUT.relative_to(REPO)} is not Pele {VERSION}; run scripts/update_pele.py")
        print(f"{OUT.relative_to(REPO)} is Pele {VERSION}")
        return
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)} (Pele {VERSION}, {len(text) // 1024} KiB)")


if __name__ == "__main__":
    main()
