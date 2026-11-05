"""Real content/cache regressions: isolation, safe publication and archive limits."""
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
import _sandbox_home
_sandbox_home.isolate()
from cubeon import content, global_mod_cache as cache, mods, net, packformat
from cubeon.modpacks import _host_allowed


def archive(path=None, *, kind='resourcepack', payload='test', wrapper=''):
    destination = path or io.BytesIO()
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as z:
        if kind == 'resourcepack':
            z.writestr(wrapper + 'pack.mcmeta', json.dumps({'pack': {'pack_format': 75, 'description': 'test'}}))
        z.writestr(wrapper + ('assets/test.txt' if kind == 'resourcepack' else 'shaders/test.fsh'), payload)
    return destination.getvalue() if path is None else path


class ContentAudit(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.root = Path(self.work.name)
        replacements = {
            'resourcepack': dict(content.CONTENT_TYPES['resourcepack'], dir=str(self.root/'game/resources')),
            'shader': dict(content.CONTENT_TYPES['shader'], dir=str(self.root/'game/shaders')),
        }
        self.patches = [patch.object(mods, 'PROFILES_DIR', str(self.root/'profiles')),
                        patch.object(mods, 'read_instance_meta', side_effect=lambda v: {'profile': v} if v else None),
                        patch.object(content, 'GLOBAL_CONTENT_DIR', str(self.root/'store')),
                        patch.object(content, '_CONTENT_META_PATH', str(self.root/'meta.json')),
                        patch.object(content, '_profile_formats', return_value=[75]),
                        patch.dict(content.CONTENT_TYPES, replacements),
                        patch.object(cache, 'GLOBAL_MODS_DIR', str(self.root/'mods-store')),
                        patch.object(cache, '_HASH_INDEX_PATH', str(self.root/'mods-store/index.json'))]
        for p in self.patches:
            p.start(); self.addCleanup(p.stop)
        cache._verified_hash.cache_clear()

    def install(self, kind, *, version='instance-A', payload='test'):
        source = self.root/f'{kind}.zip'
        archive(source, kind=kind, payload=payload)
        name = content.install_local_content(kind, str(source), '1.21.11', version, 'fabric')
        path = Path(content.resolve_content_profile_dir(kind, '1.21.11', 'fabric', version))/name
        return name, path

    def test_file_toggles_roundtrip_and_isolate_siblings(self):
        for kind in ('resourcepack', 'shader'):
            with self.subTest(kind=kind):
                name, path = self.install(kind)
                _, sibling = self.install(kind, version='instance-B')
                stored = Path(os.path.realpath(path)); original = stored.read_bytes()
                content.remember_content_meta(kind, name, slug='identity', title='Title', icon_url='https://example.com/icon')
                content._sync_content_type(kind, '1.21.11', 'fabric', 'instance-A')
                staged = Path(content.content_dir(kind))/name
                self.assertTrue(staged.exists())
                disabled = content.toggle_content(kind, name, '1.21.11', 'fabric', version_id='instance-A')
                listing = content.list_content(kind, '1.21.11', loader='fabric', version_id='instance-A')
                self.assertEqual(listing[0]['filename'], disabled)
                self.assertFalse(listing[0]['enabled'])
                self.assertEqual(listing[0]['slug'], 'identity')
                content._sync_content_type(kind, '1.21.11', 'fabric', 'instance-A')
                self.assertFalse(staged.exists())
                self.assertTrue(sibling.exists())
                self.assertEqual(stored.read_bytes(), original)
                content.toggle_content(kind, disabled, '1.21.11', 'fabric', version_id='instance-A')
                content._sync_content_type(kind, '1.21.11', 'fabric', 'instance-A')
                self.assertTrue(staged.exists())
                content.delete_content(kind, name, '1.21.11', 'fabric', version_id='instance-A')
                self.assertEqual(content.list_content(kind, '1.21.11', loader='fabric', version_id='instance-B')[0]['title'], 'Title')

    def test_folder_toggle_and_collision_preserve_bytes(self):
        for kind in ('resourcepack', 'shader'):
            directory = Path(content.profile_dir(kind, '1.21.11', 'fabric', 'instance-A'))
            pack = directory/'Unpacked'; pack.mkdir(); (pack/'data').write_text('keep')
            disabled = content.toggle_content(kind, pack.name, '1.21.11', 'fabric', version_id='instance-A')
            self.assertFalse(content.list_content(kind, '1.21.11', loader='fabric', version_id='instance-A')[0]['enabled'])
            content._sync_content_type(kind, '1.21.11', 'fabric', 'instance-A')
            self.assertFalse((Path(content.content_dir(kind))/'Unpacked').exists())
            pack.mkdir(); (pack/'data').write_text('other')
            with self.assertRaises(ValueError):
                content.toggle_content(kind, disabled, '1.21.11', 'fabric', version_id='instance-A')
            self.assertEqual((directory/disabled/'data').read_text(), 'keep')
            self.assertEqual((pack/'data').read_text(), 'other')

    def test_file_collision_never_overwrites_disabled_copy(self):
        name, path = self.install('shader')
        path.with_name(name+'.disabled').write_bytes(b'backup')
        with self.assertRaises(ValueError):
            content.toggle_content('shader', name, '1.21.11', 'fabric', version_id='instance-A')
        self.assertEqual(path.with_name(name+'.disabled').read_bytes(), b'backup')
        self.assertTrue(zipfile.is_zipfile(path))

    def test_profile_symlink_and_traversal_are_rejected(self):
        directory = self.root/'profiles'; directory.mkdir()
        outside = self.root/'outside'; outside.mkdir()
        (directory/'instance-A').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError): content.profile_dir('shader', '1.21.11', 'fabric', 'instance-A')
        for name in ('../victim.zip', '..\\victim.zip', '/victim.zip', '.hidden.zip', 'bad:name.zip'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                content.toggle_content('shader', name, '1.21.11', 'fabric')

    def test_hostile_marker_never_deletes_outside_entry(self):
        game = Path(content.content_dir('resourcepack'))
        victim = game.parent/'victim.zip'; victim.write_text('keep')
        (game/content._STAGED_MARKER).write_text(json.dumps(('../victim.zip', '/victim.zip', None, 42)))
        content._sync_content_type('resourcepack', '1.21.11', 'fabric', 'instance-A')
        self.assertEqual(victim.read_text(), 'keep')

    def test_purge_protects_outside_targets_and_shared_store(self):
        directory = Path(content.profile_dir('shader', '1.21.11', 'fabric', 'instance-A'))
        outside = self.root/'outside.zip'; outside.write_bytes(b'private')
        (directory/'outside.zip').symlink_to(outside)
        with self.assertRaises(ValueError):
            content.delete_content('shader', 'outside.zip', '1.21.11', 'fabric', purge_store=True, version_id='instance-A')
        self.assertEqual(outside.read_bytes(), b'private')
        name, path = self.install('shader'); stored = Path(os.path.realpath(path))
        self.install('shader', version='instance-B')
        content.delete_content('shader', name, '1.21.11', 'fabric', purge_store=True, version_id='instance-A')
        self.assertTrue(stored.exists())

    def test_failed_adoption_keeps_original_game_file(self):
        game = Path(content.content_dir('shader')); original = game/'manual.zip'
        archive(original, kind='shader')
        before = original.read_bytes()
        with patch.object(content, 'link_into_profile', side_effect=OSError('locked')):
            content._adopt_foreign_entries('shader', [], '1.21.11', 'fabric', 'instance-A')
        self.assertEqual(original.read_bytes(), before)

    def test_failed_staging_does_not_claim_foreign_files(self):
        name, path = self.install('shader')
        with patch.object(content.os, 'replace', side_effect=OSError('locked')):
            content._sync_content_type('shader', '1.21.11', 'fabric', 'instance-A')
        self.assertEqual(content._read_staged('shader'), [])
        self.assertTrue(path.exists())

    def test_concurrent_same_named_downloads_do_not_share_temp_or_bytes(self):
        barrier = threading.Barrier(2)
        def download(destination, url, **kwargs):
            archive(destination, kind='shader', payload=url)
            barrier.wait(timeout=5)
        def install(version):
            return content.download_content('shader', 'https://cdn.modrinth.com/'+version, 'same.zip',
                                            mc_version='1.21.11', loader='fabric', version_id=version)
        with patch.object(content.net, 'download_to', side_effect=download), ThreadPoolExecutor(max_workers=2) as pool:
            paths = list(pool.map(install, ('instance-A', 'instance-B')))
        self.assertNotEqual(os.path.realpath(paths[0]), os.path.realpath(paths[1]))
        for path, version in zip(paths, ('instance-A', 'instance-B')):
            with zipfile.ZipFile(path) as z: self.assertTrue(z.read('shaders/test.fsh').decode().endswith(version))
        self.assertFalse(list((self.root/'store/shaderpacks').glob('.fetch-*')))

    def test_failed_download_cleans_partials_and_rejects_non_shaders(self):
        def fail(destination, *a, **kw):
            Path(destination+'.part').write_bytes(b'partial'); raise OSError('offline')
        with patch.object(content.net, 'download_to', side_effect=fail), self.assertRaises(OSError):
            content.download_content('shader', 'https://cdn.modrinth.com/x', 'test.zip', mc_version='1.21.11', loader='fabric')
        self.assertEqual(list((self.root/'store/shaderpacks').iterdir()), [])
        source = archive(self.root/'not-shaders.zip')
        with self.assertRaises(ValueError): content.install_local_content('shader', str(source), '1.21.11', loader='fabric')

    def test_local_repair_leaves_source_and_sibling_store_unchanged(self):
        source = self.root/'old.zip'; archive(source)
        original = source.read_bytes()
        content.install_local_content('resourcepack', str(source), '1.21.11', 'instance-A', 'fabric')
        with patch.object(content, '_profile_formats', return_value=[84]):
            name = content.install_local_content('resourcepack', str(source), '1.21.11', 'instance-B', 'fabric')
        self.assertEqual(source.read_bytes(), original)
        path = Path(content.profile_dir('resourcepack', '1.21.11', 'fabric', 'instance-B'))/name
        self.assertTrue(packformat.pack_verdict(path, [84])['ok'])

    def test_folder_flatten_detaches_shared_symlink(self):
        stored = self.root/'shared'; (stored/'wrapper/shaders').mkdir(parents=True)
        (stored/'wrapper/shaders/test.fsh').write_text('shader')
        linked = self.root/'linked'; linked.symlink_to(stored, target_is_directory=True)
        self.assertTrue(packformat.flatten_pack(str(linked), 'wrapper'))
        self.assertTrue((stored/'wrapper/shaders/test.fsh').exists())
        self.assertTrue((linked/'shaders/test.fsh').exists())
        self.assertFalse(linked.is_symlink())

    def test_forged_cache_alias_never_publishes_wrong_file(self):
        wrong = self.root/'wrong.jar'; wrong.write_bytes(b'wrong')
        cache.put_file(str(wrong), str(self.root/'first.jar'))
        good = b'correct'; digest = hashlib.sha512(good).hexdigest()
        index = cache._load_index(); index['manifest'][digest] = hashlib.sha256(b'wrong').hexdigest(); cache._save_index(index)
        fetches = []
        def fetch(path): fetches.append(path); Path(path).write_bytes(good)
        cache.get_or_fetch(str(self.root/'result.jar'), fetch, {'sha512': digest})
        self.assertEqual((self.root/'result.jar').read_bytes(), good)
        self.assertEqual(len(fetches), 1)

    def test_cached_local_install_still_checks_requested_hashes(self):
        source = self.root/'source.jar'; source.write_bytes(b'jar')
        cache.put_file(str(source), str(self.root/'first.jar'))
        with self.assertRaises(ValueError): cache.put_file(str(source), str(self.root/'second.jar'), {'sha1': '0'*40})
        self.assertFalse((self.root/'second.jar').exists())

    def test_mod_download_failure_cleans_double_part_suffix(self):
        def fetch(path): Path(path+'.part').write_bytes(b'half'); raise OSError('offline')
        with self.assertRaises(OSError): cache.get_or_fetch(str(self.root/'test.jar'), fetch)
        self.assertFalse(list((self.root/'mods-store').glob('.fetch-*')))

    def test_cache_name_collisions_progress_and_verify(self):
        store = self.root/'mods-store'; store.mkdir()
        payload = b'fresh'; digest = hashlib.sha256(payload).hexdigest()
        (store/'same.jar').write_bytes(b'old'); (store/f'same.{digest[:8]}.jar').write_bytes(b'corrupt')
        result = cache._choose_store_name(digest, 'same.jar', {'sha256': {}})
        self.assertNotIn(result, ('same.jar', f'same.{digest[:8]}.jar'))

    def test_bad_metadata_fields_do_not_escape_into_ui(self):
        name, path = self.install('shader')
        (self.root/'meta.json').write_text(json.dumps({'shader': {name: {'slug': {}, 'title': 42, 'icon_url': []}}}))
        item = content.list_content('shader', '1.21.11', loader='fabric', version_id='instance-A')[0]
        self.assertNotIn('slug', item); self.assertNotIn('title', item)

    def test_version_selection_skips_malformed_empty_and_mismatched_releases(self):
        versions = [None, {'files': []}, {'files': [None]}, {'game_versions': ['1.20.1'], 'files': [{'filename': 'other.zip', 'url': 'url'}]},
                    {'game_versions': ['1.21.11'], 'files': [{'filename': 'good.zip', 'url': 'url', 'size': 'bad'}]}]
        result = mods._select_download(versions, mc_version='1.21.11', extensions=('.zip',))
        self.assertEqual(result['filename'], 'good.zip'); self.assertEqual(result['size_kb'], 0)

    def test_120_browse_includes_compatible_patch_tags_and_preserves_filters(self):
        for kind in ('resourcepack', 'shader'):
            for mc in ('1.20', '1.20.0'):
                with self.subTest(kind=kind, mc=mc):
                    old_key = dict(type=kind, query='test', mc_version=mc,
                                   categories=['realistic'], limit=24, offset=24)
                    content.local_cache.set('search_content', old_key, [])

                    def search(url, **kwargs):
                        params = kwargs['params']
                        facets = json.loads(params['facets'])
                        self.assertIn(['versions:1.20', 'versions:1.20.1'], facets)
                        self.assertIn([f'project_type:{kind}'], facets)
                        self.assertIn(['categories:realistic'], facets)
                        self.assertEqual(params['offset'], '24')
                        self.assertEqual(params['limit'], '24')
                        return {'hits': [{'project_id': 'compatible', 'slug': 'compatible'}]}

                    with patch.object(content.net, 'get_json', side_effect=search) as network:
                        found = content.search_content(kind, 'test', mc, ['realistic'], 24, 24)
                    self.assertEqual(found[0]['slug'], 'compatible')
                    self.assertEqual(network.call_count, 1)

    def test_120_download_prefers_exact_then_compatible_zip_and_rejects_other_formats(self):
        def release(mc, filename):
            return {'game_versions': [mc], 'files': [{'filename': filename, 'url': 'https://cdn.modrinth.com/' + filename}]}

        for kind in ('shader', 'resourcepack'):
            for mc in ('1.20', '1.20.0'):
                with self.subTest(kind=kind, mc=mc):
                    versions = [release('1.20.2', 'wrong-format.zip'),
                                release('1.20.1', 'not-a-pack.jar'),
                                release('1.20.1', 'compatible.zip')]
                    with patch.object(content.net, 'get_json', return_value=versions) as network:
                        found = content.get_content_download(kind, 'patch-' + mc, mc)
                    self.assertEqual(found['filename'], 'compatible.zip')
                    self.assertEqual(json.loads(network.call_args.kwargs['params']['game_versions']), ['1.20', '1.20.1'])
                    versions.append(release('1.20', 'exact.zip'))
                    with patch.object(content.net, 'get_json', return_value=versions):
                        found = content.get_content_download(kind, 'exact-' + mc, mc)
                    self.assertEqual(found['filename'], 'exact.zip')
                    with patch.object(content.net, 'get_json', return_value=versions[:1]):
                        self.assertIsNone(content.get_content_download(kind, 'wrong-' + mc, mc))
        self.assertEqual(content.content_mc_versions('1.20.2'), ['1.20.2'])
        self.assertEqual(content.content_mc_versions('26.3'), ['26.3'])

    def test_redirects_validate_each_hop_before_request(self):
        class Response:
            status_code = 302
            headers = {'Location': 'https://localhost/private'}
            closed = False
            def close(self): self.closed = True
        response = Response()
        with patch.object(net, '_do_get', return_value=response) as get, self.assertRaises(net.DownloadError):
            net.get_with_retry('https://cdn.modrinth.com/file', url_validator=_host_allowed, attempts=1)
        self.assertEqual(get.call_count, 1); self.assertTrue(response.closed)
        for url in ('https://user:pass@cdn.modrinth.com/x', 'https://cdn.modrinth.com:81/x', 'https://cdn.modrinth.com:invalid/x'):
            self.assertFalse(_host_allowed(url))

    def test_oversized_descriptors_are_not_decompressed(self):
        jar = self.root/'large.jar'
        with zipfile.ZipFile(jar, 'w', zipfile.ZIP_DEFLATED) as z: z.writestr('fabric.mod.json', ' '* (1024*1024+1))
        with patch.object(zipfile.ZipFile, 'open', side_effect=AssertionError('must reject by declared size')):
            self.assertIsNone(mods.read_mod_metadata(jar))

    def test_nested_metadata_reads_top_level_from_disk_and_keeps_provided_ids(self):
        nested = io.BytesIO()
        with zipfile.ZipFile(nested, 'w') as z: z.writestr('fabric.mod.json', json.dumps({'id': 'nested', 'version': '2'}))
        top = self.root/'parent.jar'
        with zipfile.ZipFile(top, 'w') as z:
            z.writestr('fabric.mod.json', json.dumps({'id': 'parent', 'version': '1'}))
            z.writestr('META-INF/jars/nested.jar', nested.getvalue())
        self.assertEqual(mods._nested_mod_metadata(top, loader='fabric'), {'parent': '1', 'nested': '2'})

    def test_archive_rewrite_streams_assets(self):
        pack = self.root/'large.zip'; archive(pack, payload='texture'*200000)
        original_read = zipfile.ZipFile.read
        def guarded(z, name, *a, **kw):
            self.assertNotIn('assets/', str(name))
            return original_read(z, name, *a, **kw)
        with patch.object(zipfile.ZipFile, 'read', guarded): packformat.repair_pack(pack, [84])
        with zipfile.ZipFile(pack) as z: self.assertEqual(z.read('assets/test.txt'), ('texture'*200000).encode())


if __name__ == '__main__': unittest.main()
