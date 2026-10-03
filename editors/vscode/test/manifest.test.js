"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { describe, it } = require("node:test");

const EXTENSION_ROOT = path.resolve(__dirname, "..");
const REPOSITORY_ROOT = path.resolve(EXTENSION_ROOT, "..", "..");
const COMMANDS = [
  "orchestwin.refresh",
  "orchestwin.status",
  "orchestwin.test",
  "orchestwin.align",
  "orchestwin.recheck",
  "orchestwin.code",
  "orchestwin.tasks",
  "orchestwin.twinsUpdate",
  "orchestwin.openReport",
  "orchestwin.connectAgents",
  "orchestwin.why",
  "orchestwin.validation",
  "orchestwin.scenarioWalkthrough",
];

function readJson(...parts) {
  return JSON.parse(fs.readFileSync(path.join(...parts), "utf8"));
}

function placeholders(value, found = []) {
  if (typeof value === "string") {
    const match = /^%([^%]+)%$/.exec(value);
    if (match !== null) {
      found.push(match[1]);
    }
  } else if (Array.isArray(value)) {
    value.forEach((item) => placeholders(item, found));
  } else if (value !== null && typeof value === "object") {
    Object.values(value).forEach((item) => placeholders(item, found));
  }
  return found;
}

describe("the manifest of the extension", () => {
  const manifest = readJson(EXTENSION_ROOT, "package.json");
  const english = readJson(EXTENSION_ROOT, "package.nls.json");
  const italian = readJson(EXTENSION_ROOT, "package.nls.it.json");

  it("names the extension and how the editor starts it", () => {
    assert.equal(manifest.name, "orchestwin-studio");
    assert.equal(manifest.displayName, "OrchesTwin Studio");
    assert.equal(manifest.publisher, "orchestwin");
    assert.equal(manifest.version, "0.1.0");
    assert.equal(manifest.license, "Apache-2.0");
    assert.deepEqual(manifest.engines, { vscode: "^1.90.0" });
    assert.equal(manifest.main, "./extension.js");
    assert.deepEqual(manifest.categories, ["Other"]);
    assert.deepEqual(manifest.activationEvents, ["workspaceContains:.orchestwin/project.json"]);
    assert.equal(manifest.capabilities.untrustedWorkspaces.supported, false);
    assert.equal(manifest.type, undefined);
  });

  it("depends on nothing and needs no build", () => {
    for (const key of [
      "dependencies",
      "devDependencies",
      "peerDependencies",
      "scripts",
      "bundleDependencies",
    ]) {
      assert.equal(manifest[key], undefined, key);
    }
    for (const name of ["node_modules", "package-lock.json", "tsconfig.json"]) {
      assert.equal(fs.existsSync(path.join(EXTENSION_ROOT, name)), false, name);
    }
  });

  it("contributes one container with one webview", () => {
    const contributes = manifest.contributes;
    assert.deepEqual(contributes.viewsContainers, {
      activitybar: [{ id: "orchestwin", title: "%container.title%", icon: "media/icon.svg" }],
    });
    assert.deepEqual(contributes.views, {
      orchestwin: [{ type: "webview", id: "orchestwin.panel", name: "%view.name%" }],
    });
  });

  it("contributes the commands with their titles and their category", () => {
    const commands = manifest.contributes.commands;
    assert.deepEqual(
      commands.map((command) => command.command),
      COMMANDS,
    );
    for (const command of commands) {
      assert.match(command.title, /^%command\.[A-Za-z]+%$/);
      assert.equal(command.category, "OrchesTwin");
    }
    assert.deepEqual(manifest.contributes.menus["view/title"], [
      { command: "orchestwin.refresh", when: "view == orchestwin.panel", group: "navigation" },
    ]);
  });

  it("lets the owner choose the program of the buttons", () => {
    const configuration = manifest.contributes.configuration;
    assert.match(configuration.title, /^%.+%$/);
    const setting = configuration.properties["orchestwin.utCommand"];
    assert.equal(setting.type, "string");
    assert.equal(setting.default, "ut");
    assert.match(setting.description, /^%.+%$/);
    assert.deepEqual(Object.keys(configuration.properties), ["orchestwin.utCommand"]);
  });

  it("finds every text of the manifest in both languages", () => {
    const keys = placeholders(manifest);
    assert.ok(keys.length >= 14);
    assert.deepEqual(Object.keys(english).sort(), Object.keys(italian).sort());
    assert.deepEqual([...new Set(keys)].sort(), Object.keys(english).sort());
    for (const table of [english, italian]) {
      for (const [key, value] of Object.entries(table)) {
        assert.equal(typeof value, "string", key);
        assert.ok(value.trim() !== "", key);
      }
    }
    assert.notEqual(english["command.test"], italian["command.test"]);
  });

  it("names only files that exist", () => {
    assert.ok(fs.statSync(path.join(EXTENSION_ROOT, manifest.main)).isFile());
    for (const container of manifest.contributes.viewsContainers.activitybar) {
      assert.ok(fs.statSync(path.join(EXTENSION_ROOT, container.icon)).isFile());
    }
  });

  it("draws the icon with one colour, the colour of the text", () => {
    const icon = fs.readFileSync(path.join(EXTENSION_ROOT, "media", "icon.svg"), "utf8");
    assert.ok(icon.startsWith("<svg "));
    assert.ok(icon.includes('stroke="currentColor"'));
    assert.ok(!/#[0-9a-f]{3,8}\b/i.test(icon));
    assert.ok(!/<(image|script|style|foreignObject)/i.test(icon));
    for (const match of icon.matchAll(/\b(fill|stroke)="([^"]*)"/g)) {
      assert.ok(["none", "currentColor"].includes(match[2]), match[0]);
    }
  });

  it("is tested by the script of the repository and by the continuous integration", () => {
    const root = readJson(REPOSITORY_ROOT, "package.json");
    assert.equal(root.scripts["test:editor"], 'node --test "editors/vscode/test/*.test.js"');
    const workflow = fs
      .readFileSync(path.join(REPOSITORY_ROOT, ".github", "workflows", "ci-cd.yml"), "utf8")
      .replace(/\r\n/g, "\n");
    const steps = [...workflow.matchAll(/^ {6}- name: (.+)$/gm)].map((match) => match[1].trim());
    const frontend = steps.indexOf("Run frontend tests");
    assert.ok(frontend >= 0);
    assert.equal(steps[frontend + 1], "Run editor panel tests");
    assert.ok(
      workflow.includes("      - name: Run editor panel tests\n        run: npm run test:editor\n"),
    );
  });
});
