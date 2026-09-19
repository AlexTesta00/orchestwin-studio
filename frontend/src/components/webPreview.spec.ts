import { describe, expect, it } from "vitest";
import { buildWebPreview, type PreviewContent } from "./webPreview";

function content(html: string): PreviewContent {
  return {
    revision_id: "revision",
    content_hash: "hash",
    files: [
      { path: "index.html", media_type: "text/html", base64: btoa(html) },
      {
        path: "app.js",
        media_type: "text/javascript",
        base64: btoa("document.querySelector('output').textContent = 2+3;"),
      },
      { path: "css/style.css", media_type: "text/css", base64: btoa("output { color: blue; }") },
    ],
  };
}
describe("generated Web preview", () => {
  it("preserves DOM-ready ordering of deferred classic scripts", () => {
    const doc = new DOMParser().parseFromString(
      buildWebPreview(
        content(
          '<html><head><script defer src="app.js"></script></head><body><output>0</output></body></html>',
        ),
      ),
      "text/html",
    );
    expect(doc.head.querySelector("script")).toBeNull();
    expect(doc.body.lastElementChild?.tagName).toBe("SCRIPT");
    expect(doc.body.lastElementChild?.hasAttribute("defer")).toBe(false);
  });
  it("resolves original local assets and prepends a restrictive policy", () => {
    const result = buildWebPreview(
      content(
        '<base href="https://evil.example"><link rel="stylesheet" href="css/style.css"><output>0</output><script src="./app.js"></script>',
      ),
    );
    const doc = new DOMParser().parseFromString(result, "text/html");
    expect(doc.head.firstElementChild?.getAttribute("http-equiv")).toBe("Content-Security-Policy");
    expect(doc.querySelector("base")).toBeNull();
    expect(doc.querySelector("script[src]")).toBeNull();
    expect(doc.querySelector("script")?.textContent).toContain("2+3");
    expect(doc.querySelector("style")?.textContent).toContain("color: blue");
    expect(result).toContain("connect-src 'none'");
  });
  it("rejects missing and external scripts instead of fetching them", () => {
    expect(() =>
      buildWebPreview(content('<script src="https://external.example/a.js"></script>')),
    ).toThrow("PREVIEW_EXTERNAL_RESOURCE");
    expect(() => buildWebPreview(content('<script src="missing.js"></script>'))).toThrow(
      "PREVIEW_RESOURCE_MISSING",
    );
  });
  it("keeps closing-tag text inside a generated script instead of changing the document", () => {
    const input = content('<output></output><script src="app.js"></script>');
    input.files[1]!.base64 = btoa(
      "document.querySelector('output').textContent = '</script><h1>text</h1>';",
    );
    const doc = new DOMParser().parseFromString(buildWebPreview(input), "text/html");
    expect(doc.querySelector("h1")).toBeNull();
    expect(doc.querySelector("script")?.textContent).toContain("<\\/script>");
  });
});
