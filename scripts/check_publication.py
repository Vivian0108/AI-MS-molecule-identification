#!/usr/bin/env python
"""Conservative credential/path scan of the current tracked publication tree."""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "personal path": re.compile(r"/(?:Users|home)/[A-Za-z0-9_.-]+/"),
    "GitHub token": re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"),
    "OpenAI token": re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{32,}"),
    "AWS key": re.compile(r"AKIA[A-Z0-9]{16}"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}


def main():
    paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    hits = []
    for name in paths:
        p = ROOT / name
        if not p.is_file() or p.suffix in {".parquet", ".png", ".gif", ".pptx"}:
            continue
        try:
            text = p.read_text()
        except UnicodeDecodeError:
            continue
        for label, pattern in PATTERNS.items():
            if pattern.search(text):
                hits.append((name, label))
    for name, label in hits:
        print(f"{name}: {label}")
    if hits:
        raise SystemExit(1)
    print("Publication scan passed: no known credential patterns or personal filesystem paths")


if __name__ == "__main__":
    main()
