#!/usr/bin/env bash
set -euo pipefail
DEST_DIR="${1:-./data/imports}"
mkdir -p -- "$DEST_DIR"
PUBLIC_KEY='https://disk.yandex.ru/d/6rI165UaOpvG0A'
api='https://cloud-api.yandex.net/v1/disk/public/resources'
metadata=$(curl --fail --silent --show-error --connect-timeout 10 --max-time 60 --get --data-urlencode "public_key=$PUBLIC_KEY" "$api")
expected=$(python3 -c 'import json,sys; print(int(json.load(sys.stdin)["size"]))' <<< "$metadata")
available=$(df -PB1 -- "$DEST_DIR" | awk 'NR==2 {print $4}')
if (( available < expected + 1073741824 )); then echo 'Insufficient space: download requires its size plus 1 GiB reserve.' >&2; exit 1; fi
if [[ -f "$DEST_DIR/hoith.gpkg" ]] && [[ $(stat -c%s "$DEST_DIR/hoith.gpkg") == "$expected" ]]; then
  echo 'GeoPackage already downloaded; preserving existing file.'; exit 0
fi
echo "Resolving HOITH GeoPackage ($expected bytes)..."
response=$(curl --fail --silent --show-error --connect-timeout 10 --max-time 60 --get --data-urlencode "public_key=$PUBLIC_KEY" "$api/download")
direct=$(python3 -c 'import json,sys; u=json.load(sys.stdin)["href"]; assert u.startswith("https://"); print(u)' <<< "$response")
curl --location --fail --show-error --connect-timeout 15 --max-time 7200 --output "$DEST_DIR/hoith.gpkg.part" "$direct"
[[ $(stat -c%s "$DEST_DIR/hoith.gpkg.part") == "$expected" ]] || { echo 'Incomplete download.' >&2; exit 1; }
python3 - "$DEST_DIR/hoith.gpkg.part" <<'PY'
import sqlite3,sys
with sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True) as db:
    assert db.execute('select count(*) from gpkg_contents').fetchone()[0] > 0
PY
mv -- "$DEST_DIR/hoith.gpkg.part" "$DEST_DIR/hoith.gpkg"
echo "Saved GeoPackage: $DEST_DIR/hoith.gpkg"
