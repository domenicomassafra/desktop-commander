import importlib.util
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('prepare', Path(__file__).with_name('prepare-secrets.py'))
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


class NativeWriterTest(unittest.TestCase):
    def test_existing_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / 'candidate.age'
            output.write_bytes(b'previous-ciphertext')
            with self.assertRaises(ValueError):
                prepare.prepare(output)
            self.assertEqual(output.read_bytes(), b'previous-ciphertext')

    def test_source_map_is_preserved_and_only_studio_key_added(self):
        with tempfile.TemporaryDirectory() as root:
            source, output = Path(root) / 'source.age', Path(root) / 'candidate.age'
            source.write_bytes(b'original-ciphertext')
            original = {'EXISTING': 'test-only', 'DISCORD_BOT_TOKEN': 'test-discord'}
            result = {}

            def write(catalog, path):
                result.update(catalog)
                path.write_bytes(b'new-ciphertext')

            writer = types.SimpleNamespace(read_ciphertext_catalog=lambda p: dict(original), write_ciphertext=write)
            with patch.object(prepare, 'native_writer', return_value=writer):
                prepare.prepare(output, source)
            self.assertEqual({k: result[k] for k in original}, original)
            self.assertEqual(set(result) - set(original), {
                'DESKTOP_COMMANDER_API_TOKEN'})
            self.assertEqual(source.read_bytes(), b'original-ciphertext')

    def test_concurrent_source_change_discards_candidate(self):
        with tempfile.TemporaryDirectory() as root:
            source, output = Path(root) / 'source.age', Path(root) / 'candidate.age'
            source.write_bytes(b'original-ciphertext')

            def write(catalog, path):
                path.write_bytes(b'candidate-ciphertext')
                source.write_bytes(b'another-writer-ciphertext')

            writer = types.SimpleNamespace(read_ciphertext_catalog=lambda p: {'EXISTING': 'test-only'}, write_ciphertext=write)
            with patch.object(prepare, 'native_writer', return_value=writer):
                with self.assertRaises(ValueError):
                    prepare.prepare(output, source)
            self.assertFalse(output.exists())
            self.assertEqual(source.read_bytes(), b'another-writer-ciphertext')


if __name__ == '__main__':
    unittest.main()
