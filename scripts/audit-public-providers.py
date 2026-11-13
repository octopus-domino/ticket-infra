#!/usr/bin/env python3
"""Explicit production smoke check. Only poetry preparation writes an anonymous result snapshot."""
import json
import time
import urllib.parse
import urllib.request
import urllib.error

BASE = "https://www.codoc.site"

def call(path, payload=None):
    request = urllib.request.Request(BASE + path,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "CoDoc-release-audit/1.0"})
    start = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=140) as response:
            body = json.load(response)
            print(path.split("?")[0], response.status, "seconds=", round(time.monotonic()-start, 1), flush=True)
            return body
    except urllib.error.HTTPError as error:
        body = json.load(error)
        print(path.split("?")[0], error.code, body.get("error"), flush=True)
        raise

places = call("/api/journeys/routes/places?" + urllib.parse.urlencode({"longitude":37.62,"latitude":55.75,"kind":"attractions","language":"ru"}))
assert places["places"], "No nearby places"
print("places=", len(places["places"]), "source=", places["source"], flush=True)
road = call("/api/journeys/routes/road", {"start":{"longitude":37.6175,"latitude":55.752},"end":{"longitude":37.621,"latitude":55.754},"mode":"foot"})
assert len(road["coordinates"]) >= 2 and road["durationSeconds"] > 0
print("walkingPoints=", len(road["coordinates"]), flush=True)
poetry = call("/api/journeys/poetry", {"latitude":55.75,"longitude":37.62,"zone":"Europe/Moscow","language":"ru","mood":"heartfelt","audience":"middle","seed":"release-audit"})
assert len(poetry["bundle"]["cards"]) == 7
print("poetryCards=", len(poetry["bundle"]["cards"]), flush=True)
