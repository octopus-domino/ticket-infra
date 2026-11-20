#!/usr/bin/env bash
set -Eeuo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$root"
case "${1:---check}" in
  --check) apply=false ;;
  --apply) apply=true ;;
  *) echo "Usage: $0 [--check|--apply]" >&2; exit 2 ;;
esac
exec 9>.codoc-deploy.lock
flock -n 9
df -h /
docker system df
sudo -n du -sh /var/cache/apt/archives /var/log
python3 - "$apply" <<'PY'
from pathlib import Path
import subprocess
import sys

apply = sys.argv[1] == 'true'
root = Path.cwd()
backups = root / 'backups'

def docker(*args):
    return subprocess.check_output(['docker', *args], text=True).splitlines()

protected = {p.read_text().strip() for p in backups.rglob('previous-image.txt')}
containers = docker('ps', '-aq')
if containers:
    protected.update(docker('inspect', '--format', '{{.Image}}', *containers))
images = docker('image', 'ls', '--no-trunc', '--format', '{{.Tag}} {{.ID}}', 'codoc-app')
seen = set()
rollback = next((tag for row in images if (tag := row.split()[0]).startswith('before-')), None)
protected.update(image for tag, image in map(str.split, images) if tag in ('latest', rollback))
for row in images:
    tag, image = row.split()
    if tag.startswith('before-') and image not in protected and tag not in seen:
        seen.add(tag)
        ref = 'codoc-app:' + tag
        print('Eligible image:', ref, flush=True)
        if apply:
            subprocess.run(['docker', 'image', 'rm', ref], check=True)
PY
if [[ "$apply" == true ]]; then
  sudo -n apt-get clean
  if sudo -n test -f /var/log/syslog.1 && ! sudo -n test -e /var/log/syslog.1.gz; then
    sudo -n gzip -- /var/log/syslog.1
  fi
fi
df -h /
