#!/usr/bin/env python3
"""Convert H3 V1/V2 reference bundles without rendering or deleting them."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reference_cache_migration import LEGACY_FORMATS, ReferenceCacheMigrator


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", required=True, type=Path,
                        help="ComfyUI output directory containing h3_reference_cache/h3_chains")
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--metadata", action="append", help="Exact scene cache JSON (repeatable)")
    scope.add_argument("--run", help="Convert only this project's reference_cache directory")
    scope.add_argument("--all", action="store_true", help="Scan shared and project-local reference caches")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="Write resumable V3 conversions; bundles retire only after a successful H3 render save")
    mode.add_argument("--dry-run", action="store_true", help="Read-only report (the default)")
    args = parser.parse_args(argv)
    migrator = ReferenceCacheMigrator(args.output_root)
    if not migrator.root.is_dir():
        parser.error("output root does not exist")
    if args.run and (Path(args.run).name != args.run or args.run in (".", "..")):
        parser.error("--run must be one project directory name")
    if args.run:
        parent = migrator.absolute(Path("h3_chains") / args.run / "reference_cache")
        if not parent.is_dir():
            parser.error("project reference_cache directory does not exist")
        paths = [path for path in parent.glob("scene_*.json")
                 if not path.name.endswith((".converted.json", ".retired.json"))]
    else:
        paths = [migrator.absolute(path) for path in args.metadata] if args.metadata else list(migrator.legacy_manifests())
    failures = 0
    for path in sorted(set(paths)):
        try:
            if migrator.read(path).get("format") not in LEGACY_FORMATS:
                continue
            result = migrator.convert(path, apply=args.apply)
            print(json.dumps(result))
        except Exception as exc:
            failures += 1
            print(json.dumps({"status": "error", "metadata": str(path), "error": str(exc)}))
    print(json.dumps({"mode": "apply" if args.apply else "dry_run", "errors": failures,
                      "legacy_bundles_deleted": 0}))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
