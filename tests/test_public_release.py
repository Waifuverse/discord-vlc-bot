import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from dotenv import dotenv_values

import config
from scripts.check_public_files import ROOT, TEMPLATE, forbidden_path, scan
from setup_config import prepare_env


class PublicReleaseTests(unittest.TestCase):
    def setUp(self):
        self.template = (ROOT / TEMPLATE).read_bytes()

    def test_template_is_blank_and_safe_to_publish(self):
        self.assertEqual(scan({TEMPLATE: self.template}), [])
        values = dotenv_values(stream=io.StringIO(self.template.decode()))
        self.assertEqual(values['MEDIA_ROOT'], 'media')
        self.assertEqual(values['VLC_URL'], 'http://127.0.0.1:8080')

    def test_new_installations_receive_distinct_private_passwords(self):
        with tempfile.TemporaryDirectory() as directory, patch('builtins.print'):
            paths = [Path(directory) / name for name in ('one.env', 'two.env')]
            for path in paths:
                prepare_env(path)
            values = [dotenv_values(path) for path in paths]
            self.assertNotEqual(values[0]['VLC_PASSWORD'], values[1]['VLC_PASSWORD'])
            for value in values:
                self.assertGreaterEqual(len(value['VLC_PASSWORD']), 32)
                self.assertEqual(value['DISCORD_TOKEN'], '')
                self.assertEqual(value['DISCORD_GUILD_ID'], '')
                self.assertEqual(value['MEDIA_ROOT'], 'media')

    def test_media_paths_resolve_from_installation_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            with patch('config.ROOT', root):
                settings = config.Settings('fixture', 1, 2, 'fixture')
                self.assertEqual(settings.media_root, root / 'media')
                self.assertEqual(config.media_directory('shows'), root / 'shows')
                self.assertEqual(config.media_directory(str(root / 'external')), root / 'external')
                values = {'DISCORD_TOKEN': 'fixture', 'VLC_PASSWORD': 'fixture',
                          'DISCORD_GUILD_ID': '111111111111111111',
                          'DISCORD_CHANNEL_ID': '222222222222222222', 'MEDIA_ROOT': 'videos'}
                self.assertEqual(config.Settings.read(values).media_root, root / 'videos')

    def test_private_paths_are_rejected(self):
        for name in ('.env', '.env.backup', 'copy.env', 'backup/.env.local',
                     '.state/playlist.json', '.venv/pyvenv.cfg', 'media/show/movie.mp4',
                     'private/movie.mkv', 'LIBRARY_REVIEW.md', 'bot.log'):
            with self.subTest(name=name):
                self.assertTrue(forbidden_path(name))
        for name in (TEMPLATE, 'README.md', 'bot.py', 'media/README.md'):
            self.assertFalse(forbidden_path(name))

    def test_copied_secrets_are_detected_without_echoing_values(self):
        secret = 'local-fixture-secret-value'
        issues = scan({TEMPLATE: self.template, 'notes.md': secret.encode()},
                      {'VLC_PASSWORD': secret})
        self.assertTrue(any('notes.md' in issue for issue in issues))
        self.assertNotIn(secret, '\n'.join(issues))
        fixtures = [('ghp_' + 'x' * 36).encode(),
                    ('C:/' + 'Users/' + 'Example/' + 'Videos').encode()]
        for value in fixtures:
            self.assertTrue(scan({TEMPLATE: self.template, 'notes.md': value}))

    def test_git_ignores_runtime_files_but_allows_template(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.gitignore').write_bytes((ROOT / '.gitignore').read_bytes())
            subprocess.run(['git', 'init', '-q'], cwd=root, check=True, capture_output=True)
            for name in ('.env', '.env.backup', '.state/playlist.json', '.venv/pyvenv.cfg',
                         'media/show/episode.mp4'):
                result = subprocess.run(['git', 'check-ignore', '-q', name], cwd=root)
                self.assertEqual(result.returncode, 0, name)
            for name in (TEMPLATE, 'media/README.md'):
                result = subprocess.run(['git', 'check-ignore', '-q', name], cwd=root)
                self.assertEqual(result.returncode, 1, name)


if __name__ == '__main__':
    unittest.main()
