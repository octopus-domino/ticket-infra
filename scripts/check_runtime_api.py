#!/usr/bin/env python3
"""Check public APIs using synthetic coordinates; creates no account or saved server documents."""
import argparse
import concurrent.futures
from datetime import date, timedelta
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


def check_radius_growth(base, longitude, latitude):
    def search(radius, label):
        query = urllib.parse.urlencode(dict(longitude=longitude, latitude=latitude,
            language='ru', themes='bars', radiusKm=radius))
        status, result, seconds = request(base, '/api/journeys/routes/places/themed?' + query)
        ids = {place['id'] for place in result.get('places', [])}
        print(json.dumps(dict(check=label, radius_km=radius, status=status, places=len(ids),
                              complete=result.get('complete'), seconds=seconds)), flush=True)
        assert status == 200 and isinstance(result.get('complete'), bool), 'Expected the tiled area response'
        return result['complete'], ids

    _, inner = search(.8, 'inner')
    complete, expanded = search(3.1, 'expanded')
    if not complete:
        _, updated = search(3.1, 'expanded-retry')
        print(json.dumps(dict(check='retained-on-retry', inner_retained=len(inner & updated),
                              inner_total=len(inner), expanded_retained=len(expanded & updated),
                              expanded_total=len(expanded))), flush=True)
    search(.8, 'inner-warm')


def check_trip(base, departure_date):
    routes = '/api/journeys/routes/places/'
    tests = [
        ('hotels', routes + 'hotels', dict(city='Moscow', checkIn=str(departure_date),
            checkOut=str(departure_date + timedelta(days=1)), guests=2), 'hotels'),
        ('trains', routes + 'trains', {'from': 'c2', 'to': 'c213', 'date': str(departure_date)}, 'trains'),
        ('rates', routes + 'rates', None, 'rates'),
        ('cities', routes + 'cities?q=Moscow&language=en', None, None),
        ('trip-auth', '/api/trips/acceptance-missing', None, None),
    ]
    results = {}
    for name, path, body, items in tests:
        status, payload, seconds = request(base, path, body)
        output = dict(check=name, status=status, seconds=seconds)
        if isinstance(payload, dict):
            for key in ('available', 'provider', 'catalogOnly', 'date'):
                if key in payload:
                    output[key] = payload[key]
        if items:
            output['count'] = len(payload.get(items, []))
        elif isinstance(payload, list):
            output['count'] = len(payload)
        print(json.dumps(output), flush=True)
        results[name] = status
    assert results['trip-auth'] in (401, 403), 'Private trip endpoint accepted an unauthenticated request'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--longitude', type=float, default=30.305333)
    parser.add_argument('--latitude', type=float, default=59.931553)
    parser.add_argument('--area', action='store_true', help='Also query 800m and 3.1km circles, including concurrent duplicates')
    parser.add_argument('--radius-growth', action='store_true', help='Check tiled radius expansion and a bounded retry')
    parser.add_argument('--trip', action='store_true', help='Probe hotel, rail, rates, city and access endpoints')
    parser.add_argument('--trip-date', type=date.fromisoformat, default=date.today() + timedelta(days=7))
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
    if args.radius_growth:
        check_radius_growth(args.base_url, args.longitude, args.latitude)
    if args.trip:
        check_trip(args.base_url, args.trip_date)
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
