"""Offline cancellation checks for streaming, cached files and dependency batches."""
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
import _sandbox_home
_sandbox_home.isolate()
from cubeon import global_mod_cache, mods, net


class ModInstallCancelTests(unittest.TestCase):
    def test_cancel_interrupts_retry_backoff_without_another_request(self):
        event = threading.Event()
        class Response:
            status_code = 429
            headers = {'Retry-After': '120'}
            def close(self):
                event.set()
        with patch.object(net, '_do_get', return_value=Response()) as request, \
                patch.object(net.time, 'sleep') as sleep:
            with self.assertRaises(net.DownloadCancelled):
                net.get_with_retry('https://cdn.modrinth.com/file.jar',
                                   cancel_check=lambda: net.check_cancelled(event))
            self.assertEqual(request.call_count, 1)
            sleep.assert_not_called()

    def test_cancel_midstream_closes_response_and_preserves_existing_file(self):
        event = threading.Event()
        class Response:
            status_code = 200
            headers = {'content-length': '131072'}
            closed = False
            def iter_content(self, chunk_size):
                yield b'a' * 65536
                yield b'b' * 65536
            def close(self):
                self.closed = True
        response = Response()
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'existing.jar'
            target.write_bytes(b'original')
            with patch.object(net, 'get_with_retry', return_value=response) as request:
                with self.assertRaises(net.DownloadCancelled):
                    net.download_to(str(target), 'https://cdn.modrinth.com/file.jar',
                                    progress_cb=lambda done, total: event.set(),
                                    cancel_check=lambda: net.check_cancelled(event))
                self.assertEqual(request.call_count, 1)
            self.assertTrue(response.closed)
            self.assertEqual(target.read_bytes(), b'original')
            self.assertFalse(Path(str(target) + '.part').exists())

    def test_cancelled_cache_hit_does_not_link_into_profile(self):
        event = threading.Event()
        def check_hashes(*args):
            event.set()
            return True
        with patch.object(global_mod_cache, '_resolve_manifest_hash', return_value='cached.jar'), \
                patch.object(global_mod_cache, '_matches_hashes', side_effect=check_hashes), \
                patch.object(global_mod_cache, 'link_into_place') as link:
            with self.assertRaises(net.DownloadCancelled):
                global_mod_cache.get_or_fetch('profile.jar', lambda target: self.fail('No download'),
                    cancel_check=lambda: net.check_cancelled(event))
            link.assert_not_called()

    def test_cancelled_cache_miss_cleans_temporary_file(self):
        event = threading.Event()
        with tempfile.TemporaryDirectory() as folder:
            def fetch(target):
                Path(target).write_bytes(b'partial')
                event.set()
            with patch.object(global_mod_cache, '_resolve_manifest_hash', return_value=None), \
                    patch.object(global_mod_cache, '_store_root', return_value=folder), \
                    patch.object(global_mod_cache, '_ingest') as ingest:
                with self.assertRaises(net.DownloadCancelled):
                    global_mod_cache.get_or_fetch(os.path.join(folder, 'profile.jar'), fetch,
                        cancel_check=lambda: net.check_cancelled(event))
                ingest.assert_not_called()
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_dependency_cancel_is_not_swallowed_as_failed_dependency(self):
        event = threading.Event()
        downloaded = []
        def download(url, filename, **kwargs):
            downloaded.append(filename)
            if filename == 'first.jar':
                event.set()
                net.check_cancelled(kwargs['cancel_event'])
        dependencies = [{'project_id': 'first', 'filename': 'first.jar', 'url': 'offline'},
                        {'project_id': 'second', 'filename': 'second.jar', 'url': 'offline'}]
        with patch.object(mods, 'installed_project_ids', return_value=set()), \
                patch.object(mods, 'required_dependencies', return_value=dependencies), \
                patch.object(mods, 'download_mod', side_effect=download), \
                patch('cubeon.mod_dependencies.run_dependency_doctor') as doctor:
            with self.assertRaises(net.DownloadCancelled):
                mods.install_mod_with_dependencies('offline', 'main.jar', '1.21.11', 'fabric',
                                                    project_id='main', cancel_event=event)
            doctor.assert_not_called()
        self.assertEqual(downloaded, ['main.jar', 'first.jar'])

    def test_cancellation_from_batch_progress_is_not_swallowed(self):
        event = threading.Event()
        def progress(done, total):
            event.set()
            net.check_cancelled(event)
        def download(url, filename, **kwargs):
            kwargs['progress_cb'](1, 2)
        with patch.object(mods, 'installed_project_ids', return_value=set()), \
                patch.object(mods, 'required_dependencies', return_value=[]), \
                patch.object(mods, 'download_mod', side_effect=download):
            with self.assertRaises(net.DownloadCancelled):
                mods.install_mod_with_dependencies('offline', 'main.jar', '1.21.11', 'fabric',
                    project_id='main', progress_cb=progress, cancel_event=event)


if __name__ == '__main__':
    unittest.main()
