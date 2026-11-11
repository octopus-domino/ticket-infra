#!/usr/bin/env python3
"""Save panel credentials privately after a read-only DNS API check."""
import getpass
import json
import os
import re
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
        "func": "domain.record", "elid": "codoc.site", "out": "xml",
    }).encode()
    request = urllib.request.Request(PANEL, data=data)
    # Credentials stay in the HTTPS POST body, never in URLs or process arguments.
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=30) as response:
        document = ET.fromstring(response.read(2_000_000))
    error = document.find(".//error")
    if document.tag != "doc" or error is not None or not document.findall("elem"):
        kind = error.get("type", "unknown") if error is not None else "unexpected-response"
        kind = kind if re.fullmatch(r"[a-zA-Z0-9_.:-]{1,64}", kind) else "rejected"
        raise RuntimeError("DNS API access not confirmed: " + kind + "; no credentials saved")
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
        reason = str(error) if type(error) is RuntimeError else type(error).__name__
        print("Configuration failed: " + reason + ". No secrets logged.", file=sys.stderr)
        sys.exit(1)
