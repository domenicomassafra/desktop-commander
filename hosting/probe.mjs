// Local acceptance probe, using the adopted MCP SDK, never prints credentials.
import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { setTimeout } from 'node:timers/promises';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';

assert(process.env.MCP_HUB_ENTRY, 'installed native hub required');
const client = new Client({ name: 'owner-477-acceptance', version: '1.0.0' });
const transport = new StdioClientTransport({
  command: process.execPath, args: [process.env.MCP_HUB_ENTRY, '--stdio'],
  env: Object.fromEntries(['PATH', 'HOME', 'CONFIG_PATH', 'TOOL_CACHE_PATH',
    'DESKTOP_COMMANDER_API_TOKEN'].map(key => [key, process.env[key]])),
});
const text = result => (result.content || []).filter(x => x.type === 'text').map(x => x.text).join(String.fromCharCode(10));
const call = async (server, tool, args) => {
  const result = await client.callTool({ name: 'call_tool', arguments: { server, tool, arguments: args } });
  assert(!result.isError, text(result));
  return text(result);
};
// Desktop Commander may finish the command after start_process returns a PID.
// Follow the process session rather than treating normal async output as failure.
const waitForCommandOutput = async (server, command, expected) => {
  let output = await call(server, 'start_process', { command, timeout_ms: 3000 });
  const match = output.match(/Process started with PID ([1-9][0-9]*)/);
  const pid = match ? Number(match[1]) : null;
  for (let attempt = 0; pid && !output.includes(expected) && attempt < 8; attempt++) {
    output += '\n' + await call(server, 'read_process_output', { pid, timeout_ms: 2000 });
  }
  assert(output.includes(expected), output);
  return output;
};

try {
  await client.connect(transport);
  // Native stdio initializes before its supervised children finish discovery.
  let ready = false;
  for (let attempt = 0; attempt < 30; attempt++) {
    const result = await client.callTool({ name: 'list_servers', arguments: {} });
    const servers = JSON.parse(text(result)).servers;
    ready = ['studio', 'minipc'].every(name => servers.some(s => s.name === name && s.toolCount > 0));
    if (ready) break;
    await setTimeout(1000);
  }
  assert(ready, 'native hub child discovery timed out after 30 probes');
  for (const [server, expected, home] of [
    ['studio', 'mac-studio-dodo', '/Users/domenico'],
    ['minipc', 'udodo', '/home/udodo'],
  ]) {
    await waitForCommandOutput(server, 'hostname', expected);
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
