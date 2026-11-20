"""Read-only MCP adapter for public Ostrovok city catalog JSON-LD."""

import json
import os
import re
import time
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

ORIGIN = "https://ostrovok.ru"
CITIES = {
    "москва": "moscow", "moscow": "moscow",
    "санкт-петербург": "st._petersburg", "saint petersburg": "st._petersburg",
    "казань": "kazan", "kazan": "kazan",
    "сочи": "sochi", "sochi": "sochi",
    "тверь": "tver", "tver": "tver",
    "кострома": "kostroma", "kostroma": "kostroma",
    "иваново": "ivanovo", "ivanovo": "ivanovo",
    "дмитров": "dmitrov", "dmitrov": "dmitrov",
    "павловский посад": "pavlovskiy_posad", "pavlovsky posad": "pavlovskiy_posad",
}
TOOL = "search_hotels"
PROTOCOL = "2025-03-26"
MAX_PAGE = 2_000_000
SCRIPTS = re.compile(r'<script\b[^>]*\btype=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.I | re.S)

PAGE_DATA = re.compile(r'<script\b[^>]*\bid=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', re.I | re.S)

class SameOriginRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        url = urlsplit(newurl)
        if url.scheme != "https" or url.netloc != "ostrovok.ru" or not url.path.startswith("/hotel/russia/"):
            raise ValueError("Unexpected catalog redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def catalog_locations(html):
    block = PAGE_DATA.search(html)
    if block is None:
        return {}
    try:
        hotels = json.loads(block[1])["props"]["pageProps"]["serpData"]["hotels"]
    except (ValueError, KeyError, TypeError):
        return {}
    if not isinstance(hotels, list):
        return {}
    locations = {}
    for hotel in hotels:
        if not isinstance(hotel, dict):
            continue
        location = hotel.get("location")
        identifier = hotel.get("masterId")
        if not isinstance(location, dict) or not isinstance(identifier, (int, str)):
            continue
        lat, lon = location.get("latitude"), location.get("longitude")
        if type(lat) in (int, float) and type(lon) in (int, float) and -85 <= lat <= 85 and -180 <= lon <= 180:
            locations[str(identifier)] = {"latitude": lat, "longitude": lon}
    return locations


def catalog_slug(label):
    tokens = [re.sub(r"^г\.\s*", "", part.strip().lower()).replace("?", "?") for part in label.split(",")]
    matches = {CITIES[token] for token in tokens if token in CITIES}
    return next(iter(matches)) if len(matches) == 1 else None


def parse_catalog(html, city):
    hotels = {}
    locations = catalog_locations(html)
    for block in SCRIPTS.findall(html):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        if not isinstance(data, dict) or data.get("@type") != "ItemList":
            continue
        for entry in data.get("itemListElement", []):
            item = entry.get("item", {}) if isinstance(entry, dict) else {}
            if not isinstance(item, dict) or item.get("@type") != "Hotel":
                continue
            name, link = item.get("name"), item.get("url")
            if not isinstance(name, str) or not name.strip() or not isinstance(link, str):
                continue
            url = urlsplit(link)
            if url.scheme != "https" or url.netloc != "ostrovok.ru":
                continue
            identifier = re.search(r"/mid(\d+)(?:/|$)", url.path)
            if not identifier:
                continue
            hotel_id = identifier[1]
            address = item.get("address") or {}
            rating = item.get("aggregateRating") or {}
            photos = item.get("image") or []
            photo = next((p for p in photos if isinstance(p, str) and p.startswith("https://cdn.ostrovok.ru/")), None) if isinstance(photos, list) else None
            row = {"id": hotel_id, "city": city, "name": name.strip()[:300], "photoUrl": photo, "sourceUrl": link}
            if isinstance(address, dict):
                row["address"] = address.get("streetAddress")
            if isinstance(rating, dict):
                try:
                    value = float(rating.get("ratingValue"))
                    if 0 <= value <= 10:
                        row["rating"] = value
                except (ValueError, TypeError):
                    pass
            row.update(locations.get(hotel_id, {}))
            hotels[hotel_id] = row
    return list(hotels.values())[:30]


class Catalog:
    def __init__(self):
        self.cache = {}
        self.next_fetch = 0

    def search(self, args):
        city = args.get("city")
        guests = args.get("guests")
        if not isinstance(city, str) or len(city) > 120 or type(guests) is not int or not 1 <= guests <= 12:
            raise ValueError("Invalid hotel query")
        start, end = date.fromisoformat(args["checkIn"]), date.fromisoformat(args["checkOut"])
        if not 1 <= (end - start).days <= 90:
            raise ValueError("Invalid dates")
        slug = catalog_slug(city)
        if not slug:
            raise ValueError("City catalog is not configured")
        now = time.monotonic()
        known = self.cache.get(slug)
        if known and known[0] > now:
            return {"catalogOnly": True, "hotels": known[1]}
        try:
            if self.next_fetch > now:
                raise ValueError("Catalog temporarily busy")
            self.next_fetch = now + 2
            request = Request(f"{ORIGIN}/hotel/russia/{slug}",
                              headers={"User-Agent": "CoDoc-HotelCatalog/1.0 (+https://www.codoc.site)"})
            with build_opener(SameOriginRedirect()).open(request, timeout=6) as response:
                body = response.read(MAX_PAGE + 1)
            if len(body) > MAX_PAGE:
                raise ValueError("Catalog response too large")
            hotels = parse_catalog(body.decode("utf-8"), city.strip())
            if not hotels:
                raise ValueError("Catalog has no recognized listings")
        except (OSError, ValueError):
            if known and now - known[0] <= 86400:
                return {"catalogOnly": True, "hotels": known[1]}
            raise
        self.cache[slug] = (now + 1800, hotels)
        return {"catalogOnly": True, "hotels": hotels}


class Handler(BaseHTTPRequestHandler):
    catalog = Catalog()

    def log_message(self, *_args):
        pass

    def send_json(self, status, value=None):
        data = b"" if value is None else json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        if data:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if data:
            self.wfile.write(data)

    def do_GET(self):
        self.send_json(200, {"status": "ok"}) if self.path == "/health" else self.send_json(405)

    def do_POST(self):
        if self.path != "/mcp":
            return self.send_json(404)
        if self.headers.get("Origin"):
            return self.send_json(403)
        self.connection.settimeout(8)
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 8192:
                return self.send_json(413)
            message = json.loads(self.rfile.read(size))
            if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                return self.send_json(400)
        except (ValueError, OSError):
            return self.send_json(400)
        method = message.get("method")
        if "id" not in message:
            return self.send_json(202)
        response = {"jsonrpc": "2.0", "id": message["id"]}
        if method == "initialize":
            result = {"protocolVersion": PROTOCOL, "capabilities": {"tools": {}},
                      "serverInfo": {"name": "codoc-ostrovok", "version": "1.0"}}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": [{"name": TOOL, "description": "Find public hotel listings in a supported Russian city. Prices and availability are unverified.",
                                "inputSchema": {"type": "object", "properties": {
                                    "city": {"type": "string"}, "checkIn": {"type": "string"},
                                    "checkOut": {"type": "string"}, "guests": {"type": "integer"}},
                                    "required": ["city", "checkIn", "checkOut", "guests"]}}]}
        elif method == "tools/call":
            try:
                params = message.get("params") or {}
                if params.get("name") != TOOL:
                    raise ValueError("Unknown tool")
                result = {"content": [], "structuredContent": self.catalog.search(params["arguments"])}
            except (ValueError, KeyError, TypeError, AttributeError, OSError):
                result = {"isError": True, "content": [{"type": "text", "text": "Public catalog unavailable for this request."}]}
        else:
            response["error"] = {"code": -32601, "message": "Method not found"}
            return self.send_json(200, response)
        response["result"] = result
        self.send_json(200, response)


if __name__ == "__main__":
    HTTPServer((os.environ.get("MCP_BIND", "127.0.0.1"), int(os.environ.get("MCP_PORT", "8192"))), Handler).serve_forever()
