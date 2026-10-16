# Reverse file browser — v1.0 — 2026-10-13

The package is now an expandable root with lazy folders for app code, libraries,
resources/Manifest, low-level instructions and files requiring review. Clicking a
file reads only an indexed path in the current lab's recorded run and displays
plain text in the workspace. Binary artifacts use a bounded hex preview. Large
files show a limited preview and offer the full ZIP export.

Analysis records persist per lab and package, allowing reload without rerunning
analysis. After partial Java reconstruction, HuntMob also runs the embedded
engine in fallback instruction mode. A successful fallback is separately reported;
it never changes the original Java result to complete. Engine error counts and
files containing un-reconstructed methods are different indicators.

## Validated on InsecureBankv2

- Java reconstruction: partial, two reported engine errors.
- Main app: 14 generated Java files; libraries: 2978 Java files.
- Resources: 676 files.
- Fallback instruction mode: successful, 2992 files.
- Export: 6660 files plus analysis metadata; ZIP verified through HTTP.
- Browser: BuildConfig.java opened in the reader; Manifest endpoint returned XML.
- 90 Python tests; JavaScript syntax and whitespace checks passed.

Tests verify text/binary previews, ZIP contents, run IDs, path traversal and
symlink escape rejection. This is read-only source inspection, not confirmation
of vulnerabilities or a guarantee of correct source reconstruction.

Changes are local; no commit or push. Previously assembled release wheels do not
include this new browser yet and must be rebuilt before distribution.
