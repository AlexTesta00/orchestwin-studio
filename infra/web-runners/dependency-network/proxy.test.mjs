import assert from 'node:assert/strict';
import { once } from 'node:events';
import net from 'node:net';
import { test } from 'node:test';

import { ALLOWED_HOSTS, createProxyServer, isPublicIPv4, parseAuthority } from './proxy.mjs';

const AUTHORITY = 'registry.npmjs.org:443';
const CONNECT = `CONNECT ${AUTHORITY} HTTP/1.1\r\nHost: ${AUTHORITY}\r\n\r\n`;

async function client(t, port) {
  const socket = net.connect({ host: '127.0.0.1', port });
  let bytes = Buffer.alloc(0);
  socket.on('data', chunk => { bytes = Buffer.concat([bytes, chunk]); });
  socket.on('error', () => {});
  t.after(() => socket.destroy());
  await once(socket, 'connect');
  return {
    socket,
    bytes: () => bytes,
    async until(predicate) {
      if (predicate(bytes)) return bytes;
      return new Promise((resolve, reject) => {
        const timer = setTimeout(() => finish(new Error('Expected response did not arrive')), 2500);
        function finish(error) {
          clearTimeout(timer);
          socket.off('data', check);
          socket.off('close', closed);
          if (error) reject(error); else resolve(bytes);
        }
        function check() { if (predicate(bytes)) finish(); }
        function closed() { if (predicate(bytes)) finish(); else finish(new Error('Socket closed early')); }
        socket.on('data', check);
        socket.on('close', closed);
      });
    },
  };
}

async function proxy(t, options = {}) {
  const instance = createProxyServer({ resolve4: async () => ['104.16.24.34'], ...options });
  instance.server.listen(0, '127.0.0.1');
  await once(instance.server, 'listening');
  t.after(() => instance.close());
  return { ...instance, port: instance.server.address().port };
}

async function echo(t, onData = undefined) {
  const sockets = new Set();
  const server = net.createServer(socket => {
    sockets.add(socket);
    socket.on('error', () => {});
    socket.on('close', () => sockets.delete(socket));
    if (onData) onData(socket); else socket.pipe(socket);
  });
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  t.after(async () => {
    for (const socket of sockets) socket.destroy();
    await new Promise(resolve => server.close(resolve));
  });
  const calls = [];
  return {
    calls,
    dial(options) {
      calls.push(options);
      return net.connect({ host: '127.0.0.1', port: server.address().port });
    },
  };
}

async function request(t, instance, text, expected) {
  const connection = await client(t, instance.port);
  connection.socket.write(text);
  const bytes = await connection.until(data => data.includes('\r\n\r\n'));
  assert.match(bytes.toString(), new RegExp(`^HTTP/1.1 ${expected} `));
  return connection;
}

test('authority parsing permits only exact dependency hosts and port 443', () => {
  assert.deepEqual(ALLOWED_HOSTS, ['registry.npmjs.org', 'repo.packagist.org', 'api.github.com', 'codeload.github.com']);
  for (const host of ALLOWED_HOSTS) assert.equal(parseAuthority(`${host}:443`), host);
  assert.equal(parseAuthority('REGISTRY.NPMJS.ORG:443'), 'registry.npmjs.org');
  for (const value of [undefined, '', 'registry.npmjs.org', 'registry.npmjs.org:0443',
    'registry.npmjs.org:80', 'registry.npmjs.org.:443', 'registry.npmjs.org.evil.test:443',
    'https://registry.npmjs.org:443', 'user@registry.npmjs.org:443', '127.0.0.1:443',
    '[::1]:443', '2130706433:443', 'registry%2Enpmjs.org:443', 'registry.npmjs.org:443/path',
    'registry.npmjs.org:443\n', ' localhost:443', 'registry.npmjs.org:443#fragment']) {
    assert.equal(parseAuthority(value), null, String(value));
  }
});

test('IPv4 filter denies special-purpose ranges and noncanonical addresses', () => {
  for (const value of ['0.1.2.3', '10.1.2.3', '100.64.0.1', '100.127.255.255',
    '127.0.0.1', '169.254.169.254', '172.16.0.1', '172.31.255.255', '192.0.0.9',
    '192.0.2.1', '192.31.196.1', '192.52.193.1', '192.88.99.1', '192.168.0.1',
    '192.175.48.1', '198.18.0.1', '198.19.255.255', '198.51.100.1', '203.0.113.1',
    '224.0.0.1', '239.255.255.255', '240.0.0.1', '255.255.255.255',
    '127.1', '0177.0.0.1', '1.2.3.256', '::ffff:104.16.24.34', '::1', '', undefined]) {
    assert.equal(isPublicIPv4(value), false, String(value));
  }
  for (const value of ['104.16.24.34', '140.82.112.6', '185.199.108.133',
    '100.63.255.255', '100.128.0.0', '172.15.255.255', '172.32.0.0', '198.20.0.1']) {
    assert.equal(isPublicIPv4(value), true, value);
  }
});

test('denies ordinary HTTP forwarding without invoking DNS or dial', async t => {
  const instance = await proxy(t, { resolve4: () => assert.fail('Unexpected DNS'), dial: () => assert.fail('Unexpected dial') });
  await request(t, instance, 'GET http://registry.npmjs.org/ HTTP/1.1\r\nHost: registry.npmjs.org\r\n\r\n', 405);
});

test('denies unauthorized CONNECT destinations before resolving', async t => {
  const instance = await proxy(t, { resolve4: () => assert.fail('Unexpected DNS') });
  await request(t, instance, 'CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n', 403);
});

test('rejects a Host authority inconsistent with CONNECT', async t => {
  const instance = await proxy(t, { resolve4: () => assert.fail('Unexpected DNS') });
  await request(t, instance, `CONNECT ${AUTHORITY} HTTP/1.1\r\nHost: api.github.com:443\r\n\r\n`, 400);
});

test('accepts the HTTP/1.0 CONNECT without Host emitted by PHP stream transport', async t => {
  const upstream = await echo(t);
  const instance = await proxy(t, { dial: upstream.dial });
  const connection = await request(t, instance, 'CONNECT repo.packagist.org:443 HTTP/1.0\r\n\r\n', 200);
  connection.socket.write('php-tunnel');
  await connection.until(bytes => bytes.includes('php-tunnel'));
  assert.equal(upstream.calls.length, 1);
});

test('HTTP/1.0 compatibility does not relax Host validation or HTTP/1.1 requirements', async t => {
  const instance = await proxy(t, { resolve4: () => assert.fail('Unexpected DNS') });
  await request(t, instance, `CONNECT ${AUTHORITY} HTTP/1.1\r\n\r\n`, 400);
  await request(t, instance, `CONNECT ${AUTHORITY} HTTP/1.0\r\nHost: api.github.com:443\r\n\r\n`, 400);
  await request(t, instance, `CONNECT ${AUTHORITY} HTTP/1.0\r\nHost: ${AUTHORITY}\r\nHost: ${AUTHORITY}\r\n\r\n`, 400);
  await request(t, instance, 'CONNECT forbidden.example:443 HTTP/1.0\r\n\r\n', 403);
});

test('rejects HTTP upgrades and malformed request framing', async t => {
  const instance = await proxy(t, { resolve4: () => assert.fail('Unexpected DNS') });
  await request(t, instance, 'GET / HTTP/1.1\r\nHost: registry.npmjs.org\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n\r\n', 405);
  await request(t, instance, `${CONNECT.slice(0, -2)}Content-Length: 1\r\n\r\nx`, 400);
});

test('fails closed on empty, private, mixed or invalid DNS answers', async t => {
  for (const answers of [[], ['127.0.0.1'], ['104.16.24.34', '10.0.0.1'], ['::1'], ['104.16.24.34', 'garbage']]) {
    const instance = await proxy(t, { resolve4: async () => answers, dial: () => assert.fail('Unexpected dial') });
    await request(t, instance, CONNECT, 502);
  }
});

test('pins the verified IPv4 address and preserves buffered CONNECT bytes exactly once', async t => {
  const upstream = await echo(t);
  let resolutions = 0;
  const instance = await proxy(t, {
    resolve4: async host => { resolutions += 1; assert.equal(host, 'registry.npmjs.org'); return ['104.16.24.34']; },
    dial: upstream.dial,
  });
  const connection = await request(t, instance, `${CONNECT}first-payload`, 200);
  await connection.until(bytes => bytes.includes('first-payload'));
  connection.socket.write('second-payload');
  const observed = await connection.until(bytes => bytes.includes('second-payload'));
  assert.equal(observed.toString().split('\r\n\r\n')[1], 'first-payloadsecond-payload');
  assert.equal(resolutions, 1);
  assert.deepEqual(upstream.calls, [{ host: '104.16.24.34', port: 443, family: 4 }]);
});

test('DNS failure becomes bounded 502 without exposing provider error text', async t => {
  const logs = [];
  const instance = await proxy(t, { resolve4: async () => { throw new Error('secret-token'); }, log: event => logs.push(event) });
  const connection = await request(t, instance, CONNECT, 502);
  assert.doesNotMatch(connection.bytes().toString() + JSON.stringify(logs), /secret-token/);
});

test('logs contain only policy codes and allowlisted authority, never proxy credentials', async t => {
  const logs = [];
  const instance = await proxy(t, { resolve4: async () => [], log: event => logs.push(event) });
  await request(t, instance, `${CONNECT.slice(0, -2)}Proxy-Authorization: Basic secret-credential\r\n\r\n`, 502);
  assert.deepEqual(logs, [{ code: 'HTTP_502', host: 'registry.npmjs.org', port: 443 }]);
});

test('DNS timeout cancels resolution and cannot dial after a late result', async t => {
  let complete;
  let signal;
  const instance = await proxy(t, {
    limits: { connectTimeoutMs: 40 },
    resolve4: (_host, abortSignal) => { signal = abortSignal; return new Promise(resolve => { complete = resolve; }); },
    dial: () => assert.fail('Late DNS must not dial'),
  });
  await request(t, instance, CONNECT, 504);
  assert.equal(signal.aborted, true);
  complete(['104.16.24.34']);
  await new Promise(resolve => setImmediate(resolve));
});

test('upstream refusal returns 502 and cleans up the pending connection', async t => {
  let outbound;
  const instance = await proxy(t, { dial: () => {
    outbound = new net.Socket();
    queueMicrotask(() => outbound.destroy(new Error('ECONNREFUSED')));
    return outbound;
  } });
  await request(t, instance, CONNECT, 502);
  assert.equal(outbound.destroyed, true);
});

test('upstream connect timeout closes its socket', async t => {
  let outbound;
  const instance = await proxy(t, { limits: { connectTimeoutMs: 40 }, dial: () => { outbound = new net.Socket(); return outbound; } });
  await request(t, instance, CONNECT, 504);
  assert.equal(outbound.destroyed, true);
});

test('upstream error after CONNECT closes the tunnel instead of writing HTTP into TLS bytes', async t => {
  let remote;
  const upstream = await echo(t, socket => { remote = socket; });
  const instance = await proxy(t, { dial: upstream.dial });
  const connection = await request(t, instance, CONNECT, 200);
  const closed = once(connection.socket, 'close');
  remote.resetAndDestroy();
  await closed;
  assert.equal(connection.bytes().toString(), 'HTTP/1.1 200 Connection Established\r\n\r\n');
});

test('bounds header bytes and header count before DNS', async t => {
  const instance = await proxy(t, { limits: { maxHeaderBytes: 512, maxHeaders: 4 }, resolve4: () => assert.fail('Unexpected DNS') });
  await request(t, instance, `CONNECT ${AUTHORITY} HTTP/1.1\r\nHost: ${AUTHORITY}\r\nX-Long: ${'a'.repeat(600)}\r\n\r\n`, 431);
  const headers = Array.from({ length: 5 }, (_, index) => `X-${index}: value\r\n`).join('');
  await request(t, instance, `CONNECT ${AUTHORITY} HTTP/1.1\r\nHost: ${AUTHORITY}\r\n${headers}\r\n`, 431);
});

test('absolute header deadline closes a client that never completes its request', async t => {
  const instance = await proxy(t, { limits: { headerTimeoutMs: 40 } });
  const connection = await client(t, instance.port);
  connection.socket.write('CONNECT registry');
  const bytes = await connection.until(data => data.includes('\r\n\r\n'));
  assert.match(bytes.toString(), /^HTTP\/1.1 408 /);
});

test('active connection budget includes clients waiting to send headers', async t => {
  const instance = await proxy(t, { limits: { maxConnections: 1 } });
  const first = await client(t, instance.port);
  await request(t, instance, CONNECT, 503);
  const closed = once(first.socket, 'close');
  first.socket.destroy();
  await closed;
  await instance.close();
  assert.deepEqual(instance.snapshot(), { activeConnections: 0, activeTunnels: 0, closing: true });
});

test('tunnel byte budget includes both directions and terminates before over-limit bytes are forwarded', async t => {
  const upstream = await echo(t);
  const instance = await proxy(t, { dial: upstream.dial, limits: { maxTunnelBytes: 12 } });
  const connection = await request(t, instance, CONNECT, 200);
  connection.socket.write('12345');
  await connection.until(bytes => bytes.includes('12345'));
  const closed = once(connection.socket, 'close');
  connection.socket.write('678');
  await closed;
  assert.equal(connection.bytes().toString().split('\r\n\r\n')[1], '12345');
});

test('excessive initial tunnel data is refused before dial', async t => {
  const instance = await proxy(t, { limits: { maxTunnelBytes: 4 }, dial: () => assert.fail('Unexpected dial') });
  await request(t, instance, `${CONNECT}12345`, 413);
});

test('idle and absolute tunnel deadlines clean up outbound sockets', async t => {
  for (const limits of [{ idleTimeoutMs: 40 }, { tunnelTimeoutMs: 40, idleTimeoutMs: 2000 }]) {
    const upstream = await echo(t);
    const instance = await proxy(t, { dial: upstream.dial, limits });
    const connection = await request(t, instance, CONNECT, 200);
    await once(connection.socket, 'close');
    await instance.close();
    assert.equal(instance.snapshot().activeTunnels, 0);
  }
});

test('connection close during DNS cancels pending work and never dials afterward', async t => {
  let resolveDns;
  let signal;
  const resolving = new Promise(resolve => { resolveDns = resolve; });
  const instance = await proxy(t, {
    resolve4: (_host, abortSignal) => { signal = abortSignal; return resolving; },
    dial: () => assert.fail('Unexpected dial after disconnect'),
  });
  let accepted;
  instance.server.once('connection', socket => { accepted = socket; });
  const connection = await client(t, instance.port);
  connection.socket.write(CONNECT);
  while (!signal) await new Promise(resolve => setImmediate(resolve));
  const closed = once(accepted, 'close');
  accepted.destroy();
  await closed;
  assert.equal(signal.aborted, true);
  resolveDns(['104.16.24.34']);
  await new Promise(resolve => setImmediate(resolve));
});

test('shutdown terminates established tunnels and pending headers, and is idempotent', async t => {
  const upstream = await echo(t);
  const instance = await proxy(t, { dial: upstream.dial });
  await request(t, instance, CONNECT, 200);
  await client(t, instance.port);
  await instance.close();
  await instance.close();
  assert.deepEqual(instance.snapshot(), { activeConnections: 0, activeTunnels: 0, closing: true });
});

test('large transfers use stream backpressure without losing or duplicating bytes', async t => {
  const payload = Buffer.alloc(512 * 1024, 0x5a);
  const upstream = await echo(t, socket => socket.end(payload));
  const instance = await proxy(t, { dial: upstream.dial });
  const connection = await request(t, instance, CONNECT, 200);
  connection.socket.pause();
  const closed = once(connection.socket, 'close');
  connection.socket.resume();
  await closed;
  const observed = connection.bytes();
  const index = observed.indexOf('\r\n\r\n') + 4;
  assert.deepEqual(observed.subarray(index), payload);
});

test('invalid runtime limits fail at construction', () => {
  for (const limits of [{ maxConnections: 0 }, { maxTunnelBytes: -1 }, { connectTimeoutMs: NaN }, { typo: 2 }]) {
    assert.throws(() => createProxyServer({ limits }), /limit/i);
  }
});
