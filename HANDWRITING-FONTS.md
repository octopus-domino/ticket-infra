# Handwriting in shared albums and cards

Fonts are bundled locally for reproducible PDFs and no external font requests:

| Font | Coverage | Upstream | SHA-256 of bundled TTF |
| --- | --- | --- | --- |
| Marck Script | Cyrillic, Latin, Latin extended | https://github.com/google/fonts/tree/main/ofl/marckscript | `504de8cc6f919163bc9afb67b9bc208d258230c5e8d00cb82ec52474f9fafc3b` |
| Zhi Mang Xing | Simplified Chinese, Latin | https://github.com/google/fonts/tree/main/ofl/zhimangxing | `644e0cae9b40f0b10ab729a01bd32032e3973bac22be3dccae01bf6ae7fde969` |

Both use SIL OFL 1.1. Unmodified font files and their complete copyright/licence
notices live under `ticket-pdf/src/main/resources/fonts/`. Do not remove licence
files from distributions. Fonts are subset-embedded into PDFs by FOP. Browser
previews load only faces present in the actual SVG.

The album uses the common native constructor template and `photos` data array,
four photos per repeated page. Captions, contributors, images and handwriting
font are model values. Optional text fitting is performed after model binding;
it preserves page geometry and rejects text that cannot fit at its minimum size.

Zhi Mang Xing does not cover arbitrary Cyrillic/Chinese mixtures within a single
caption. Separate captions in the nine UI languages are supported. Do not claim
complete Unicode coverage, and verify glyph coverage when adding other scripts.
