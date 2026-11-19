# UI languages

The browser UI supports English and German. The top-bar selector stores the
preference as `heist-language` in localStorage. Without a saved preference,
German browser locales select German; other locales select English. The
document `lang` attribute follows the selection. Translation support uses React
context without an additional runtime dependency.

`LanguageProvider` and `useI18n` live in `frontend/src/lib/i18n.tsx`. Components
call `const { t } = useI18n()` and render `t('common.actions.edit')`. The explicit
English catalog is `frontend/src/lib/messages/en.ts`; its `MessageKey` type
defines the accepted semantic identifiers. `de.ts` must satisfy the identical
key set. Keep keys stable when wording changes. Add both catalog entries in the
same change. Type checking rejects unknown keys, and tests verify matching keys,
placeholder parity and interpolation. Keys describe intent, for example
`authoring.edit.drainInstructions` or `grading.exportMoodle`.

Use named placeholders rather than variables inside keys:

```tsx
t('users.confirmUsername', { username: user.username })
```

Translations return plain text rendered by React. Do not insert translated
HTML. Switching language updates context without remounting forms, preserving
unsaved input.

Translate labels, never protocol values. `localizedValues.ts` maps known domain
codes such as `READY` to semantic message keys. String select options keep their
values and use that explicit mapping for captions. `[value, label]` options preserve the
supplied label: translate static placeholders explicitly and keep exercise
names and filenames unchanged.

Exercise names, descriptions, hints, solutions, student input, commands, network
names, URLs and identifiers retain their authored content. This feature does
not create translated exercise variants. Legal documents retain their reviewed
German text and declare `lang="de"`. Host diagnostic evidence and unknown server
messages retain their source text; known legacy API errors have an explicit
compatibility map. There is no general English-text-to-key lookup.

All frontend source and supported configuration files use Prettier, pinned as
a development-only dependency. Run `npm --prefix frontend run format` after
editing. `npm --prefix frontend run format:check` verifies formatting without
changing files. It is included in `npm run check`, so the existing CI frontend
gate enforces it. Generated output (`dist`, `coverage`, `.vite`) and
`node_modules` are excluded.

Run `npm --prefix frontend run check` and `npm --prefix frontend run build`, then
the browser suites in `docs/testing/UI-VERIFICATION.md`. Browser acceptance
checks language persistence, German mobile layouts, unchanged exercise/flag
values and preservation of unsaved input. Regenerate documentation screenshots
after changing UI messages.
