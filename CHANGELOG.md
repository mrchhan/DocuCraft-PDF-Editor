# Changelog

## 0.1.4
- Print preview: *File → Print preview…*, the toolbar button or Ctrl+Shift+P shows the pages as they will print (edits included) before you print. Ctrl+P still prints directly.
- Printing and preview no longer freeze or crash if the printer reports a problem; a message is shown instead.
- New tests for printing to a PDF printer and for the preview (120 total).

## 0.1.3
- Contact number written in international format (+923363330884) everywhere.
- Faint Shadow emblem watermark over every screen of the application (ignores the mouse, does not affect anything underneath).

## 0.1.2 - Shadow branding and watermark
- Shadow Creative Studio logo built into the app (window icon, header, Home, About) with integrity checks; maker contact details in the footer.
- Watermark on everything DocuCraft writes: PDF pages (centre emblem + footer line), Word footers, exported page images. Saving twice never stamps twice; rotated pages are handled.
- Recent Documents: select several with Ctrl/Shift or *Select all*, then *Remove selected*; right-click a document on Home to remove it. Files on disk are never touched.
- New tests for branding and watermarking (115 total); the packaged self-test now checks branding.

## 0.1.1 - text replacement that matches the document
- Replace text now keeps the original font, size, colour and baseline: it reuses the document's own embedded font, then an installed or bundled font of the same family, then a built-in match.
- Only the words you select are replaced (a sloppy selection no longer erases text on the line below), and the rest of the line moves so spacing stays natural.
- Bundled open-licence fonts (Inter, Poppins, Liberation, Carlito) for faithful results on machines without the original font.
- Fixed: closing a document no longer crashes late UI events; undo back to the saved state clears the modified mark; invalid PDFs show a message in Convert.

## 0.1.0 - first public preview
- PDF reader: tabs, thumbnails, bookmarks, search, zoom/fit, rotate, single / continuous / two-page layouts, full screen, print, document info, drag and drop, lazy rendering.
- Editor: highlight / underline / strikethrough, notes, text boxes, freehand, lines, arrows, rectangles, ellipses, images, signatures, page tools (insert, delete, duplicate, rotate, reorder, extract, replace), unlimited-depth undo / redo, existing-text replacement (redaction + overlay, labelled as such), true redaction with verification.
- Safe saving: never overwrites without confirmation, backup of the previous version, Save As, Save a copy, flattened export.
- PDF -> Word (layout / editable modes, page ranges, images, tables, OCR for scans, conversion report), Word -> PDF (via LibreOffice), batch conversion.
- Organise: merge, split, compress, images <-> PDF, extract text / images / pages, metadata.
- Security: AES-256 passwords, sanitise, secure temp folders, input validation, resource limits.
- Settings, history, favourites, crash recovery, light / dark themes, no telemetry.
