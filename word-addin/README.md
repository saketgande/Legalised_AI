# Frontdoor Word add-in

Redline a counterparty's NDA against your playbook **inside Word** — the task
pane reads the open document, runs it through the same inbound redline engine the
web app uses, and inserts the proposed edits as **tracked changes**.

The task pane is a page in the Next app (`/word-addin`); this folder only holds
the Office manifest that points Word at it.

## How it works
1. Sign in (same accounts as the web app) in the task pane.
2. Click **Review this document** — the add-in reads the document text via
   Office.js (`Word.run` → `body.text`), POSTs it to `/api/requests/inbound`, and
   shows the deviations + missing clauses.
3. Click **Insert as tracked change** on any finding — the add-in turns on
   `changeTrackingMode = trackAll`, searches for the clause, and replaces it (or
   appends a missing clause), so every edit lands as a reviewable tracked change.

> Outside Word (a normal browser), the page falls back to a paste box so you can
> preview it — the "insert" buttons are disabled since there's no document.

## Sideload it
1. Deploy the frontend (the manifest's `SourceLocation` points at
   `https://legalised-web.onrender.com/word-addin` — change it if you host
   elsewhere) and add `addin-icon-32.png` / `addin-icon-80.png` to the frontend's
   `public/` (any 32px / 80px PNG), or edit the icon URLs.
2. **Word on the web:** Insert → Add-ins → Upload My Add-in → pick `manifest.xml`.
   **Word desktop (Mac):** copy `manifest.xml` into
   `~/Library/Containers/com.microsoft.Word/Data/Documents/wef/`.
   **Word desktop (Windows):** put `manifest.xml` on a
   [shared folder catalog](https://learn.microsoft.com/office/dev/add-ins/testing/create-a-network-shared-folder-catalog-for-task-pane-and-content-add-ins)
   and trust it, then Insert → My Add-ins → Shared Folder.
3. Open the add-in from the Home ribbon → **Frontdoor Redline**.

## Known limits (skeleton)
- Word `search` matches within a paragraph and caps the query length, so a very
  long or multi-paragraph clause falls back to appending the redline rather than
  in-place replacement.
- The manifest is unsigned dev sideload; production would go through
  [AppSource / centralized deployment](https://learn.microsoft.com/office/dev/add-ins/publish/publish).
