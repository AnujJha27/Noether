#!/usr/bin/env python3
import hashlib
import json
import pathlib
import sys

artifact = None
for index, argument in enumerate(sys.argv[:-2]):
    if argument == "--ro-bind" and sys.argv[index + 2] == "/input/model.pt2":
        artifact = pathlib.Path(sys.argv[index + 1])
        break
if artifact is None:
    print("artifact bind was missing", file=sys.stderr)
    raise SystemExit(2)

print(json.dumps({
    "status": "ok",
    "extractor_version": "fake-inventory-v1",
    "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
    "inventory": {"nodes": []},
    "facts": {},
}))
