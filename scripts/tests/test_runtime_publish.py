import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import runtime_publish as publish
import runtime_publish_remote as remote


class RuntimePublishTest(unittest.TestCase):
    def test_frontend_archive_omits_hidden_configuration_and_keeps_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            web = root / 'dist'
            (web / 'assets').mkdir(parents=True)
            (web / 'index.html').write_text('<html></html>')
            (web / '.env.local').write_text('PRIVATE_TEST_VALUE')
            (web / 'assets/app.js').write_text('console.log(1)')
            payload = root / 'payload.zip'
            publish.pack_web(web, payload)
            with zipfile.ZipFile(payload) as archive:
                self.assertEqual(set(archive.namelist()), {'web/index.html', 'web/assets/app.js'})

    def test_web_publish_checks_that_nginx_serves_the_new_index(self):
        for component in ('editor', 'private-journey'):
            for response in (b'new index', b'old index'):
                with self.subTest(component=component, response=response), tempfile.TemporaryDirectory() as directory:
                    stage = Path(directory)
                    web = stage / 'web'
                    web.mkdir()
                    (web / 'index.html').write_bytes(b'new index')
                    config = dict(container='test', component=component)
                    with patch.object(remote, 'build_image'), patch.object(remote, 'run', return_value=SimpleNamespace(stdout=response)) as call:
                        if response == b'new index':
                            remote.publish_web(config, stage, 'release')
                        else:
                            with self.assertRaisesRegex(RuntimeError, 'did not serve'):
                                remote.publish_web(config, stage, 'release')
                        suffix = '/private-journey/' if component == 'private-journey' else '/'
                        self.assertEqual(call.call_args.args[-1], 'http://127.0.0.1' + suffix)

    def test_traversal_or_unexpected_payloads_are_rejected_before_extraction(self):
        for name in ['web/../../outside', '/web/index.html', 'BOOT-INF/classes/evil.class']:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                payload = Path(directory) / 'payload.zip'
                with zipfile.ZipFile(payload, 'w') as archive:
                    archive.writestr(name, 'bad')
                with zipfile.ZipFile(payload) as archive:
                    with self.assertRaises(ValueError):
                        remote.checked_members(archive, 'web')
        # Windows' ZIP writer normalizes separators; emulate the original Linux archive metadata.
        entry = SimpleNamespace(filename='web\\outside', orig_filename='web\\outside', file_size=3)
        archive = SimpleNamespace(infolist=lambda: [entry])
        with self.assertRaises(ValueError):
            remote.checked_members(archive, 'web')

    def test_class_patch_selects_only_requested_java17_class(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            classes = root / 'ru/ticket/demo'
            classes.mkdir(parents=True)
            for name in ['Selected', 'Unrelated']:
                (classes / (name + '.class')).write_bytes(b'\xca\xfe\xba\xbe\x00\x00\x00\x3d')
            payload = root / 'payload.zip'
            publish.pack_classes(root, ['ru/ticket/demo/Selected'], payload)
            with zipfile.ZipFile(payload) as archive:
                self.assertEqual(archive.namelist(), ['BOOT-INF/classes/ru/ticket/demo/Selected.class'])

    def test_health_requires_public_http200_and_does_not_accept401(self):
        class Result:
            returncode = 0
            def __init__(self, value): self.stdout = value
        config = dict(container='codoc-app-1', backend_port=8080, health_path='/api/guest/recognition/capabilities')
        with patch.object(remote.subprocess, 'run', side_effect=[Result(b'401'), Result(b'200')]) as call, patch.object(remote.time, 'sleep'):
            self.assertTrue(remote.ready(config))
            self.assertEqual(call.call_count, 2)

    def test_patching_preserves_executable_jar_metadata_and_existing_resources(self):
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory)
            original = stage / 'original.jar'
            entry = 'BOOT-INF/classes/ru/ticket/demo/Selected.class'
            with zipfile.ZipFile(original, 'w') as jar:
                jar.writestr(entry, b'old')
                info = zipfile.ZipInfo('BOOT-INF/lib/dependency.jar')
                info.compress_type = zipfile.ZIP_STORED
                jar.writestr(info, b'nested-library')
            payload = stage / 'payload.zip'
            with zipfile.ZipFile(payload, 'w') as archive:
                archive.writestr(entry, b'new')
            with zipfile.ZipFile(payload) as archive, patch.object(remote, 'run'):
                remote.patch_jar(dict(container='test'), stage, archive)
            with zipfile.ZipFile(stage / 'app.jar') as jar:
                self.assertEqual(jar.read(entry), b'new')
                self.assertEqual(jar.read('BOOT-INF/lib/dependency.jar'), b'nested-library')
                self.assertEqual(jar.getinfo('BOOT-INF/lib/dependency.jar').compress_type, zipfile.ZIP_STORED)

    def test_failed_health_restores_jar_and_image_without_touching_nginx(self):
        config = dict(container='test')
        with tempfile.TemporaryDirectory() as directory, patch.object(remote, 'patch_jar'), \
                patch.object(remote, 'backend_pid', return_value='42'), \
                patch.object(remote, 'build_image', return_value=('codoc-app:latest', 'codoc-app:backup')), \
                patch.object(remote, 'ready', side_effect=[False, True]), patch.object(remote, 'run') as run:
            with self.assertRaises(RuntimeError):
                remote.publish_backend(config, Path(directory), None, 'test-release')
            calls = [call.args for call in run.call_args_list]
            self.assertIn(('docker', 'tag', 'codoc-app:backup', 'codoc-app:latest'), calls)
            self.assertIn(('docker', 'exec', 'test', 'mv', '/app/app.jar.before-runtime-test-release', '/app/app.jar'), calls)
            self.assertFalse(any('nginx' in str(call) or 'compose' in str(call) for call in calls))


if __name__ == '__main__':
    unittest.main()
