# Publishing DocuCraft on GitHub

1. **Create the repository** named `DocuCraft-PDF-Editor` (public, no template files; the repo already has a README, LICENSE and .gitignore).
2. **Repository link:** `https://github.com/mrchhan/DocuCraft-PDF-Editor` is already used in the README, docs and the app's About link.
3. **Push** from the project folder:
   ```
   git init
   git add .
   git commit -m "DocuCraft v0.1.3"
   git branch -M main
   git remote add origin https://github.com/<you>/DocuCraft-PDF-Editor.git
   git push -u origin main
   ```
4. **About box:** paste the text from `marketing/github_description.md` and add topics: `pdf`, `pdf-editor`, `pdf-to-word`, `pyside6`, `pymupdf`, `python`, `offline`, `privacy`, `windows`, `open-source`.
5. **Social preview:** *Settings → General → Social preview* → upload `marketing/media/github-social-preview.png`.
6. **Release v0.1.3:** *Releases → Draft a new release*, tag `v0.1.3`, paste the 0.1.3 entry from `CHANGELOG.md`, attach `DocuCraft-Setup-*.exe` from `dist/installer` once you have built and tested it. Mark it *pre-release* until it has been tested on a clean Windows PC.
7. **CI:** the workflow in `.github/workflows/build.yml` runs on push; check that it is green.
