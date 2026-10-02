"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { isDeepStrictEqual } = require("node:util");
const { bareProgram } = require("./commands");

const SERVER_NAME = "orchestwin-twins";
const MCP_FOLDER = ".vscode";
const MCP_NAME = "mcp.json";
const MCP_FILE = `${MCP_FOLDER}/${MCP_NAME}`;
const PROJECT_DIR_OPTION = "--project-dir";
const MCP_COMMAND = "mcp";
const STDIO = "stdio";

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function posixPath(value, platform = process.platform) {
  const text = String(value);
  return platform === "win32" ? text.replace(/\\/g, "/") : text;
}

function serverEntry(root, utCommand, platform = process.platform) {
  const folder = posixPath(root, platform);
  return {
    type: STDIO,
    command: bareProgram(utCommand),
    args: [PROJECT_DIR_OPTION, folder, MCP_COMMAND],
    cwd: folder,
  };
}

function mcpSnippet(root, utCommand, platform = process.platform) {
  return { servers: { [SERVER_NAME]: serverEntry(root, utCommand, platform) } };
}

function mcpPath(root) {
  return path.join(root, MCP_FOLDER, MCP_NAME);
}

function readConfiguration(root) {
  let content;
  try {
    content = fs.readFileSync(mcpPath(root), "utf8");
  } catch (error) {
    const missing = error && (error.code === "ENOENT" || error.code === "ENOTDIR");
    return { status: missing ? "MISSING" : "UNREADABLE", document: null };
  }
  let document;
  try {
    document = JSON.parse(content.replace(/^﻿/, ""));
  } catch {
    return { status: "INVALID", document: null };
  }
  if (!isObject(document) || (document.servers !== undefined && !isObject(document.servers))) {
    return { status: "INVALID", document: null };
  }
  return { status: "OK", document };
}

function agentsState(root) {
  if (typeof root !== "string" || root === "") {
    return { file: MCP_FILE, status: "MISSING" };
  }
  const found = readConfiguration(root);
  if (found.status !== "OK") {
    return { file: MCP_FILE, status: found.status };
  }
  const servers = found.document.servers;
  const connected = isObject(servers) && Object.hasOwn(servers, SERVER_NAME);
  return { file: MCP_FILE, status: connected ? "CONNECTED" : "NOT_CONNECTED" };
}

function connectAgents(root, utCommand, platform = process.platform) {
  const found = readConfiguration(root);
  if (found.status === "INVALID" || found.status === "UNREADABLE") {
    return { file: MCP_FILE, status: found.status };
  }
  const entry = serverEntry(root, utCommand, platform);
  let document;
  if (found.status === "MISSING") {
    document = { servers: { [SERVER_NAME]: entry } };
  } else {
    const servers = isObject(found.document.servers) ? found.document.servers : {};
    if (isDeepStrictEqual(servers[SERVER_NAME], entry)) {
      return { file: MCP_FILE, status: "UNCHANGED" };
    }
    document = { ...found.document, servers: { ...servers, [SERVER_NAME]: entry } };
  }
  try {
    fs.mkdirSync(path.join(root, MCP_FOLDER), { recursive: true });
    fs.writeFileSync(mcpPath(root), `${JSON.stringify(document, null, 2)}\n`, "utf8");
  } catch {
    return { file: MCP_FILE, status: "FAILED" };
  }
  return { file: MCP_FILE, status: found.status === "MISSING" ? "CREATED" : "UPDATED" };
}

module.exports = {
  MCP_FILE,
  SERVER_NAME,
  agentsState,
  connectAgents,
  mcpSnippet,
  posixPath,
  serverEntry,
};
