#!/usr/bin/env python3
"""Explicit live release check; creates snapshots and revokes its synthetic PDF document."""
import collections
import json
import time
import urllib.request

BASE = 'https://www.codoc.site'

def call(path, payload=None, headers=None, binary=False):
    request = urllib.request.Request(BASE + path,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json', 'User-Agent': 'CoDoc-release-audit/1.0', **(headers or {})})
    with urllib.request.urlopen(request, timeout=140) as response:
        body = response.read(16000000)
        return body if binary else json.loads(body)

first = None
for language, audience in [('ru', 'middle'), ('en', 'middle'), ('es', 'middle'), ('ru', 'child')]:
    start = time.monotonic()
    prepared = call('/api/journeys/poetry', {'latitude': 55.75, 'longitude': 37.62,
        'zone': 'Europe/Moscow', 'language': language, 'mood': 'heartfelt', 'audience': audience,
        'seed': 'release-verification-20261113'})
    bundle = prepared['bundle']
    assert len(bundle['cards']) == 7
    assert call('/api/journeys/poetry/' + prepared['id']) == bundle
    for card in bundle['cards']:
        assert card['poem'].strip() and card['author'] and card['sourceUrl'].startswith('https://')
        assert card['sourceMetadata']['text_complete'] is True
        assert card['sourceMetadata']['language'] == language
    counts = collections.Counter(card['sourceMetadata']['source'] for card in bundle['cards'])
    print(json.dumps({'language': language, 'audience': audience, 'cards': 7,
        'sources': dict(counts), 'seconds': round(time.monotonic() - start, 1), 'snapshotRoundTrip': True}), flush=True)
    if first is None:
        first = prepared

created = None
try:
    [created] = call('/api/journeys', {'kind': 'POETRY', 'title': 'Release verification',
        'data': {'poetry': first['id'], 'locale': 'ru'}, 'recipients': []})
    pdf = call('/api/journeys/' + created['document']['id'] + '/pdf', binary=True)
    assert pdf.startswith(b'%PDF')
    print(json.dumps({'nativePdf': True, 'bytes': len(pdf)}), flush=True)
finally:
    if created:
        status = call('/api/journeys/' + created['document']['id'] + '/status',
            {'action': 'REVOKE'}, {'X-Management-Key': created['managementKey']})
        assert status['state'] == 'REVOKED'
        print('Synthetic publication revoked; management key was not logged.', flush=True)
