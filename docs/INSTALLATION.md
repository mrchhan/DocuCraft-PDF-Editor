# Installation

## Windows (installer)
1. Download `DocuCraft-Setup-<version>.exe` from the Releases page.
2. Run it. It installs per-user by default (no administrator rights needed) and can optionally add a desktop shortcut and offer DocuCraft as a PDF viewer.
3. Windows SmartScreen may warn about an unknown publisher because the installer is **not code-signed** yet. Code signing needs a paid certificate; until then verify the download came from the project's Releases page.

Your data (settings, history, logs) is in `%APPDATA%\DocuCraft` and is not removed on uninstall. Delete the folder, or use Settings -> About -> *Delete all local data*, to remove it.

## From source (Windows, macOS, Linux)
Requires Python 3.11-3.13.
```bash
git clone https://github.com/your-username/DocuCraft-PDF-Editor.git
cd DocuCraft-PDF-Editor
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

## Optional components
- **OCR (scanned PDFs):** install [Tesseract](https://github.com/UB-Mannheim/tesseract/wiki) and restart DocuCraft, or place a Tesseract folder at `vendor/tesseract` before building so it is bundled.
- **Word -> PDF:** install [LibreOffice](https://www.libreoffice.org/). DocuCraft finds it automatically.

## Build the Windows installer yourself
```powershell
pip install -r requirements-dev.txt
python scripts/build_windows.py --installer     # needs Inno Setup 6 or 7
```
The script runs the tests, builds with PyInstaller, runs a packaged self-test, then builds the installer into `dist/installer/`.

## Without an installer (portable zip)
`python scripts\build_windows.py --skip-tests` also writes `dist\DocuCraft-<version>-windows-portable.zip`. Unzip it anywhere and double-click `DocuCraft.exe`. No Python and no Inno Setup are needed. This is also the easiest file to attach to a GitHub release.
