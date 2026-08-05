#!/usr/bin/env python3
import json
import os
import sys

request = json.load(sys.stdin)
if request.get("agent") == "critic":
    print(json.dumps({"ordered_ids": [], "feedback": "fixture critic"}))
else:
    patch = "bad" if os.environ.get("FAKE_LLM_BAD") else "by rfl"
    print(json.dumps({"candidates": [{"patch": patch, "rationale": "fixture"}]}))
