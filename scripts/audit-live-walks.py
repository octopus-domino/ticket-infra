"""Explicit post-deployment checks; no public documents are created or messages sent.

One attributed Commons image may be stored to verify the real media pipeline.
"""
import argparse
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--base', default='https://www.codoc.site')
parser.add_argument('--report', required=True)
parser.add_argument('--pdf-output', required=True)
args = parser.parse_args()
result = {}


def request(path, body=None):
    data = None if body is None else json.dumps(body).encode()
    query = urllib.request.Request(args.base + path, data=data,
        headers={'Content-Type': 'application/json', 'User-Agent': 'CoDoc-Release-Audit/1.0'})
    started = time.monotonic()
    with urllib.request.urlopen(query, timeout=100) as response:
        content = response.read(24_000_001)
        if len(content) > 24_000_000:
            raise ValueError('Unexpectedly large audit response')
        return content, round(time.monotonic() - started, 2)


content, elapsed = request('/api/journeys/routes/places/themes')
assert set(json.loads(content)) == {'bars', 'mystic', 'religious', 'cultural'}
result['themes'] = {'ok': True, 'seconds': elapsed}

query = urllib.parse.urlencode({'theme': 'mystic', 'longitude': 30.314,
    'latitude': 59.939, 'visitTime': '2026-11-13T20:00', 'language': 'ru'})
content, elapsed = request('/api/journeys/routes/places/themed?' + query)
places = json.loads(content)['places']
result['mystic'] = {'seconds': elapsed, 'count': len(places),
    'sources': sorted(set(place.get('source', '') for place in places)),
    'with_description': sum(bool(place.get('description')) for place in places)}

content, elapsed = request('/api/journeys/routes/road', {
    'start': {'longitude': 37.6175, 'latitude': 55.7525},
    'end': {'longitude': 37.6215, 'latitude': 55.754}, 'mode': 'foot'})
road = json.loads(content)
assert len(road['coordinates']) >= 2 and road['durationSeconds'] > 0
result['walking_road'] = {'seconds': elapsed, 'points': len(road['coordinates']),
    'distance_m': road['distanceMeters']}

content, elapsed = request('/api/journeys/routes/places/themed/enrich?language=en', [{
    'id': 'release-eiffel', 'label': 'Eiffel Tower', 'longitude': 2.2945,
    'latitude': 48.8584, 'zone': 'Europe/Paris', 'stayMinutes': 30,
    'meta': {'theme': 'cultural', 'source': 'osm'}}])
photos = json.loads(content)
result['commons_photo'] = {'seconds': elapsed, 'count': len(photos)}
assert photos, 'Known Commons fixture did not produce an attributed stored image'
if photos:
    assert photos[0]['licenseUrl'].startswith('https://creativecommons.org/')
    image, _ = request('/api/journeys/media/' + photos[0]['imageId'])
    assert image.startswith(b'\xff\xd8') or image.startswith(b'\x89PNG')
    result['commons_photo'].update({'stored_bytes': len(image), 'license': photos[0]['license']})

content, elapsed = request('/api/journeys/artwork', {'kind': 'INVITATION',
    'title': 'Release verification', 'data': {'locale': 'ru', 'background_preset': 'corporate-blue'}})
pages = json.loads(content)['pages']
assert pages and 'data:image/png;base64,' in pages[0]['svg']
result['preset_export'] = {'seconds': elapsed, 'pages': len(pages), 'ok': True}

content, elapsed = request('/api/journeys/iKc4EQOxruWK/pdf')
assert content.startswith(b'%PDF-')
Path(args.pdf_output).write_bytes(content)
result['existing_poetry_pdf'] = {'seconds': elapsed, 'bytes': len(content)}
Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(result, ensure_ascii=True))
