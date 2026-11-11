#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
: "${CLOUDFLARE_API_TOKEN:?Set a DNS-edit token scoped only to codoc.site}"
: "${CLOUDFLARE_ZONE_ID:?Set the codoc.site zone ID}"
: "${CODOC_PUBLIC_IP:?Set the public IPv4 address of the CoDoc server}"
: "${ACME_EMAIL:?Set the certificate notification email}"
command -v certbot >/dev/null
certbot plugins | grep -q dns-cloudflare || { echo 'Install python3-certbot-dns-cloudflare first.'; exit 1; }
python3 - <<'PY'
import os, json, ipaddress, urllib.request
ip = str(ipaddress.IPv4Address(os.environ['CODOC_PUBLIC_IP']))
base = 'https://api.cloudflare.com/client/v4/zones/' + os.environ['CLOUDFLARE_ZONE_ID'] + '/dns_records'
headers = {'Authorization': 'Bearer ' + os.environ['CLOUDFLARE_API_TOKEN'], 'Content-Type':'application/json'}
def call(url, data=None):
    req = urllib.request.Request(url, data=None if data is None else json.dumps(data).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=30) as response: result = json.load(response)
    if not result.get('success'): raise RuntimeError('DNS provider rejected the request')
    return result['result']
existing = call(base + '?name=%2A.codoc.site&type=A')
if existing:
    if any(record['content'] != ip for record in existing): raise RuntimeError('Wildcard already points elsewhere; review DNS before changing it')
    print('Wildcard A record already matches the server')
else:
    call(base, {'type':'A','name':'*.codoc.site','content':ip,'ttl':300,'proxied':False})
    print('Wildcard A record created')
PY
credentials="$(mktemp)"
trap 'rm -f -- "$credentials"' EXIT
printf 'dns_cloudflare_api_token = %s\n' "$CLOUDFLARE_API_TOKEN" > "$credentials"
# Keep a private credentials file for automated certificate renewal.
install -d -m 700 /etc/letsencrypt
install -m 600 "$credentials" /etc/letsencrypt/codoc-cloudflare.ini
certbot certonly --non-interactive --agree-tos --email "$ACME_EMAIL" \
  --dns-cloudflare --dns-cloudflare-credentials /etc/letsencrypt/codoc-cloudflare.ini \
  --dns-cloudflare-propagation-seconds 60 --cert-name codoc-wildcard -d codoc.site -d '*.codoc.site'
echo 'Certificate and wildcard DNS are ready. Install nginx.journeys.conf, run nginx -t and reload nginx.'
