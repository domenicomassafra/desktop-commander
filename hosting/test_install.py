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
            'DESKTOP_COMMANDER_API_TOKEN': 'test-only-token', 'COMPUTER_MCP_OPENAI_RUNTIME_KEY': 'test-only-runtime'})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_minipc_keeps_secrets_out_of_children_and_unit(self):
        with patch.object(installer.subprocess, 'run') as run:
            run.return_value.stdout = '$2b$12$test'
            unit = installer.configure('minipc', self.release)
        config = json.loads((installer.CONFIG / 'mcp.json').read_text())
        self.assertEqual(list(config['mcpServers']), ['studio', 'minipc'])
        child = config['mcpServers']['minipc']['env']
        self.assertNotIn('DESKTOP_COMMANDER_API_TOKEN', child)
        self.assertEqual(child['DESKTOP_COMMANDER_DISABLE_TELEMETRY'], '1')
        self.assertTrue(child['DC_FLAG_URL'].startswith('data:'))
        self.assertIn('NoNewPrivileges=yes', unit.read_text())
        for path in [unit, installer.CONFIG / 'mcp.json']:
            self.assertNotIn('test-only-token', path.read_text())
            self.assertNotIn('test-only-password', path.read_text())
        private = installer.CONFIG / 'gateway-env.json'
        self.assertEqual(private.stat().st_mode & 0o777, 0o600)
        self.assertNotIn('PASSWORD', json.loads(private.read_text()))

    def test_private_stdio_has_no_listener_oauth_or_cloudflare(self):
        with patch.dict(installer.os.environ, {'COMPUTER_MCP_OPENAI_RUNTIME_KEY': 'test-only-runtime'}):
            with patch.object(installer.subprocess, 'run') as run:
                unit = installer.configure('minipc', self.release)
        environment = json.loads((installer.CONFIG / 'gateway-env.json').read_text())
        for key in ['PORT', 'EXTERNAL_URL', 'PASSWORD_HASH', 'PASSWORD', 'COMPUTER_MCP_OPENAI_RUNTIME_KEY']:
            self.assertNotIn(key, environment)
        self.assertEqual(environment['DESKTOP_COMMANDER_API_TOKEN'], 'test-only-token')
        self.assertEqual((installer.CONFIG / 'openai-runtime-key').read_text(), 'test-only-runtime')
        self.assertEqual((installer.CONFIG / 'openai-runtime-key').stat().st_mode & 0o777, 0o600)
        self.assertIn('tunnel-client run --profile computer-mcp', unit.read_text())
        self.assertIn('tunnel-client-0.0.18/tunnel-client run', unit.read_text())
        command = run.call_args.args[0]
        self.assertIn('tunnel-client-0.0.18/tunnel-client', command[0])
        self.assertIn('sample_mcp_stdio_local', command)
        self.assertIn('file:' + str(installer.CONFIG / 'openai-runtime-key'), command)
        self.assertNotIn('test-only-runtime', str(command))
        self.assertIn('tunnel_6ada9565bc9081918acfcd3dee77b650', command)

    def test_studio_uses_native_gateway_and_sandbox(self):
        installer.BASE.mkdir()
        (installer.BASE / 'supergateway-4.2.1').write_text('')
        path = installer.configure('studio', self.release)
        plist = plistlib.loads(path.read_bytes())
        self.assertEqual(plist['ProgramArguments'][0], '/usr/bin/sandbox-exec')
        self.assertIn('supergateway-4.2.1', plist['ProgramArguments'][3])
        self.assertIn('--apiKeyFile', plist['ProgramArguments'])
        self.assertNotIn('test-only-token', str(plist))
        self.assertEqual((installer.CONFIG / 'studio-api-key').stat().st_mode & 0o777, 0o600)

    def test_missing_build_fails_without_projection(self):
        (self.release / 'dist/index.js').unlink()
        with self.assertRaises(SystemExit):
            installer.configure('minipc', self.release)
        self.assertFalse(installer.CONFIG.exists())


if __name__ == '__main__':
    unittest.main()
