#!/usr/bin/env python3
"""Retry explicitly unresolved Maven artifacts through standard HTTPS repositories.

Used when Maven's Java transport times out while the workstation HTTPS proxy works.
No credentials, mirrors or application configuration are changed.
"""
import argparse
import concurrent.futures
import pathlib
import re
import urllib.request
import zipfile

parser = argparse.ArgumentParser()
parser.add_argument('log', type=pathlib.Path)
parser.add_argument('cache', type=pathlib.Path)
args = parser.parse_args()
raw = args.log.read_bytes()
content = raw.decode('utf-16') if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else raw.decode('utf-8', errors='replace')
artifacts = sorted(set(re.findall(r'([\w.\-]+):([\w.\-]+):jar:([\w.\-]+) \(absent\)', content)))

def fetch(coordinates):
    group, artifact, version = coordinates
    relative = '/'.join([group.replace('.', '/'), artifact, version, f'{artifact}-{version}.jar'])
    target = args.cache / relative
    if target.is_file():
        return artifact, True
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix('.jar.download')
    repositories = ['https://repo.maven.apache.org/maven2/', 'https://repo1.maven.org/maven2/', 'https://maven-central.storage-download.googleapis.com/maven2/', 'https://repo.osgeo.org/repository/release/', 'https://repo.osgeo.org/repository/geotools-releases/']
    for base in repositories:
        try:
            with urllib.request.urlopen(base + relative, timeout=12) as response, partial.open('wb') as output:
                while chunk := response.read(65536):
                    output.write(chunk)
            if not zipfile.is_zipfile(partial):
                raise ValueError('Not a JAR')
            partial.replace(target)
            return artifact, True
        except Exception:
            partial.unlink(missing_ok=True)
    return artifact, False

with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    results = []
    for future in concurrent.futures.as_completed([pool.submit(fetch, item) for item in artifacts]):
        artifact, ok = future.result()
        results.append((artifact, ok))
        print(artifact, 'cached' if ok else 'FAILED', flush=True)
raise SystemExit(0 if all(ok for _, ok in results) else 1)
