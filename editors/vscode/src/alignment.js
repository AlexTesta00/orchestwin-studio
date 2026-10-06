"use strict";

const fs = require("node:fs");
const path = require("node:path");

const ALIGNMENT_FILE = ".orchestwin/align/latest.json";

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function textOf(value) {
  return typeof value === "string" && value.trim() !== "" ? value : null;
}

function countOf(value) {
  if (Array.isArray(value)) {
    return value.length;
  }
  return Number.isInteger(value) && value >= 0 ? value : 0;
}

function readDocument(folder) {
  const file = path.join(folder, ...ALIGNMENT_FILE.split("/"));
  try {
    return JSON.parse(fs.readFileSync(file, "utf8").replace(/^﻿/, ""));
  } catch {
    return null;
  }
}

function readAlignment(folder) {
  if (typeof folder !== "string" || folder.trim() === "") {
    return null;
  }
  const document = readDocument(folder);
  if (!isObject(document)) {
    return null;
  }
  return {
    runId: textOf(document.run_id),
    finishedAt: textOf(document.finished_at),
    fromCommit: textOf(document.from_commit),
    toCommit: textOf(document.to_commit),
    proposals: countOf(document.proposals),
    waiting: countOf(document.waiting),
    applied: countOf(document.applied),
    skipped: countOf(document.skipped),
  };
}

module.exports = { ALIGNMENT_FILE, readAlignment };
