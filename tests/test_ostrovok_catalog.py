import importlib.util
import json
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    'ostrovok_catalog', Path(__file__).resolve().parents[1] / 'mcp/ostrovok/server.py')
catalog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(catalog)


class CatalogCoordinatesTest(unittest.TestCase):
    def test_reads_visible_listings_missing_from_structured_metadata(self):
        page = {'props': {'pageProps': {'serpData': {'hotels': [{
            'masterId': '42', 'name': 'Visible hotel', 'rating': 9, 'stars': 4,
            'location': {'latitude': 59.94, 'longitude': 30.34, 'address': 'Nevsky Avenue'},
        }]}}}}
        html = (f'<script id="__NEXT_DATA__">{json.dumps(page)}</script>'
                '<a href="/hotel/russia/st._petersburg/mid42/visible_hotel/">Book</a>')
        self.assertEqual(catalog.parse_catalog(html, 'Saint Petersburg'), [{
            'id': '42', 'city': 'Saint Petersburg', 'name': 'Visible hotel', 'rating': 9, 'stars': 4,
            'address': 'Nevsky Avenue', 'latitude': 59.94, 'longitude': 30.34,
            'sourceUrl': 'https://ostrovok.ru/hotel/russia/st._petersburg/mid42/visible_hotel/',
        }])
    def test_joins_coordinates_by_master_id_and_ignores_invalid_locations(self):
        items = [{'item': {'@type': 'Hotel', 'name': f'Hotel {i}',
                           'url': f'https://ostrovok.ru/hotel/russia/moscow/mid{i}/'}}
                 for i in (1, 2, 3)]
        metadata = {'@type': 'ItemList', 'itemListElement': items}
        hotels = [{'masterId': 2, 'location': {'latitude': 55.75, 'longitude': 37.62}},
                  {'masterId': 3, 'location': {'latitude': 999, 'longitude': 37.62}}]
        page = {'props': {'pageProps': {'serpData': {'hotels': hotels}}}}
        html = (f'<script type="application/ld+json">{json.dumps(metadata)}</script>'
                f'<script id="__NEXT_DATA__">{json.dumps(page)}</script>')
        by_id = {row['id']: row for row in catalog.parse_catalog(html, 'Moscow')}
        self.assertEqual((by_id['2']['latitude'], by_id['2']['longitude']), (55.75, 37.62))
        self.assertNotIn('latitude', by_id['1'])
        self.assertNotIn('latitude', by_id['3'])

    def test_matches_one_supported_city_in_an_address(self):
        self.assertEqual(catalog.catalog_slug('Kazan, Tatarstan, Russia'), 'kazan')
        self.assertIsNone(catalog.catalog_slug('Kazan, Moscow'))
        self.assertIsNone(catalog.catalog_slug('Moscow street'))


if __name__ == '__main__':
    unittest.main()
