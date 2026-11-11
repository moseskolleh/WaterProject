"""The app's one stylesheet, and the colours it is written in.

Design language ("field instrument"): quiet neutral surfaces, the brand
green as an accent only (the primary button, the current page, links, the
focus ring, a done tick), sentence case, Space Grotesk for titles, Inter for
text and IBM Plex Mono for numbers, units and identifiers. The browser app
(``docs/css/gwt.css``) is written to the same brief, and the tokens here
carry its names and its values, so the two read as one product. The printed
reports keep their own house style (``config.HouseStyle``), and the figures
keep their own colours: those go into the reports.

The stylesheet is a function of the theme because Streamlit does not say in
the page which of its two themes (``[theme.light]`` and ``[theme.dark]`` in
``.streamlit/config.toml``) is on. ``st.context.theme.type`` says it to the
script, so the tokens are written for that theme; and because choosing a
theme in Streamlit's menu does not run the script again, a few lines of
script (:data:`THEME_SYNC`) mirror the theme on the page's root element
(``data-gw-theme``), where the second and third token blocks answer to it at
once.

Two generations of Streamlit's markup are styled: the baseweb widgets of
1.58 and earlier (the browser demo pins 1.57.0) and the react-aria widgets
of 1.59 and later. A rule that names one of them says which.
"""

from __future__ import annotations

import base64
from pathlib import Path

#: Every colour the interface is drawn in: name, light value, dark value.
#: The names and the values are those of ``docs/css/gwt.css``.
TOKENS: tuple[tuple[str, str, str], ...] = (
    # surfaces: the navigation a step darker than the page, a card a step
    # lighter, a well a step back
    ("bg", "#f6f7f5", "#0d0f0e"),
    ("bg-raised", "#ffffff", "#151817"),
    ("bg-sunken", "#f1f3f0", "#101211"),
    ("bg-nav", "#eff1ee", "#0a0c0b"),
    ("hover", "rgba(0, 0, 0, 0.04)", "rgba(255, 255, 255, 0.05)"),
    # text in three steps, each at least 4.5:1 on all four surfaces
    ("ink", "#161a17", "#ebedec"),
    ("ink-soft", "#4b524d", "#b1b5b3"),
    ("ink-faint", "#5f6661", "#8f9491"),
    # hairlines are neutral; the control line edges what is typed into
    ("line", "rgba(0, 0, 0, 0.09)", "rgba(255, 255, 255, 0.09)"),
    ("line-strong", "rgba(0, 0, 0, 0.14)", "rgba(255, 255, 255, 0.16)"),
    ("line-control", "rgba(0, 0, 0, 0.3)", "rgba(255, 255, 255, 0.26)"),
    # the accent; the strong step is for text on the accent's own tint
    ("brand", "#1b7a2e", "#8ae06c"),
    ("brand-strong", "#145f23", "#a3ea8a"),
    ("brand-tint", "rgba(27, 122, 46, 0.09)", "rgba(138, 224, 108, 0.12)"),
    ("on-brand", "#ffffff", "#0d0f0e"),
    # status: "ok" is a teal, so a pass is never read as the accent
    ("ok", "#0b6b5a", "#4cc9a4"),
    ("ok-bg", "rgba(11, 107, 90, 0.1)", "rgba(76, 201, 164, 0.13)"),
    ("warn", "#7d5600", "#e6b23c"),
    ("warn-bg", "rgba(125, 86, 0, 0.1)", "rgba(230, 178, 60, 0.13)"),
    ("bad", "#ad3f28", "#f08d74"),
    ("bad-bg", "rgba(173, 63, 40, 0.1)", "rgba(240, 141, 116, 0.13)"),
    ("info", "#1b639e", "#6cb4f0"),
    ("info-bg", "rgba(27, 99, 158, 0.1)", "rgba(108, 180, 240, 0.13)"),
    ("neutral-bg", "rgba(0, 0, 0, 0.06)", "rgba(255, 255, 255, 0.08)"),
    # a card has no shadow in the dark and a very soft one in the light
    ("shadow", "0 1px 2px rgba(22, 26, 23, 0.06)", "none"),
    ("scrim", "rgba(22, 26, 23, 0.45)", "rgba(0, 0, 0, 0.6)"),
    # categorical slots for a breakdown drawn in the page (not a figure)
    ("cat-1", "#2a78d6", "#3987e5"),
    ("cat-2", "#eb6834", "#d95926"),
    ("cat-3", "#1baf7a", "#199e70"),
    ("cat-4", "#eda100", "#c98500"),
    ("cat-5", "#e87ba4", "#d55181"),
    ("cat-6", "#4a3aa7", "#9085e9"),
)

#: The slots a breakdown bar is drawn in, in order.
CATEGORICAL = [f"var(--cat-{n})" for n in range(1, 7)]

_SHARED_TOKENS = """
  --radius: 10px;
  --radius-sm: 6px;
  --ease: 0.15s ease;
  --measure: 60ch;
  --font: "Inter", "Segoe UI", system-ui, -apple-system, "Helvetica Neue", Arial, sans-serif;
  --font-display: "Space Grotesk", "Segoe UI", system-ui, sans-serif;
  --mono: "IBM Plex Mono", "SF Mono", ui-monospace, Menlo, Consolas, monospace;
"""


def _tokens(theme: str) -> str:
    column = 1 if theme == "light" else 2
    lines = [f"  color-scheme: {'light' if theme == 'light' else 'dark'};"]
    lines += [f"  --{row[0]}: {row[column]};" for row in TOKENS]
    return "\n".join(lines)


def font_faces(brand_dir: Path) -> str:
    """The three faces as @font-face rules with the files inlined.

    They ship as package data (Latin subsets, SIL Open Font License, see
    THIRD_PARTY_NOTICES.md), so the app sets its type without a request
    to a font service - it works offline and in the browser demo alike.
    A missing file falls through to the system stack in the rules below.
    """
    faces = (
        ("Space Grotesk", "400 700", "space-grotesk-latin.woff2"),
        ("Inter", "400 600", "inter-latin.woff2"),
        ("IBM Plex Mono", "400", "ibm-plex-mono-latin-400.woff2"),
        ("IBM Plex Mono", "500", "ibm-plex-mono-latin-500.woff2"),
    )
    rules = []
    for family, weight, name in faces:
        path = brand_dir / "fonts" / name
        if not path.exists():
            continue
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        rules.append(
            f"@font-face{{font-family:'{family}';font-style:normal;"
            f"font-weight:{weight};font-display:swap;"
            f"src:url(data:font/woff2;base64,{data}) format('woff2');}}"
        )
    return "".join(rules)


def brand_icon(brand_dir: Path) -> str:
    """The droplet as a data address for an ``<img>``, or "" without the file."""
    path = brand_dir / "icon.svg"
    if not path.exists():
        return ""
    return "data:image/svg+xml;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


#: Mirrors Streamlit's theme on the root element. Choosing Light or Dark in
#: Streamlit's menu repaints its own widgets without running the script, so
#: the script cannot write the tokens for the new theme until something else
#: reruns it; this reads the page's background as it changes and sets
#: ``data-gw-theme``, which the stylesheet answers to. It runs in a frame of
#: no size (``.st-key-gw_theme_sync``); where a frame may not reach its page
#: the tokens the script wrote stay in force until the next run.
THEME_SYNC = """<script>
(function () {
  try {
    var doc = window.parent.document, root = doc.documentElement;
    var sync = function () {
      var app = doc.querySelector('.stApp');
      if (!app) return;
      var c = getComputedStyle(app).backgroundColor.match(/[0-9.]+/g);
      if (!c || c.length < 3) return;
      var theme = (0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]) / 255 < 0.5 ? 'dark' : 'light';
      if (root.getAttribute('data-gw-theme') !== theme) root.setAttribute('data-gw-theme', theme);
    };
    sync();
    new MutationObserver(sync).observe(doc.body,
      { attributes: true, subtree: true, attributeFilter: ['class'] });
  } catch (e) { /* the tokens the script wrote stay in force */ }
})();
</script>"""


# Selector pieces. The sidebar navigation is one st.radio per group, keyed
# nav_<group>; a row is the radio's option label in either markup.
_SB = 'section[data-testid="stSidebar"]'
_NAV = f'{_SB} [class*="st-key-nav_"]'
_ROW_ARIA = f'{_NAV} label[data-testid="stRadioOption"]'        # Streamlit >= 1.59
_ROW_BASE = f'{_NAV} label[data-baseweb="radio"]'               # Streamlit <= 1.58
_STEPS = f"{_SB} .st-key-nav_borehole"
_STEP_ARIA = f'{_STEPS} label[data-testid="stRadioOption"]'
_STEP_BASE = f'{_STEPS} label[data-baseweb="radio"]'

# a column of a row that holds number fields and nothing wide
_NUMERIC_COLUMN = (
    '[data-testid="stColumn"]:has([data-testid="stNumberInput"])'
    ':not(:has([data-testid="stImage"], [data-testid="stDataFrame"], '
    '[data-testid="stFileUploader"], [data-testid="stTextArea"], '
    '[data-testid="stExpander"]))'
)

_RULES = """
/* ---------------------------------------------------------------- type */
html, body, [data-testid="stAppViewContainer"], .stMarkdown,
button, input, textarea, select { font-family: var(--font); }
h1, h2, h3, h4 {
  font-family: var(--font-display) !important;
  font-weight: 600 !important; line-height: 1.2; color: var(--ink);
}
code, pre, kbd { font-family: var(--mono); }
a { color: var(--brand); text-decoration-thickness: 1px; text-underline-offset: 2px; }
a:hover { color: var(--brand-strong); }
hr { border-color: var(--line-strong) !important; }

/* ---------------------------------------------------------------- page */
[data-testid="stMainBlockContainer"] {
  padding: 3rem 2.5rem 4rem; max-width: 80rem;
}
/* the two style elements are held in a box that takes no room */
.st-key-gw_style { display: none; }
/* The product's name is said once above every page, small: the page's own
   header is the title. */
.st-key-gw_eyebrow { gap: 0 !important; }
.st-key-gw_eyebrow [data-testid="stHeading"] h1 {
  font-family: var(--font) !important; font-size: 0.75rem !important;
  font-weight: 500 !important; line-height: 1.35; letter-spacing: 0;
  color: var(--ink-faint); padding: 0; margin: 0;
}
.st-key-gw_eyebrow [data-testid="stHeaderActionElements"] { display: none; }
[data-testid="stMain"] h2 {
  font-size: 1.625rem; letter-spacing: -0.01em; padding: 0.125rem 0 0.25rem;
}
[data-testid="stMain"] h3 {
  font-size: 1.125rem; letter-spacing: -0.005em; padding: 0.5rem 0 0.25rem;
}
[data-testid="stMain"] h4 { font-size: 1rem; }
/* running text is capped near 72 characters */
[data-testid="stMain"] [data-testid="stMarkdownContainer"] > p,
[data-testid="stMain"] [data-testid="stMarkdownContainer"] li,
[data-testid="stMain"] [data-testid="stCaptionContainer"] p {
  max-width: var(--measure);
}
[data-testid="stMain"] [data-testid="stMarkdownContainer"] > p:has(> .gw-chip) {
  max-width: none;
}
/* a caption is muted text, not faded text: it holds 4.5:1 everywhere */
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {
  color: var(--ink-soft) !important; opacity: 1;
}
[data-testid="stSidebarUserContent"] [data-testid="stCaptionContainer"] p {
  font-size: 0.8125rem; line-height: 1.4;
}

/* ------------------------------------------------------------- buttons */
/* The primary action is filled; every other is outlined in neutral. */
.stButton > button, .stDownloadButton > button, .stLinkButton > a,
[data-testid="stFormSubmitButton"] > button {
  font-family: var(--font); font-weight: 500; font-size: 0.875rem;
  letter-spacing: 0; text-transform: none;
  border-radius: var(--radius-sm); min-height: 2.25rem; padding: 0.3rem 0.9rem;
  transition: background-color var(--ease), border-color var(--ease), color var(--ease);
}
/* (the baseweb markup sizes a button's text on the text, not the button) */
[data-testid^="stBaseButton-secondary"], [data-testid^="stBaseButton-primary"],
[data-testid^="stBaseButton-tertiary"] { font-size: 0.875rem; }
[data-testid^="stBaseButton-secondary"] [data-testid="stMarkdownContainer"],
[data-testid^="stBaseButton-primary"] [data-testid="stMarkdownContainer"],
[data-testid^="stBaseButton-tertiary"] [data-testid="stMarkdownContainer"],
[data-testid^="stBaseButton-secondary"] p, [data-testid^="stBaseButton-primary"] p,
[data-testid^="stBaseButton-tertiary"] p { font-size: inherit; }
[data-testid="stBaseButton-secondary"],
[data-testid="stBaseButton-secondaryFormSubmit"] {
  background: var(--bg-raised); border: 1px solid var(--line-control);
  color: var(--ink);
}
[data-testid="stBaseButton-secondary"]:hover,
[data-testid="stBaseButton-secondaryFormSubmit"]:hover {
  background: var(--bg-raised); border-color: var(--ink-faint); color: var(--ink);
}
[data-testid="stBaseButton-primary"],
[data-testid="stBaseButton-primaryFormSubmit"] {
  background: var(--brand); border: 1px solid var(--brand);
  color: var(--on-brand); font-weight: 600;
}
[data-testid="stBaseButton-primary"] p,
[data-testid="stBaseButton-primaryFormSubmit"] p { color: var(--on-brand); }
[data-testid="stBaseButton-primary"]:hover,
[data-testid="stBaseButton-primaryFormSubmit"]:hover {
  background: var(--brand-strong); border-color: var(--brand-strong);
  color: var(--on-brand);
}
.stButton > button:disabled, .stDownloadButton > button:disabled {
  background: var(--bg-sunken); border-color: var(--line); color: var(--ink-faint);
}
.stButton > button:disabled p { color: var(--ink-faint); }

/* --------------------------------------------------------------- cards */
/* Flat: one hairline, 10px, no shadow in the dark and a soft one in light. */
div[data-testid="stMetric"] {
  background: var(--bg-raised); border: 1px solid var(--line);
  border-radius: var(--radius); box-shadow: var(--shadow);
  padding: 0.7rem 0.9rem;
}
div[data-testid="stMetric"] label p,
div[data-testid="stMetric"] [data-testid="stMetricLabel"] p {
  font-family: var(--font); font-size: 0.75rem; font-weight: 500;
  line-height: 1.35; color: var(--ink-soft);
}
/* a headline value is a number and a unit on one line; it never wraps */
[data-testid="stMetricValue"] {
  font-family: var(--font-display); font-weight: 600; font-size: 1.625rem;
  line-height: 1.2; color: var(--ink);
}
[data-testid="stMetricValue"] > div {
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
[data-testid="stMetricDelta"] { font-size: 0.8125rem; }
[data-testid="stExpander"] details {
  background: var(--bg-raised); border: 1px solid var(--line);
  border-radius: var(--radius); box-shadow: var(--shadow);
}
[data-testid="stExpander"] summary p {
  font-family: var(--font); font-weight: 600; font-size: 0.875rem;
}
[data-testid="stDataFrame"], [data-testid="stTable"] {
  border-radius: var(--radius); overflow: hidden;
}
[data-testid="stAlert"] p { max-width: 72ch; }
/* an upload is one compact row: the button, or the file's name with the
   buttons that replace and remove it */
[data-testid="stFileUploaderDropzone"] {
  min-height: 0; padding: 0.5rem 0.75rem; border-radius: var(--radius);
  background: var(--bg-raised);
}
[data-testid="stFileUploaderFile"] { padding-block: 0.125rem; }

/* A figure is a sheet of paper on the page: the figures are drawn for the
   printed report, on white, and are framed here, not recoloured. */
[data-testid="stImage"] img, [data-testid="stImageContainer"] img {
  background: #ffffff; box-sizing: border-box; padding: 0.75rem;
  border: 1px solid var(--line-strong); border-radius: var(--radius);
  box-shadow: var(--shadow);
}

/* --------------------------------------------------------------- focus */
/* One clear ring in the accent, with an offset, on whatever holds the
   keyboard - a field is ringed on its box. */
button:focus-visible, a:focus-visible, summary:focus-visible,
[role="tab"]:focus-visible, [role="button"]:focus-visible,
[role="checkbox"]:focus-visible, [role="switch"]:focus-visible,
[tabindex]:not(input):not(textarea):focus-visible {
  outline: 2px solid var(--brand) !important; outline-offset: 2px !important;
  box-shadow: none !important;
}
[data-baseweb="input"]:focus-within, [data-baseweb="textarea"]:focus-within,
[data-baseweb="select"] > div:focus-within,
[data-testid="stTextInputRootElement"]:focus-within,
[data-testid="stNumberInputContainer"]:focus-within,
[data-testid="stTextAreaRootElement"]:focus-within,
[data-testid="stSelectbox"] [role="group"]:focus-within,
[data-testid="stMultiSelect"] [role="group"]:focus-within,
[data-testid="stDateInput"] [data-baseweb="input"]:focus-within {
  outline: 2px solid var(--brand); outline-offset: 2px; box-shadow: none;
}
[data-testid="stNumberInputContainer"] [data-baseweb="input"]:focus-within,
[data-testid="stTextInputRootElement"] [data-baseweb="input"]:focus-within {
  outline: none;
}
label:has(> input[type="checkbox"]:focus-visible),
label:has(input[type="radio"]:focus-visible) {
  outline: 2px solid var(--brand); outline-offset: 2px; border-radius: var(--radius-sm);
}

/* ------------------------------------------------------------- sidebar */
/* The sidebar's own header row holds only the button that closes it; the
   brand sits in that row, so the navigation starts at the top. */
SB [data-testid="stSidebarHeader"] {
  height: 0; min-height: 0; padding: 0; margin: 0; position: relative; z-index: 2;
}
SB [data-testid="stSidebarCollapseButton"] {
  position: absolute; top: 0.6rem; right: 0.6rem;
}
SB [data-testid="stSidebarContent"] { padding-inline: 0.25rem; }
SB [data-testid="stSidebarUserContent"] { padding: 0.75rem 0.5rem 1.25rem; }
SB [data-testid="stSidebarUserContent"] [data-testid="stVerticalBlock"] { gap: 0.375rem; }
SB [data-testid="stExpanderDetails"] [data-testid="stVerticalBlock"] { gap: 0.75rem; }
SB [data-testid="stExpander"] details { background: transparent; box-shadow: none; }
/* (Streamlit pulls what follows a markdown block up by 1rem, for the
   margin a paragraph would have left; these blocks have none to give) */
.gw-brand {
  display: flex; align-items: center; gap: 0.5rem;
  min-height: 2rem; padding: 0 2.5rem 0 0.5rem; margin-bottom: 1rem;
}
.gw-brand img { width: 1.375rem; height: 1.375rem; flex: none; }
.gw-brand-name {
  font: 600 0.9375rem/1.2 var(--font-display); color: var(--ink);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
/* the project in hand: its name on one line, its state beside it */
.gw-project {
  display: flex; align-items: center; justify-content: space-between; gap: 0.5rem;
  min-height: 2.125rem; padding: 0.25rem 0.5rem 0.25rem 0.625rem; margin: 0.125rem 0 1.25rem;
  background: var(--bg-raised); border: 1px solid var(--line);
  border-radius: var(--radius); box-shadow: var(--shadow);
}
.gw-project-name {
  min-width: 0; font: 600 0.8125rem/1.3 var(--font); color: var(--ink);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}

/* Navigation: five groups, all on screen in a 1366 by 850 window. Each
   group is a radio; its options are the rows and its label the group's
   name. The native ring is hidden in both markups and the row itself shows
   the current page. */
NAV { width: 100% !important; }
NAV .stRadio, NAV [role="radiogroup"] { width: 100%; }
NAV [role="radiogroup"] { gap: 0; counter-reset: gw-step; }
NAV [role="radiogroup"] > div { width: 100%; margin: 0; padding: 0; min-height: 0; }
NAV [data-testid="stWidgetLabel"] {
  min-height: 0; margin: 0; padding: 0.1875rem 0.5rem 0.0625rem;
}
NAV [data-testid="stWidgetLabel"] p {
  font-family: var(--font); font-size: 0.75rem; font-weight: 500;
  line-height: 1.35; color: var(--ink-faint);
}
ROW_ARIA, ROW_BASE {
  display: flex; align-items: center; gap: 0.5rem; box-sizing: border-box;
  width: 100%; min-height: 1.5rem; margin: 0; padding: 0 0.5rem;
  border-radius: var(--radius-sm); background: transparent; cursor: pointer;
  position: relative;
  transition: background-color var(--ease);
}
ROW_ARIA:hover, ROW_BASE:hover { background: var(--hover); }
/* the native ring: the first box beside the text (react-aria), the label's
   first child (baseweb) */
ROW_ARIA > div > div:not([data-testid]), ROW_BASE > div:first-child { display: none; }
ROW_ARIA > div, ROW_BASE > div:last-child {
  gap: 0; margin: 0; padding: 0; min-width: 0;
}
ROW_ARIA p, ROW_BASE [data-testid="stMarkdownContainer"] p {
  font-family: var(--font); font-size: 0.8125rem; font-weight: 400;
  line-height: 1.2; letter-spacing: 0; color: var(--ink-soft);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
ROW_ARIA:hover p, ROW_BASE:hover p { color: var(--ink); }
ROW_ARIA[data-selected="true"] { background: var(--brand-tint); }
ROW_ARIA[data-selected="true"] p { color: var(--brand-strong); font-weight: 600; }
ROW_BASE:has(input:checked) { background: var(--brand-tint); }
ROW_BASE:has(input:checked) [data-testid="stMarkdownContainer"] p {
  color: var(--brand-strong); font-weight: 600;
}
ROW_ARIA:focus-within, ROW_BASE:focus-within {
  outline: 2px solid var(--brand); outline-offset: -2px;
}
@supports selector(:has(a)) {
  ROW_ARIA:focus-within, ROW_BASE:focus-within { outline: none; }
  ROW_ARIA:has(input:focus-visible), ROW_BASE:has(input:focus-visible) {
    outline: 2px solid var(--brand); outline-offset: -2px;
  }
}
/* The Borehole group is the work itself, in the order it is done: full-size
   rows, each with its step's number, and a tick in its place when done
   (the rules that say which steps are done are written on every run, by
   nav_done_css). */
STEP_ARIA, STEP_BASE { min-height: 1.875rem; }
STEP_ARIA p, STEP_BASE [data-testid="stMarkdownContainer"] p {
  font-size: 0.875rem; font-weight: 500; color: var(--ink);
}
STEP_ARIA::before, STEP_BASE::before {
  counter-increment: gw-step; content: counter(gw-step);
  flex: none; display: inline-flex; align-items: center; justify-content: center;
  box-sizing: border-box; width: 1.25rem; height: 1.25rem; border-radius: 50%;
  border: 1px solid var(--line-control); color: var(--ink-soft);
  font-family: var(--mono); font-size: 0.75rem; font-weight: 500; line-height: 1;
}
STEP_ARIA[data-selected="true"]::before, STEP_BASE:has(input:checked)::before {
  border-color: var(--brand); color: var(--brand-strong);
}
@media (min-height: 960px) {
  SB [data-testid="stSidebarUserContent"] [data-testid="stVerticalBlock"] { gap: 0.625rem; }
  SB [data-testid="stExpanderDetails"] [data-testid="stVerticalBlock"] { gap: 0.75rem; }
  ROW_ARIA, ROW_BASE { min-height: 1.75rem; }
  STEP_ARIA, STEP_BASE { min-height: 2.125rem; }
}
/* the frame the theme script runs in takes no room */
.st-key-gw_theme_sync {
  position: absolute !important; width: 0 !important; height: 0 !important;
  overflow: hidden; visibility: hidden;
}

/* ------------------------------------------- shared pieces in the pages */
.gw-cap {
  font-family: var(--font); font-size: 0.75rem; font-weight: 500;
  line-height: 1.35; color: var(--ink-soft);
}
.gw-note { font-size: 0.8125rem; line-height: 1.45; color: var(--ink-soft); margin-top: 0.375rem; }
.gw-lead { font-size: 0.875rem; line-height: 1.55; color: var(--ink-soft); max-width: 72ch; }
.gw-unit { font: 400 0.75rem/1.4 var(--mono); color: var(--ink-soft); }
.gw-chip {
  display: inline-block; font-family: var(--font); font-size: 0.75rem;
  font-weight: 500; line-height: 1.35; letter-spacing: 0;
  border-radius: 999px; padding: 0.0625rem 0.5625rem; vertical-align: middle;
  white-space: nowrap;
}
.gw-chip-green { color: var(--ok); background: var(--ok-bg); }
.gw-chip-amber { color: var(--warn); background: var(--warn-bg); }
.gw-chip-red { color: var(--bad); background: var(--bad-bg); }
.gw-chip-grey { color: var(--ink-soft); background: var(--neutral-bg); }
.gw-chip-blue { color: var(--info); background: var(--info-bg); }
.gw-title { margin: 0 0 0.125rem; }
.gw-title .gw-chip { margin-left: 0.375rem; }
.gw-card {
  background: var(--bg-raised); border: 1px solid var(--line);
  border-radius: var(--radius); box-shadow: var(--shadow);
  padding: 0.875rem 1rem; margin-bottom: 0.875rem;
}
.gw-card .gw-cap { display: block; margin-bottom: 0.5rem; }
.gw-big {
  font: 600 1.625rem/1.15 var(--font-display); color: var(--ink);
  white-space: nowrap;
}
.gw-big small { font: 400 0.8125rem/1.2 var(--mono); color: var(--ink-soft); }
.gw-row {
  display: flex; justify-content: space-between; gap: 0.625rem;
  font-size: 0.8125rem; color: var(--ink-soft); padding: 0.1875rem 0;
}
.gw-row b {
  color: var(--ink); font-weight: 500; font-family: var(--mono); text-align: right;
}
/* The headline a page was opened for: a tile like any other, set larger.
   Each value is a number and a unit; what qualifies it is a line beneath. */
.gw-callout {
  display: flex; flex-wrap: wrap; gap: 0.75rem 2rem; align-items: flex-start;
  background: var(--bg-raised); border: 1px solid var(--line-strong);
  border-radius: var(--radius); box-shadow: var(--shadow);
  padding: 0.875rem 1.125rem; margin: 0.25rem 0 0.75rem;
}
.gw-callout .gw-cap { display: block; margin-bottom: 0.25rem; }
.gw-callout .gw-big { font-size: 2rem; }
.gw-callout p {
  flex-basis: 100%; margin: 0; font-size: 0.8125rem; line-height: 1.45;
  color: var(--ink-soft);
}
.gw-steps { display: flex; align-items: flex-start; margin: 0.375rem 0 0.25rem; }
.gw-step {
  display: flex; flex-direction: column; align-items: center;
  gap: 0.3125rem; flex: none; min-width: 3.5rem;
}
.gw-step-dot {
  box-sizing: border-box; width: 1.625rem; height: 1.625rem; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font: 500 0.75rem/1 var(--mono);
}
.gw-step-done .gw-step-dot { background: var(--brand); color: var(--on-brand); }
.gw-step-todo .gw-step-dot {
  background: var(--bg-sunken); border: 1px solid var(--line-control);
  color: var(--ink-soft);
}
.gw-step-label {
  font: 500 0.75rem/1.35 var(--font); color: var(--ink);
}
.gw-step-todo .gw-step-label { color: var(--ink-soft); }
.gw-step-line {
  flex: 1; height: 0; border-top: 2px solid var(--line-control);
  margin: 0.75rem 0.375rem 0;
}
.gw-step-line-todo { border-top: 2px dashed var(--line-strong); }
.gw-bar {
  display: flex; height: 0.5625rem; border-radius: 0.3125rem;
  overflow: hidden; margin: 0.5rem 0; background: var(--bg-sunken);
}
.gw-legend {
  display: flex; flex-wrap: wrap; gap: 0.1875rem 0.75rem;
  font-size: 0.75rem; color: var(--ink-soft);
}
.gw-legend i {
  display: inline-block; width: 0.5rem; height: 0.5rem;
  border-radius: 2px; margin-right: 0.25rem;
}
.gw-report-row {
  display: flex; justify-content: space-between; align-items: center;
  font-size: 0.8125rem; color: var(--ink-soft); padding: 0.25rem 0;
  border-bottom: 1px solid var(--line);
}
.gw-report-row:last-child { border-bottom: none; }

/* --------------------------------------------------------------- phone */
/* One bar at the top: Streamlit's menu button, the project's name on one
   line, Streamlit's actions. The bar is drawn behind Streamlit's own header
   row, which is made clear, and stays put while the page scrolls. */
.gw-topbar { display: none; }
@media (max-width: 768px) {
  .gw-topbar {
    display: flex; align-items: center; gap: 0.5rem; box-sizing: border-box;
    position: fixed; top: 0; left: 0; right: 0; height: 3.75rem;
    padding: 0 6.5rem 0 3.5rem; z-index: 999989; pointer-events: none;
    background: var(--bg-nav); border-bottom: 1px solid var(--line);
  }
  .gw-topbar-name {
    min-width: 0; font: 600 0.9375rem/1.2 var(--font-display); color: var(--ink);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .gw-topbar .gw-chip { flex: none; }
  [data-testid="stHeader"] { background: transparent !important; }
  [data-testid="stMainBlockContainer"] { padding: 4.5rem 1rem 3rem; }
  [data-testid="stMain"] h2 { font-size: 1.375rem; }
  /* the drawer: a scrim behind it, rows a thumb can hit */
  SB[aria-expanded="true"], SB[data-collapsed="false"] {
    box-shadow: 0 0 0 100vmax var(--scrim);
  }
  ROW_ARIA, ROW_BASE, STEP_ARIA, STEP_BASE { min-height: 2.75rem; }
  ROW_ARIA p, ROW_BASE [data-testid="stMarkdownContainer"] p { font-size: 0.9375rem; }
  STEP_ARIA p, STEP_BASE [data-testid="stMarkdownContainer"] p { font-size: 0.9375rem; }
  .stButton > button, .stDownloadButton > button,
  [data-testid="stFormSubmitButton"] > button { min-height: 2.75rem; }
  .gw-steps { overflow: hidden; }
  .gw-step { min-width: 0; flex: 0 1 auto; }
  .gw-step-line { min-width: 0.5rem; margin-inline: 0.125rem; }
}
/* short numeric fields sit two to a row where Streamlit would stack them */
@media (max-width: 640px) {
  [data-testid="stHorizontalBlock"]:has(> NUMERIC_COLUMN) { align-items: flex-end; }
  [data-testid="stHorizontalBlock"] > NUMERIC_COLUMN {
    min-width: calc(50% - 0.5rem) !important; width: calc(50% - 0.5rem) !important;
    flex: 1 1 calc(50% - 0.5rem) !important;
  }
}

/* -------------------------------------------------------------- motion */
@media (prefers-reduced-motion: reduce) {
  html, [data-testid="stMain"], [data-testid="stSidebarContent"] {
    scroll-behavior: auto !important;
  }
  *, *::before, *::after {
    transition-duration: 0.01ms !important; transition-delay: 0s !important;
  }
}
"""


def _expand(rules: str) -> str:
    """Write the selector shorthands of ``_RULES`` out in full.

    A shorthand stands for one selector and is used in comma lists, so a
    rule for both markups is written ``ROW_ARIA x, ROW_BASE x``.
    """
    for short, full in (
        ("STEP_ARIA", _STEP_ARIA), ("STEP_BASE", _STEP_BASE),
        ("ROW_ARIA", _ROW_ARIA), ("ROW_BASE", _ROW_BASE),
        ("NUMERIC_COLUMN", _NUMERIC_COLUMN), ("NAV", _NAV), ("SB", _SB),
    ):
        rules = rules.replace(short, full)
    return rules


def stylesheet(theme: str = "dark") -> str:
    """The stylesheet as one ``<style>`` element, for ``theme``.

    The first token block is the theme the script was told is on; the two
    after it follow ``data-gw-theme`` (see :data:`THEME_SYNC`), so a theme
    chosen in Streamlit's menu takes effect without waiting for a run.
    """
    theme = "light" if theme == "light" else "dark"
    return (
        "<style>\n"
        f":root {{\n{_tokens(theme)}\n{_SHARED_TOKENS}}}\n"
        f':root[data-gw-theme="light"] {{\n{_tokens("light")}\n}}\n'
        f':root[data-gw-theme="dark"] {{\n{_tokens("dark")}\n}}\n'
        + _expand(_RULES)
        + "</style>"
    )


def nav_done_css(done: list[bool]) -> str:
    """Rules that put a tick on the Borehole steps that are done.

    ``done`` is in the order of the group's rows. The tick takes the place
    of the step's number; a row is found by its position, in the react-aria
    markup (each option in a box of its own) and in the baseweb one (the
    options side by side).
    """
    rules = []
    for n, is_done in enumerate(done, start=1):
        if not is_done:
            continue
        aria = f'{_STEPS} [role="radiogroup"] > div:nth-child({n}) > label[data-testid="stRadioOption"]'
        base = f'{_STEPS} [role="radiogroup"] > label[data-baseweb="radio"]:nth-child({n})'
        rules.append(
            f"{aria}::before, {base}::before {{ content: ''; content: '' / 'Done: '; "
            "background: var(--brand); border-color: var(--brand); }\n"
            f"{aria}::after, {base}::after {{ content: ''; position: absolute; "
            "left: calc(0.5rem + 0.46875rem); top: 50%; width: 0.3125rem; height: 0.5625rem; "
            "margin-top: -0.375rem; box-sizing: border-box; "
            "border: solid var(--on-brand); border-width: 0 2px 2px 0; "
            "transform: rotate(45deg); }"
        )
    return "<style>\n" + "\n".join(rules) + "\n</style>" if rules else ""
