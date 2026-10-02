import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
import zlib from "node:zlib";

export const EXTENSION_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const LICENSE_FILE = path.resolve(EXTENSION_ROOT, "..", "..", "LICENSE");
export const ROOT_FILES = Object.freeze([
  "package.json",
  "package.nls.json",
  "package.nls.it.json",
  "extension.js",
]);
export const PACKAGED_FOLDERS = Object.freeze(["src", "media"]);
export const CONTENT_TYPES_NAME = "[Content_Types].xml";
export const MANIFEST_NAME = "extension.vsixmanifest";
export const EXTENSION_PREFIX = "extension/";
export const LICENSE_NAME = "extension/LICENSE.txt";

const LOCAL_SIGNATURE = 0x04034b50;
const CENTRAL_SIGNATURE = 0x02014b50;
const END_SIGNATURE = 0x06054b50;
const VERSION_NEEDED = 20;
const VERSION_MADE_BY = (3 << 8) | 20;
const UTF8_NAMES = 0x0800;
const DEFLATE = 8;
const DOS_TIME = 0;
const DOS_DATE = (1 << 5) | 1;
const FILE_ATTRIBUTES = (0o100644 << 16) >>> 0;
const MEDIA_TYPES = Object.freeze({
  ".js": "application/javascript",
  ".json": "application/json",
  ".svg": "image/svg+xml",
  ".txt": "text/plain",
  ".vsixmanifest": "text/xml",
  ".xml": "text/xml",
});
const XML_ENTITIES = Object.freeze({
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&apos;",
});
const MESSAGES = Object.freeze({
  en: Object.freeze({
    written: "Package written: {file} ({size} bytes, {count} entries).",
    install: "Install it in Visual Studio Code with: {command}",
    usage: "Usage: node editors/vscode/scripts/package-vsix.mjs [--out FOLDER] [--lang en|it]",
  }),
  it: Object.freeze({
    written: "Pacchetto scritto: {file} ({size} byte, {count} voci).",
    install: "Installalo in Visual Studio Code con: {command}",
    usage: "Uso: node editors/vscode/scripts/package-vsix.mjs [--out CARTELLA] [--lang en|it]",
  }),
});

function byName(left, right) {
  if (left.name < right.name) {
    return -1;
  }
  return left.name > right.name ? 1 : 0;
}

function escapeXml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => XML_ENTITIES[character]);
}

function fill(pattern, values) {
  return pattern.replace(/\{(\w+)\}/g, (match, name) =>
    Object.hasOwn(values, name) ? String(values[name]) : match,
  );
}

function localized(value, nls) {
  if (typeof value !== "string") {
    return "";
  }
  const match = /^%([^%]+)%$/.exec(value);
  return match !== null && typeof nls[match[1]] === "string" ? nls[match[1]] : value;
}

export function listFiles(folder, prefix) {
  const names = [];
  for (const entry of fs.readdirSync(folder, { withFileTypes: true })) {
    const relative = `${prefix}/${entry.name}`;
    if (entry.isDirectory()) {
      names.push(...listFiles(path.join(folder, entry.name), relative));
    } else if (entry.isFile()) {
      names.push(relative);
    }
  }
  return names.sort();
}

export function extensionFiles(extensionRoot = EXTENSION_ROOT) {
  const names = [...ROOT_FILES];
  for (const folder of PACKAGED_FOLDERS) {
    names.push(...listFiles(path.join(extensionRoot, folder), folder));
  }
  return names.sort();
}

export function vsixManifest(manifest, nls = {}) {
  const engines = manifest.engines ?? {};
  const categories = Array.isArray(manifest.categories) ? manifest.categories.join(",") : "";
  return [
    '<?xml version="1.0" encoding="utf-8"?>',
    '<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011" xmlns:d="http://schemas.microsoft.com/developer/vsx-schema-design/2011">',
    "  <Metadata>",
    `    <Identity Language="en-US" Id="${escapeXml(manifest.name)}" Version="${escapeXml(manifest.version)}" Publisher="${escapeXml(manifest.publisher)}" />`,
    `    <DisplayName>${escapeXml(localized(manifest.displayName, nls))}</DisplayName>`,
    `    <Description xml:space="preserve">${escapeXml(localized(manifest.description, nls))}</Description>`,
    "    <Tags></Tags>",
    `    <Categories>${escapeXml(categories)}</Categories>`,
    "    <GalleryFlags>Public</GalleryFlags>",
    "    <Properties>",
    `      <Property Id="Microsoft.VisualStudio.Code.Engine" Value="${escapeXml(engines.vscode ?? "*")}" />`,
    '      <Property Id="Microsoft.VisualStudio.Code.ExtensionDependencies" Value="" />',
    '      <Property Id="Microsoft.VisualStudio.Code.ExtensionPack" Value="" />',
    '      <Property Id="Microsoft.VisualStudio.Code.ExtensionKind" Value="workspace" />',
    '      <Property Id="Microsoft.VisualStudio.Code.LocalizedLanguages" Value="" />',
    '      <Property Id="Microsoft.VisualStudio.Services.Content.Pricing" Value="Free" />',
    "    </Properties>",
    `    <License>${LICENSE_NAME}</License>`,
    "  </Metadata>",
    "  <Installation>",
    '    <InstallationTarget Id="Microsoft.VisualStudio.Code" />',
    "  </Installation>",
    "  <Dependencies />",
    "  <Assets>",
    `    <Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="${EXTENSION_PREFIX}package.json" Addressable="true" />`,
    `    <Asset Type="Microsoft.VisualStudio.Services.Content.License" Path="${LICENSE_NAME}" Addressable="true" />`,
    "  </Assets>",
    "</PackageManifest>",
    "",
  ].join("\n");
}

export function contentTypes(names) {
  const extensions = [
    ...new Set(
      names
        .filter((name) => name !== CONTENT_TYPES_NAME)
        .map((name) => path.posix.extname(name))
        .filter((extension) => extension !== ""),
    ),
  ].sort();
  const defaults = extensions.map(
    (extension) =>
      `  <Default Extension="${escapeXml(extension)}" ContentType="${escapeXml(MEDIA_TYPES[extension] ?? "application/octet-stream")}" />`,
  );
  return [
    '<?xml version="1.0" encoding="utf-8"?>',
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
    ...defaults,
    "</Types>",
    "",
  ].join("\n");
}

export function packageEntries({
  extensionRoot = EXTENSION_ROOT,
  licenseFile = LICENSE_FILE,
} = {}) {
  const manifest = JSON.parse(fs.readFileSync(path.join(extensionRoot, "package.json"), "utf8"));
  const nls = JSON.parse(fs.readFileSync(path.join(extensionRoot, "package.nls.json"), "utf8"));
  const entries = extensionFiles(extensionRoot).map((name) => ({
    name: `${EXTENSION_PREFIX}${name}`,
    data: fs.readFileSync(path.join(extensionRoot, ...name.split("/"))),
  }));
  entries.push({ name: LICENSE_NAME, data: fs.readFileSync(licenseFile) });
  entries.push({ name: MANIFEST_NAME, data: Buffer.from(vsixManifest(manifest, nls), "utf8") });
  const names = entries.map((entry) => entry.name);
  entries.push({ name: CONTENT_TYPES_NAME, data: Buffer.from(contentTypes(names), "utf8") });
  return { manifest, entries: entries.sort(byName) };
}

export function zipArchive(entries) {
  const records = [];
  const directory = [];
  let offset = 0;
  for (const entry of entries) {
    const name = Buffer.from(entry.name, "utf8");
    const data = Buffer.from(entry.data);
    const compressed = zlib.deflateRawSync(data, { level: 9 });
    const crc = zlib.crc32(data) >>> 0;
    const local = Buffer.alloc(30);
    local.writeUInt32LE(LOCAL_SIGNATURE, 0);
    local.writeUInt16LE(VERSION_NEEDED, 4);
    local.writeUInt16LE(UTF8_NAMES, 6);
    local.writeUInt16LE(DEFLATE, 8);
    local.writeUInt16LE(DOS_TIME, 10);
    local.writeUInt16LE(DOS_DATE, 12);
    local.writeUInt32LE(crc, 14);
    local.writeUInt32LE(compressed.length, 18);
    local.writeUInt32LE(data.length, 22);
    local.writeUInt16LE(name.length, 26);
    local.writeUInt16LE(0, 28);
    records.push(local, name, compressed);
    const central = Buffer.alloc(46);
    central.writeUInt32LE(CENTRAL_SIGNATURE, 0);
    central.writeUInt16LE(VERSION_MADE_BY, 4);
    central.writeUInt16LE(VERSION_NEEDED, 6);
    central.writeUInt16LE(UTF8_NAMES, 8);
    central.writeUInt16LE(DEFLATE, 10);
    central.writeUInt16LE(DOS_TIME, 12);
    central.writeUInt16LE(DOS_DATE, 14);
    central.writeUInt32LE(crc, 16);
    central.writeUInt32LE(compressed.length, 20);
    central.writeUInt32LE(data.length, 24);
    central.writeUInt16LE(name.length, 28);
    central.writeUInt16LE(0, 30);
    central.writeUInt16LE(0, 32);
    central.writeUInt16LE(0, 34);
    central.writeUInt16LE(0, 36);
    central.writeUInt32LE(FILE_ATTRIBUTES, 38);
    central.writeUInt32LE(offset, 42);
    directory.push(central, name);
    offset += local.length + name.length + compressed.length;
  }
  const central = Buffer.concat(directory);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(END_SIGNATURE, 0);
  end.writeUInt16LE(0, 4);
  end.writeUInt16LE(0, 6);
  end.writeUInt16LE(entries.length, 8);
  end.writeUInt16LE(entries.length, 10);
  end.writeUInt32LE(central.length, 12);
  end.writeUInt32LE(offset, 16);
  end.writeUInt16LE(0, 20);
  return Buffer.concat([...records, central, end]);
}

export function vsixName(manifest) {
  return `${manifest.name}-${manifest.version}.vsix`;
}

export function buildVsix({
  extensionRoot = EXTENSION_ROOT,
  licenseFile = LICENSE_FILE,
  outDir = path.join(extensionRoot, "dist"),
} = {}) {
  const { manifest, entries } = packageEntries({ extensionRoot, licenseFile });
  const archive = zipArchive(entries);
  fs.mkdirSync(outDir, { recursive: true });
  const file = path.join(outDir, vsixName(manifest));
  fs.writeFileSync(file, archive);
  return { file, size: archive.length, entries: entries.map((entry) => entry.name) };
}

export function parseArguments(argv) {
  const options = { out: null, lang: "en" };
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if ((argument === "--out" || argument === "--lang") && index + 1 < argv.length) {
      options[argument.slice(2)] = argv[index + 1];
      index += 1;
    } else if (argument.startsWith("--out=")) {
      options.out = argument.slice("--out=".length);
    } else if (argument.startsWith("--lang=")) {
      options.lang = argument.slice("--lang=".length);
    } else {
      return null;
    }
  }
  if (options.out === "" || !Object.hasOwn(MESSAGES, options.lang)) {
    return null;
  }
  return options;
}

function shellWord(value) {
  return /\s/.test(value) ? `"${value}"` : value;
}

export function main(
  argv = process.argv.slice(2),
  { stdout = process.stdout, stderr = process.stderr, cwd = process.cwd() } = {},
) {
  const options = parseArguments(argv);
  if (options === null) {
    stderr.write(`${MESSAGES.en.usage}\n${MESSAGES.it.usage}\n`);
    return 2;
  }
  const texts = MESSAGES[options.lang];
  const result = buildVsix(options.out === null ? {} : { outDir: path.resolve(cwd, options.out) });
  const written = fill(texts.written, {
    file: result.file,
    size: result.size,
    count: result.entries.length,
  });
  const install = fill(texts.install, {
    command: `code --install-extension ${shellWord(result.file)}`,
  });
  stdout.write(`${written}\n${install}\n`);
  return 0;
}

function launchedDirectly() {
  if (typeof process.argv[1] !== "string") {
    return false;
  }
  try {
    return (
      fs.realpathSync(path.resolve(process.argv[1])) ===
      fs.realpathSync(fileURLToPath(import.meta.url))
    );
  } catch {
    return false;
  }
}

if (launchedDirectly()) {
  process.exitCode = main();
}
