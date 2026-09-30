"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { after, before, describe, it } = require("node:test");
const fixtures = require("./fixtures");
const {
  MCP_FILE,
  SERVER_NAME,
  agentsState,
  connectAgents,
  mcpSnippet,
  posixPath,
  serverEntry,
} = require("../src/agents");

function mcpFile(root) {
  return path.join(root, ".vscode", "mcp.json");
}

function readMcp(root) {
  return fs.readFileSync(mcpFile(root), "utf8");
}

describe("the MCP configuration of the editor", () => {
  let base;
  let counter = 0;

  before(() => {
    base = fixtures.makeTemporaryFolder();
  });

  after(() => {
    fixtures.removeFolder(base);
  });

  function project() {
    counter += 1;
    const root = path.join(base, `project ${counter}`);
    fs.mkdirSync(root, { recursive: true });
    return root;
  }

  it("writes the snippet that ut mcp --config vscode prints", () => {
    const root = project();
    const folder = posixPath(root);
    const snippet = mcpSnippet(root, "ut");
    assert.equal(
      JSON.stringify(snippet),
      JSON.stringify({
        servers: {
          "orchestwin-twins": {
            type: "stdio",
            command: "ut",
            args: ["--project-dir", folder, "mcp"],
            cwd: folder,
          },
        },
      }),
    );
    assert.equal(SERVER_NAME, "orchestwin-twins");
    assert.equal(MCP_FILE, ".vscode/mcp.json");
  });

  it("uses / separators on every platform", () => {
    const windows = ["projects", "tip calculator"].join("\\");
    assert.equal(posixPath(windows, "win32"), "projects/tip calculator");
    assert.equal(posixPath("projects/tip", "linux"), "projects/tip");
    assert.equal(posixPath(windows, "darwin"), windows);
    const entry = serverEntry(windows, "ut", "win32");
    assert.deepEqual(entry.args, ["--project-dir", "projects/tip calculator", "mcp"]);
    assert.equal(entry.cwd, "projects/tip calculator");
    const root = project();
    const written = serverEntry(root, "ut");
    assert.ok(!written.cwd.includes("\\"));
    assert.ok(!written.args[1].includes("\\"));
  });

  it("creates .vscode/mcp.json when it is missing", () => {
    const root = project();
    assert.deepEqual(agentsState(root), { file: MCP_FILE, status: "MISSING" });
    assert.deepEqual(connectAgents(root, "ut"), { file: MCP_FILE, status: "CREATED" });
    assert.equal(readMcp(root), `${JSON.stringify(mcpSnippet(root, "ut"), null, 2)}\n`);
    assert.deepEqual(agentsState(root), { file: MCP_FILE, status: "CONNECTED" });
  });

  it("keeps the other servers and the other keys of an existing file", () => {
    const root = project();
    const other = { type: "stdio", command: "other-server", args: [] };
    const inputs = [{ type: "promptString", id: "folder", description: "An example input" }];
    fixtures.writeJson(root, ".vscode/mcp.json", { inputs, servers: { other } });
    assert.deepEqual(agentsState(root), { file: MCP_FILE, status: "NOT_CONNECTED" });
    assert.deepEqual(connectAgents(root, "ut"), { file: MCP_FILE, status: "UPDATED" });
    const written = JSON.parse(readMcp(root));
    assert.deepEqual(Object.keys(written), ["inputs", "servers"]);
    assert.deepEqual(written.inputs, inputs);
    assert.deepEqual(Object.keys(written.servers), ["other", SERVER_NAME]);
    assert.deepEqual(written.servers.other, other);
    assert.deepEqual(written.servers[SERVER_NAME], serverEntry(root, "ut"));
  });

  it("adds the servers to a file that has none and replaces an older entry", () => {
    const root = project();
    fixtures.writeJson(root, ".vscode/mcp.json", { inputs: [] });
    assert.equal(connectAgents(root, "ut").status, "UPDATED");
    const program = path.join(os.tmpdir(), "tools dir", "ut");
    assert.equal(connectAgents(root, `"${program}"`).status, "UPDATED");
    const written = JSON.parse(readMcp(root));
    assert.deepEqual(written, {
      inputs: [],
      servers: { [SERVER_NAME]: serverEntry(root, program) },
    });
    assert.equal(written.servers[SERVER_NAME].command, program);
  });

  it("leaves the file alone when the server is already there", () => {
    const root = project();
    connectAgents(root, "ut");
    const before = readMcp(root);
    fs.writeFileSync(mcpFile(root), before.replace(/\n/g, "\r\n"), "utf8");
    assert.deepEqual(connectAgents(root, "ut"), { file: MCP_FILE, status: "UNCHANGED" });
    assert.equal(readMcp(root), before.replace(/\n/g, "\r\n"));
  });

  it("never overwrites a file that is not valid JSON", () => {
    for (const content of [
      "{ not json",
      '{\n  "servers": {},\n}\n',
      '{ "servers": [] }',
      "[1, 2]",
    ]) {
      const root = project();
      fixtures.writeText(root, ".vscode/mcp.json", content);
      assert.deepEqual(agentsState(root), { file: MCP_FILE, status: "INVALID" });
      assert.deepEqual(connectAgents(root, "ut"), { file: MCP_FILE, status: "INVALID" });
      assert.equal(readMcp(root), content);
    }
  });

  it("reads a file that starts with a byte order mark", () => {
    const root = project();
    fixtures.writeText(root, ".vscode/mcp.json", `﻿${JSON.stringify({ servers: {} })}`);
    assert.equal(connectAgents(root, "ut").status, "UPDATED");
    assert.ok(!readMcp(root).startsWith("﻿"));
  });

  it("says so when the file cannot be written", () => {
    const root = project();
    fixtures.writeText(root, ".vscode", "a file where the folder should be\n");
    assert.deepEqual(connectAgents(root, "ut"), { file: MCP_FILE, status: "FAILED" });
    assert.equal(
      fs.readFileSync(path.join(root, ".vscode"), "utf8"),
      "a file where the folder should be\n",
    );
  });

  it("says that nothing is connected without a folder", () => {
    assert.deepEqual(agentsState(null), { file: MCP_FILE, status: "MISSING" });
    assert.deepEqual(agentsState(""), { file: MCP_FILE, status: "MISSING" });
  });
});
