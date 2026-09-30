from __future__ import annotations

import json
from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

MAX_SNAPSHOT_ELEMENTS: Final = 150
MAX_SNAPSHOT_TEXT_LENGTH: Final = 6000
MAX_SNAPSHOT_OPTIONS: Final = 20
MAX_TARGET_NAME_LENGTH: Final = 200
MAX_VALUE_LENGTH: Final = 200
INDEX_ATTRIBUTE: Final = "data-ot-index"

ROLE_OF: Final[Mapping[str, str]] = MappingProxyType(
    {
        "a": "link",
        "area": "link",
        "button": "button",
        "summary": "button",
        "select": "combobox",
        "textarea": "textbox",
        "h1": "heading",
        "h2": "heading",
        "h3": "heading",
        "h4": "heading",
        "h5": "heading",
        "h6": "heading",
        "img": "image",
        "dialog": "dialog",
        "li": "listitem",
        "td": "cell",
        "th": "cell",
        "progress": "progressbar",
        "meter": "progressbar",
        "output": "status",
        "input": "textbox",
        "input:text": "textbox",
        "input:email": "textbox",
        "input:password": "textbox",
        "input:search": "textbox",
        "input:tel": "textbox",
        "input:url": "textbox",
        "input:date": "textbox",
        "input:time": "textbox",
        "input:datetime-local": "textbox",
        "input:month": "textbox",
        "input:week": "textbox",
        "input:color": "textbox",
        "input:number": "spinbutton",
        "input:range": "slider",
        "input:checkbox": "checkbox",
        "input:radio": "radio",
        "input:button": "button",
        "input:submit": "button",
        "input:reset": "button",
        "input:image": "button",
        "input:file": "button",
        "input:hidden": "",
        "role:button": "button",
        "role:link": "link",
        "role:textbox": "textbox",
        "role:searchbox": "textbox",
        "role:checkbox": "checkbox",
        "role:radio": "radio",
        "role:combobox": "combobox",
        "role:option": "option",
        "role:slider": "slider",
        "role:spinbutton": "spinbutton",
        "role:switch": "switch",
        "role:heading": "heading",
        "role:img": "image",
        "role:image": "image",
        "role:alert": "alert",
        "role:status": "status",
        "role:dialog": "dialog",
        "role:alertdialog": "dialog",
        "role:tab": "tab",
        "role:listitem": "listitem",
        "role:treeitem": "listitem",
        "role:cell": "cell",
        "role:gridcell": "cell",
        "role:columnheader": "cell",
        "role:rowheader": "cell",
        "role:progressbar": "progressbar",
        "role:meter": "progressbar",
        "role:menuitem": "button",
        "role:menuitemcheckbox": "checkbox",
        "role:menuitemradio": "radio",
        "role:paragraph": "text",
        "role:none": "",
        "role:presentation": "",
    }
)
TEXT_TAGS: Final = (
    "p",
    "span",
    "li",
    "td",
    "th",
    "dt",
    "dd",
    "label",
    "legend",
    "figcaption",
    "output",
    "small",
    "strong",
    "em",
    "div",
    "a",
    "b",
    "i",
    "u",
    "s",
    "mark",
    "time",
    "code",
    "kbd",
    "pre",
    "q",
    "cite",
    "abbr",
    "sub",
    "sup",
    "del",
    "ins",
    "blockquote",
    "caption",
    "address",
    "section",
    "article",
    "main",
    "header",
    "footer",
    "aside",
    "nav",
    "figure",
)
FIRST_ROLES: Final = (
    "button",
    "link",
    "textbox",
    "checkbox",
    "radio",
    "combobox",
    "option",
    "slider",
    "spinbutton",
    "switch",
    "tab",
    "dialog",
    "alert",
    "status",
)
LEAF_ROLES: Final = (
    "button",
    "link",
    "heading",
    "tab",
    "option",
    "checkbox",
    "radio",
    "switch",
    "image",
    "textbox",
    "combobox",
    "slider",
    "spinbutton",
    "progressbar",
)
BLOCK_ROLES: Final = ("text", "listitem", "cell", "alert", "status")
CONTENT_ROLES: Final = (
    "button",
    "link",
    "heading",
    "text",
    "listitem",
    "cell",
    "tab",
    "option",
    "checkbox",
    "radio",
    "switch",
    "status",
    "alert",
)

_SNAPSHOT_TEMPLATE: Final = r"""() => {
  const roleOf = __ROLE_OF__;
  const textTags = new Set(__TEXT_TAGS__);
  const firstRoles = new Set(__FIRST_ROLES__);
  const leafRoles = new Set(__LEAF_ROLES__);
  const blockRoles = new Set(__BLOCK_ROLES__);
  const contentRoles = new Set(__CONTENT_ROLES__);
  const limits = __LIMITS__;
  const attribute = "__ATTRIBUTE__";
  const hiddenTags = new Set(["script", "style", "template", "noscript", "head", "meta", "link", "title", "base"]);
  const opaqueTags = new Set(["select", "svg", "iframe", "object", "embed", "canvas", "video", "audio", "math", "textarea", "img", "input", "progress", "meter"]);
  const fieldTags = new Set(["input", "select", "textarea"]);
  const owns = (object, key) => Object.prototype.hasOwnProperty.call(object, key);
  const collapse = (value) => String(value ?? "").replace(/\s+/g, " ").trim();
  const cut = (value, limit) => (value.length > limit ? value.slice(0, limit).trim() : value);
  const clip = (value, limit) => (value.length > limit ? value.slice(0, limit) : value);
  const styles = new Map();
  const styleOf = (element) => {
    let style = styles.get(element);
    if (style === undefined) {
      style = getComputedStyle(element);
      styles.set(element, style);
    }
    return style;
  };
  const typeOf = (element) => collapse(element.getAttribute("type")).toLowerCase() || "text";
  const childrenOf = (node) => {
    if (node.shadowRoot) {
      return Array.from(node.shadowRoot.childNodes);
    }
    if (node.localName === "slot" && typeof node.assignedNodes === "function") {
      return node.assignedNodes({ flatten: true });
    }
    const children = Array.from(node.childNodes);
    if (node.localName === "details" && !node.open) {
      const summary = children.find((child) => child.nodeType === 1 && child.localName === "summary");
      return summary ? [summary] : [];
    }
    return children;
  };
  const concealed = (element, style, forPeople) =>
    style.display === "none" ||
    style.contentVisibility === "hidden" ||
    (!forPeople && element.getAttribute("aria-hidden") === "true");
  const clipped = (element, style) => {
    if (style.overflowX === "visible" && style.overflowY === "visible") {
      return false;
    }
    const box = element.getBoundingClientRect();
    return box.width === 0 || box.height === 0;
  };
  const inline = (style) => style.display.startsWith("inline") || style.display === "contents";
  const textOf = (root, options) => {
    const parts = [];
    let size = 0;
    const walk = (node, visible) => {
      for (const child of childrenOf(node)) {
        if (size >= options.budget) {
          return;
        }
        if (child.nodeType === 3) {
          if (visible) {
            parts.push(child.data);
            size += child.data.length;
          }
          continue;
        }
        if (child.nodeType !== 1 || child === options.exclude) {
          continue;
        }
        const tag = child.localName;
        if (hiddenTags.has(tag)) {
          continue;
        }
        const style = styleOf(child);
        if (concealed(child, style, !options.names)) {
          continue;
        }
        if (options.inlineOnly && !inline(style)) {
          continue;
        }
        const own = style.visibility === "visible";
        if (tag === "img" || (tag === "input" && typeOf(child) === "image")) {
          const alt = collapse(child.getAttribute("alt"));
          if (alt && own) {
            parts.push(" " + alt + " ");
            size += alt.length;
          }
          continue;
        }
        if (tag === "svg") {
          const heading = child.querySelector("title");
          const label = collapse(child.getAttribute("aria-label") || (heading ? heading.textContent : ""));
          if (label && own && options.names) {
            parts.push(" " + label + " ");
            size += label.length;
          }
          continue;
        }
        if (tag === "br") {
          parts.push(" ");
          continue;
        }
        if (opaqueTags.has(tag) || clipped(child, style)) {
          continue;
        }
        const block = !inline(style);
        if (block) {
          parts.push(" ");
        }
        walk(child, own);
        if (block) {
          parts.push(" ");
        }
      }
    };
    walk(root, root.nodeType !== 1 || styleOf(root).visibility === "visible");
    return collapse(parts.join(""));
  };
  const labelShown = (element) =>
    Boolean(element.labels) &&
    Array.from(element.labels).some((label) => {
      const style = styleOf(label);
      const box = label.getBoundingClientRect();
      return style.display !== "none" && style.visibility === "visible" && box.width > 1 && box.height > 1;
    });
  const listable = (element, style, tag) => {
    if (style.visibility === "visible") {
      const box = element.getBoundingClientRect();
      const offPage = box.right + window.scrollX <= 0 || box.bottom + window.scrollY <= 0;
      if (box.width > 1 && box.height > 1 && !offPage) {
        return true;
      }
    }
    return fieldTags.has(tag) && labelShown(element);
  };
  const explicitRole = (element) => {
    for (const token of collapse(element.getAttribute("role")).toLowerCase().split(" ")) {
      if (token && owns(roleOf, "role:" + token)) {
        return roleOf["role:" + token];
      }
    }
    return null;
  };
  const implicitRole = (element, tag) => {
    if (tag === "input") {
      const type = typeOf(element);
      if (type === "checkbox" && element.hasAttribute("switch")) {
        return "switch";
      }
      return owns(roleOf, "input:" + type) ? roleOf["input:" + type] : roleOf.input;
    }
    if ((tag === "a" || tag === "area") && !element.hasAttribute("href")) {
      return "";
    }
    if (tag === "img" && !collapse(element.getAttribute("alt"))) {
      return "";
    }
    if (owns(roleOf, tag)) {
      return roleOf[tag];
    }
    if (element.isContentEditable && !(element.parentElement && element.parentElement.isContentEditable)) {
      return "textbox";
    }
    return "";
  };
  const directText = (element) =>
    Array.from(element.childNodes).some((child) => child.nodeType === 3 && child.data.trim() !== "");
  const labelsListedControl = (element, tag) => {
    if (tag !== "label" || !element.control) {
      return false;
    }
    const control = element.control;
    const style = styleOf(control);
    return !concealed(control, style, false) && listable(control, style, control.localName);
  };
  const found = [];
  const visit = (node, suppress) => {
    for (const child of childrenOf(node)) {
      if (child.nodeType !== 1) {
        continue;
      }
      const tag = child.localName;
      if (hiddenTags.has(tag)) {
        continue;
      }
      const style = styleOf(child);
      if (concealed(child, style, false)) {
        continue;
      }
      const explicit = explicitRole(child);
      let role = explicit !== null ? explicit : implicitRole(child, tag);
      if (!role && textTags.has(tag) && directText(child) && !labelsListedControl(child, tag)) {
        const hidden = suppress === "all" || (suppress === "inline" && inline(style));
        role = hidden ? "" : "text";
      }
      let next = suppress;
      if (role && listable(child, style, tag)) {
        found.push({ element: child, role, tag });
        next = leafRoles.has(role) ? "all" : blockRoles.has(role) ? "inline" : "none";
      }
      if (opaqueTags.has(tag) || clipped(child, style)) {
        continue;
      }
      visit(child, next);
    }
  };
  const nameOf = (element, role, tag) => {
    const budget = limits.name * 2;
    const labelledBy = collapse(element.getAttribute("aria-labelledby"));
    if (labelledBy) {
      const root = element.getRootNode();
      const text = collapse(
        labelledBy
          .split(" ")
          .map((id) => {
            const target = (typeof root.getElementById === "function" ? root.getElementById(id) : null) || document.getElementById(id);
            if (!target) {
              return "";
            }
            return textOf(target, { names: true, budget, exclude: null }) || collapse(target.textContent);
          })
          .join(" "),
      );
      if (text) {
        return text;
      }
    }
    const label = collapse(element.getAttribute("aria-label"));
    if (label) {
      return label;
    }
    if (element.labels && element.labels.length > 0) {
      const text = collapse(
        Array.from(element.labels)
          .map((item) => textOf(item, { names: true, budget, exclude: element }))
          .join(" "),
      );
      if (text) {
        return text;
      }
    }
    if (role === "textbox" || role === "combobox" || role === "spinbutton" || role === "slider") {
      const placeholder = collapse(element.getAttribute("placeholder") || element.getAttribute("aria-placeholder"));
      if (placeholder) {
        return placeholder;
      }
    }
    if (tag === "img" || tag === "area" || (tag === "input" && typeOf(element) === "image")) {
      const alt = collapse(element.getAttribute("alt"));
      if (alt) {
        return alt;
      }
    }
    if (tag === "input" && ["button", "submit", "reset"].includes(typeOf(element))) {
      const value = collapse(element.value);
      if (value) {
        return value;
      }
    }
    if (contentRoles.has(role)) {
      const text = textOf(element, { names: true, budget, exclude: null, inlineOnly: role === "text" });
      if (text) {
        return text;
      }
    }
    const title = collapse(element.getAttribute("title"));
    if (title) {
      return title;
    }
    if (role === "dialog") {
      const heading = element.querySelector("h1, h2, h3, h4, h5, h6, [role=heading]");
      if (heading) {
        return textOf(heading, { names: true, budget, exclude: null });
      }
    }
    return "";
  };
  const valueOf = (element, role, tag) => {
    if (tag === "select") {
      return Array.from(element.selectedOptions)
        .map((option) => collapse(option.label || option.textContent))
        .join(", ");
    }
    if (tag === "input" || tag === "textarea") {
      const type = tag === "input" ? typeOf(element) : "text";
      if (["checkbox", "radio", "button", "submit", "reset", "image", "file", "hidden"].includes(type)) {
        return null;
      }
      const value = String(element.value ?? "");
      return type === "password" ? String.fromCharCode(8226).repeat(value.length) : value;
    }
    if (tag === "progress" || tag === "meter") {
      return String(element.value);
    }
    if (role === "textbox" && element.isContentEditable) {
      return textOf(element, { names: false, budget: limits.value * 2, exclude: null });
    }
    if (["slider", "spinbutton", "progressbar", "combobox", "textbox"].includes(role)) {
      const described = element.getAttribute("aria-valuetext") ?? element.getAttribute("aria-valuenow");
      if (described !== null) {
        return String(described);
      }
      if (typeof element.value === "string") {
        return element.value;
      }
    }
    return null;
  };
  const stateOf = (element, role) => {
    const disabled = (typeof element.matches === "function" && element.matches(":disabled")) || element.getAttribute("aria-disabled") === "true";
    if (disabled) {
      return "disabled";
    }
    if (role === "checkbox" || role === "radio" || role === "switch") {
      return element.checked === true || element.getAttribute("aria-checked") === "true" ? "checked" : null;
    }
    if (element.getAttribute("aria-pressed") === "true" || element.getAttribute("aria-selected") === "true") {
      return "checked";
    }
    return null;
  };
  const optionsOf = (element, role, tag) => {
    if (role !== "combobox") {
      return null;
    }
    const labels = [];
    if (tag === "select") {
      for (const option of Array.from(element.options)) {
        if (!option.hidden) {
          labels.push(option.label || option.textContent);
        }
      }
    } else {
      const ids = [element.getAttribute("aria-controls"), element.getAttribute("aria-owns")].filter(Boolean).join(" ");
      for (const id of collapse(ids).split(" ")) {
        const list = id ? document.getElementById(id) : null;
        if (list) {
          for (const option of Array.from(list.querySelectorAll('[role="option"]'))) {
            labels.push(textOf(option, { names: true, budget: limits.name * 2, exclude: null }));
          }
        }
      }
    }
    return labels
      .map((label) => cut(collapse(label), limits.name))
      .filter((label) => label)
      .slice(0, limits.options);
  };
  const marked = [];
  const collect = (root) => {
    for (const item of Array.from(root.querySelectorAll("[" + attribute + "]"))) {
      marked.push(item);
    }
    for (const host of Array.from(root.querySelectorAll("*"))) {
      if (host.shadowRoot) {
        collect(host.shadowRoot);
      }
    }
  };
  collect(document);
  const body = document.body || document.documentElement;
  if (body) {
    visit(body, "none");
  }
  let kept = found;
  if (found.length > limits.elements) {
    const priority = (role) => (firstRoles.has(role) ? 0 : role === "heading" ? 1 : 2);
    kept = found
      .map((entry, position) => ({ entry, position }))
      .sort((left, right) => priority(left.entry.role) - priority(right.entry.role) || left.position - right.position)
      .slice(0, limits.elements)
      .sort((left, right) => left.position - right.position)
      .map((item) => item.entry);
  }
  const elements = kept.map((entry, index) => {
    const value = valueOf(entry.element, entry.role, entry.tag);
    return {
      index,
      role: entry.role,
      name: cut(nameOf(entry.element, entry.role, entry.tag), limits.name),
      value: value === null ? null : clip(value, limits.value),
      state: stateOf(entry.element, entry.role),
      options: optionsOf(entry.element, entry.role, entry.tag),
    };
  });
  const text = body ? cut(textOf(body, { names: false, budget: limits.text * 2, exclude: null }), limits.text) : "";
  for (const item of marked) {
    item.removeAttribute(attribute);
  }
  kept.forEach((entry, index) => entry.element.setAttribute(attribute, String(index)));
  return { url: String(location.href), title: collapse(document.title), text, elements };
}"""

_FIND: Final = r"""const find = (index) => {
    const selector = '[__ATTRIBUTE__="' + index + '"]';
    const search = (root) => {
      const direct = root.querySelector(selector);
      if (direct) {
        return direct;
      }
      for (const host of Array.from(root.querySelectorAll("*"))) {
        if (host.shadowRoot) {
          const inner = search(host.shadowRoot);
          if (inner) {
            return inner;
          }
        }
      }
      return null;
    };
    return search(document);
  };"""

_SCROLL_TEMPLATE: Final = r"""(index) => {
  __FIND__
  const element = find(index);
  if (!element) {
    return { found: false };
  }
  element.scrollIntoView({ block: "center", inline: "center", behavior: "instant" });
  return { found: true };
}"""

_RECT_TEMPLATE: Final = r"""(index) => {
  __FIND__
  const element = find(index);
  if (!element) {
    return { found: false };
  }
  const usable = (box) => box.width >= 2 && box.height >= 2;
  const first = (target) => Array.from(target.getClientRects()).find(usable) || null;
  let box = first(element);
  if (!box && element.labels) {
    for (const label of Array.from(element.labels)) {
      box = first(label);
      if (box) {
        break;
      }
    }
  }
  if (!box) {
    const whole = element.getBoundingClientRect();
    box = whole.width > 0 && whole.height > 0 ? whole : null;
  }
  if (!box) {
    return { found: true, visible: false };
  }
  const x = Math.min(Math.max(box.left + box.width / 2, 0), Math.max(window.innerWidth - 1, 0));
  const y = Math.min(Math.max(box.top + box.height / 2, 0), Math.max(window.innerHeight - 1, 0));
  return { found: true, visible: true, x: Math.round(x), y: Math.round(y) };
}"""

_FIELD_TEMPLATE: Final = r"""(index) => {
  __FIND__
  const element = find(index);
  if (!element) {
    return { found: false };
  }
  if (element.localName === "select") {
    return { found: true, kind: "select" };
  }
  const type = String(element.getAttribute("type") || "").toLowerCase();
  const scripted = ["range", "date", "time", "datetime-local", "month", "week", "color"];
  if (element.localName === "input" && scripted.includes(type)) {
    return { found: true, kind: "value" };
  }
  return { found: true, kind: "text" };
}"""

_FOCUS_TEMPLATE: Final = r"""(index) => {
  __FIND__
  const element = find(index);
  if (!element) {
    return { found: false };
  }
  const active = element.getRootNode().activeElement || document.activeElement;
  if (active !== element && !element.contains(active)) {
    element.focus();
  }
  if (typeof element.select === "function") {
    element.select();
  } else if (element.isContentEditable) {
    const range = document.createRange();
    range.selectNodeContents(element);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
  }
  return { found: true };
}"""

_VALUE_TEMPLATE: Final = r"""(index, value) => {
  __FIND__
  const element = find(index);
  if (!element) {
    return { found: false };
  }
  element.focus();
  const descriptor = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(element), "value");
  if (descriptor && descriptor.set) {
    descriptor.set.call(element, value);
  } else {
    element.value = value;
  }
  element.dispatchEvent(new Event("input", { bubbles: true }));
  element.dispatchEvent(new Event("change", { bubbles: true }));
  return { found: true, ok: element.value !== "" || value === "" };
}"""

_SELECT_TEMPLATE: Final = r"""(index, wanted) => {
  __FIND__
  const element = find(index);
  if (!element) {
    return { found: false };
  }
  if (element.localName !== "select") {
    return { found: true, ok: false, detail: "the element is not a list to choose from" };
  }
  const simple = (value) =>
    String(value ?? "").normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase().replace(/\s+/g, " ").trim();
  const target = simple(wanted);
  const options = Array.from(element.options).filter((option) => !option.disabled);
  const label = (option) => simple(option.label || option.textContent);
  const chosen =
    options.find((option) => label(option) === target) ||
    options.find((option) => label(option).startsWith(target)) ||
    options.find((option) => label(option).includes(target));
  if (!chosen) {
    return { found: true, ok: false, detail: "no option called " + JSON.stringify(String(wanted)) };
  }
  element.focus();
  element.value = chosen.value;
  if (element.selectedIndex !== chosen.index) {
    element.selectedIndex = chosen.index;
  }
  element.dispatchEvent(new Event("input", { bubbles: true }));
  element.dispatchEvent(new Event("change", { bubbles: true }));
  return { found: true, ok: true };
}"""


def _json(value: object) -> str:
    return json.dumps(value, separators=(",", ":"))


def _action(template: str) -> str:
    return template.replace("__FIND__", _FIND).replace("__ATTRIBUTE__", INDEX_ATTRIBUTE)


SNAPSHOT_SCRIPT: Final = (
    _SNAPSHOT_TEMPLATE.replace("__ROLE_OF__", _json(dict(ROLE_OF)))
    .replace("__TEXT_TAGS__", _json(list(TEXT_TAGS)))
    .replace("__FIRST_ROLES__", _json(list(FIRST_ROLES)))
    .replace("__LEAF_ROLES__", _json(list(LEAF_ROLES)))
    .replace("__BLOCK_ROLES__", _json(list(BLOCK_ROLES)))
    .replace("__CONTENT_ROLES__", _json(list(CONTENT_ROLES)))
    .replace(
        "__LIMITS__",
        _json(
            {
                "elements": MAX_SNAPSHOT_ELEMENTS,
                "text": MAX_SNAPSHOT_TEXT_LENGTH,
                "name": MAX_TARGET_NAME_LENGTH,
                "value": MAX_VALUE_LENGTH,
                "options": MAX_SNAPSHOT_OPTIONS,
            }
        ),
    )
    .replace("__ATTRIBUTE__", INDEX_ATTRIBUTE)
)
READY_SCRIPT: Final = "() => document.readyState"
SCROLL_SCRIPT: Final = _action(_SCROLL_TEMPLATE)
RECT_SCRIPT: Final = _action(_RECT_TEMPLATE)
FIELD_SCRIPT: Final = _action(_FIELD_TEMPLATE)
FOCUS_SCRIPT: Final = _action(_FOCUS_TEMPLATE)
VALUE_SCRIPT: Final = _action(_VALUE_TEMPLATE)
SELECT_SCRIPT: Final = _action(_SELECT_TEMPLATE)


def expression(script: str, *arguments: object) -> str:
    values = ", ".join(_json(argument) for argument in arguments)
    return f"JSON.stringify(({script})({values}))"
