# Data Sorter

Data Sorter is a browser app for reviewing local files and sorting them into category folders. It previews JPEG, PNG, DICOM, PDF, DOCX, TXT and CSV. The browser processes files locally.

## Use Data Sorter

Open `Data Sorter.html` in current desktop Chrome or Edge. The standalone file includes the app and its libraries and works offline. The downloadable build is named **data-sorter-offline** in the repository's Actions workflow.

1. Choose an input folder and an output folder. Data Sorter scans the input recursively and skips the selected output folder.
2. Select **Copy** or **Move**, enter category names and assign a shortcut to each category.
3. Click **Start sorting**. Use the category buttons or shortcuts to sort, the arrow keys to navigate and Ctrl+Z or Command+Z to undo.
4. Click **Export CSV** to save the session in the output folder. To continue later, import `data_sorter_results.csv` and select the current folder locations.

Move mode requires write access to the input folder. The browser prompts for local folder access. Zoom carries across previews. The file list follows the active file and keeps up to four undecided files in view where space permits.

DICOM shows the first frame and supports common transfer syntaxes. DOCX preview extracts text. Session CSVs retain exact path and category text. When opening a session CSV in a spreadsheet, import its columns as text.

## Build and serve

Run `python -B scripts/build.py` with Python 3.13 or newer. The build uses the checked-in libraries and needs no downloads. It writes `dist/Data Sorter.html` and `dist/website/`.

Serve the contents of `dist/website/` at an HTTPS address to use the offline cache. Wait for **Offline ready** on first access. Return to the same URL offline. The portable HTML remains available if the browser clears its site cache.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for tests and linting, [AGENTS.md](AGENTS.md) for the maintainer handover and [SECURITY.md](SECURITY.md) for reporting guidance. The [validation report](docs/validation.md) records the checks run before handover.

The [MIT licence](LICENSE) applies to original Data Sorter source. [Bundled components](THIRD_PARTY.md) retain their own licences.
