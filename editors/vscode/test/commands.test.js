"use strict";

const assert = require("node:assert/strict");
const os = require("node:os");
const path = require("node:path");
const { describe, it } = require("node:test");
const {
  ARGUMENTS,
  bareProgram,
  commandLine,
  costOf,
  isPowerShell,
  programWord,
} = require("../src/commands");

describe("commandLine", () => {
  it("writes the ut command of every button", () => {
    assert.equal(commandLine("status", "ut"), "ut status");
    assert.equal(commandLine("test", "ut"), "ut test");
    assert.equal(commandLine("verify", "ut"), "ut verify");
    assert.equal(commandLine("recheck", "ut"), "ut verify --recheck");
    assert.equal(commandLine("align", "ut"), "ut align");
    assert.equal(commandLine("alignPending", "ut"), "ut align --pending");
    assert.equal(commandLine("code", "ut"), "ut code");
    assert.equal(commandLine("tasks", "ut"), "ut tasks");
    assert.equal(commandLine("twinsUpdate", "ut"), "ut twins update");
    assert.equal(commandLine("tasksFromTest", "ut"), "ut tasks from-test");
    assert.equal(commandLine("init", "ut"), "ut init");
    assert.equal(commandLine("design", "ut"), "ut design");
    assert.equal(commandLine("publish", "ut"), "ut package publish");
  });

  it("knows no other command", () => {
    for (const id of ["openReport", "connectAgents", "refresh", "rm", "", "toString", null, 3]) {
      assert.equal(commandLine(id, "ut"), null);
    }
    assert.deepEqual(Object.keys(ARGUMENTS).sort(), [
      "align",
      "alignPending",
      "code",
      "design",
      "init",
      "publish",
      "recheck",
      "status",
      "tasks",
      "tasksFromTest",
      "test",
      "twinsUpdate",
      "verify",
    ]);
  });

  it("uses the configured program and ut when nothing is configured", () => {
    assert.equal(commandLine("test", "ut-dev"), "ut-dev test");
    for (const empty of [undefined, null, "", "   ", 7]) {
      assert.equal(commandLine("test", empty), "ut test");
    }
  });

  it("quotes a program that holds a space", () => {
    const program = path.join(os.tmpdir(), "tools dir", "ut");
    assert.equal(commandLine("test", program), `"${program}" test`);
    assert.equal(commandLine("recheck", `  ${program}  `), `"${program}" verify --recheck`);
    assert.equal(commandLine("test", `"${program}"`), `"${program}" test`);
  });

  it("calls a quoted program with the call operator of PowerShell", () => {
    const program = path.join(os.tmpdir(), "tools dir", "ut");
    assert.equal(commandLine("test", program, "pwsh"), `& "${program}" test`);
    assert.equal(
      commandLine("test", program, path.join("bin", "powershell.exe")),
      `& "${program}" test`,
    );
    assert.equal(commandLine("test", program, "bash"), `"${program}" test`);
    assert.equal(commandLine("test", "ut", "pwsh"), "ut test");
  });

  it("tells the shells apart by the name of their program", () => {
    assert.equal(isPowerShell("pwsh"), true);
    assert.equal(isPowerShell(path.join("any", "PowerShell.EXE")), true);
    assert.equal(isPowerShell(path.join("any", "pwsh-preview")), false);
    assert.equal(isPowerShell("cmd.exe"), false);
    assert.equal(isPowerShell(undefined), false);
    assert.equal(programWord("ut", "pwsh"), "ut");
  });

  it("gives the program without quotes where no shell reads it", () => {
    const program = path.join(os.tmpdir(), "tools dir", "ut");
    assert.equal(bareProgram(`"${program}"`), program);
    assert.equal(bareProgram(program), program);
    assert.equal(bareProgram('""'), "ut");
    assert.equal(bareProgram(undefined), "ut");
  });
});

describe("costOf", () => {
  it("marks the commands that may spend, the coding agent and the free ones", () => {
    for (const id of [
      "test",
      "verify",
      "recheck",
      "align",
      "alignPending",
      "twinsUpdate",
      "init",
      "design",
    ]) {
      assert.equal(costOf(id), "SPENDS", id);
    }
    assert.equal(costOf("code"), "AGENT");
    for (const id of ["status", "tasks", "tasksFromTest", "publish"]) {
      assert.equal(costOf(id), "FREE", id);
    }
    assert.equal(costOf("openReport"), null);
    assert.equal(costOf("hasOwnProperty"), null);
  });
});
