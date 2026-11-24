# Maintainer handover

## Layout

- `web/session.js` scans folders, validates and serialises sessions, writes category files and records undo history.
- `web/app.js` connects the UI to folder permissions and the active session. `web/preview.js` manages zoom, pan and previews. `web/dicom_worker.js` decodes the first DICOM frame separately.
- `web/index.template.html` and `web/style.css` define the workspace. `scripts/build.py` embeds resources and produces the content security policy and the two release formats.
- `web/offline.template.js` verifies the complete HTML against the build hash before caching it. File bytes, filenames and session data stay outside the cache.

## Invariants

- Maintain the version 1 session CSV fields. Restore relative paths under selected handles and validate them before filesystem access. A restore starts with empty undo history.
- Never overwrite an existing category file. Verify a move destination before deleting the source. On failure, retain the source or a verified copy and surface incomplete rollback to the user.
- Keep the page independent of runtime requests. PDF fonts, CMaps, codecs and worker code are bundled. Test PDF rendering both from `file:` and from a cached HTTP or HTTPS address.
- Treat all input paths and document contents as private. Use synthetic fixtures in tests and reports. Keep browser profiles, data, build products and test artefacts out of repository history.

## Changes

Use Python 3.13 and Node 24 for development. Follow [CONTRIBUTING.md](CONTRIBUTING.md) before packaging. Review [THIRD_PARTY.md](THIRD_PARTY.md) when changing a bundled component. The PDF.js worker transformation assumes the pinned upstream worker entry point and fails if that entry point changes. Keep the preview smoke test passing before updating its pin.

Oxlint checks the assembled application inside its private function scope. Keep helpers there so they do not become browser globals. The DICOM worker uses a transferable buffer in its `postMessage` call. Its second argument is the transfer list.
