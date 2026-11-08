# Frequently asked questions

**1. Is DocuCraft really free, and does it upload my files?**
Yes, it is free and open source (AGPL-3.0-or-later). Everything runs on your own computer. There is no account, no upload and no telemetry. The app does not need an internet connection to read, edit, redact, merge, split, secure or convert PDFs.

**2. Which systems does it run on?**
The ready-made download is for Windows 10 and 11. Download the portable zip from the Releases page, extract it (right-click, Extract All) and run `DocuCraft.exe`. There is no installer to run. You can also run it from source on other systems, but only Windows builds are provided and tested. There is no phone or tablet version.

**3. Windows shows a SmartScreen warning. Is the app safe?**
The app is not code-signed yet, because a signing certificate costs money. Windows therefore warns about unknown publishers. Click "More info", then "Run anyway". The full source code is public in this repository, so you can read it or build the app yourself.

**4. How good is the PDF to Word conversion?**
It produces an editable .docx file offline, and a report lists what may need checking. Simple documents convert well. Complex layouts, such as many columns, overlapping objects or unusual fonts, may need touching up in Word. No converter is perfect, so please check the result before sending it on.

**5. Can it convert scanned PDFs or Word files to PDF?**
Scanned pages need OCR, which uses the free Tesseract program. Install it separately and DocuCraft will use it. Converting Word to PDF needs LibreOffice installed on the computer. Without these two programs, the other features still work.

**6. Is redaction really permanent?**
Redaction removes the underlying text and image pixels under the marked area, not just a black box on top. After saving, the app checks that the redacted text is gone from the file. Keep your original, because a redacted file cannot be undone.

**7. Why do my saved files carry a small "Made with DocuCraft" mark?**
Files written by the app include a faint Shadow Creative Studio emblem and a footer line with the creator's contact details. The source code is public under AGPL, so anyone who builds their own version can change this.

**8. Can DocuCraft remove a password I have forgotten?**
No. It can add a password (AES-256) and remove one from a file you own when you enter the correct password. It does not guess or crack passwords.

**9. How do I report a bug or suggest a feature?**
Open an issue on the GitHub page for this repository (the Issues tab) and describe what happened. If you can, include your Windows version and the steps that cause the problem. Please do not attach private documents.

**10. Who made DocuCraft?**
DocuCraft is made by Hassan Malik of Shadow Creative Studio, +923363330884, hassanmalik.net@gmail.com.
