# UI languages

The browser UI supports English and German. The top-bar selector stores the
preference as `heist-language` in localStorage. Without a saved preference,
German browser locales select German; other locales select English. The
document `lang` attribute follows the selection. No new dependency is required.

`LanguageProvider` and `useI18n` live in `frontend/src/lib/i18n.tsx`. Components
call `const {t}=useI18n()` and render `t('English source message')`. English
source messages are keys in `frontend/src/lib/messages/de.ts`. Missing messages
retain their English text. Keep keys stable and add the German entry in the
same change. Frontend tests check static messages, fallback and interpolation.

Use named placeholders rather than variables inside keys:

```tsx
t('Type {username} to confirm', {username: user.username})
```

Translations return plain text rendered by React. Do not insert translated
HTML. Switching language updates context without remounting forms, preserving
unsaved input.

Translate labels, never protocol values. String select options keep their
values and translate captions. Explicit `[value, label]` options preserve the
supplied label: translate static placeholders explicitly and keep exercise
names and filenames unchanged.

Exercise names, descriptions, hints, solutions, student input, commands, network
names, URLs and identifiers retain their authored content. This feature does
not create translated exercise variants. Legal documents retain their reviewed
German text and declare `lang="de"`. Host diagnostic evidence and unknown server
messages retain their source text; known UI errors have catalog entries.

Run `npm --prefix frontend run check` and `npm --prefix frontend run build`, then
the browser suites in `docs/testing/UI-VERIFICATION.md`. Browser acceptance
checks language persistence, German mobile layouts, unchanged exercise/flag
values and preservation of unsaved input. Regenerate documentation screenshots
after changing UI messages.
