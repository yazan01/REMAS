"""The report stylesheet.

Kept apart from the document structure for the same reason a web project keeps
its CSS out of its templates: it changes for different reasons and by different
people. FR-34 lets iValue restyle the report — brand colours, the maturity
ramp, spacing — and that work happens here without touching a single line that
decides what goes on the page.

`$TOKEN` substitution rather than an f-string: the sheet is full of braces, and
an f-string would need every one of them doubled.
"""

from __future__ import annotations

#: The maturity ramp, level 1 → 5. It lives here because it is a palette, and
#: the palette belongs with the stylesheet: `render_stylesheet` falls back to it
#: whenever a report template's branding does not override `ramp`.
RAMP = ["#c9d2db", "#9db4cc", "#6d8fb2", "#426b95", "#1e3a5c"]


def render_stylesheet(rtl: bool, brand: dict | None = None) -> str:
    """The stylesheet is a template: branding tokens are substituted, so a
    change in the report template restyles the PDF with no code change
    (FR-34)."""
    brand = brand or {}
    ramp = brand.get("ramp") or RAMP
    tokens = {
        "$PRIMARY": brand.get("primary", "#1e3a5c"),
        "$ACCENT": brand.get("accent", "#b8863b"),
        "$INK": brand.get("ink", "#0f1b28"),
        "$MUTED": brand.get("muted", "#6b7d8d"),
        "$LINE": brand.get("line", "#dbe2e9"),
        "$SURFACE": brand.get("surface_alt", "#f6f8fa"),
    }
    for index, colour in enumerate(ramp[:5], start=1):
        tokens[f"$M{index}"] = colour
    css = _CSS_TEMPLATE
    for token, value in tokens.items():
        css = css.replace(token, value)
    return css


_CSS_TEMPLATE = """
@page { size: A4; margin: 16mm 14mm 18mm; }
* { box-sizing: border-box; }
body { font-family: "IBM Plex Sans Arabic","IBM Plex Sans",sans-serif; color:$INK;
  font-size: 10.5pt; line-height: 1.65; margin:0; }
h1,h2,h3,h4 { font-family:"Readex Pro","IBM Plex Sans Arabic",sans-serif; margin:0; font-weight:600; }
h2 { font-size: 15pt; padding-bottom:6px; border-bottom:2px solid $PRIMARY; margin-bottom:14px; }
h4 { font-size: 10.5pt; margin-bottom:6px; }
.mono { font-family:"IBM Plex Mono",monospace; font-variant-numeric: tabular-nums; }
.dim { color:$MUTED; }
.num { text-align:end; }
.mt { margin-top:16px; }
section.page { page-break-before: always; padding-top:2mm; }
.cover { min-height: 250mm; display:flex; flex-direction:column; justify-content:center; }
.cover-mark { display:flex; align-items:flex-end; gap:4px; height:40px; margin-bottom:22px; }
.cover-mark i { width:7px; border-radius:2px; display:block; }
.cover-mark i:nth-child(1){height:30%;background:$M1}
.cover-mark i:nth-child(2){height:47%;background:$M2}
.cover-mark i:nth-child(3){height:64%;background:$M3}
.cover-mark i:nth-child(4){height:82%;background:$M4}
.cover-mark i:nth-child(5){height:100%;background:$PRIMARY}
.cover-logo { max-height:56px; max-width:220px; margin-bottom:22px; display:block; }
.eyebrow { font-family:"IBM Plex Mono",monospace; font-size:8pt; letter-spacing:.18em;
  text-transform:uppercase; color:$MUTED; }
.cover h1 { font-size:26pt; margin:10px 0 26px; letter-spacing:-.02em; }
.cover-meta { border-collapse:collapse; width:100%; max-width:150mm; }
.cover-meta th { text-align:start; font-weight:500; color:$MUTED; font-size:9pt;
  padding:7px 0; width:38mm; border-bottom:1px solid $LINE; }
.cover-meta td { padding:7px 0; border-bottom:1px solid $LINE; }
.scope { margin-top:26px; padding:12px 14px; background:$SURFACE; border:1px solid $LINE; border-radius:6px; }
.scope .label { font-size:8.5pt; color:$MUTED; margin-bottom:3px; }
.scope p { margin:0; font-size:10pt; }
.confidential { margin-top:auto; padding-top:22px; font-size:8.5pt; color:$MUTED; }
.tiles { display:grid; grid-template-columns:repeat(4,1fr); gap:8px; margin-bottom:14px; }
.tile { border:1px solid $LINE; border-radius:6px; padding:10px 12px; }
.tile.hero { border-color:$M3; background:$SURFACE; }
.tile-v { display:block; font-family:"Readex Pro",sans-serif; font-size:17pt; line-height:1.1;
  font-variant-numeric:tabular-nums; }
.tile.hero .tile-v { color:$PRIMARY; }
.tile-l { display:block; font-size:8pt; color:$MUTED; margin-top:3px; }
.lede { font-size:10.5pt; margin:10px 0 14px; }
.two-col { display:grid; grid-template-columns:1fr 1fr; gap:14px; margin:12px 0; }
.chip { display:inline-block; font-size:8.5pt; padding:2px 9px; border-radius:99px;
  border:1px solid $LINE; background:$SURFACE; margin:0 0 4px; }
.chip.ok { background:$SURFACE; border-color:$LINE; color:#1f6b4a; }
.chip.bad { background:$SURFACE; border-color:$LINE; color:#9b3d2e; }
.note { margin-top:12px; padding:9px 12px; background:$SURFACE; border:1px solid $LINE;
  border-radius:5px; font-size:9pt; color:$INK; }
table.data { width:100%; border-collapse:collapse; font-size:9.5pt; }
table.data th { text-align:start; font-size:8.5pt; color:$MUTED; font-weight:600;
  background:$SURFACE; padding:6px 8px; border-bottom:1px solid $LINE; }
table.data td { padding:5px 8px; border-bottom:1px solid $LINE; }
.bar-cell { width:34mm; }
.bar { display:block; height:7px; background:$LINE; border-radius:99px; overflow:hidden; }
.bar i { display:block; height:100%; border-radius:99px; }
.results-grid { display:grid; grid-template-columns:1fr 92mm; gap:14px; align-items:start; }
.radar-wrap svg { width:100%; height:auto; }
.heat { display:grid; grid-template-columns:repeat(8,1fr); gap:4px; }
.heat-cell { border-radius:5px; padding:6px 7px; min-height:15mm; display:flex;
  flex-direction:column; justify-content:space-between; }
.heat-cell .hc { font-family:"IBM Plex Mono",monospace; font-size:7pt; opacity:.85; }
.heat-cell .hv { font-family:"IBM Plex Mono",monospace; font-size:11pt; font-weight:500; }
.axis-block { border:1px solid $LINE; border-radius:6px; padding:11px 13px; margin-bottom:9px;
  page-break-inside: avoid; }
.axis-head { display:flex; align-items:center; gap:8px; margin-bottom:7px; }
.axis-head h4 { flex:1; }
.swatch { width:10px; height:10px; border-radius:2px; display:inline-block; }
.axis-score { font-size:12pt; font-weight:500; }
dl { margin:0; display:grid; grid-template-columns:32mm 1fr; gap:3px 10px; font-size:9.5pt; }
dt { color:$MUTED; font-size:9pt; }
dd { margin:0; }
.init { border:1px solid $LINE; border-radius:6px; padding:11px 13px; margin-bottom:9px;
  page-break-inside: avoid; }
.init-head { display:flex; align-items:center; gap:8px; margin-bottom:7px; }
.init-head h4 { flex:1; }
.prio { font-family:"IBM Plex Mono",monospace; font-size:8.5pt; background:$PRIMARY; color:#fff;
  padding:2px 7px; border-radius:4px; }
.lanes { display:grid; grid-template-columns:repeat(4,1fr); gap:8px; }
.lane { border:1px solid $LINE; border-radius:6px; overflow:hidden; }
.lane-head { background:$SURFACE; padding:7px 9px; border-bottom:1px solid $LINE; font-size:9pt;
  display:flex; justify-content:space-between; gap:6px; }
.lane ul { margin:0; padding:8px 9px; padding-inline-start:20px; font-size:9pt; }
.lane li { margin-bottom:4px; }
.doc-footer { margin-top:16px; padding-top:8px; border-top:1px solid $LINE;
  font-size:8.5pt; color:$MUTED; }
"""
