"""Avatar publication and Discord replay checks, without HTTP or Discord."""
import hashlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
import _sandbox_home
_sandbox_home.isolate()
from PIL import Image
from cubeon import skins, discord_rpc


def png(size, color):
    output = io.BytesIO()
    Image.new('RGBA', size, color).save(output, format='PNG')
    return output.getvalue()


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.sheet = png((64, 64), 'purple')
        self.face = png((128, 128), 'purple')
        self.config = {'username': 'bgkiller_91', 'active_skin': 'enderman.png'}
        self.posts = []
        self.response = SimpleNamespace(status_code=200, json=lambda: {})
        for context in (
            patch.object(skins, '_PUBLISH_STATE_PATH', str(Path(self.temp.name)/'skin_net.json')),
            patch.object(skins, 'stable_uuid', return_value='00000000-0000-0000-0000-000000000001'),
            patch.object(skins, 'stable_secret', return_value='fixture-secret'),
            patch.object(skins, '_composed_skin_png', return_value=self.sheet),
            patch.object(skins, '_compose_face_png', return_value=self.face),
            patch.object(skins, '_active_skin_is_slim', return_value=False),
            patch('cubeon.cosmetics.selection_payload', side_effect=lambda cfg: {'version': 1}),
            patch.object(skins, '_post', side_effect=lambda url, **kw: self.posts.append((url, kw)) or self.response),
        ):
            context.start()
            self.addCleanup(context.stop)
        skins._save_publish_state({'username': 'bgkiller_91', 'uuid': skins.stable_uuid(),
                                   'base': skins.csl.CUBEON_API_BASE, 'cosmetics': {},
                                   'hash': hashlib.sha256(self.sheet).hexdigest(), 'model': 'default'})

    def test_old_skin_record_uploads_face_once_then_exposes_immutable_url(self):
        self.assertIsNone(skins.get_discord_face_url('bgkiller_91'))
        skins._publish_skin(self.config)
        self.assertEqual(len(self.posts), 1)
        self.assertEqual(self.posts[0][0], skins._UPLOAD_URL)
        self.assertIn('face', self.posts[0][1]['json'])
        expected = skins.csl.CUBEON_API_BASE+'/textures/'+hashlib.sha256(self.face).hexdigest()
        self.assertEqual(skins.get_discord_face_url('BGKILLER_91'), expected)
        skins._publish_skin(self.config)
        self.assertEqual(len(self.posts), 1, 'Unchanged skins must not spend more writes')

    def test_failed_upload_never_advertises_missing_face(self):
        self.response.status_code = 503
        skins._publish_skin(self.config)
        self.assertIsNone(skins.get_discord_face_url('bgkiller_91'))
        self.assertNotIn('face_version', skins._load_publish_state())

    def test_optional_cosmetic_failure_cannot_prevent_skin_face_upload(self):
        state = skins._load_publish_state()
        state.pop('cosmetics')
        skins._save_publish_state(state)
        def post(url, **kwargs):
            self.posts.append((url, kwargs))
            return SimpleNamespace(status_code=200 if url==skins._UPLOAD_URL else 503, json=lambda: {})
        with patch.object(skins, '_post', side_effect=post):
            skins._publish_skin(self.config)
        self.assertEqual([url for url, _ in self.posts],
                         [skins._UPLOAD_URL, skins.csl.CUBEON_API_BASE+'/api/cosmetics'])
        self.assertIsNotNone(skins.get_discord_face_url('bgkiller_91'))
        self.assertTrue(skins._publish_on_cooldown(skins._load_publish_state()))

    def test_unrelated_name_service_or_invalid_hash_cannot_reuse_avatar(self):
        skins._publish_skin(self.config)
        self.assertIsNone(skins.get_discord_face_url('AnotherPlayer'))
        state = skins._load_publish_state()
        for key, value in (('face_hash', '../not-an-image'), ('base', 'https://old.example')):
            changed = {**state, key: value}
            skins._save_publish_state(changed)
            self.assertIsNone(skins.get_discord_face_url('bgkiller_91'))


class RpcTests(unittest.TestCase):
    def setUp(self):
        with patch.object(discord_rpc.threading.Thread, 'start'):
            self.rpc = discord_rpc.DiscordPresence('fixture-client')
        self.addCleanup(self.rpc.close)
        self.sent = []
        self.rpc._ipc = object()
        self.rpc._ensure_connected = lambda: True
        self.rpc._write_frame = lambda op, payload: self.sent.append(payload)
        self.rpc._drop_ipc = lambda: None
        self.avatar = None

    def announce(self):
        self.rpc.set_activity(state='Playing Minecraft 1.21.11 (Fabric)', start=123,
                              large_image='cubeon', small_text='bgkiller_91',
                              small_image_provider=lambda: self.avatar)

    def replay_once(self):
        with patch.object(self.rpc._stop, 'wait', side_effect=[False, True]):
            self.rpc._retry_loop()

    def test_replay_adds_ready_face_without_resetting_game_or_timer(self):
        self.announce()
        self.assertNotIn('small_image', self.sent[-1]['args']['activity']['assets'])
        self.avatar = 'https://skins.example/textures/'+'a'*64
        self.replay_once()
        activity = self.sent[-1]['args']['activity']
        self.assertEqual(activity['assets']['small_image'], self.avatar)
        self.assertEqual(activity['assets']['small_text'], 'bgkiller_91')
        self.assertEqual(activity['assets']['large_image'], 'cubeon')
        self.assertEqual(activity['state'], 'Playing Minecraft 1.21.11 (Fabric)')
        self.assertEqual(activity['timestamps']['start'], 123)
        self.avatar = 'https://skins.example/textures/'+'b'*64
        self.replay_once()
        self.assertEqual(self.sent[-1]['args']['activity']['assets']['small_image'], self.avatar)

    def test_clear_cannot_resurrect_avatar(self):
        self.announce()
        self.rpc.clear()
        self.avatar = 'https://skins.example/textures/'+'a'*64
        self.replay_once()
        self.assertEqual(self.sent[-1]['args']['activity'], {})


if __name__ == '__main__':
    unittest.main()
