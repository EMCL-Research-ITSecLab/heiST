import { german } from './messages/de.ts';
import { english, type MessageKey } from './messages/en.ts';
export type Language = 'en' | 'de';
export type Values = Record<string, string | number>;

/** Semantic keys are checked at compile time; interpolation always returns plain text. */
export function translate(language: Language, key: MessageKey, values: Values = {}): string {
  const output = Object.hasOwn(english, key)
    ? language === 'de'
      ? (german[key] ?? english[key])
      : english[key]
    : key;
  return output.replace(/\{([a-zA-Z_]+)\}/g, (placeholder, name) =>
    Object.hasOwn(values, name) ? String(values[name]) : placeholder,
  );
}
