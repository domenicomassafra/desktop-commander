#!/usr/bin/env python3
"""Project the reviewed Desktop Commander release; never touch the old connector."""
import argparse
import json
import os
from pathlib import Path
import plistlib
import shutil
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


def configure(host, release, public_url):
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
    if host == 'studio':
        gateway = BASE / 'supergateway'
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
    # The catalog projector is the only code allowed to read secret values.
    env = {
        'EXTERNAL_URL': public_url.rstrip('/'), 'CONFIG_PATH': str(CONFIG / 'mcp.json'),
        'DATA_PATH': str(STATE / 'oauth'), 'PORT': '8497',
        'TRUSTED_PROXIES': 'loopback', 'DEFAULT_RESOURCE': 'hub',
        'CIMD_ALLOWED_ORIGINS': 'https://chatgpt.com',
        'PATH': common['PATH'],
        'PASSWORD': os.environ['DESKTOP_COMMANDER_OAUTH_PASSWORD'],
        'DESKTOP_COMMANDER_API_TOKEN': os.environ['DESKTOP_COMMANDER_API_TOKEN'],
    }
    # PASSWORD_HASH avoids plaintext password exposure in the long-running hub.
    bcrypt = BASE / 'gateway/node_modules/bcryptjs/index.js'
    hashed = subprocess.run([node, '--input-type=module', '-e',
        "import bcrypt from " + json.dumps(str(bcrypt)) + "; let s=''; for await (const c of process.stdin) s+=c; process.stdout.write(bcrypt.hashSync(s, 12));"],
        input=env.pop('PASSWORD'), text=True, check=True, capture_output=True).stdout
    env['PASSWORD_HASH'] = hashed
    # JSON is read by the launcher, never sourced as shell or logged.
    put(CONFIG / 'gateway-env.json', json.dumps(env))
    launcher = Path(__file__).with_name('run-gateway.py').resolve(strict=True)
    unit = chr(10).join([
        '[Unit]', 'Description=Desktop Commander owner MCP gateway',
        'After=network-online.target', '', '[Service]',
        f'ExecStart=/usr/bin/python3 {launcher}', 'Restart=on-failure',
        'RestartSec=10', 'NoNewPrivileges=yes', 'UMask=0077',
        'MemoryMax=1G', 'TasksMax=128', '', '[Install]',
        'WantedBy=default.target', '',
    ])
    path = HOME / '.config/systemd/user/desktop-commander.service'
    put(path, unit, 0o644)
    return path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('host', choices=['studio', 'minipc'])
    parser.add_argument('--release', required=True)
    parser.add_argument('--public-url', default='https://computer-mcp.dichiarazionipubbliche.it')
    args = parser.parse_args()
    print(configure(args.host, args.release, args.public_url))
