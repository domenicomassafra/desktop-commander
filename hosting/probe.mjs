// Local acceptance probe, using the adopted MCP SDK, never prints credentials.
import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';

const token = process.env.DESKTOP_COMMANDER_PROBE_TOKEN;
assert(token, 'ephemeral probe token required');
const client = new Client({ name: 'owner-477-acceptance', version: '1.0.0' });
const transport = new StreamableHTTPClientTransport(new URL(process.env.PROBE_URL || 'http://127.0.0.1:8497/hub'), {
  requestInit: { headers: { Authorization: 'Bearer ' + token } },
});
const text = result => (result.content || []).filter(x => x.type === 'text').map(x => x.text).join(String.fromCharCode(10));
const call = async (server, tool, args) => {
  const result = await client.callTool({ name: 'call_tool', arguments: { server, tool, arguments: args } });
  assert(!result.isError, text(result));
  return text(result);
};
try {
  await client.connect(transport);
  const servers = await client.callTool({ name: 'list_servers', arguments: {} });
  console.log(text(servers));
  for (const [server, expected, home] of [
    ['studio', 'mac-studio-dodo', '/Users/domenico'],
    ['minipc', 'udodo', '/home/udodo'],
  ]) {
    const output = await call(server, 'start_process', { command: 'hostname', timeout_ms: 3000 });
    assert(output.includes(expected), output);
    console.log(server + ': hostname=' + expected + ' PASS');
    const path = home + '/.local/state/desktop-commander/probe-' + randomUUID() + '.txt';
    const marker = 'desktop-commander-477-' + randomUUID();
    try {
      await call(server, 'write_file', { path, content: marker, mode: 'rewrite' });
      const read = await call(server, 'read_file', { path });
      assert(read.includes(marker), read);
      console.log(server + ': native write_file/read_file PASS');
    } finally {
      await call(server, 'start_process', { command: 'rm -f -- ' + path, timeout_ms: 3000 });
    }
    const elevation = await client.callTool({ name: 'call_tool', arguments: {
      server, tool: 'start_process', arguments: { command: 'sudo -n true', timeout_ms: 3000 },
    } });
    assert(elevation.isError && /not allowed|not permitted|password|denied/i.test(text(elevation)), text(elevation));
    console.log(server + ': sudo denied PASS');
  }
  console.log('local_acceptance=PASS (not a ChatGPT receipt)');
} finally {
  await client.close();
}
