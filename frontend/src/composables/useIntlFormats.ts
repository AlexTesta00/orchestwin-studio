import { computed, toValue, type MaybeRefOrGetter } from "vue";

export function useIntlFormats(locale: MaybeRefOrGetter<string>) {
  const dateFormat = computed(
    () => new Intl.DateTimeFormat(toValue(locale), { dateStyle: "medium", timeStyle: "short" }),
  );
  const listFormat = computed(
    () => new Intl.ListFormat(toValue(locale), { style: "long", type: "conjunction" }),
  );
  return { dateFormat, listFormat };
}
