"""Modpack discovery recovers names without losing filters, pages or healthy results."""
import inspect
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT)]
import _sandbox_home
_sandbox_home.isolate()
from cubeon import modpacks, thread_safe_ui
from cubeon.fuzzy_search import recovery_queries
from cubeon.theme import THEME, section_label
from _fuzz_common import FakePage
from ui import modpacks_tab


PACK = dict(source='curseforge', project_id='959010', slug='all-the-mods-9-no-frills',
            title='All the Mods 9 - No Frills', downloads=1200000)
RELATED = dict(source='curseforge', project_id='1529168', slug='atm9-johnstone-edition',
               title='Johnstone Edition 9 - MC1.20', downloads=100)


def cf_payload(hits):
    return dict(data=[dict(id=hit['project_id'], name=hit['title'], slug=hit['slug'],
                           downloadCount=hit.get('downloads', 0)) for hit in hits])


class ModpackSearchTests(unittest.TestCase):
    def setUp(self):
        for namespace in ('search_modpacks_mr', 'search_modpacks_cf', 'search_modpacks',
                          'modpack_search_recovery'):
            modpacks.local_cache.invalidate(namespace)
        self.keys = patch.object(modpacks, '_curseforge_api_key', return_value='test-key')
        self.keys.start()
        self.addCleanup(self.keys.stop)

    def test_spaced_acronym_recovers_official_pack_and_keeps_pages(self):
        calls = []
        def request(path, params):
            calls.append(dict(params))
            key = params['searchFilter'], params['index']
            if key == ('ATM 9 no frills', '0'):
                return cf_payload([RELATED])
            if key == ('atm9 no frills', '0'):
                return cf_payload([RELATED, PACK])
            if key == ('atm9 no frills', '2'):
                return cf_payload([dict(PACK, project_id='next', title='ATM9 No Frills Community')])
            self.fail(f'Unexpected provider query: {key}')
        with patch.object(modpacks, '_cf_request', side_effect=request):
            first = modpacks.search_modpacks_curseforge('ATM 9 no frills', limit=2)
            ranked = modpacks.merge_modpack_hits([], first, 'ATM 9 no frills')
            self.assertEqual(ranked[0]['project_id'], '959010')
            second = modpacks.search_modpacks_curseforge('ATM 9 no frills', limit=2, offset=2)
            self.assertEqual(second[0]['project_id'], 'next')
            self.assertEqual(modpacks.search_modpacks_curseforge('ATM 9 no frills', limit=2), first)
        self.assertEqual(len(calls), 3)
        self.assertEqual([call['sortField'] for call in calls], ['1'] * 3)
        self.assertTrue(all(call['classId'] == '4471' for call in calls))

    def test_typo_recovery_keeps_modrinth_version_facets(self):
        calls = []
        query = 'all the mds no frills'
        def request(url, **kwargs):
            params = kwargs['params']
            calls.append(dict(params))
            hit = dict(PACK, source='modrinth')
            return dict(hits=[hit] if params['query'] == 'no frills' else [])
        with patch.object(modpacks.net, 'get_json', side_effect=request):
            hits = modpacks.search_modpacks_modrinth(query, '1.20.1', limit=24)
        self.assertEqual(hits[0]['project_id'], '959010')
        self.assertEqual([call['query'] for call in calls], [query, 'all the mds', 'no frills'])
        self.assertTrue(all(json.loads(call['facets']) ==
                            [['project_type:modpack'], ['versions:1.20.1']] for call in calls))
        self.assertTrue(all(call['offset'] == '0' and call['limit'] == '24' for call in calls))

    def test_matching_names_browse_and_later_pages_need_one_request(self):
        for query, offset, pack, expected_sort in (
                ('ATM9 no frils', 0, PACK, '1'), ('', 0, PACK, '2'),
                ('anything', 24, RELATED, '1')):
            with self.subTest(query=query), patch.object(modpacks, '_cf_request',
                                                         return_value=cf_payload([pack])) as request:
                modpacks.search_modpacks_curseforge(query, offset=offset)
                self.assertEqual(request.call_count, 1)
                self.assertEqual(request.call_args.kwargs['params']['sortField'], expected_sort)

    def test_single_word_typo_uses_a_bounded_prefix_probe(self):
        calls = []
        def request(path, params):
            calls.append(params['searchFilter'])
            return cf_payload([dict(PACK, title='RLCraft', slug='rlcraft')]
                              if params['searchFilter'] == 'rlc' else [])
        with patch.object(modpacks, '_cf_request', side_effect=request):
            hits = modpacks.search_modpacks_curseforge('rlcarft')
        self.assertEqual(hits[0]['title'], 'RLCraft')
        self.assertEqual(calls, ['rlcarft', 'rlc'])

    def test_failed_or_irrelevant_probes_keep_description_results(self):
        for failure in (False, True):
            calls = []
            def request(path, params):
                calls.append(params['searchFilter'])
                if len(calls) > 1 and failure:
                    raise OSError('offline')
                return cf_payload([RELATED])
            with self.subTest(failure=failure), patch.object(modpacks, '_cf_request', side_effect=request):
                hits = modpacks.search_modpacks_curseforge(f'technical exploration {failure}')
                self.assertEqual(hits[0]['project_id'], RELATED['project_id'])
                self.assertLessEqual(len(calls), 4)
                self.assertNotIn('', calls)

    def test_keyless_curated_packs_use_same_fuzzy_matcher(self):
        widget = dict(id=959010, title=PACK['title'], files=[],
                      urls={'curseforge': 'https://www.curseforge.com/minecraft/modpacks/' + PACK['slug']})
        with (patch.object(modpacks, '_curseforge_api_key', return_value=None),
              patch.object(modpacks, '_cfwidget_fetch', return_value=widget),
              patch.object(modpacks, '_cf_request', side_effect=AssertionError('key-only endpoint'))):
            hits = modpacks.search_modpacks_curseforge('ATM 9 no frils')
            self.assertEqual([hit['project_id'] for hit in hits], ['959010'])
            self.assertEqual(modpacks.search_modpacks_curseforge('ATM 9 no frils', offset=40), [])

    def test_empty_results_expire_and_old_search_cache_is_not_reused(self):
        old_key = dict(query='missing', mc_version=None, limit=40, offset=0, keyed=True)
        modpacks.local_cache.set('search_modpacks_cf', old_key, [RELATED])
        with (patch.object(modpacks, '_cf_request', return_value={'data': []}) as request,
              patch.object(modpacks.local_cache.time, 'time', return_value=1000000) as now):
            self.assertEqual(modpacks.search_modpacks_curseforge('missing'), [])
            count = request.call_count
            self.assertEqual(modpacks.search_modpacks_curseforge('missing'), [])
            self.assertEqual(request.call_count, count)
            now.return_value += 61
            self.assertEqual(modpacks.search_modpacks_curseforge('missing'), [])
            self.assertGreater(request.call_count, count)

    def test_names_outrank_related_results_from_either_provider_and_deduplicate(self):
        related = dict(RELATED, downloads=99999999, description='All the Mods 9 - No Frills')
        mr = dict(PACK, source='modrinth', project_id='mr', title='ATM9 No Frils', slug='atm9-no-frils')
        exact = dict(PACK, source='curseforge', project_id='mr')
        hits = modpacks.merge_modpack_hits([related, mr], [exact, exact], 'ATM9 no frills')
        self.assertEqual(hits[0], exact)
        self.assertEqual(len(hits), 3)
        self.assertEqual(hits[-1], related)
        self.assertEqual(modpacks.merge_modpack_hits([related], [PACK], ''), [related, PACK])

    def test_recovery_queries_are_small_nonempty_and_handle_short_input(self):
        self.assertEqual(recovery_queries('ATM 9 no frills'), ['atm9 no frills', 'atm9', 'no frills'])
        self.assertEqual(recovery_queries('rlcarft'), ['rlc'])
        self.assertEqual(recovery_queries('r'), [])
        self.assertLessEqual(len(recovery_queries('  ATM--9  no frils  ')), 3)
        self.assertEqual(recovery_queries(''), [])


class ModpackSearchUiTests(unittest.TestCase):
    def test_fuzzy_matches_reach_visible_browse_in_either_provider_order(self):
        class DeferredThread:
            jobs = []
            def __init__(self, target, **kwargs):
                self.target = target
            def start(self):
                self.jobs.append(self.target)
        def functions(*roots):
            found = {}
            def visit(fn):
                if not inspect.isfunction(fn) or fn.__name__ in found:
                    return
                found[fn.__name__] = fn
                for value in inspect.getclosurevars(fn).nonlocals.values():
                    visit(value)
            for root in roots:
                visit(root)
            return found
        for order in ((0, 1), (1, 0)):
            DeferredThread.jobs.clear()
            with (patch.object(modpacks_tab.threading, 'Thread', DeferredThread),
                  patch.object(modpacks_tab.core, 'list_installed_modpacks', return_value=[]),
                  patch.object(modpacks_tab._icons, 'prefetch'), patch.object(thread_safe_ui, 'refresh'),
                  patch.object(modpacks_tab.core, 'search_modpacks_modrinth', return_value=[RELATED]),
                  patch.object(modpacks_tab.core, 'search_modpacks_curseforge', return_value=[PACK])):
                tab, installed, load = modpacks_tab.build_modpacks_tab(
                    FakePage(), {}, {}, section_label=section_label, go_to_pack=lambda meta: None, **THEME)
                fn = functions(load, installed)
                field = inspect.getclosurevars(fn['_current_query']).nonlocals['search_field']
                field.value = 'ATM 9 no frils'
                fn['run_search']()
                jobs = list(DeferredThread.jobs)
                self.assertEqual(len(jobs), 2)
                for index in order:
                    jobs[index]()
                scope = inspect.getclosurevars(fn['_render_page']).nonlocals
                self.assertEqual(scope['browse_state']['results'][0], PACK)
                self.assertFalse(scope['results_view'].disabled)


if __name__ == '__main__':
    unittest.main()
