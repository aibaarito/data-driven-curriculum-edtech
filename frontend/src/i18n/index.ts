import { ru } from "./ru";

// Localization-ready: add `en.ts` / `kk.ts` with the same shape and switch LOCALE.
export type Dictionary = typeof ru;
export type Locale = "ru";
const dictionaries: Record<Locale, Dictionary> = { ru };
export const LOCALE: Locale = "ru";
export const t: Dictionary = dictionaries[LOCALE];
