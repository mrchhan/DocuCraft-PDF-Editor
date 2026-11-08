# PyInstaller spec - build with:  python scripts/build_windows.py   (or: pyinstaller docucraft.spec --noconfirm)
# One-folder build (faster start-up and fewer antivirus false positives than one-file).
from pathlib import Path

ROOT = Path(SPECPATH)
datas = []
if (ROOT / "assets").is_dir():
    datas.append((str(ROOT / "assets"), "assets"))
# Optional: bundle Tesseract OCR. Put a Tesseract install under vendor/tesseract (tesseract.exe + tessdata/).
vendor = ROOT / "vendor" / "tesseract"
if vendor.is_dir():
    datas.append((str(vendor), "tesseract"))

a = Analysis(
    ["main.py"],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=["pdf2docx", "docx", "PIL.Image", "reportlab.pdfgen.canvas", "pytesseract"],
    excludes=["tkinter", "matplotlib", "IPython", "pytest", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
              "PySide6.Qt3DCore", "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtMultimedia"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="DocuCraft", console=False,
          icon=str(ROOT / "assets" / "icons" / "docucraft.ico"), upx=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="DocuCraft")
