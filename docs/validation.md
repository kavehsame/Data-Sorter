# Data Sorter validation

Local validation ran on 24 November 2026 using Darwin 27.0.0 arm64, Python 3.13.9, Node v24.22.3.

## Results

| Check | Result |
| --- | --- |
| Python lint and format | Ruff returned exit status 0 for both checks. |
| JavaScript | Node parsed the sources. Oxlint returned exit status 0 with warnings treated as errors. |
| Unit tests | 40 passed. 0 failures, 0 errors and 0 skips. |
| Chrome offline checks | 43 checkpoints passed and the console error check passed. |
| Build | The standalone page and website page have identical bytes. The service worker embeds their SHA-256 checksum. |

The unit tests cover CSV parsing and legacy path compatibility, category validation, recursive scanning, destination collisions, copy and move transitions, undo, failed writes and rollback. They also check deterministic builds, the content security policy and service worker cache integrity.

The browser checks use synthetic files. The cached site reopens after the loopback server stops. JPEG, PNG, PDF, DOCX, TXT, CSV, uncompressed DICOM and RLE DICOM previews were exercised. The checks cover PDF zoom, pan and scrolling, category shortcuts, copy, move, undo, CSV restore and file-list scrolling.

## Review findings addressed

- When a CSV mixed existing Copy decisions with Move mode, reclassification could leave a stale copy behind. The sorter now removes the superseded copy after validating the new destination. If source removal fails, it restores the previous copy before cleaning up the new file.
- Rollback now checks the identity and metadata of a staged file before removing it. This reduces the risk of removing a file changed during recovery.
- A missing old category folder is handled consistently when reclassifying a copied file. Reclassification of the final file in Move mode refreshes its preview.
- The offline cache uses a portable conversion for digest bytes. The build uses the OFL release of Liberation Sans and preserves the upstream notices. Linting flagged control character validation, shadowed names and worker listener style. Those changes were checked against the unit and browser tests.

## Limits

The browser tests supply folder handles in place of the native folder picker. Chrome was tested on macOS. Edge, other operating systems, additional DICOM transfer syntaxes and concurrent external filesystem edits require their own checks. GitHub Actions configuration is included for a future run. The review did not include a comprehensive third-party security audit.

Reproduce from repository root with `python -B scripts/validate.py`. It writes raw reports to `.checks/reports/`.
