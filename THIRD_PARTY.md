# Bundled components

Original Data Sorter code uses the MIT licence. The assets under `web/vendor/` retain their upstream licences. The build embeds the notices in the portable HTML and writes a text copy beside the website.

| Component | Version | Use and licence |
| --- | --- | --- |
| [PDF.js](https://github.com/mozilla/pdf.js) | 6.5.438 | PDF renderer. Apache-2.0. Fonts, colour profiles, CMaps and decoder licences are retained alongside the assets. |
| [Daikon](https://github.com/rii-mango/Daikon) | 1.2.46 | DICOM parsing and decoding. BSD-3-Clause, with bundled codec notices in the distributed script. |
| [fflate](https://github.com/101arrowz/fflate) | 0.8.3 | Reads the DOCX archive. MIT. |
| [Lucide](https://lucide.dev/license) | 1.79.0 | Interface icons. ISC and MIT notices travel with the distribution. |
| [Liberation Sans](https://github.com/liberationfonts/liberation-fonts/releases/tag/2.1.5) | 2.1.5 | PDF font fallback. SIL Open Font License 1.1. |

The PDF.js build adapts the worker entry point to run from both hosted and local HTML. The upstream files in the repository remain intact apart from substituting the four Liberation Sans fonts with their separately sourced SIL OFL versions. `scripts/fetch_vendor.py` records the sources and verification method.
