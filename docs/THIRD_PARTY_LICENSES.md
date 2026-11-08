# Third-party components and licence review

| Component | Used for | Licence | Notes |
|---|---|---|---|
| PySide6 / Qt | GUI | LGPL-3.0 | Dynamically linked; replaceable. |
| PyMuPDF / MuPDF | Rendering, editing, redaction | **AGPL-3.0** (or commercial from Artifex) | Reason DocuCraft is AGPL-3.0-or-later. |
| pdf2docx | PDF -> Word layout engine | MIT | |
| python-docx | Word files | MIT | |
| Pillow | Images | MIT-CMU | |
| ReportLab | Image -> PDF helpers | BSD | |
| pytesseract + Tesseract OCR | OCR (optional bundle) | Apache-2.0 | Language data under Apache-2.0. |
| LibreOffice | Word -> PDF (optional, installed separately) | MPL-2.0 | Not bundled; called as a separate program. |
| Inter, Poppins, Liberation fonts, Carlito | Re-creating replaced text (bundled in `assets/fonts`) | SIL OFL-1.1 | Licence texts in `assets/fonts/licenses/`. |
| PyInstaller / Inno Setup | Packaging only | GPL-2.0+ with bootloader exception / Inno licence | Not part of the shipped code. |

**What this means:** because PyMuPDF is AGPL, DocuCraft is published under AGPL-3.0-or-later and its source must stay available to anyone who receives the app. If you want to ship a closed-source or commercial derivative, you need a commercial PyMuPDF licence from Artifex or a different PDF engine. This is a summary, not legal advice - have a lawyer review before commercial distribution. Re-check licences when you update dependencies.
