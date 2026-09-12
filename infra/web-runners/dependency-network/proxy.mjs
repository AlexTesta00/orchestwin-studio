/**
 * Dependency SETUP egress: exact CONNECT authorities on port 443 only.
 * TLS remains end to end: this is a destination allowlist, not an HTTP path,
 * method, package-integrity or TLS-SNI filter. Run only on the isolated SETUP
 * network; npm scripts and Composer scripts/plugins remain disabled by runner
 * policy. Never publish this listener on the host or use it for application RUN.
 *
 * Node APIs: https://nodejs.org/api/http.html#event-connect_1
 * Backpressure: https://nodejs.org/api/stream.html#readablepipedestination-options
 * Conservative exclusions: https://www.iana.org/assignments/iana-ipv4-special-registry
 */
import { Resolver } from 'node:dns/promises';
import http from 'node:http';
import net from 'node:net';
import { resolve } from 'node:path';
import { Transform } from 'node:stream';
import { pathToFileURL } from 'node:url';

export const ALLOWED_HOSTS = Object.freeze([
  'registry.npmjs.org', 'repo.packagist.org', 'api.github.com', 'codeload.github.com',
]);
const DEFAULT_LIMITS = Object.freeze({
  maxConnections: 32,
  maxHeaderBytes: 8192,
  maxHeaders: 32,
  maxTunnelBytes: 128 * 1024 * 1024,
  headerTimeoutMs: 10_000,
  connectTimeoutMs: 15_000,
  idleTimeoutMs: 60_000,
  tunnelTimeoutMs: 300_000,
  responseTimeoutMs: 1000,
});

// Deliberately deny entire special-purpose ranges, including globally reachable
// exceptions inside them. Dependency hosts do not require these exceptions.
const SPECIAL_RANGES = [
  ['0.0.0.0', 8], ['10.0.0.0', 8], ['100.64.0.0', 10], ['127.0.0.0', 8],
  ['169.254.0.0', 16], ['172.16.0.0', 12], ['192.0.0.0', 24],
  ['192.0.2.0', 24], ['192.31.196.0', 24], ['192.52.193.0', 24],
  ['192.88.99.0', 24], ['192.168.0.0', 16], ['192.175.48.0', 24],
  ['198.18.0.0', 15], ['198.51.100.0', 24], ['203.0.113.0', 24],
  ['224.0.0.0', 4], ['240.0.0.0', 4],
].map(([address, bits]) => [ipv4Number(address), (0xffffffff << (32 - bits)) >>> 0]);

function ipv4Number(address) {
  return address.split('.').reduce((value, part) => ((value << 8) | Number(part)) >>> 0, 0);
}

export function isPublicIPv4(address) {
  if (typeof address !== 'string' || net.isIP(address) !== 4) return false;
  const numeric = ipv4Number(address);
  return !SPECIAL_RANGES.some(([network, mask]) => ((numeric & mask) >>> 0) === network);
}

export function parseAuthority(authority) {
  if (typeof authority !== 'string' || authority.length > 128) return null;
  const match = /^([a-zA-Z0-9.-]+):443$/.exec(authority);
  if (!match || match[0] !== authority) return null;
  const host = match[1].toLowerCase();
  return ALLOWED_HOSTS.includes(host) ? host : null;
}

async function resolveIPv4(host, signal) {
  const resolver = new Resolver({ timeout: 5000, tries: 1 });
  const cancel = () => resolver.cancel();
  signal.throwIfAborted();
  signal.addEventListener('abort', cancel, { once: true });
  try {
    return await resolver.resolve4(host);
  } finally {
    signal.removeEventListener('abort', cancel);
  }
}

function validatedLimits(overrides) {
  for (const [key, value] of Object.entries(overrides)) {
    if (!(key in DEFAULT_LIMITS) || !Number.isSafeInteger(value) || value < 1 || value > 0x7fffffff) {
      throw new TypeError(`Invalid proxy limit: ${key}`);
    }
  }
  return { ...DEFAULT_LIMITS, ...overrides };
}

/** Injection is for local tests; the executable uses the fixed policy above. */
export function createProxyServer({
  resolve4 = resolveIPv4,
  dial = options => net.connect(options),
  limits: overrides = {},
  log = () => {},
} = {}) {
  const limits = validatedLimits(overrides);
  const connections = new Map();
  let closing = false;
  let closingPromise;
  const server = http.createServer({
    maxHeaderSize: limits.maxHeaderBytes,
    headersTimeout: limits.headerTimeoutMs,
    requestTimeout: limits.headerTimeoutMs,
    keepAliveTimeout: 1,
  });
  // One extra socket receives a bounded 503. Further sockets are rejected by net.
  server.maxConnections = limits.maxConnections + 1;
  server.maxHeadersCount = limits.maxHeaders + 1;
  server.maxRequestsPerSocket = 1;

  function emit(code, host = undefined) {
    // Never log request targets, headers, addresses, credentials or exception text.
    try { log(host ? { code, host, port: 443 } : { code }); } catch { /* Logging cannot affect enforcement. */ }
  }

  function clearWork(record) {
    clearTimeout(record.headerTimer);
    clearTimeout(record.connectTimer);
    clearTimeout(record.lifeTimer);
    record.abort?.abort();
  }

  function terminate(record, code) {
    if (record.done) return;
    record.done = true;
    clearWork(record);
    record.upstream?.destroy();
    record.outbound?.destroy();
    record.inbound?.destroy();
    record.socket.destroy();
    emit(code, record.host);
  }

  function reply(record, status) {
    if (!record || record.done) return;
    record.done = true;
    clearWork(record);
    record.upstream?.destroy();
    const response = `HTTP/1.1 ${status} ${http.STATUS_CODES[status]}\r\nConnection: close\r\nContent-Length: 0\r\n\r\n`;
    record.responseTimer = setTimeout(() => record.socket.destroy(), limits.responseTimeoutMs);
    record.responseTimer.unref();
    record.socket.end(response, () => record.socket.destroy());
    emit(`HTTP_${status}`, record.host);
  }

  server.on('connection', socket => {
    const record = { socket, done: false, tunnel: false };
    connections.set(socket, record);
    socket.on('error', () => terminate(record, 'CLIENT_ERROR'));
    socket.on('close', () => {
      record.done = true;
      clearWork(record);
      clearTimeout(record.responseTimer);
      record.upstream?.destroy();
      record.outbound?.destroy();
      record.inbound?.destroy();
      connections.delete(socket);
    });
    if (closing || connections.size > limits.maxConnections) {
      reply(record, 503);
      return;
    }
    record.headerTimer = setTimeout(() => reply(record, 408), limits.headerTimeoutMs);
    record.headerTimer.unref();
  });

  server.on('request', request => reply(connections.get(request.socket), 405));
  server.on('checkContinue', request => reply(connections.get(request.socket), 405));
  server.on('checkExpectation', request => reply(connections.get(request.socket), 405));
  server.on('upgrade', (_request, socket) => reply(connections.get(socket), 405));
  server.on('clientError', (error, socket) => {
    reply(connections.get(socket), error.code === 'HPE_HEADER_OVERFLOW' ? 431 : 400);
  });

  server.on('connect', (request, socket, head) => {
    const record = connections.get(socket);
    if (!record || record.done) return;
    clearTimeout(record.headerTimer);
    socket.pause();
    if (request.rawHeaders.length / 2 > limits.maxHeaders) return reply(record, 431);
    const host = parseAuthority(request.url);
    if (!host) return reply(record, 403);
    record.host = host;
    const hostHeaders = request.rawHeaders.filter((_value, index, headers) => index % 2 === 1 && headers[index - 1].toLowerCase() === 'host');
    // PHP's stream transport uses HTTP/1.0 CONNECT with no Host header. The
    // allowlisted CONNECT authority remains the sole destination in that case.
    const validHost = hostHeaders.length === 0
      ? request.httpVersion === '1.0'
      : hostHeaders.length === 1 && parseAuthority(hostHeaders[0]) === host;
    if (!validHost ||
        request.headers['transfer-encoding'] !== undefined ||
        (request.headers['content-length'] !== undefined && request.headers['content-length'] !== '0')) {
      return reply(record, 400);
    }
    if (head.length > limits.maxTunnelBytes) return reply(record, 413);
    record.abort = new AbortController();
    record.connectTimer = setTimeout(() => reply(record, 504), limits.connectTimeoutMs);
    record.connectTimer.unref();

    void (async () => {
      try {
        const addresses = await resolve4(host, record.abort.signal);
        if (record.done || socket.destroyed) return;
        if (!Array.isArray(addresses) || addresses.length === 0 || addresses.length > 64 ||
            !addresses.every(isPublicIPv4)) return reply(record, 502);
        // Dial the already checked literal, never the hostname: no second lookup.
        const upstream = dial({ host: addresses[0], port: 443, family: 4 });
        record.upstream = upstream;
        upstream.on('error', () => {
          if (record.tunnel) terminate(record, 'UPSTREAM_ERROR'); else reply(record, 502);
        });
        let upstreamEnded = false;
        upstream.on('end', () => { upstreamEnded = true; });
        upstream.on('close', () => {
          if (record.done) return;
          // A normal FIN is propagated by pipe/end, allowing buffered bytes to
          // drain. Only an abrupt close destroys the client immediately.
          if (!upstreamEnded) {
            if (record.tunnel) terminate(record, 'UPSTREAM_CLOSED'); else reply(record, 502);
          }
        });
        upstream.once('connect', () => {
          if (record.done || socket.destroyed) { upstream.destroy(); return; }
          clearTimeout(record.connectTimer);
          record.tunnel = true;
          let transferred = 0;
          const meter = () => new Transform({
            highWaterMark: 16 * 1024,
            transform(chunk, _encoding, callback) {
              if (transferred + chunk.length > limits.maxTunnelBytes) {
                callback(new Error('TUNNEL_BYTE_LIMIT'));
              } else {
                transferred += chunk.length;
                callback(null, chunk);
              }
            },
          });
          record.outbound = meter();
          record.inbound = meter();
          record.outbound.on('error', () => terminate(record, 'TUNNEL_BYTE_LIMIT'));
          record.inbound.on('error', () => terminate(record, 'TUNNEL_BYTE_LIMIT'));
          socket.setTimeout(limits.idleTimeoutMs, () => terminate(record, 'IDLE_TIMEOUT'));
          upstream.setTimeout(limits.idleTimeoutMs, () => terminate(record, 'IDLE_TIMEOUT'));
          record.lifeTimer = setTimeout(() => terminate(record, 'TUNNEL_TIMEOUT'), limits.tunnelTimeoutMs);
          record.lifeTimer.unref();
          socket.write('HTTP/1.1 200 Connection Established\r\n\r\n');
          upstream.pipe(record.inbound).pipe(socket);
          record.outbound.pipe(upstream);
          // CONNECT head belongs to the tunnel. Its write and later client data
          // share the same metering transform and normal pipe backpressure.
          const pipeClient = () => { if (!record.done) socket.pipe(record.outbound); };
          if (head.length && !record.outbound.write(head)) record.outbound.once('drain', pipeClient);
          else pipeClient();
          emit('TUNNEL_OPEN', host);
        });
      } catch {
        if (!record.done) reply(record, 502);
      }
    })();
  });

  return {
    server,
    snapshot() {
      return {
        activeConnections: connections.size,
        activeTunnels: [...connections.values()].filter(record => record.tunnel && !record.done).length,
        closing,
      };
    },
    close() {
      if (closingPromise) return closingPromise;
      closing = true;
      closingPromise = new Promise((resolveClose, rejectClose) => {
        server.close(error => {
          if (error && error.code !== 'ERR_SERVER_NOT_RUNNING') rejectClose(error); else resolveClose();
        });
        for (const record of connections.values()) {
          record.done = true;
          clearWork(record);
          clearTimeout(record.responseTimer);
          record.upstream?.destroy();
          record.outbound?.destroy();
          record.inbound?.destroy();
          record.socket.destroy();
        }
        connections.clear();
      });
      return closingPromise;
    },
  };
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  if (process.argv.length !== 2) {
    process.stderr.write('Dependency proxy accepts no arguments.\n');
    process.exitCode = 2;
  } else {
    // Drop events while stdout is congested instead of building an unbounded
    // logging queue. Events contain only a fixed code and an allowlisted host.
    let writableLog = true;
    process.stdout.on('drain', () => { writableLog = true; });
    const proxy = createProxyServer({ log: event => {
      if (writableLog) writableLog = process.stdout.write(`${JSON.stringify(event)}\n`);
    } });
    proxy.server.on('error', () => {
      process.stderr.write('Dependency proxy listener failed.\n');
      process.exitCode = 1;
      void proxy.close();
    });
    for (const signal of ['SIGTERM', 'SIGINT']) {
      process.once(signal, () => { void proxy.close().catch(() => { process.exitCode = 1; }); });
    }
    proxy.server.listen(3128, '0.0.0.0', () => process.stdout.write('{"code":"LISTENING","port":3128}\n'));
  }
}
