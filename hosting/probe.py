#!/usr/bin/env python3
"""Run the native SDK acceptance probe over stdio, without OAuth or listeners."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

home = Path.home()
base = home / '.local/opt/desktop-commander'
env = os.environ.copy()
env.update(json.loads((home / '.config/desktop-commander/gateway-env.json').read_text()))
env.pop('NODE_DEBUG', None)
env['MCP_HUB_ENTRY'] = str(base / 'gateway/node_modules/@ni-c/mcp-hub/dist/index.js')
node = shutil.which('node', path=env['PATH'])
with tempfile.TemporaryDirectory(prefix='desktop-commander-probe-') as directory:
    env['TOOL_CACHE_PATH'] = str(Path(directory) / 'tool-cache.json')
    subprocess.run([node, str(Path(__file__).with_name('probe.mjs'))], env=env, check=True)
