"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const zlib = require("node:zlib");
const { after, before, describe, it } = require("node:test");
const fixtures = require("./fixtures");

const EXTENSION_ROOT = path.resolve(__dirname, "..");
const LICENSE = path.resolve(EXTENSION_ROOT, "..", "..", "LICENSE");
const SCRIPT = path.join(EXTENSION_ROOT, "scripts", "package-vsix.mjs");
const END_SIGNATURE = Buffer.from([0x50, 0x4b, 0x05, 0x06]);

function walk(folder, prefix) {
  const names = [];
  for (const entry of fs.readdirSync(folder, { withFileTypes: true })) {
    const relative = `${prefix}/${entry.name}`;
    if (entry.isDirectory()) {
      names.push(...walk(path.join(folder, entry.name), relative));
    } else {
      names.push(relative);
    }
  }
  return names;
}

function expectedEntries() {
  const sources = [
    "package.json",
    "package.nls.json",
    "package.nls.it.json",
    "extension.js",
    ...walk(path.join(EXTENSION_ROOT, "src"), "src"),
    ...walk(path.join(EXTENSION_ROOT, "media"), "media"),
  ];
  return [
    "[Content_Types].xml",
    "extension.vsixmanifest",
    "extension/LICENSE.txt",
    ...sources.map((name) => `extension/${name}`),
  ].sort();
}

function sourceOf(name) {
  if (name === "extension/LICENSE.txt") {
    return fs.readFileSync(LICENSE);
  }
  return fs.readFileSync(path.join(EXTENSION_ROOT, ...name.slice("extension/".length).split("/")));
}

function readZip(archive) {
  const end = archive.lastIndexOf(END_SIGNATURE);
  assert.ok(end > 0);
  assert.equal(end, archive.length - 22);
  const count = archive.readUInt16LE(end + 10);
  const size = archive.readUInt32LE(end + 12);
  let position = archive.readUInt32LE(end + 16);
  assert.equal(position + size, end);
  const entries = [];
  for (let index = 0; index < count; index += 1) {
    assert.equal(archive.readUInt32LE(position), 0x02014b50);
    const method = archive.readUInt16LE(position + 10);
    const time = archive.readUInt16LE(position + 12);
    const date = archive.readUInt16LE(position + 14);
    const crc = archive.readUInt32LE(position + 16);
    const compressedSize = archive.readUInt32LE(position + 20);
    const originalSize = archive.readUInt32LE(position + 24);
    const nameLength = archive.readUInt16LE(position + 28);
    const extraLength = archive.readUInt16LE(position + 30);
    const commentLength = archive.readUInt16LE(position + 32);
    const offset = archive.readUInt32LE(position + 42);
    const name = archive.toString("utf8", position + 46, position + 46 + nameLength);
    assert.equal(archive.readUInt32LE(offset), 0x04034b50);
    assert.equal(archive.readUInt32LE(offset + 14), crc);
    const localName = archive.readUInt16LE(offset + 26);
    const localExtra = archive.readUInt16LE(offset + 28);
    assert.equal(archive.toString("utf8", offset + 30, offset + 30 + localName), name);
    const start = offset + 30 + localName + localExtra;
    const data = zlib.inflateRawSync(archive.subarray(start, start + compressedSize));
    entries.push({ name, method, time, date, crc, originalSize, data });
    position += 46 + nameLength + extraLength + commentLength;
  }
  return entries;
}

describe("the package of the extension", () => {
  let base;
  let vsix;

  before(async () => {
    base = fixtures.makeTemporaryFolder();
    vsix = await import(pathToFileURL(SCRIPT).href);
  });

  after(() => {
    fixtures.removeFolder(base);
  });

  it("holds exactly the files of the extension, each equal to its source", () => {
    const result = vsix.buildVsix({ outDir: path.join(base, "first") });
    assert.equal(result.file, path.join(base, "first", "orchestwin-studio-0.1.0.vsix"));
    const archive = fs.readFileSync(result.file);
    assert.equal(result.size, archive.length);
    const entries = readZip(archive);
    assert.deepEqual(
      entries.map((entry) => entry.name),
      expectedEntries(),
    );
    assert.deepEqual(result.entries, expectedEntries());
    for (const entry of entries) {
      assert.equal(entry.method, 8, entry.name);
      assert.equal(entry.time, 0, entry.name);
      assert.equal(entry.date, 33, entry.name);
      assert.equal(entry.crc, zlib.crc32(entry.data), entry.name);
      assert.equal(entry.originalSize, entry.data.length, entry.name);
      if (entry.name.startsWith("extension/")) {
        assert.ok(entry.data.equals(sourceOf(entry.name)), entry.name);
      }
    }
    for (const entry of entries) {
      assert.ok(!/\/(test|scripts|dist|node_modules)\//.test(entry.name), entry.name);
    }
  });

  it("describes the extension for the editor", () => {
    const entries = readZip(
      fs.readFileSync(vsix.buildVsix({ outDir: path.join(base, "xml") }).file),
    );
    const byName = new Map(entries.map((entry) => [entry.name, entry.data.toString("utf8")]));
    const types = byName.get("[Content_Types].xml");
    for (const extension of [".js", ".json", ".svg", ".txt", ".vsixmanifest"]) {
      assert.ok(types.includes(`<Default Extension="${extension}" `), extension);
    }
    const manifest = byName.get("extension.vsixmanifest");
    assert.ok(
      manifest.includes(
        '<Identity Language="en-US" Id="orchestwin-studio" Version="0.1.0" Publisher="orchestwin" />',
      ),
    );
    assert.ok(manifest.includes("<DisplayName>OrchesTwin Studio</DisplayName>"));
    assert.ok(manifest.includes('Value="^1.90.0"'));
    assert.ok(manifest.includes('Path="extension/package.json"'));
    assert.ok(manifest.includes("<License>extension/LICENSE.txt</License>"));
    const description = /<Description xml:space="preserve">([^<]*)<\/Description>/.exec(
      manifest,
    )[1];
    const nls = JSON.parse(fs.readFileSync(path.join(EXTENSION_ROOT, "package.nls.json"), "utf8"));
    assert.equal(description, nls.description);
  });

  it("gives the same bytes twice", () => {
    const first = fs.readFileSync(vsix.buildVsix({ outDir: path.join(base, "one") }).file);
    const second = fs.readFileSync(vsix.buildVsix({ outDir: path.join(base, "two") }).file);
    assert.ok(first.equals(second));
  });

  it("prints where the package is and how to install it, and installs nothing", () => {
    const written = [];
    const errors = [];
    const out = path.join(base, "printed dir");
    const status = vsix.main(["--out", out], {
      stdout: { write: (value) => written.push(value) },
      stderr: { write: (value) => errors.push(value) },
      cwd: base,
    });
    assert.equal(status, 0);
    assert.deepEqual(errors, []);
    const file = path.join(out, "orchestwin-studio-0.1.0.vsix");
    assert.ok(fs.statSync(file).isFile());
    const output = written.join("");
    assert.ok(output.includes(file));
    assert.ok(output.includes(`code --install-extension "${file}"`));
    assert.deepEqual(fs.readdirSync(out), ["orchestwin-studio-0.1.0.vsix"]);
  });

  it("speaks Italian when asked and refuses unknown options", () => {
    const written = [];
    const status = vsix.main(["--out=it", "--lang", "it"], {
      stdout: { write: (value) => written.push(value) },
      stderr: { write: () => {} },
      cwd: base,
    });
    assert.equal(status, 0);
    assert.ok(
      written.join("").includes("Installalo in Visual Studio Code con: code --install-extension"),
    );
    const errors = [];
    for (const argv of [["--bogus"], ["--out"], ["--lang", "fr"], ["--out="]]) {
      assert.equal(
        vsix.main(argv, {
          stdout: { write: () => assert.fail("nothing is printed") },
          stderr: { write: (value) => errors.push(value) },
          cwd: base,
        }),
        2,
      );
    }
    assert.equal(errors.length, 4);
  });
});
