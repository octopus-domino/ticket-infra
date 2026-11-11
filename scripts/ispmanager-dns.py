#!/usr/bin/env python3
"""Certbot DNS hooks restricted to _acme-challenge.codoc.site TXT records."""
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

CONFIG = Path("/etc/letsencrypt/codoc-ispmanager.json")
PANEL = "https://server67.hosting.reg.ru:1500/ispmgr"
DOMAIN = "codoc.site"
CHALLENGE = "_acme-challenge." + DOMAIN


class PanelApiError(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class PanelClient:
    def __init__(self, credentials):
        if credentials.get("panel") != PANEL:
            raise RuntimeError("Unexpected DNS panel endpoint")
        self.credentials = credentials
        self.opener = urllib.request.build_opener(NoRedirect())

    def call(self, function, **parameters):
        parameters.update(func=function, out="xml", authinfo=(
            self.credentials["username"] + ":" + self.credentials["password"]))
        request = urllib.request.Request(PANEL, data=urllib.parse.urlencode(parameters).encode())
        with self.opener.open(request, timeout=30) as response:
            document = ET.fromstring(response.read(2_000_000))
        error = document.find(".//error")
        if error is not None:
            kind = error.get("type", "unknown")
            kind = kind if re.fullmatch(r"[a-zA-Z0-9_.:-]{1,64}", kind) else "rejected"
            field = error.get("object", "unknown")
            field = field if field in {"name", "plid", "elid", "rtype", "txt", "value", "ttl", "authinfo", "auth"} else "unknown"
            raise PanelApiError("DNS API rejected " + function + ": " + kind + " (field: " + field + ")")
        if document.tag != "doc" or document.find("auth") is not None:
            raise PanelApiError("Unexpected DNS API response")
        return document

    def records(self):
        return [{child.tag: child.text or "" for child in element}
                for element in self.call("domain.record", elid=DOMAIN).findall("elem")]


def load_credentials():
    with CONFIG.open("r", encoding="utf-8") as stream:
        metadata = os.fstat(stream.fileno())
        if CONFIG.is_symlink() or not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_mode & 0o077:
            raise RuntimeError("Credentials must be a root-owned private regular file")
        return json.loads(stream.read(16_384))


def challenge_value():
    if os.environ.get("CERTBOT_DOMAIN") not in (DOMAIN, "*." + DOMAIN):
        raise RuntimeError("Hook is restricted to codoc.site")
    value = os.environ.get("CERTBOT_VALIDATION", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", value):
        raise RuntimeError("Unexpected ACME validation value")
    return value


def matching(records, value):
    return [r for r in records if r.get("rtype", "").upper() == "TXT"
            and r.get("name", "").rstrip(".") in (CHALLENGE, "_acme-challenge")
            and r.get("value", "").strip().strip('"') == value]


def add(client, value):
    if matching(client.records(), value):
        return False
    client.call("domain.record.edit", plid=DOMAIN, sok="ok", name="_acme-challenge",
                rtype="txt", value=value, ttl="300")
    return True


def remove(client, value):
    for record in matching(client.records(), value):
        key = record.get("rkey")
        if not key:
            raise RuntimeError("Cannot safely identify the challenge record")
        client.call("domain.record.delete", plid=DOMAIN, elid=key, sok="ok")


def visible(server, value):
    try:
        result = subprocess.run(["dig", "+short", "+time=3", "+tries=1", "TXT", CHALLENGE, "@" + server],
                                capture_output=True, text=True, timeout=5, check=False)
        return result.returncode == 0 and '"' + value + '"' in result.stdout.splitlines()
    except (OSError, subprocess.TimeoutExpired):
        return False


def wait_for_dns(value):
    deadline = time.monotonic() + 1800
    servers = ("ns1.hosting.reg.ru", "ns2.hosting.reg.ru", "8.8.8.8", "1.1.1.1")
    while time.monotonic() < deadline:
        if all(visible(server, value) for server in servers):
            # Multi-perspective CA checks may still have an older cached RRset.
            # Let one full record TTL elapse, then confirm visibility again.
            if time.monotonic() + 300 >= deadline:
                break
            time.sleep(300)
            if all(visible(server, value) for server in servers):
                return
        time.sleep(15)
    raise RuntimeError("DNS propagation did not complete within 30 minutes")


def authenticate(client, value):
    created = add(client, value)
    try:
        wait_for_dns(value)
    except BaseException:
        if created:
            remove(client, value)
        raise
    # Certbot passes this per-challenge output to the matching cleanup hook.
    print(json.dumps({"created": created}))


def main():
    action = sys.argv[1] if len(sys.argv) == 2 else ""
    if action not in ("check", "auth", "cleanup"):
        raise RuntimeError("Usage: ispmanager-dns.py check|auth|cleanup")
    client = PanelClient(load_credentials())
    if action == "check":
        print("DNS API reachable; record count:", len(client.records()))
        return
    value = challenge_value()
    if action == "auth":
        authenticate(client, value)
    elif json.loads(os.environ.get("CERTBOT_AUTH_OUTPUT") or "{}").get("created") is True:
        remove(client, value)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        reason = str(error) if isinstance(error, PanelApiError) else type(error).__name__
        print("ISPmanager DNS hook failed: " + reason + ". No secrets logged.", file=sys.stderr)
        sys.exit(1)
