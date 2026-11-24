# Data Sorter

Data Sorter is a browser app for reviewing local files and sorting them into category folders. It previews JPEG, PNG, DICOM, PDF, DOCX, TXT and CSV. The browser processes files locally.

## Use Data Sorter

Open the [Data Sorter website](https://kavehsame.github.io/data-sorter/) in current desktop Chrome or Edge. The [user guide](https://kavehsame.github.io/data-sorter/guide.html) covers local folders, shortcuts and resuming a session. For a portable copy, extract the [offline ZIP](https://github.com/kavehsame/data-sorter/releases/latest/download/data-sorter-offline.zip) and open `Data Sorter.html`.

1. Choose an input folder and an output folder. Data Sorter scans the input recursively and skips the selected output folder.
2. Select **Copy** or **Move**, enter category names and assign a shortcut to each category.
3. Click **Start sorting**. Use the category buttons or shortcuts to sort, the arrow keys to navigate and Ctrl+Z or Command+Z to undo.
4. Click **Export CSV** to save the session in the output folder. To continue later, import `data_sorter_results.csv` and select the current folder locations.

Move mode requires write access to the input folder. The browser prompts for local folder access. Zoom carries across previews. The file list follows the active file and keeps up to four undecided files in view where space permits.

DICOM shows the first frame and supports common transfer syntaxes. DOCX preview extracts text. Session CSVs retain exact path and category text. When opening a session CSV in a spreadsheet, import its columns as text.

## Build and serve

Run `python -B -m scripts.build_site` with Python 3.13 or newer. The build uses the checked-in libraries and needs no downloads. It writes the Pages site to `dist/pages/` and the ZIP and checksum to `dist/release/`.

Serve the contents of `dist/pages/` at an HTTPS address. Open the app and wait for **Offline ready**. Bookmark the app page to return to it offline.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for tests and linting, [AGENTS.md](AGENTS.md) for the maintainer handover and [SECURITY.md](SECURITY.md) for reporting guidance. The [validation report](docs/validation.md) records the checks run before handover.

The [MIT licence](LICENSE) applies to original Data Sorter source. [Bundled components](THIRD_PARTY.md) retain their own licences.
