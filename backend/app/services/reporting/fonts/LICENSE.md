# Fonts bundled with the REMAS report

These files are redistributed with the application so a report renders
identically on any host and without outbound network access. Both families are
licensed under the **SIL Open Font License 1.1**, which permits bundling,
embedding in documents, and redistribution as part of a larger work.

| Family | Upstream | Licence |
| --- | --- | --- |
| IBM Plex Sans Arabic | https://github.com/IBM/plex | SIL OFL 1.1 |
| IBM Plex Mono | https://github.com/IBM/plex | SIL OFL 1.1 |
| Readex Pro | https://github.com/ThomasJockin/readexpro | SIL OFL 1.1 |

Full licence text: <https://openfontlicense.org/open-font-license-official-text/>

## What is here, and why these files

`manifest.json` records every face with the `unicode-range` it was subset for.
The files are Google Fonts' per-script subsets, and **both the `arabic` and
`latin` subsets are kept for every weight** — the report is bilingual, and
keeping only the larger subset per weight silently leaves the English edition
in a fallback face.

Only the weights the report stylesheet actually asks for (400/500/600) are
bundled. Adding more is payload with no visible effect.

## Regenerating

The faces are static masters. Google serves a *variable* instance when several
weights are requested in one URL; against that baseline these files lay out
identically (same advance widths, same line breaks) and differ only in edge
antialiasing — measured at 0.19% of pixels on a 40px sample, with text width
identical to the pixel.
