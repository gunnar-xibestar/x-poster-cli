#!/usr/bin/env python3
"""Fail (exit 1) if a deploy tarball contains secrets or runtime state: env files, *.jsonl, state files, crash logs."""
import re, sys, tarfile

BAD = re.compile(r"(^|/)(\.?env(\..*)?|state\.json|queue\.json|found\.json|filtered\.json|crash\.log|.*\.jsonl|.*\.pem|.*\.key)$")
OK = re.compile(r"(^|/)\.env\.example$")


def bad_members(path):
    with tarfile.open(path) as t:
        return [m.name for m in t.getmembers() if BAD.search(m.name) and not OK.search(m.name)]


if __name__ == "__main__":
    bad = bad_members(sys.argv[1] if len(sys.argv) > 1 else "xbot.tar.gz")
    if bad:
        print("refusing to deploy: tarball contains " + ", ".join(bad)); sys.exit(1)
    print("tarball ok")
