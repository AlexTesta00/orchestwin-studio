export interface PreviewFile {
  path: string;
  media_type: string;
  base64: string;
}
export interface PreviewContent {
  revision_id: string;
  content_hash: string;
  files: PreviewFile[];
}

export function buildWebPreview(content: PreviewContent): string {
  const files = new Map(content.files.map((file) => [file.path, file]));
  function find(value: string, base = "index.html"): PreviewFile {
    const url = new URL(value, `https://preview.invalid/${base}`);
    if (url.origin !== "https://preview.invalid") throw new Error("PREVIEW_EXTERNAL_RESOURCE");
    const file = files.get(decodeURIComponent(url.pathname.slice(1)));
    if (!file) throw new Error("PREVIEW_RESOURCE_MISSING");
    return file;
  }
  function text(file: PreviewFile): string {
    return new TextDecoder("utf-8", { fatal: true }).decode(
      Uint8Array.from(atob(file.base64), (c) => c.charCodeAt(0)),
    );
  }
  function data(file: PreviewFile): string {
    return `data:${file.media_type};base64,${file.base64}`;
  }
  const doc = new DOMParser().parseFromString(text(find("index.html")), "text/html");
  doc
    .querySelectorAll("base, meta[http-equiv], iframe, object, embed")
    .forEach((element) => element.remove());
  for (const link of doc.querySelectorAll<HTMLLinkElement>('link[rel="stylesheet"]')) {
    const file = find(link.getAttribute("href") ?? "");
    const css = text(file);
    if (/@import\b/i.test(css)) throw new Error("PREVIEW_CSS_IMPORT_UNSUPPORTED");
    const style = doc.createElement("style");
    style.textContent = css.replace(
      /url\(\s*(['"]?)(.*?)\1\s*\)/g,
      (_match, _quote, path: string) =>
        path.startsWith("data:") ? `url("${path}")` : `url("${data(find(path, file.path))}")`,
    );
    link.replaceWith(style);
  }
  for (const script of doc.querySelectorAll<HTMLScriptElement>("script[src]")) {
    const source = text(find(script.getAttribute("src") ?? ""));
    // Inline classic scripts ignore defer. Keep their DOM-ready ordering when
    // packaging the original local resource into the isolated document.
    const deferred = script.hasAttribute("defer") && script.type !== "module";
    script.removeAttribute("src");
    script.removeAttribute("integrity");
    script.removeAttribute("crossorigin");
    // Preserve literal closing tags in JavaScript strings across srcdoc parsing.
    script.textContent = source.replace(/<\/script/gi, "<\\/script");
    if (deferred) {
      script.removeAttribute("defer");
      doc.body.append(script);
    }
  }
  for (const element of doc.querySelectorAll("img[src], source[src], audio[src], video[src]")) {
    const src = element.getAttribute("src") ?? "";
    if (!src.startsWith("data:")) element.setAttribute("src", data(find(src)));
    element.removeAttribute("srcset");
  }
  doc.querySelectorAll("a[href]").forEach((anchor) => {
    if (!anchor.getAttribute("href")?.startsWith("#")) anchor.removeAttribute("href");
  });
  const policy = doc.createElement("meta");
  policy.httpEquiv = "Content-Security-Policy";
  policy.content =
    "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:; media-src data:; connect-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'";
  doc.head.prepend(policy);
  return "<!doctype html>\n" + doc.documentElement.outerHTML;
}
