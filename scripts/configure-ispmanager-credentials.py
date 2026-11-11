#!/usr/bin/env python3
"""Save panel credentials privately after a read-only DNS API check."""
import getpass
import json
import os
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

PANEL = "https://server67.hosting.reg.ru:1500/ispmgr"
CREDENTIALS = "/etc/letsencrypt/codoc-ispmanager.json"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main():
    if os.geteuid() != 0:
        raise RuntimeError("Run with sudo on the CoDoc server")
    if os.path.lexists(CREDENTIALS):
        raise RuntimeError("Credentials file already exists; review it before replacing it")
    username = input("ISPmanager hosting username: ").strip()
    password = getpass.getpass("ISPmanager hosting password (hidden): ")
    if not username or not password or ":" in username:
        raise RuntimeError("Username and password are required")
    data = urllib.parse.urlencode({
        "authinfo": username + ":" + password,
        "func": "domain.record", "plid": "codoc.site", "out": "xml",
    }).encode()
    request = urllib.request.Request(PANEL, data=data)
    # Credentials stay in the HTTPS POST body, never in URLs or process arguments.
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=30) as response:
        document = ET.fromstring(response.read(2_000_000))
    if document.tag != "doc" or document.find(".//error") is not None or not document.findall("elem"):
        raise RuntimeError("DNS API access was not confirmed; no credentials saved")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    fd = os.open(CREDENTIALS, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"panel": PANEL, "username": username, "password": password}, stream)
            stream.write("\n")
    except BaseException:
        os.unlink(CREDENTIALS)
        raise
    print("DNS API access confirmed. Credentials saved privately in " + CREDENTIALS)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Never print response bodies or exception URLs containing credentials.
        print("Configuration failed (" + type(error).__name__ + "). No secrets logged.", file=sys.stderr)
        sys.exit(1)
