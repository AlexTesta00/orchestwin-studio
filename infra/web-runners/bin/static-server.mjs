import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { createServer } from "node:http";
import { extname, resolve, sep } from "node:path";

const argumentsByName = new Map();
for (let index = 2; index < process.argv.length; index += 2) {
  argumentsByName.set(process.argv[index], process.argv[index + 1]);
}

const root = resolve(argumentsByName.get("--root") ?? ".");
const port = Number.parseInt(argumentsByName.get("--port") ?? "4173", 10);
if (!Number.isInteger(port) || port < 1 || port > 65535) {
  throw new Error("Static server port is outside the valid range.");
}

const mediaTypes = new Map([
  [".css", "text/css; charset=utf-8"],
  [".html", "text/html; charset=utf-8"],
  [".js", "text/javascript; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
  [".mjs", "text/javascript; charset=utf-8"],
  [".png", "image/png"],
  [".svg", "image/svg+xml"],
  [".webp", "image/webp"],
]);

createServer(async (request, response) => {
  if (!request.url || !["GET", "HEAD"].includes(request.method ?? "")) {
    response.writeHead(405).end();
    return;
  }
  const requestedPath = decodeURIComponent(new URL(request.url, "http://localhost").pathname);
  const candidate = resolve(root, `.${requestedPath === "/" ? "/index.html" : requestedPath}`);
  if (candidate !== root && !candidate.startsWith(`${root}${sep}`)) {
    response.writeHead(403).end();
    return;
  }
  try {
    const metadata = await stat(candidate);
    if (!metadata.isFile()) {
      response.writeHead(404).end();
      return;
    }
    response.writeHead(200, {
      "content-length": metadata.size,
      "content-type": mediaTypes.get(extname(candidate).toLowerCase()) ?? "application/octet-stream",
    });
    if (request.method === "HEAD") {
      response.end();
    } else {
      createReadStream(candidate).pipe(response);
    }
  } catch {
    response.writeHead(404).end();
  }
}).listen(port, "0.0.0.0");
