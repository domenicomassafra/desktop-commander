#!/usr/bin/env python3
"""Project the reviewed Desktop Commander release; never touch the old connector."""
import argparse
import json
import os
from pathlib import Path
import plistlib
import shutil
import shlex
import subprocess

HOME = Path.home()
BASE = HOME / '.local/opt/desktop-commander'
CONFIG = HOME / '.config/desktop-commander'
STATE = HOME / '.local/state/desktop-commander'
FLAGS = 'data:application/json,{"flags":{}}'


def put(path, content, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_bytes(content if isinstance(content, bytes) else content.encode())
    temporary.chmod(mode)
    temporary.replace(path)


def configure(host, release, network_trace=False):
    release = Path(release).resolve(strict=True)
    node = shutil.which('node')
    if not node or not (release / 'dist/index.js').is_file():
        raise SystemExit('Node and a built release are required')
    CONFIG.mkdir(parents=True, exist_ok=True, mode=0o700)
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    for directory in (CONFIG, STATE):
        directory.chmod(0o700)
    common = {
        'DESKTOP_COMMANDER_DISABLE_TELEMETRY': '1',
        'DC_FLAG_URL': FLAGS,
        'PATH': os.environ['PATH'],
        'HOME': str(HOME),
    }
    if network_trace:
        common['NODE_DEBUG'] = 'net'
    if host == 'studio':
        gateway = BASE / 'supergateway-4.2.1'
        if not gateway.is_file():
            raise SystemExit('Install the attested Supergateway binary first')
        # Reuse an existing catalog secret, never invent a plaintext secret store.
        token = os.environ['DESKTOP_COMMANDER_API_TOKEN']
        put(CONFIG / 'studio-api-key', token + chr(10))
        put(CONFIG / 'no-elevation.sb', chr(10).join(['(version 1)', '(allow default)', '']) + ''.join(
            f'(deny process-exec (literal "{p}"))' + chr(10) for p in
            ['/usr/bin/sudo', '/usr/bin/su', '/usr/sbin/visudo', '/usr/bin/security']))
        label = 'it.domenico.desktop-commander'
        command = [str(gateway), '--host', '100.99.195.87', '--port', '9197',
                   '--apiKeyFile', str(CONFIG / 'studio-api-key'),
                   '--stdio', f'{node} {release}/dist/index.js --no-onboarding',
                   '--outputTransport', 'streamableHttp', '--stateful']
        plist = {
            'Label': label,
            'ProgramArguments': ['/usr/bin/sandbox-exec', '-f', str(CONFIG / 'no-elevation.sb'), *command],
            'EnvironmentVariables': common,
            'RunAtLoad': True, 'KeepAlive': True, 'ThrottleInterval': 10,
            'StandardOutPath': str(STATE / 'studio.stdout.log'),
            'StandardErrorPath': str(STATE / 'studio.stderr.log'),
        }
        path = HOME / 'Library/LaunchAgents' / (label + '.plist')
        put(path, plistlib.dumps(plist))
        return path
    # MCP is required by ChatGPT's remote file/process tool discovery and calls;
    # the local CLI cannot expose those MCP tools through the Secure MCP Tunnel.
    # mcp-hub uses the SDK safe environment for children, not the OAuth secrets.
    servers = {
        'studio': {
            'type': 'http', 'url': 'http://100.99.195.87:9197/mcp',
            'headers': {'Authorization': 'Bearer ${DESKTOP_COMMANDER_API_TOKEN}'},
        },
        'minipc': {
            'command': node, 'args': [str(release / 'dist/index.js'), '--no-onboarding'],
            'env': common, 'keepAlive': True,
        },
    }
    put(CONFIG / 'mcp.json', json.dumps({'mcpServers': servers}, indent=2) + chr(10))
    # Only the Studio API secret belongs in the stdio hub environment.
    env = {
        'CONFIG_PATH': str(CONFIG / 'mcp.json'),
        'TOOL_CACHE_PATH': str(STATE / 'tool-cache.json'),
        'PATH': common['PATH'],
        'DESKTOP_COMMANDER_API_TOKEN': os.environ['DESKTOP_COMMANDER_API_TOKEN'],
    }
    # Native stdio starts no listener or authorization server. Preserve old OAuth
    # state on disk: it is protected data, not part of the active transport.
    put(CONFIG / 'openai-runtime-key', os.environ['COMPUTER_MCP_OPENAI_RUNTIME_KEY'])
    subprocess.run([str(BASE / 'tunnel-client-0.0.18/tunnel-client'), 'init',
        '--sample', 'sample_mcp_stdio_local', '--profile', 'computer-mcp',
        '--profile-dir', str(CONFIG / 'tunnel-profiles'), '--force',
        '--tunnel-id', 'tunnel_6ada9565bc9081918acfcd3dee77b650',
        '--control-plane-api-key-ref', 'file:' + str(CONFIG / 'openai-runtime-key'),
        '--health-listen-addr', '127.0.0.1:8498',
        '--mcp-command', shlex.join(['/usr/bin/python3', str(BASE / 'hosting/run-gateway.py')])],
        check=True, capture_output=True, text=True)
    if network_trace:
        env['NODE_DEBUG'] = 'net'
    # JSON is read by the launcher, never sourced as shell or logged.
    put(CONFIG / 'gateway-env.json', json.dumps(env))
    unit_source = Path(__file__).with_name('desktop-commander.service').resolve(strict=True)
    path = HOME / '.config/systemd/user/desktop-commander.service'
    put(path, unit_source.read_bytes(), 0o644)
    return path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('host', choices=['studio', 'minipc'])
    parser.add_argument('--release', required=True)
    parser.add_argument('--network-trace', action='store_true', help='Node native net diagnostics; no HTTP payload logging')
    args = parser.parse_args()
    print(configure(args.host, args.release, args.network_trace))
