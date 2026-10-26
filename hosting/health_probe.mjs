// Inspect the active private Studio MCP transport using the adopted SDK.
// The API token stays in its 0600 owner file and is never logged.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const release = process.argv[2];
assert(release, 'selected immutable release required');
const host = process.argv[3] || 'studio';
const sdk = join(release, 'node_modules/@modelcontextprotocol/sdk/dist/esm/client');
const { Client } = await import(pathToFileURL(join(sdk, 'index.js')));
const client = new Client({ name: 'native-retention-health', version: '1.0.0' });
let transport;
if (host === 'studio') {
  const { StreamableHTTPClientTransport } = await import(pathToFileURL(join(sdk, 'streamableHttp.js')));
  const key = (await readFile(join(homedir(), '.config/desktop-commander/studio-api-key'), 'utf8')).trim();
  assert(key, 'missing private Studio API key');
  transport = new StreamableHTTPClientTransport(new URL('http://100.99.195.87:9197/mcp'), {
    requestInit: { headers: { Authorization: `Bearer ${key}` } },
  });
} else if (host === 'minipc') {
  const { StdioClientTransport } = await import(pathToFileURL(join(sdk, 'stdio.js')));
  transport = new StdioClientTransport({
    command: process.execPath,
    args: [join(release, 'dist/index.js'), '--no-onboarding'],
    env: {
      HOME: homedir(), PATH: process.env.PATH,
      DESKTOP_COMMANDER_DISABLE_TELEMETRY: '1',
      DC_FLAG_URL: 'data:application/json,{"flags":{}}',
    },
  });
} else {
  throw new Error('unsupported native host');
}
try {
  await client.connect(transport);
  const tools = await client.listTools();
  assert(tools.tools.some(tool => tool.name === 'start_process'), 'running MCP tools unavailable');
  console.log('mcp-health=ready');
} finally {
  await client.close();
}
