"""Fuzzy content search tolerates typos without flooding unrelated matches."""
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _sandbox_home
_sandbox_home.isolate()
from cubeon.fuzzy_search import search_items


class FuzzySearchTests(unittest.TestCase):
    def setUp(self):
        self.items = [
            dict(display_name='Sodium', filename='sodium-0.8.14.jar', mod_id='sodium'),
            dict(display_name='Concurrent Chunk Management Engine', filename='c2me-fabric-0.3.6.jar', mod_id='c2me'),
            dict(display_name='LambDynamicLights', slug='lambdynamiclights'),
            dict(display_name='More Culling', slug='moreculling'),
            dict(display_name='Cloth Config', mod_id='cloth_config'),
            dict(display_name='Fabric API', slug='fabric-api'),
            dict(display_name='Iris Shaders', filename='iris-1.10.jar'),
            dict(display_name='Lithium', mod_id='lithium')]

    def test_typos_and_transposed_letters(self):
        for query, expected in (('soduim', 'Sodium'), ('sodum', 'Sodium'),
                                ('concurent', 'Concurrent Chunk Management Engine'),
                                ('concurent chunk', 'Concurrent Chunk Management Engine'),
                                ('lambdynmiclights', 'LambDynamicLights'),
                                ('moreculing', 'More Culling'), ('cloth confg', 'Cloth Config')):
            with self.subTest(query=query):
                self.assertEqual(search_items(self.items, query)[0]['display_name'], expected)

    def test_names_acronyms_ids_and_filenames(self):
        for query, expected in (('concurrent', 'Concurrent Chunk Management Engine'),
                                ('c2me', 'Concurrent Chunk Management Engine'),
                                ('ccme', 'Concurrent Chunk Management Engine'),
                                ('c2me-fabric', 'Concurrent Chunk Management Engine'),
                                ('ldl', 'LambDynamicLights'), ('cloth_config', 'Cloth Config'),
                                ('fabapi', 'Fabric API')):
            with self.subTest(query=query):
                self.assertEqual(search_items(self.items, query)[0]['display_name'], expected)

    def test_exact_results_outrank_fuzzy_and_sort_is_stable(self):
        items = [dict(name='Sodum'), dict(name='Sodium Extra'), dict(name='Sodium'), dict(name='Sodium')]
        self.assertEqual(search_items(items, 'sodium'), [items[2], items[3], items[1], items[0]])
        self.assertEqual(search_items(items, ''), items)

    def test_unrelated_and_short_queries_do_not_get_fuzzy_noise(self):
        for query in ('zzzzzz', 'concurent lithium', 'q', 'zz', 'dragon'):
            self.assertEqual(search_items(self.items, query), [], query)
        self.assertEqual([item['display_name'] for item in search_items(self.items, 'ir')], ['Iris Shaders'])

    def test_spaces_punctuation_case_and_accents(self):
        self.assertEqual(search_items([dict(name='Café Resource Pack')], 'cafe')[0]['name'], 'Café Resource Pack')
        self.assertEqual(search_items(self.items, '  CLOTH--CONFIG  ')[0]['display_name'], 'Cloth Config')
        self.assertEqual(search_items([dict(name='动态光源')], '动态')[0]['name'], '动态光源')

    def test_large_cached_catalogue_is_bounded_and_does_not_mutate_items(self):
        items = [dict(name=f'Unique Mod {number}', filename=f'mod-{number}.jar') for number in range(1000)] + self.items
        before = [dict(item) for item in items]
        result = search_items(items, 'concurent')
        self.assertEqual(result, [self.items[1]])
        started = time.monotonic()
        for repeat in range(20):
            self.assertEqual(search_items(items, 'concurent'), result)
        self.assertLess(time.monotonic() - started, 1)
        self.assertEqual(items, before)


if __name__ == '__main__':
    unittest.main()
