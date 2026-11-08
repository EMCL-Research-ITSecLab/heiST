# Documentation assets

- `screenshots/`: generated full-page UI captures and their source/checksum manifest.
- `legal-sources.json`: provenance for the copied operator legal pages.

Application logos, avatars and default challenge images have one maintained source
under `frontend/public/assets/`. The documentation links to those files directly.
Regenerate screenshots with `python tools/testing/screenshots.py`; do not manually
retouch captures. See [UI verification](../docs/testing/UI-VERIFICATION.md).
