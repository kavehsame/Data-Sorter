# Security

Report security issues privately to the repository maintainer. Include the browser version, a minimal reproduction and any relevant error messages. Use synthetic or de-identified files. Keep private file paths, DICOM metadata and session CSVs out of public reports.

The app runs as static HTML and JavaScript in the browser. It does not provide an upload endpoint. The page blocks network connections using its content security policy. The website's service worker fetches the application page for offline setup. The browser mediates local folder access.
