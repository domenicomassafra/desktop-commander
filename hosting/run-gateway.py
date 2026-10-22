#!/usr/bin/env python3
"""Start the adopted hub with its private projected environment."""
import json
import os
from pathlib import Path
import shutil

home = Path.home()
environment = json.loads((home / '.config/desktop-commander/gateway-env.json').read_text())
os.environ.update(environment)
node = shutil.which('node')
if not node:
    raise SystemExit('Node missing from service PATH')
os.execv(node, [node, str(home / '.local/opt/desktop-commander/gateway/node_modules/@ni-c/mcp-hub/dist/index.js')])
