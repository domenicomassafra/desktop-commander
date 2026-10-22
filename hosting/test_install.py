import importlib.util
import json
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('installer', Path(__file__).with_name('install.py'))
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class ProjectionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        for name, value in [('HOME', self.home), ('BASE', self.home / 'runtime'),
                            ('CONFIG', self.home / 'config'), ('STATE', self.home / 'state')]:
            p = patch.object(installer, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.release = self.home / 'release'
        (self.release / 'dist').mkdir(parents=True)
        (self.release / 'dist/index.js').write_text('')
        self.env = patch.dict(installer.os.environ, {
            'MINIPC_MCP_TOKEN': 'test-only-token', 'MINIPC_MCP_OAUTH_PASSWORD': 'test-only-password'})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_minipc_keeps_secrets_out_of_children_and_unit(self):
        with patch.object(installer.subprocess, 'run') as run:
            run.return_value.stdout = '$2b$12$test'
            unit = installer.configure('minipc', self.release, 'https://owner.example')
        config = json.loads((installer.CONFIG / 'mcp.json').read_text())
        self.assertEqual(list(config['mcpServers']), ['studio', 'minipc'])
        child = config['mcpServers']['minipc']['env']
        self.assertNotIn('MINIPC_MCP_TOKEN', child)
        self.assertEqual(child['DESKTOP_COMMANDER_DISABLE_TELEMETRY'], '1')
        self.assertTrue(child['DC_FLAG_URL'].startswith('data:'))
        self.assertIn('NoNewPrivileges=yes', unit.read_text())
        for path in [unit, installer.CONFIG / 'mcp.json']:
            self.assertNotIn('test-only-token', path.read_text())
            self.assertNotIn('test-only-password', path.read_text())
        private = installer.CONFIG / 'gateway-env.json'
        self.assertEqual(private.stat().st_mode & 0o777, 0o600)
        self.assertNotIn('PASSWORD', json.loads(private.read_text()))

    def test_studio_uses_native_gateway_and_sandbox(self):
        installer.BASE.mkdir()
        (installer.BASE / 'supergateway').write_text('')
        path = installer.configure('studio', self.release, 'https://owner.example')
        plist = plistlib.loads(path.read_bytes())
        self.assertEqual(plist['ProgramArguments'][0], '/usr/bin/sandbox-exec')
        self.assertIn('--apiKeyFile', plist['ProgramArguments'])
        self.assertNotIn('test-only-token', str(plist))
        self.assertEqual((installer.CONFIG / 'studio-api-key').stat().st_mode & 0o777, 0o600)

    def test_missing_build_fails_without_projection(self):
        (self.release / 'dist/index.js').unlink()
        with self.assertRaises(SystemExit):
            installer.configure('minipc', self.release, 'https://owner.example')
        self.assertFalse(installer.CONFIG.exists())


if __name__ == '__main__':
    unittest.main()
