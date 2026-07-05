#!/usr/bin/python3
"""Check a KWin CTM patch strictly without modifying its source tree."""

import argparse
import pathlib
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument("patch", type=pathlib.Path)
parser.add_argument("source", type=pathlib.Path)
args = parser.parse_args()
raise SystemExit(subprocess.run([
    "patch", "--dry-run", "--batch", "--forward", "--fuzz=0", "-p1",
    "-i", str(args.patch.resolve()),
], cwd=args.source).returncode)
