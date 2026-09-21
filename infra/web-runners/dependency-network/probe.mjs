// A real network observation, run in a separate non-root container attached
// exclusively to the internal bridge. It never grants profile Level D.
import http from "node:http";
import https from "node:https";
import net from "node:net";
import tls from "node:tls";

const host = process.env.PROXY_HOST;
const port = Number(process.env.PROXY_PORT);
if (!/^[a-z0-9][a-z0-9.-]{0,62}$/.test(host ?? "") || port !== 3128) {
  throw new Error("DEPENDENCY_PROBE_CONFIGURATION_INVALID");
}

function connect(authority) {
  return new Promise((resolve, reject) => {
    const request = http.request({
      host, port, method: "CONNECT", path: authority, agent: false,
      headers: { Host: authority }, maxHeaderSize: 8192,
    });
    const timer = setTimeout(() => {
      request.destroy(new Error("DEPENDENCY_PROBE_CONNECT_TIMEOUT"));
    }, 10000);
    request.once("error", (error) => { clearTimeout(timer); reject(error); });
    request.once("connect", (response, socket, head) => {
      clearTimeout(timer);
      if (head.length !== 0) {
        socket.destroy();
        reject(new Error("DEPENDENCY_PROBE_UNEXPECTED_CONNECT_BYTES"));
        return;
      }
      resolve({ status: response.statusCode, socket });
    });
    request.end();
  });
}

async function denied(authority) {
  const result = await connect(authority);
  result.socket.destroy();
  return result.status === 403;
}

async function npmTls() {
  const result = await connect("registry.npmjs.org:443");
  if (result.status !== 200) { result.socket.destroy(); return false; }
  const agent = new https.Agent({ keepAlive: false });
  agent.createConnection = () => tls.connect({
    socket: result.socket, servername: "registry.npmjs.org", rejectUnauthorized: true,
  });
  try {
    return await new Promise((resolve, reject) => {
      const request = https.request({
        hostname: "registry.npmjs.org", path: "/typescript/5.8.3", agent,
        headers: { Accept: "application/json" }, maxHeaderSize: 16384,
      });
      const timer = setTimeout(() => {
        request.destroy(new Error("DEPENDENCY_PROBE_TLS_TIMEOUT"));
      }, 10000);
      request.once("error", (error) => { clearTimeout(timer); reject(error); });
      request.once("response", (response) => {
        const chunks = [];
        let size = 0;
        response.on("data", (chunk) => {
          size += chunk.length;
          if (size > 1024 * 1024) {
            request.destroy(new Error("DEPENDENCY_PROBE_RESPONSE_TOO_LARGE"));
          } else chunks.push(chunk);
        });
        response.once("error", (error) => { clearTimeout(timer); reject(error); });
        response.once("end", () => {
          clearTimeout(timer);
          try {
            const metadata = JSON.parse(Buffer.concat(chunks).toString("utf8"));
            resolve(response.statusCode === 200 && metadata.name === "typescript"
              && metadata.version === "5.8.3" && response.socket?.authorized !== false);
          } catch { reject(new Error("DEPENDENCY_PROBE_METADATA_INVALID")); }
        });
      });
      request.end();
    });
  } finally { agent.destroy(); result.socket.destroy(); }
}

function forwardHttpDenied() {
  return new Promise((resolve, reject) => {
    const request = http.request({
      host, port, path: "http://registry.npmjs.org/typescript/5.8.3", agent: false,
      headers: { Host: "registry.npmjs.org", Connection: "close" }, maxHeaderSize: 8192,
    });
    const timer = setTimeout(() => {
      request.destroy(new Error("DEPENDENCY_PROBE_HTTP_TIMEOUT"));
    }, 10000);
    request.once("error", (error) => { clearTimeout(timer); reject(error); });
    request.once("response", (response) => {
      clearTimeout(timer);
      resolve(response.statusCode === 405);
      response.destroy();
    });
    request.end();
  });
}

function directEgressDenied() {
  return new Promise((resolve) => {
    const socket = net.connect({ host: "1.1.1.1", port: 443 });
    let settled = false;
    const finish = (denied) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      socket.destroy();
      resolve(denied);
    };
    const timer = setTimeout(() => finish(true), 3000);
    socket.once("connect", () => finish(false));
    socket.once("error", () => finish(true));
  });
}

const observations = {};
for (const [name, run] of Object.entries({
  allowed_npm_tls: npmTls,
  unknown_host_denied: () => denied("example.com:443"),
  literal_ip_denied: () => denied("127.0.0.1:443"),
  metadata_ip_denied: () => denied("169.254.169.254:443"),
  invalid_port_denied: () => denied("registry.npmjs.org:80"),
  forward_http_denied: forwardHttpDenied,
  direct_egress_denied: directEgressDenied,
})) {
  try { observations[name] = await run(); }
  catch { observations[name] = false; process.stderr.write(`${name}: PROBE_FAILED\n`); }
}
const passed = Object.values(observations).every((value) => value === true);
process.stdout.write(`${JSON.stringify({ schema_version: 1, passed, checks: observations })}\n`);
process.exitCode = passed ? 0 : 1;
