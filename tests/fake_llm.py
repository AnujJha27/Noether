#!/usr/bin/env python3
import json
import sys

request = json.load(sys.stdin)
if request.get("agent") == "critic":
    print(json.dumps({"ordered_ids": [], "feedback": "fixture critic"}))
else:
    print(json.dumps({"candidates": [{"patch": "by rfl", "rationale": "fixture"}]}))
