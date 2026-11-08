# LinkedIn announcement (ready to post)

I just open-sourced **DocuCraft** — a free desktop app to read, annotate, secure and convert PDFs, including PDF → Word.

The idea: **Your Documents. Your Control.**
Everything runs on your own computer. No account, no upload, no tracking.

What it does today (v0.1 preview):
• Read PDFs with tabs, thumbnails, bookmarks and search
• Highlight, comment, draw, add text, images and signatures — with undo/redo
• Real redaction (the content is removed from the file, then verified — not a black box)
• PDF → Word with a report of what was and wasn't preserved, OCR for scans, batch mode
• Merge, split, compress, images ↔ PDF, password protection (AES-256)
• Every file it writes carries a small Shadow Creative Studio mark

What I want to be upfront about:
• PDF → Word is never 100% perfect — complex layouts may need touching up
• Windows download is a portable zip (unzip and run), not yet code-signed, so SmartScreen may warn. It is a pre-release while I test it on more PCs
• It's AGPL-3.0 (driven by the PyMuPDF engine)

Built with Python, PySide6 and PyMuPDF, with an automated test suite and a self-testing packaged build.

Code, screenshots and docs: https://github.com/mrchhan/DocuCraft-PDF-Editor
Windows download (v0.1.3 pre-release): https://github.com/mrchhan/DocuCraft-PDF-Editor/releases/tag/v0.1.3
I'd love feedback — what would make this your daily PDF tool? Bug reports and ideas are very welcome.

#OpenSource #Python #PDF #Privacy #Productivity #DesktopApps #PySide6

---
## Publishing checklist

**Media (all in `marketing/media/`)**
- `docucraft-demo.mp4`: 63 s, 1080p, captions burned in, works muted. Upload it directly to the LinkedIn post (best reach).
- `linkedin-card.png`: use as the cover image if you post an image instead of the video, or as the article/banner image.
- `before-after-replace.png`: good second image or a follow-up comment.
- `feature-overview.png`: a feature summary for a carousel or comment.
- `docucraft-demo-preview.gif`: used in the README.
- `github-social-preview.png`: upload under GitHub *Settings → Social preview*.

**Steps**
1. Repo link in this project is already set to `https://github.com/mrchhan/DocuCraft-PDF-Editor`; check it opens.
2. Done: repo and v0.1.3 pre-release are published with the portable zip. Test the zip on one other PC if you can.
3. Links in the post above are final.
4. Post the text with the video attached. Put the link in the first comment if you want better reach.
5. Reply to every comment in the first hour.

**Do not post** claims you have not checked: no accuracy percentages, and do not say the installer is tested until you have tested it.
