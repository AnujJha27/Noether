#!/usr/bin/env python3
import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    if request.get("type") == "ping":
        response = {"version": 1, "id": request["id"], "status": "ok"}
    elif request.get("type") == "search_batch":
        results = []
        winner = None
        for candidate in request["candidates"]:
            verified = candidate["patch"] in ("by rfl", "good")
            status = "verified" if verified else "lean_error"
            results.append({"version": 1, "id": candidate["id"], "status": status,
                            "elapsed_ms": 1, "cached": False,
                            "diagnostics": "type mismatch" if not verified else ""})
            if verified and winner is None:
                winner = candidate["id"]
                if request.get("stop_on_first_success"):
                    break
        response = {"version": 1, "id": request["id"],
                    "status": "verified" if winner else "no_candidate_verified",
                    "results": results}
        if winner:
            response["winner_id"] = winner
    else:
        response = {"version": 1, "id": request.get("id", ""),
                    "status": "invalid_request"}
    print(json.dumps(response), flush=True)
