"""Static Streamlit theme matching the approved scKG workbench v4 design.

Layout hooks are application-owned container keys. Bordered content cards use a
``wb_card_`` key prefix so layout-only Streamlit blocks never acquire card borders.
No prototype content, sample knowledge, JavaScript or external assets are loaded.
"""
from __future__ import annotations

from html import escape
from urllib.parse import quote

import streamlit as st


_CSS = """
:root {
  --wb-bg: #f6f7f9;
  --wb-paper: #ffffff;
  --wb-text: #203044;
  --wb-muted: #5e6e81;
  --wb-line: #dce2ea;
  --wb-accent: #285d9a;
  --wb-accentbg: #eaf1fa;
  --wb-good: #266953;
  --wb-goodbg: #e8f4ed;
  --wb-warn: #875f1e;
  --wb-warnbg: #faf0dc;
  --wb-danger: #a53740;
  --wb-font: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", sans-serif;
}
.stApp {
  background: var(--wb-paper);
  color: var(--wb-text);
  font-family: var(--wb-font);
  color-scheme: light;
}
[data-testid="stHeader"], [data-testid="stToolbar"],
[data-testid="stDecoration"], [data-testid="stAppDeployButton"],
#MainMenu, footer { display: none !important; }
[data-testid="stMainBlockContainer"] {
  max-width: 1480px;
  padding: 20px 24px 36px;
}
.st-key-workbench_frame {
  background: var(--wb-bg);
  border: 1px solid var(--wb-line);
  border-radius: 12px;
  gap: 0 !important;
  overflow: clip;
  font: 14px/1.55 var(--wb-font);
  color: var(--wb-text);
}
.st-key-workbench_frame *, .st-key-workbench_frame *::before,
.st-key-workbench_frame *::after { box-sizing: border-box; }
.st-key-workbench_frame :is(button, input, select, textarea) {
  font-family: var(--wb-font);
  font-size: 14px;
}
.st-key-workbench_frame :is(p, li, label) {
  font-family: var(--wb-font);
  font-size: 14px;
  line-height: 1.55;
}
.st-key-workbench_frame :is(h1, h2, h3, strong) {
  font-family: var(--wb-font);
  font-weight: 500;
  color: var(--wb-text);
}
.st-key-workbench_frame h1 {
  font-size: 23px !important;
  line-height: 1.3 !important;
  letter-spacing: 0;
  padding: 0 0 4px;
}
.st-key-workbench_frame h2 {
  font-size: 17px !important;
  line-height: 1.4;
  padding: 0 0 8px;
}
.st-key-workbench_frame h3 {
  font-size: 14px !important;
  line-height: 1.55;
  padding: 0 0 6px;
}
.st-key-workbench_frame [data-testid="stCaptionContainer"],
.st-key-workbench_frame [data-testid="stCaptionContainer"] p,
.st-key-workbench_frame [data-testid="stWidgetLabel"] p {
  font-size: 12px;
  color: var(--wb-muted);
  line-height: 1.55;
}
.st-key-workbench_frame [data-testid="stMarkdownContainer"] > p:last-child { margin-bottom: 0; }
.st-key-workbench_frame a { color: var(--wb-accent); }
.st-key-workbench_top {
  padding: 13px 18px;
  background: var(--wb-paper);
  border-bottom: 1px solid var(--wb-line);
  gap: 0 !important;
}
.st-key-workbench_top [data-testid="stHorizontalBlock"] {
  align-items: center;
  gap: 12px;
}
.st-key-workbench_footer {
  background: var(--wb-paper);
  border-top: 1px solid var(--wb-line);
  gap: 0 !important;
}
.st-key-workbench_body { gap: 0 !important; }
.st-key-workbench_body > [data-testid="stHorizontalBlock"],
.st-key-workbench_body > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] {
  gap: 0 !important;
  align-items: stretch;
}
.st-key-workbench_body [data-testid="stColumn"]:has(.st-key-workbench_nav) {
  flex: 0 0 158px !important;
  width: 158px !important;
  min-width: 158px;
  background: var(--wb-paper);
  border-right: 1px solid var(--wb-line);
}
.st-key-workbench_body [data-testid="stColumn"]:has(.st-key-workbench_main) {
  flex: 1 1 0 !important;
  min-width: 0;
}
.st-key-workbench_nav {
  background: var(--wb-paper);
  padding: 20px 10px;
  gap: 18px;
}
.st-key-workbench_main {
  padding: 24px;
  min-height: 660px;
  min-width: 0;
  gap: 15px;
}
.st-key-workbench_main [data-testid="stHorizontalBlock"] { gap: 15px; }
.st-key-workbench_main [data-testid="stColumn"] { min-width: 0; }

/* Keep the actual radio inputs and keyboard behavior, replacing only the circle. */
.st-key-workbench_nav [role="radiogroup"] {
  display: flex;
  flex-direction: column;
  gap: 5px;
  width: 100%;
}
.st-key-workbench_nav label[data-baseweb="radio"] {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  min-height: 40px;
  margin: 0;
  padding: 10px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--wb-text);
  position: relative;
}
.st-key-workbench_nav label[data-baseweb="radio"] > div:first-of-type,
.st-key-ingest_steps label[data-baseweb="radio"] > div:first-of-type { display: none; }
.st-key-workbench_nav label[data-baseweb="radio"] > div:last-child,
.st-key-ingest_steps label[data-baseweb="radio"] > div:last-child { padding: 0; }
.st-key-workbench_nav label[data-baseweb="radio"] p {
  font-size: 13px;
  line-height: 1.55;
  color: inherit;
  white-space: nowrap;
}
.st-key-workbench_nav label[data-baseweb="radio"]:hover { background: var(--wb-bg); }
.st-key-workbench_nav label[data-baseweb="radio"]:has(input:checked) {
  background: var(--wb-accentbg);
  color: var(--wb-accent);
}
.st-key-workbench_nav label[data-baseweb="radio"]:has(input:focus-visible),
.st-key-ingest_steps label[data-baseweb="radio"]:has(input:focus-visible) {
  outline: 2px solid var(--wb-accent);
  outline-offset: 2px;
}
.st-key-workbench_nav label[data-baseweb="radio"]::before {
  content: "";
  display: block;
  flex: 0 0 16px;
  width: 16px;
  height: 16px;
  background: currentColor;
  -webkit-mask: var(--wb-nav-icon) center / 16px 16px no-repeat;
  mask: var(--wb-nav-icon) center / 16px 16px no-repeat;
}
.st-key-workbench_nav label[data-baseweb="radio"]:nth-of-type(7) { margin-top: 14px; }
.st-key-workbench_nav label[data-baseweb="radio"]:nth-of-type(7)::after {
  content: "";
  position: absolute;
  top: -9px;
  left: 0;
  right: 0;
  height: 1px;
  background: var(--wb-line);
}

/* Application-owned card keys distinguish content panels from layout blocks. */
.st-key-workbench_main [class*="st-key-wb_card_"] {
  background: var(--wb-paper);
  border: 1px solid var(--wb-line);
  border-radius: 8px;
  padding: 16px;
  min-width: 0;
  gap: 12px;
}
.st-key-workbench_main [class*="st-key-wb_card_"] [data-testid="stHeading"] h3 {
  font-size: 17px !important;
  line-height: 1.4;
  font-weight: 500;
}
.st-key-workbench_frame [data-testid="stForm"] {
  background: var(--wb-paper);
  border-color: var(--wb-line);
  border-radius: 8px;
}
.st-key-workbench_frame button[data-testid^="stBaseButton"] {
  border-radius: 6px;
  min-height: 34px;
  padding: 7px 11px;
  font-size: 14px;
  font-weight: 400;
  box-shadow: none;
}
.st-key-workbench_frame button[data-testid^="stBaseButton-secondary"] {
  background: var(--wb-paper);
  border: 1px solid var(--wb-line);
  color: var(--wb-text);
}
.st-key-workbench_frame button[data-testid^="stBaseButton-secondary"]:hover:not(:disabled) {
  background: var(--wb-accentbg);
  color: var(--wb-accent);
  border-color: var(--wb-accent);
}
.st-key-workbench_frame button[data-testid^="stBaseButton-primary"] {
  background: var(--wb-accent);
  border: 1px solid var(--wb-accent);
  color: var(--wb-paper);
}
.st-key-workbench_frame button[data-testid^="stBaseButton-primary"]:hover:not(:disabled) { filter: brightness(.95); }
.st-key-workbench_frame button:disabled { opacity: .5; }
.st-key-workbench_frame button:focus-visible {
  outline: 2px solid var(--wb-accent);
  outline-offset: 2px;
}
.st-key-workbench_frame :is([data-testid="stTextInput"], [data-testid="stNumberInput"]) [data-baseweb="input"],
.st-key-workbench_frame [data-testid="stTextArea"] [data-baseweb="textarea"],
.st-key-workbench_frame :is([data-testid="stSelectbox"], [data-testid="stMultiSelect"]) [data-baseweb="select"] > div:first-child {
  background: var(--wb-paper);
  border: 1px solid var(--wb-line);
  border-radius: 5px;
  min-height: 36px;
}
.st-key-workbench_frame :is(input, textarea) {
  color: var(--wb-text);
  background: var(--wb-paper) !important;
}
.st-key-workbench_frame [data-baseweb="base-input"] { background: var(--wb-paper); }
.st-key-workbench_frame :is(input, textarea)::placeholder { color: var(--wb-muted); opacity: .8; }
.st-key-workbench_frame :is([data-baseweb="input"], [data-baseweb="textarea"]):focus-within {
  border-color: var(--wb-accent);
}
.st-key-workbench_frame input { accent-color: var(--wb-accent); }
.st-key-workbench_frame label[data-baseweb="checkbox"]:has(input:checked) > span:first-child {
  background-color: var(--wb-accent);
  border-color: var(--wb-accent);
}
.st-key-workbench_frame [data-testid="stFileUploaderDropzone"] {
  background: var(--wb-bg);
  border: 1px dashed var(--wb-line);
  border-radius: 6px;
  padding: 16px;
}
.st-key-workbench_frame [data-testid="stFileUploaderDropzone"] :is(p, span, small) { font-size: 12px; }
.st-key-workbench_frame [data-testid="stExpander"] details {
  background: var(--wb-paper);
  border-color: var(--wb-line);
  border-radius: 8px;
}
.st-key-workbench_frame [data-testid="stExpander"] summary { font-size: 13px; }
.st-key-workbench_frame [data-testid="stAlert"] { font-size: 12px; }
.st-key-workbench_frame [data-testid="stAlert"] p { font-size: 12px; line-height: 1.65; }
.st-key-workbench_frame [data-testid="stMetric"] {
  background: var(--wb-paper);
  border: 1px solid var(--wb-line);
  border-radius: 7px;
  padding: 12px;
}
.st-key-workbench_frame [data-testid="stMetricLabel"] p { color: var(--wb-muted); font-size: 12px; }
.st-key-workbench_frame [data-testid="stMetricValue"] { font-size: 23px; font-weight: 500; }
.st-key-workbench_frame [data-testid="stJson"] { font-size: 12px; }
.st-key-workbench_frame hr { border-color: var(--wb-line); margin: 13px 0; }

.st-key-workbench_frame [data-baseweb="tab-list"] {
  gap: 18px;
  background: transparent;
}
.st-key-workbench_frame [role="tab"] {
  background: transparent;
  min-height: 39px;
  padding: 9px 0;
  font-size: 14px;
  color: var(--wb-muted);
  font-weight: 400;
}
.st-key-workbench_frame [role="tab"][aria-selected="true"] { color: var(--wb-accent); }
.st-key-workbench_frame [data-baseweb="tab-highlight"] { height: 2px; background: var(--wb-accent); }
.st-key-workbench_frame [data-baseweb="tab-border"] { height: 1px; background: var(--wb-line); }
.st-key-workbench_frame [role="tabpanel"] { padding-top: 16px; }

/* Native horizontal radio remains a single accessible five-stage control. */
.st-key-ingest_steps [role="radiogroup"] {
  display: grid !important;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 5px;
  counter-reset: wb-step;
}
.st-key-ingest_steps label[data-baseweb="radio"] {
  counter-increment: wb-step;
  display: grid;
  align-content: center;
  justify-items: center;
  gap: 2px;
  width: 100%;
  min-width: 0;
  min-height: 56px;
  margin: 0;
  padding: 9px 5px;
  border: 1px solid var(--wb-line);
  border-radius: 5px;
  background: var(--wb-paper);
  color: var(--wb-muted);
  text-align: center;
}
.st-key-ingest_steps label[data-baseweb="radio"]::before {
  content: counter(wb-step, decimal-leading-zero);
  font-size: 11px;
  line-height: 1.2;
  color: inherit;
  font-variant-numeric: tabular-nums;
  opacity: .85;
}
.st-key-ingest_steps label[data-baseweb="radio"] p {
  margin: 0;
  color: inherit;
  font-size: 12px;
  font-weight: 500;
  line-height: 1.55;
}
.st-key-ingest_steps label[data-baseweb="radio"]:has(input:checked) {
  border-color: var(--wb-accent);
  background: var(--wb-accentbg);
  color: var(--wb-accent);
}
.st-key-ingest_steps label[data-baseweb="radio"]:hover { border-color: var(--wb-accent); }

/* Research chat is the primary surface; these keys do not affect other pages. */
.st-key-research_chat_toolbar,
.st-key-research_chat_options,
.st-key-research_chat_empty,
.st-key-research_messages,
.st-key-research_composer {
  width: 100%;
  max-width: 840px;
  min-width: 0;
  margin-left: auto;
  margin-right: auto;
}
.st-key-research_chat_toolbar { gap: 8px; }
.st-key-research_chat_options { gap: 8px; padding-bottom: 4px; }
.st-key-research_chat_toolbar [data-testid="stHorizontalBlock"],
.st-key-research_chat_options [data-testid="stHorizontalBlock"] {
  align-items: end;
  gap: 10px;
}
.st-key-research_chat_toolbar button[data-testid^="stBaseButton"],
.st-key-research_chat_options button[data-testid^="stBaseButton"] {
  font-size: 13px;
  min-height: 36px;
}
.st-key-research_chat_toolbar button p,
.st-key-research_chat_options button p { font-size: 13px; }
.st-key-research_chat_empty {
  min-height: 220px;
  padding: 38px 20px 32px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  gap: 10px;
  text-align: center;
}
.st-key-research_chat_empty :is(h2, h3) {
  font-size: 23px !important;
  line-height: 1.35;
  font-weight: 500;
  padding: 0;
  text-align: center;
}
.wb-chat-mark {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 42px;
  height: 42px;
  margin: 0 auto 8px;
  border-radius: 12px;
  color: var(--wb-accent);
  background: var(--wb-accentbg);
  font: 500 21px/1 var(--wb-font);
}
.st-key-research_chat_empty [data-testid="stMarkdownContainer"] > p,
.st-key-research_chat_empty [data-testid="stCaptionContainer"] p {
  color: var(--wb-muted);
  margin: 0 auto;
  max-width: 560px;
  line-height: 1.7;
  text-align: center;
}
.st-key-research_messages { gap: 16px; }
.st-key-research_messages [data-testid="stChatMessage"] {
  background: var(--wb-paper);
  border: 0;
  border-radius: 10px;
  box-shadow: none;
  gap: 12px;
  padding: 14px 15px;
  min-width: 0;
}
.st-key-research_messages [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]),
.st-key-research_messages [data-testid="stChatMessage"]:has([aria-label="Chat message from user"]),
.st-key-research_messages [data-testid="stChatMessage"]:has([aria-label="Chat message from human"]) {
  background: var(--wb-accentbg);
  margin-left: 36px;
  width: calc(100% - 36px);
}
.st-key-research_messages [data-testid="stChatMessageContent"] { min-width: 0; }
.st-key-research_messages [data-testid="stChatMessageContent"] :is(p, li) {
  font-size: 14px;
  line-height: 1.75;
  overflow-wrap: anywhere;
}
.st-key-research_messages [data-testid="stChatMessageAvatarUser"],
.st-key-research_messages [data-testid="stChatMessageAvatarAssistant"] {
  width: 28px;
  height: 28px;
  min-width: 28px;
  border-radius: 7px;
  background: var(--wb-accentbg);
  color: var(--wb-accent);
}
.st-key-research_messages [data-testid="stChatMessageAvatarUser"] {
  background: var(--wb-paper);
  color: var(--wb-muted);
}
.st-key-research_messages [data-testid="stCaptionContainer"] p {
  font-size: 12px;
  color: var(--wb-muted);
}
.st-key-research_composer { padding-top: 10px; gap: 6px; }
.st-key-research_composer [data-testid="stChatInput"] {
  background: transparent;
  border: 0;
  min-width: 0;
}
.st-key-research_composer [data-testid="stChatInput"] > div {
  background: var(--wb-paper);
  border: 1px solid var(--wb-line);
  border-radius: 12px;
  padding: 10px 12px;
  box-shadow: 0 2px 6px rgba(32, 48, 68, .035);
}
.st-key-research_composer [data-testid="stChatInput"]:focus-within > div {
  border-color: var(--wb-accent);
  box-shadow: 0 0 0 2px rgba(40, 93, 154, .08);
}
.st-key-research_composer [data-testid="stChatInputTextArea"] {
  color: var(--wb-text);
  background: var(--wb-paper);
  font-size: 14px;
  line-height: 1.65;
  min-height: 32px;
}
.st-key-research_composer [data-testid="stChatInputSubmitButton"] {
  width: 34px;
  height: 34px;
  min-width: 34px;
  border: 0;
  border-radius: 8px;
  background: var(--wb-accent);
  color: var(--wb-paper);
}
.st-key-research_composer [data-testid="stChatInputSubmitButton"]:disabled {
  background: var(--wb-line);
  color: var(--wb-muted);
}
.st-key-research_composer [data-testid="stCaptionContainer"] p {
  color: var(--wb-muted);
  font-size: 12px;
  line-height: 1.55;
}

/* Escaped application markup helpers, with the prototype's original tokens. */
.wb-brand { display: flex; align-items: center; flex-wrap: wrap; gap: 9px; font-size: 19px; letter-spacing: -.5px; }
.wb-brand strong { font-size: 19px; font-weight: 500; }
.wb-mark { background: var(--wb-accent); color: var(--wb-paper); padding: 2px 6px; border-radius: 6px; font-size: 13px; font-weight: 500; }
.wb-small, .wb-subtitle { font-size: 12px; color: var(--wb-muted); line-height: 1.55; }
.wb-subtitle { margin: 5px 0 4px; }
.wb-row { display: flex; align-items: center; flex-wrap: wrap; gap: 9px; }
.wb-between { justify-content: space-between; }
.wb-chip { display: inline-block; border-radius: 4px; padding: 2px 7px; font-size: 12px; color: var(--wb-accent); background: var(--wb-accentbg); line-height: 1.55; }
.wb-chip.good { color: var(--wb-good); background: var(--wb-goodbg); }
.wb-chip.warn { color: var(--wb-warn); background: var(--wb-warnbg); }
.wb-chip.muted { color: var(--wb-muted); background: var(--wb-bg); }
.wb-chip.danger { color: var(--wb-danger); background: var(--wb-paper); }
.wb-project { padding: 0 8px; display: grid; gap: 5px; }
.wb-project strong { font-size: 13px; font-weight: 500; }
.wb-card { background: var(--wb-paper); border: 1px solid var(--wb-line); border-radius: 8px; padding: 16px; min-width: 0; }
.wb-context { padding: 12px 14px; background: var(--wb-paper); border: 1px solid var(--wb-line); border-radius: 7px; }
.wb-welcome { display: grid; gap: 12px; padding: 12px 0 24px; }
.wb-welcome p { margin: 0; line-height: 1.75; }
.wb-welcome ol { margin: 4px 0; padding-left: 20px; display: grid; gap: 7px; }
.wb-kv { display: grid; grid-template-columns: 82px minmax(0, 1fr); gap: 9px 13px; margin: 12px 0; font-size: 13px; }
.wb-kv dt { color: var(--wb-muted); }
.wb-kv dd { margin: 0; overflow-wrap: anywhere; }
.wb-empty { padding: 28px 18px; border: 1px dashed var(--wb-line); border-radius: 7px; background: var(--wb-paper); display: grid; gap: 10px; text-align: center; }
.wb-note { padding: 10px 12px; border-left: 3px solid var(--wb-accent); background: var(--wb-accentbg); font-size: 12px; color: var(--wb-text); }
.wb-note.warn { border-color: var(--wb-warn); background: var(--wb-warnbg); }
.wb-provenance { font-family: ui-monospace, monospace; font-size: 11px; overflow-wrap: anywhere; color: var(--wb-muted); }
.wb-footer { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; padding: 10px 18px; background: var(--wb-paper); color: var(--wb-muted); font-size: 12px; line-height: 1.55; }

@media (max-width: 850px) {
  [data-testid="stMainBlockContainer"] { padding: 10px 10px 24px; }
  .st-key-workbench_top { padding: 12px; }
  .st-key-workbench_body > [data-testid="stHorizontalBlock"],
  .st-key-workbench_body > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] {
    flex-direction: column;
    flex-wrap: nowrap;
  }
  .st-key-workbench_body [data-testid="stColumn"]:has(.st-key-workbench_nav),
  .st-key-workbench_body [data-testid="stColumn"]:has(.st-key-workbench_main) {
    flex: 1 1 auto !important;
    width: 100% !important;
    min-width: 0;
  }
  .st-key-workbench_body [data-testid="stColumn"]:has(.st-key-workbench_nav) {
    border-right: 0;
    border-bottom: 1px solid var(--wb-line);
  }
  .st-key-workbench_nav { padding: 10px 12px; gap: 8px; }
  .st-key-workbench_nav .wb-project { display: none; }
  .st-key-workbench_nav [role="radiogroup"] {
    flex-direction: row;
    flex-wrap: nowrap;
    gap: 4px;
    overflow-x: auto;
    max-width: 100%;
    padding: 2px 0 5px;
    scrollbar-width: thin;
  }
  .st-key-workbench_nav label[data-baseweb="radio"] {
    flex: 0 0 auto;
    width: auto;
    padding: 8px 10px;
    min-height: 40px;
  }
  .st-key-workbench_nav label[data-baseweb="radio"]:nth-of-type(7) { margin-top: 0; }
  .st-key-workbench_nav label[data-baseweb="radio"]:nth-of-type(7)::after { display: none; }
  .st-key-workbench_nav_status {
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    min-height: 40px;
  }
  .st-key-workbench_nav_status > [data-testid="stElementContainer"] {
    flex: 0 1 auto !important;
    width: auto !important;
    min-width: 0;
  }
  .st-key-workbench_nav_status > [data-testid="stElementContainer"]:first-child { display: none; }
  .st-key-workbench_nav_status [data-testid="stCaptionContainer"] p { margin: 0; font-size: 12px; }
  .st-key-workbench_nav_status button[data-testid^="stBaseButton"] {
    min-height: 34px;
    padding: 5px 8px;
    font-size: 12px;
  }
  .st-key-workbench_nav_status button p { font-size: 12px; }
  .st-key-workbench_main { padding: 20px; min-height: 540px; }
  .st-key-workbench_main [class*="st-key-wb_card_"] { padding: 16px; }
  .st-key-workbench_frame h1 { font-size: 23px !important; }
  .st-key-workbench_frame [data-baseweb="tab-list"] { gap: 15px; }
  .st-key-workbench_frame [role="tab"] { font-size: 13px; }
  .st-key-research_chat_toolbar [data-testid="stHorizontalBlock"],
  .st-key-research_chat_options [data-testid="stHorizontalBlock"] {
    flex-direction: row;
    flex-wrap: wrap;
    gap: 8px;
  }
  .st-key-research_chat_toolbar [data-testid="stColumn"],
  .st-key-research_chat_options [data-testid="stColumn"] {
    width: auto !important;
    flex: 1 1 140px !important;
    min-width: 0;
  }
  .st-key-research_chat_toolbar [data-testid="stColumn"]:last-child,
  .st-key-research_chat_options [data-testid="stColumn"]:last-child {
    flex: 0 0 auto !important;
  }
  .st-key-research_chat_empty { min-height: 170px; padding: 26px 12px 30px; }
  .st-key-research_chat_empty :is(h2, h3) { font-size: 21px !important; }
  .st-key-research_messages { gap: 12px; }
  .st-key-research_messages [data-testid="stChatMessage"] { padding: 12px; gap: 9px; }
  .st-key-research_messages [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]),
  .st-key-research_messages [data-testid="stChatMessage"]:has([aria-label="Chat message from user"]),
  .st-key-research_messages [data-testid="stChatMessage"]:has([aria-label="Chat message from human"]) {
    margin-left: 12px;
    width: calc(100% - 12px);
  }
  .st-key-research_composer [data-testid="stChatInput"] > div { padding: 9px 10px; }
  .wb-kv { grid-template-columns: 70px minmax(0, 1fr); }
  .wb-brand { gap: 7px; }
  .wb-brand .wb-small { font-size: 11px; }
}
@media (max-width: 650px) {
  .st-key-workbench_main { padding: 16px; }
  .st-key-workbench_main [data-testid="stHorizontalBlock"] { flex-direction: column; }
  .st-key-workbench_main [data-testid="stColumn"] { width: 100% !important; flex: 1 1 auto !important; }
  .st-key-ingest_steps [role="radiogroup"] { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .wb-footer { padding: 10px 12px; gap: 6px 12px; }
}
@media (pointer: coarse) {
  .st-key-workbench_frame button[data-testid^="stBaseButton"],
  .st-key-workbench_nav label[data-baseweb="radio"],
  .st-key-workbench_frame [role="tab"] { min-height: 44px; }
}
"""


# Same order as the workbench's native radio: research, data, knowledge, intake,
# runs, quality, settings. SVG paths are static; no user data enters CSS or URLs.
_NAV_PATHS = (
    '<path d="M21 11.5a7.5 7.5 0 0 1-7.5 7.5H6l-4 3V11.5A7.5 7.5 0 0 1 9.5 4H14"/><path d="M14 2h8v8h-8z"/>',
    '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v7c0 4 16 4 16 0V5M4 12v7c0 4 16 4 16 0v-7"/>',
    '<rect x="9" y="2" width="6" height="6" rx="1"/><rect x="2" y="16" width="6" height="6" rx="1"/><rect x="16" y="16" width="6" height="6" rx="1"/><path d="M12 8v4M5 16v-4h14v4"/>',
    '<path d="M14 2H6a2 2 0 0 0-2 2v4M4 16v4a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6zM14 2v6h6M2 12h10M8 8l4 4-4 4"/>',
    '<path d="M9 2h6M10 2v7l-6 10a2 2 0 0 0 2 3h12a2 2 0 0 0 2-3L14 9V2M8 15h8"/>',
    '<path d="m3 12 4 4L17 6M12 16l9-9"/>',
    '<path d="M4 5h7M15 5h5M4 12h2M10 12h10M4 19h11M19 19h1"/><circle cx="13" cy="5" r="2"/><circle cx="8" cy="12" r="2"/><circle cx="17" cy="19" r="2"/>',
)


def _navigation_css() -> str:
    rules = []
    for index, paths in enumerate(_NAV_PATHS, 1):
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
               'fill="none" stroke="black" stroke-width="1.6" stroke-linecap="round" '
               f'stroke-linejoin="round">{paths}</svg>')
        uri = "data:image/svg+xml," + quote(svg, safe="")
        rules.append('.st-key-workbench_nav label[data-baseweb="radio"]'
                     f':nth-of-type({index}) {{ --wb-nav-icon: url("{uri}"); }}')
    return "\n".join(rules)


def inject_theme() -> None:
    """Inject static styles only; state, controls and accessible labels stay native."""
    st.html("<style>" + _CSS + "\n" + _navigation_css() + "</style>")


def badge_html(label: str, tone: str = "accent") -> str:
    """Return a safely escaped status badge for application-owned HTML fragments."""
    if tone not in {"accent", "good", "warn", "muted", "danger"}:
        raise ValueError("unknown badge tone")
    modifier = "" if tone == "accent" else " " + tone
    return f'<span class="wb-chip{modifier}">{escape(str(label), quote=True)}</span>'
