"""Read-only Qdrant observations, independent of framework projection state."""

import hashlib
import json
from urllib.request import Request, urlopen


def observe(url, prefix, fingerprint, api_key=None):
    namespace = "semantic_" + fingerprint
    collection = prefix + "_" + hashlib.sha256(namespace.encode()).hexdigest()
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["api-key"] = api_key
    request = Request(
        url.rstrip("/") + f"/collections/{collection}/points/scroll",
        data=json.dumps({"limit": 100, "with_payload": True, "with_vector": False}).encode(),
        headers=headers,
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        result = json.load(response)["result"]
    if result.get("next_page_offset") is not None:
        raise RuntimeError("Acceptance fixture exceeded its bounded remote observation")
    return {
        "collection": collection,
        "ids": sorted(point["id"] for point in result["points"]),
        "payloads": [point.get("payload", {}) for point in result["points"]],
    }
