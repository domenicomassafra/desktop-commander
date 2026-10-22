#!/usr/bin/env python3
"""Mint, use and revoke an ephemeral native hub token without printing it."""
import json
import os
from pathlib import Path
import shutil
import subprocess

home = Path.home()
base = home / '.local/opt/desktop-commander'
env = os.environ.copy()
env.update(json.loads((home / '.config/desktop-commander/gateway-env.json').read_text()))
node = shutil.which('node', path=env['PATH'])
admin = [node, str(base / 'gateway/node_modules/@ni-c/mcp-hub/dist/admin.js')]
created = subprocess.run(admin + ['tokens', 'create', '--resource', 'hub', '--days', '1', '--label', 'probe-477'],
                         env=env, text=True, capture_output=True, check=True)
metadata = json.loads(created.stderr[created.stderr.index('{'):])
token_id = metadata['id']
try:
    env['DESKTOP_COMMANDER_PROBE_TOKEN'] = created.stdout.strip()
    subprocess.run([node, str(Path(__file__).with_name('probe.mjs'))], env=env, check=True)
finally:
    subprocess.run(admin + ['tokens', 'revoke', token_id], env=env, capture_output=True, check=True)
