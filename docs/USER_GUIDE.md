# User guide

## Open and read
**File -> Open** (Ctrl+O), drag a PDF onto the window, or pick one from Home / Recent. Password-protected files ask for the password. Use the page panel (F4) for thumbnails and bookmarks, the search box (or Ctrl+F) to find text, and the view ribbon for zoom, rotation, layout, full screen (F11), print and document info.

## Annotate and edit
Choose **Edit** at the top. Pick a tool (highlight, underline, strikethrough, note, text box, pen, line, arrow, rectangle, ellipse, image, signature), set colour / size / opacity, then draw on the page. Click an annotation to move, restyle or delete it. **Undo / Redo** at any time.

Changes are kept in memory until you save. **Save** asks before replacing the original and keeps a backup of the previous version; **Save As** and **Save a copy** never touch the original; **Export flattened** burns annotations into the page.

## Replace or remove text
- **Replace text** removes the selected words and draws the new text at the same spot, in the same font, size and colour where the font is available (otherwise the closest match, which the dialog tells you). Words after it on the same line move along. This is not native editing, so paragraphs do not re-wrap; check the preview before applying.
- **Redact** permanently removes everything under the chosen area (or every occurrence of words you list). DocuCraft verifies the content is really gone. You can undo until you save.

## Pages
Right-click thumbnails or use the **Pages** menu: insert blank page, duplicate, rotate, delete, extract, replace from another PDF; drag thumbnails to reorder.

## Convert
**Convert -> PDF -> Word:** add one or many PDFs, optionally a page range (e.g. `1-3, 7`), choose *Preserve layout* or *Editable text*, then Convert. A report lists what was preserved and what may need checking. Scanned pages use OCR when Tesseract is available. **Word -> PDF** uses LibreOffice.

## Organise and secure
**Organize:** merge, split (by ranges / every page / groups), compress, images <-> PDF, extract text / images / pages. **Security:** add or remove a password (AES-256), sanitise, OCR.

## Settings
Output folders, default zoom and layout, render quality, OCR language, theme, interface scale, history (on / off / clear), autosave recovery, and *Delete all local data*.

## Shortcuts
Ctrl+O open · Ctrl+S save · Ctrl+Shift+S save as · Ctrl+W close tab · Ctrl+Tab next tab · Ctrl+Z / Ctrl+Y undo / redo · F4 page panel · F11 full screen · Esc leave full screen
