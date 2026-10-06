"use strict";

const PROGRAM = "ut";

const ARGUMENTS = Object.freeze({
  status: Object.freeze(["status"]),
  init: Object.freeze(["init"]),
  design: Object.freeze(["design"]),
  publish: Object.freeze(["package", "publish"]),
  test: Object.freeze(["test"]),
  verify: Object.freeze(["verify"]),
  recheck: Object.freeze(["verify", "--recheck"]),
  align: Object.freeze(["align"]),
  alignPending: Object.freeze(["align", "--pending"]),
  push: Object.freeze(["push"]),
  code: Object.freeze(["code"]),
  tasks: Object.freeze(["tasks"]),
  tasksFromTest: Object.freeze(["tasks", "from-test"]),
  twinsUpdate: Object.freeze(["twins", "update"]),
});

const COSTS = Object.freeze({
  status: "FREE",
  init: "SPENDS",
  design: "SPENDS",
  publish: "FREE",
  test: "SPENDS",
  verify: "SPENDS",
  recheck: "SPENDS",
  align: "SPENDS",
  alignPending: "SPENDS",
  push: "FREE",
  code: "AGENT",
  tasks: "FREE",
  tasksFromTest: "FREE",
  twinsUpdate: "SPENDS",
});

const POWERSHELL = /^(pwsh|powershell)(\.exe)?$/i;

function cleanProgram(utCommand) {
  if (typeof utCommand !== "string" || utCommand.trim() === "") {
    return PROGRAM;
  }
  return utCommand.trim();
}

function isQuoted(program) {
  return program.length > 1 && program.startsWith('"') && program.endsWith('"');
}

function bareProgram(utCommand) {
  const program = cleanProgram(utCommand);
  return isQuoted(program) ? program.slice(1, -1).trim() || PROGRAM : program;
}

function isPowerShell(shell) {
  if (typeof shell !== "string" || shell.trim() === "") {
    return false;
  }
  const name = shell.trim().split(/[\\/]/).pop();
  return POWERSHELL.test(name);
}

function programWord(utCommand, shell) {
  const program = cleanProgram(utCommand);
  const quoted = isQuoted(program);
  if (!quoted && !/\s/.test(program)) {
    return program;
  }
  const word = quoted ? program : `"${program}"`;
  return isPowerShell(shell) ? `& ${word}` : word;
}

function commandLine(id, utCommand, shell) {
  if (typeof id !== "string" || !Object.hasOwn(ARGUMENTS, id)) {
    return null;
  }
  return [programWord(utCommand, shell), ...ARGUMENTS[id]].join(" ");
}

function costOf(id) {
  return typeof id === "string" && Object.hasOwn(COSTS, id) ? COSTS[id] : null;
}

module.exports = {
  ARGUMENTS,
  COSTS,
  PROGRAM,
  bareProgram,
  commandLine,
  costOf,
  isPowerShell,
  programWord,
};
