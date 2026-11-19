#!/usr/bin/env python3
"""Check public APIs using synthetic coordinates; creates no account or saved server documents."""
import argparse
import concurrent.futures
import json
import time
import urllib.error
import urllib.parse
import urllib.request


def request(base, path, body=None):
    headers = {'Accept': 'application/json', 'User-Agent': 'CoDoc-release-check/1.0'}
    data = None
    if body is not None:
        headers['Content-Type'] = 'application/json'
        data = json.dumps(body).encode()
    started = time.monotonic()
    call = urllib.request.Request(base.rstrip('/') + path, data=data, headers=headers)
    try:
        with urllib.request.urlopen(call, timeout=55) as response:
            return response.status, json.load(response), round(time.monotonic() - started, 2)
    except urllib.error.HTTPError as error:
        return error.code, {}, round(time.monotonic() - started, 2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--longitude', type=float, default=30.305333)
    parser.add_argument('--latitude', type=float, default=59.931553)
    parser.add_argument('--area', action='store_true', help='Also query 800m and 3.1km circles, including concurrent duplicates')
    args = parser.parse_args()
    if urllib.parse.urlparse(args.base_url).scheme not in ['http', 'https']:
        parser.error('Use an explicit HTTP(S) base URL')
    status, _, seconds = request(args.base_url, '/api/journeys/routes/places/themes')
    print(json.dumps(dict(check='themes', status=status, seconds=seconds)), flush=True)
    assert status == 200, 'Public themes API is unavailable'
    status, result, seconds = request(args.base_url, '/api/journeys/routes/road', dict(
        start=dict(longitude=args.longitude, latitude=args.latitude),
        end=dict(longitude=args.longitude + .004, latitude=args.latitude + .002), mode='foot'))
    points = len(result.get('coordinates', []))
    print(json.dumps(dict(check='foot-route', status=status, points=points, seconds=seconds)), flush=True)
    assert status == 200 and points > 1, 'No usable walking route returned'
    if not args.area:
        return

    def search(radius, themes):
        query = urllib.parse.urlencode(dict(longitude=args.longitude, latitude=args.latitude, language='ru', themes=themes, radiusKm=radius))
        status, result, seconds = request(args.base_url, '/api/journeys/routes/places/themed?' + query)
        print(json.dumps(dict(check='area', radius=radius, themes=themes, status=status,
                              count=len(result.get('places', [])), seconds=seconds)), flush=True)
        return status

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        assert all(status == 200 for status in executor.map(lambda _: search(.8, 'bars'), range(3)))
    for radius, themes in [(3.1, 'bars'), (3.1, 'bars,cultural'), (.8, 'bars')]:
        assert search(radius, themes) == 200, 'Area source unavailable; inspect runtime logs'


if __name__ == '__main__':
    main()
