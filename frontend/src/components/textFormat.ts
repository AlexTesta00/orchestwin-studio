import type { Ref } from "vue";

export function fill(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (_match, key: string) => String(values[key] ?? ""));
}

export function plural(count: number, forms: readonly [string, string]): string {
  return fill(count === 1 ? forms[0] : forms[1], { count });
}

export function commandParts(text: string): { key: number; text: string; command: boolean }[] {
  return text
    .split("`")
    .map((part, index) => ({ key: index, text: part, command: index % 2 === 1 }))
    .filter((part) => part.text.length > 0);
}

export function formatDateTime(value: string, locale: string): string {
  return new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(
    new Date(value),
  );
}

export function formatDate(value: string, locale: string): string {
  return Number.isNaN(new Date(value).getTime()) ? value : formatDateTime(value, locale);
}

export function confidence(value: number, locale: string): string {
  return new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 0 }).format(
    value,
  );
}

export function compareCodes(left: string, right: string, locale: string): number {
  return left.localeCompare(right, locale, { numeric: true, sensitivity: "base" });
}

export function moveTabFocus(
  event: KeyboardEvent,
  focusIndex: Ref<number>,
  count: number,
  tablist: HTMLElement | null,
): void {
  const targets: Record<string, number> = {
    ArrowRight: focusIndex.value + 1,
    ArrowLeft: focusIndex.value - 1,
    Home: 0,
    End: count - 1,
  };
  const target = targets[event.key];
  if (target === undefined || count === 0) {
    return;
  }
  event.preventDefault();
  focusIndex.value = (target + count) % count;
  tablist?.querySelectorAll<HTMLElement>("[role='tab']")[focusIndex.value]?.focus();
}
