"""
Download ALL data from the D&D 5e API (dnd5eapi.co) into local JSON files.

What it does:
1) Fetches the API index at /api to discover all top-level endpoints.
2) For each endpoint, walks pagination (if present) using the `next` field.
3) Saves:
   - one JSON file per endpoint under ./dnd5eapi_dump/
   - a master index file with endpoint metadata

Requirements:
  pip install requests
(Optional):
  pip install tqdm
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests

try:
    from tqdm import tqdm
except Exception:  # pragma: no cover
    tqdm = None  # type: ignore


BASE_URL = "https://www.dnd5eapi.co"
API_INDEX_PATH = "/api"
OUT_DIR = "dnd5eapi_dump"

# Be polite to the public API
REQUEST_TIMEOUT = 30
SLEEP_BETWEEN_REQUESTS_SEC = 0.15
MAX_RETRIES = 5
BACKOFF_SEC = 0.75


@dataclass
class FetchStats:
    requests_made: int = 0
    items_collected: int = 0


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def safe_filename(name: str) -> str:
    return "".join(c if (c.isalnum() or c in "-_.") else "_" for c in name).strip("_")


def is_absolute_url(url: str) -> bool:
    return bool(urlparse(url).scheme and urlparse(url).netloc)


def normalize_url(maybe_relative: str) -> str:
    # The API sometimes returns relative paths like "/api/spells"
    return maybe_relative if is_absolute_url(maybe_relative) else urljoin(BASE_URL, maybe_relative)


def request_json(session: requests.Session, url: str) -> Dict[str, Any]:
    last_err: Optional[Exception] = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT)
            # Handle rate-limit-ish behavior
            if resp.status_code in (429, 503):
                retry_after = resp.headers.get("Retry-After")
                wait = float(retry_after) if retry_after and retry_after.isdigit() else BACKOFF_SEC * attempt
                time.sleep(wait)
                continue

            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            last_err = e
            time.sleep(BACKOFF_SEC * attempt)
    raise RuntimeError(f"Failed to fetch {url} after {MAX_RETRIES} retries. Last error: {last_err}")


def fetch_paginated_collection(
    session: requests.Session,
    start_url: str,
    stats: FetchStats,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Walks pages if the response is a collection.
    Common D&D 5e API collection shape includes:
      { "count": int, "results": [...], "next": "..." (optional), "previous": "..." (optional) }
    Some endpoints may just return a dict for non-collection resources; we treat those separately elsewhere.
    """
    items: List[Dict[str, Any]] = []
    meta: Dict[str, Any] = {"start_url": start_url, "pages": []}

    url = start_url
    while url:
        time.sleep(SLEEP_BETWEEN_REQUESTS_SEC)
        data = request_json(session, url)
        stats.requests_made += 1

        # Record page meta lightly
        page_info = {
            "url": url,
            "count": data.get("count"),
            "num_results": len(data.get("results", [])) if isinstance(data.get("results"), list) else None,
            "next": data.get("next"),
            "previous": data.get("previous"),
        }
        meta["pages"].append(page_info)

        # If this is a collection page, accumulate results
        if isinstance(data, dict) and isinstance(data.get("results"), list):
            for r in data["results"]:
                if isinstance(r, dict):
                    items.append(r)
                else:
                    # Rare, but keep it robust
                    items.append({"value": r})

            next_url = data.get("next")
            url = normalize_url(next_url) if next_url else ""
        else:
            # Not a standard collection shape -> stop
            meta["non_collection_payload_sample"] = data
            break

    stats.items_collected += len(items)
    return items, meta


def fetch_full_objects_for_results(
    session: requests.Session,
    results: List[Dict[str, Any]],
    stats: FetchStats,
) -> List[Dict[str, Any]]:
    """
    Many collection endpoints return lightweight objects:
      {"index": "...", "name": "...", "url": "/api/spells/acid-arrow"}
    This function follows each item's `url` to retrieve the full object.
    """
    full: List[Dict[str, Any]] = []

    iterable = results
    if tqdm is not None:
        iterable = tqdm(results, desc="Fetching full objects", unit="item")  # type: ignore

    for item in iterable:
        item_url = item.get("url")
        if not isinstance(item_url, str) or not item_url:
            full.append(item)
            continue

        url = normalize_url(item_url)
        time.sleep(SLEEP_BETWEEN_REQUESTS_SEC)
        obj = request_json(session, url)
        stats.requests_made += 1

        # Keep a pointer to original lightweight record (helpful for debugging)
        if isinstance(obj, dict) and "url" not in obj:
            obj["url"] = item_url
        full.append(obj)

    return full


def dump_json(path: str, obj: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def main() -> None:
    ensure_dir(OUT_DIR)
    stats = FetchStats()

    with requests.Session() as session:
        # Discover endpoints
        index_url = normalize_url(API_INDEX_PATH)
        api_index = request_json(session, index_url)
        stats.requests_made += 1

        if not isinstance(api_index, dict):
            raise RuntimeError(f"Unexpected API index payload at {index_url}: {type(api_index)}")

        # The index maps endpoint name -> path, e.g. {"spells": "/api/spells", ...}
        endpoints: Dict[str, str] = {
            k: v for k, v in api_index.items() if isinstance(k, str) and isinstance(v, str)
        }

        # Save the API index
        dump_json(os.path.join(OUT_DIR, "_api_index.json"), api_index)

        master_meta: Dict[str, Any] = {
            "base_url": BASE_URL,
            "fetched_at_unix": int(time.time()),
            "endpoints": {},
            "stats": {},
        }

        for endpoint_name, endpoint_path in sorted(endpoints.items()):
            print(f"\n==> Endpoint: {endpoint_name} ({endpoint_path})")
            endpoint_url = normalize_url(endpoint_path)

            # Try to treat it as a collection first
            results, meta = fetch_paginated_collection(session, endpoint_url, stats)

            # If we got collection results with "url" fields, follow them to get full objects
            if results and isinstance(results[0], dict) and isinstance(results[0].get("url"), str):
                full_objects = fetch_full_objects_for_results(session, results, stats)
                payload = {
                    "endpoint": endpoint_name,
                    "endpoint_url": endpoint_url,
                    "items": full_objects,
                }
            else:
                # Either empty collection or non-collection payload sample
                payload = {
                    "endpoint": endpoint_name,
                    "endpoint_url": endpoint_url,
                    "items": results,
                    "note": "No per-item URLs detected; stored collection results as-is.",
                    "collection_meta": meta,
                }

            out_path = os.path.join(OUT_DIR, f"{safe_filename(endpoint_name)}.json")
            dump_json(out_path, payload)

            master_meta["endpoints"][endpoint_name] = {
                "path": endpoint_path,
                "url": endpoint_url,
                "output_file": os.path.basename(out_path),
                "num_items": len(payload.get("items", [])),
                "collection_walked": bool(meta.get("pages")),
            }

        master_meta["stats"] = {
            "requests_made": stats.requests_made,
            "items_collected": stats.items_collected,
        }
        dump_json(os.path.join(OUT_DIR, "_dump_meta.json"), master_meta)

    print("\nDone.")
    print(f"Saved to: {os.path.abspath(OUT_DIR)}")
    print(f"Requests made: {stats.requests_made}")
    print(f"Items collected (collection-level): {stats.items_collected}")


if __name__ == "__main__":
    main()