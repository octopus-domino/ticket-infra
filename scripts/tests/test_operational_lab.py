import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from operational_lab import Lab, artifact_sha256, require_restore_inputs


class OperationalLabTest(unittest.TestCase):
    def test_restore_rejects_missing_archive_and_incompatible_release_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts = {name: root / name for name in ('database', 'files', 'document', 'routing')}
            for name, path in artifacts.items():
                path.write_bytes(name.encode('ascii'))
            manifest = {name: artifact_sha256(path) for name, path in artifacts.items()}
            require_restore_inputs(manifest, artifacts)

            artifacts['files'].unlink()
            with self.assertRaisesRegex(RuntimeError, 'artifact missing: files'):
                require_restore_inputs(manifest, artifacts)

            artifacts['files'].write_bytes(b'files')
            artifacts['routing'].write_bytes(b'different release')
            with self.assertRaisesRegex(RuntimeError, 'checksum mismatch: routing'):
                require_restore_inputs(manifest, artifacts)

    def test_lab_rejects_nonlocal_docker_before_allocating_a_workspace(self):
        context = [{'Endpoints': {'docker': {'Host': 'tcp://docker.example.test:2376'}}}]
        with patch('operational_lab.docker', return_value=json.dumps(context).encode()), \
                patch('operational_lab.tempfile.mkdtemp') as allocate:
            with self.assertRaisesRegex(RuntimeError, 'local Docker socket'):
                Lab()
            allocate.assert_not_called()
