import csv
import base64
import hashlib
import importlib.util
import io
import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any, Dict, List, Optional

import streamlit as st
import streamlit.components.v1 as components


def _install_streamlit_compatibility() -> None:
    """Translate newer layout arguments when the local Streamlit is older."""

    import inspect
    from streamlit.delta_generator import DeltaGenerator

    if "width" not in inspect.signature(DeltaGenerator.button).parameters:
        original_button = DeltaGenerator.button
        original_st_button = st.button

        def button_compat(self, label, *args, width=None, type="secondary", **kwargs):
            if width is not None:
                kwargs["use_container_width"] = width == "stretch"
            if type == "tertiary":
                type = "secondary"
            return original_button(self, label, *args, type=type, **kwargs)

        DeltaGenerator.button = button_compat

        def st_button_compat(label, *args, width=None, type="secondary", **kwargs):
            if width is not None:
                kwargs["use_container_width"] = width == "stretch"
            if type == "tertiary":
                type = "secondary"
            return original_st_button(label, *args, type=type, **kwargs)

        st.button = st_button_compat

    if "width" not in inspect.signature(DeltaGenerator.download_button).parameters:
        original_download = DeltaGenerator.download_button
        original_st_download = st.download_button

        def download_compat(self, label, data, *args, width=None, **kwargs):
            if width is not None:
                kwargs["use_container_width"] = width == "stretch"
            return original_download(self, label, data, *args, **kwargs)

        DeltaGenerator.download_button = download_compat
        st.download_button = lambda label, data, *args, width=None, **kwargs: original_st_download(
            label,
            data,
            *args,
            use_container_width=width == "stretch" if width is not None else False,
            **kwargs,
        )

    if "width" not in inspect.signature(DeltaGenerator.popover).parameters:
        original_popover = DeltaGenerator.popover
        original_st_popover = st.popover

        def popover_compat(self, label, *args, width=None, key=None, type=None, **kwargs):
            if width is not None:
                kwargs["use_container_width"] = width == "stretch"
            return original_popover(self, label, *args, **kwargs)

        DeltaGenerator.popover = popover_compat

        def st_popover_compat(label, *args, width=None, key=None, type=None, **kwargs):
            return original_st_popover(
                label,
                *args,
                use_container_width=width == "stretch" if width is not None else False,
                **kwargs,
            )

        st.popover = st_popover_compat

    if "accept_file" not in inspect.signature(DeltaGenerator.chat_input).parameters:
        original_chat_input = DeltaGenerator.chat_input
        original_st_chat_input = st.chat_input

        def chat_input_compat(
            self,
            placeholder="Your message",
            *,
            accept_file=None,
            file_type=None,
            height=None,
            **kwargs,
        ):
            return original_chat_input(self, placeholder, **kwargs)

        DeltaGenerator.chat_input = chat_input_compat

        st.chat_input = lambda placeholder="Your message", **kwargs: original_st_chat_input(
            placeholder,
            **{
                key: value
                for key, value in kwargs.items()
                if key not in {"accept_file", "file_type", "height"}
            },
        )

    if not hasattr(st, "segmented_control"):
        st.segmented_control = lambda label, options, default=None, **kwargs: st.radio(
            label,
            options,
            index=options.index(default) if default in options else 0,
            horizontal=True,
            **kwargs,
        )


_install_streamlit_compatibility()

st.set_page_config(
    page_title="scKG-Agent",
    layout="wide",
    initial_sidebar_state="auto",
)

if "current_view" not in st.session_state:
    st.session_state.current_view = "chat"


_BASE_UI_CSS = """
    :root {
        color-scheme: light;
    }
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    button[title="Open sidebar"],
    button[title="Close sidebar"],
    button[aria-label="Open sidebar"],
    button[aria-label="Close sidebar"],
    button[aria-label="Collapse sidebar"],
    button[aria-label="Expand sidebar"] {
        display: inline-flex !important;
        visibility: visible !important;
        opacity: 1 !important;
        pointer-events: auto !important;
    }
    html,
    body,
    .stApp,
    [data-testid="stAppViewContainer"],
    [data-testid="stAppViewContainer"] > .main,
    [data-testid="stMain"],
    [data-testid="stMainBlockContainer"],
    main {
        background: #f8f9fa !important;
        color: #141413;
    }
    .stApp {
        background: #f8f9fa;
        color: #141413;
    }
    h1,
    h2,
    h3,
    p,
    li {
        letter-spacing: 0;
    }
    .app-title {
        font-size: 1.28rem;
        font-weight: 650;
        margin-bottom: 0.15rem;
        color: #171717;
    }
    .app-subtitle {
        color: #626260;
        font-size: 0.92rem;
        margin-bottom: 1.15rem;
    }
    .status-chip {
        display: inline-block;
        border: 1px solid #d8dee8;
        border-radius: 999px;
        padding: 0.16rem 0.52rem;
        margin: 0 0.28rem 0.38rem 0;
        background: #f8fafc;
        color: #334155;
        font-size: 0.78rem;
        line-height: 1.4;
    }
    .status-chip.good {
        border-color: #b8dec8;
        background: #eef8f1;
        color: #17643a;
    }
    .status-chip.warn {
        border-color: #ead29a;
        background: #fff7df;
        color: #705000;
    }
    .status-chip.bad {
        border-color: #efb9b1;
        background: #fff1ef;
        color: #8a1f11;
    }
    .data-workbench-intro {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 0;
        margin: 0.25rem 0 1.4rem;
        border: 1px solid #dedbd5;
        border-radius: 8px;
        background: #ffffff;
        overflow: hidden;
    }
    .data-workbench-step {
        min-width: 0;
        padding: 0.85rem 0.9rem;
        border-right: 1px solid #e7e4de;
    }
    .data-workbench-step:last-child {
        border-right: 0;
    }
    .data-workbench-step span {
        display: block;
        color: #77736c;
        font-size: 0.72rem;
        font-weight: 650;
        text-transform: uppercase;
        margin-bottom: 0.18rem;
    }
    .data-workbench-step strong {
        display: block;
        color: #232321;
        font-size: 0.9rem;
        font-weight: 620;
        line-height: 1.35;
    }
    .data-workbench-section-title {
        color: #242421;
        font-size: 1.02rem;
        font-weight: 650;
        margin: 1.15rem 0 0.1rem;
    }
    .data-workbench-section-copy {
        color: #716e68;
        font-size: 0.88rem;
        line-height: 1.5;
        margin-bottom: 0.65rem;
    }
    .data-workbench-boundary {
        color: #5e5b55;
        font-size: 0.84rem;
        padding: 0.65rem 0.75rem;
        margin: 0 0 0.95rem;
        border-left: 3px solid #4f8b73;
        background: #f4f8f5;
    }
    .managed-step-strip {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 0.5rem;
        margin: 0.7rem 0 0.65rem;
    }
    .managed-step {
        min-width: 0;
        padding: 0.62rem 0.7rem;
        border: 1px solid #dedbd5;
        border-radius: 6px;
        background: #ffffff;
    }
    .managed-step span {
        display: block;
        color: #77736c;
        font-size: 0.66rem;
        font-weight: 700;
        margin-bottom: 0.12rem;
    }
    .managed-step strong {
        display: block;
        color: #292825;
        font-size: 0.8rem;
        line-height: 1.3;
        overflow-wrap: anywhere;
    }
    .managed-step.done {border-color: #b8dec8; background: #eef8f1;}
    .managed-step.ready {border-color: #95b7aa; background: #f5faf8;}
    .managed-step.stale {border-color: #ead29a; background: #fff7df;}
    .managed-step.blocked,
    .managed-step.failed {border-color: #efb9b1; background: #fff1ef;}
    .quiet-note {
        color: #6b7280;
        font-size: 0.9rem;
    }
    @media (max-width: 760px) {
.data-workbench-intro {
            grid-template-columns: repeat(2, minmax(0, 1fr));
        }
    .data-workbench-step:nth-child(2) {
            border-right: 0;
        }
    .data-workbench-step:nth-child(-n + 2) {
            border-bottom: 1px solid #e7e4de;
        }
    .managed-step-strip {
            grid-template-columns: repeat(2, minmax(0, 1fr));
        }
}
    @media (max-width: 900px) {
.data-workbench-boundary,
    .data-workbench-intro {
            max-width: 100%;
        }
}
    .source-item {
        border-left: 3px solid #d8dee8;
        padding: 0.15rem 0 0.15rem 0.72rem;
        margin: 0.55rem 0;
        color: #374151;
        font-size: 0.9rem;
    }
    .source-meta {
        color: #6b7280;
        font-size: 0.82rem;
    }
    .graph-card {
        border: 1px solid #e3ded7;
        border-radius: 8px;
        padding: 0.48rem 0.58rem;
        margin-bottom: 0.38rem;
        background: #ffffff;
    }
    .graph-card strong {
        font-size: 0.92rem;
    }
    .sidebar-link-like {
        color: #313130 !important;
        border-radius: 8px;
        padding: 0.35rem 0.48rem;
    }
    .chat-nav-dot {
        display: inline-block;
        width: 0.44rem;
        color: #cc785c;
    }
    .chat-list-note {
        color: #94a3b8;
        font-size: 0.82rem;
        margin: 0.25rem 0 0.65rem;
    }
    .memory-note {
        color: #6c6a64;
        font-size: 0.82rem;
        line-height: 1.45;
        margin: 0.25rem 0 0.55rem 0;
    }
    .compact-top {
        margin-bottom: 0.8rem;
    }
    .chat-active {
        color: #111827;
        font-weight: 650;
    }
    .chat-muted {
        color: #475569;
    }
    html,
    body,
    .stApp,
    [data-testid="stAppViewContainer"],
    [data-testid="stAppViewContainer"] > .main,
    [data-testid="stMain"],
    [data-testid="stMainBlockContainer"],
    main {
        background: linear-gradient(135deg, #f0f4f9 0%, #f8f9fa 100%) !important;
        color: #172033 !important;
        font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif !important;
    }
    h1,
    h2,
    h3,
    h4,
    p,
    li {
        letter-spacing: 0 !important;
    }
    p,
    li {
        line-height: 1.72 !important;
        margin-bottom: 1.05rem;
    }
    code {
        border-radius: 8px !important;
        background: rgba(229, 237, 248, 0.74) !important;
        color: #27405f !important;
        padding: 0.12rem 0.36rem !important;
        border: 1px solid rgba(55, 83, 115, 0.06);
    }
    pre {
        border-radius: 16px !important;
        background: rgba(255, 255, 255, 0.74) !important;
        border: 1px solid rgba(0, 0, 0, 0.04) !important;
        box-shadow: 0 4px 24px rgba(0, 0, 0, 0.03) !important;
    }
    blockquote {
        border-left: 4px solid rgba(92, 146, 184, 0.38) !important;
        background: rgba(255, 255, 255, 0.54) !important;
        border-radius: 0 14px 14px 0 !important;
        padding: 0.85rem 1rem !important;
        color: #405168 !important;
        box-shadow: 0 4px 24px rgba(0, 0, 0, 0.025);
    }
    .status-chip {
        border-radius: 999px !important;
        border: 1px solid rgba(0, 0, 0, 0.045) !important;
        background: rgba(255, 255, 255, 0.62) !important;
        color: #526071 !important;
        padding: 0.24rem 0.62rem !important;
        box-shadow: 0 4px 18px rgba(0, 0, 0, 0.018);
    }
    .status-chip.good {
        background: rgba(230, 245, 237, 0.78) !important;
        color: #285b44 !important;
    }
    .status-chip.warn {
        background: rgba(255, 245, 224, 0.82) !important;
        color: #7a5624 !important;
    }
    .status-chip.bad {
        background: rgba(252, 234, 232, 0.82) !important;
        color: #8b3a35 !important;
    }
    .source-item,
    .graph-card {
        border: 1px solid rgba(0, 0, 0, 0.04) !important;
        border-radius: 16px !important;
        background: rgba(255, 255, 255, 0.72) !important;
        box-shadow: 0 4px 24px rgba(0, 0, 0, 0.03) !important;
    }
    .source-item {
        border-left: 4px solid rgba(92, 146, 184, 0.28) !important;
        padding: 0.78rem 0.95rem !important;
        margin: 0.8rem 0 !important;
    }
    div[data-testid="stDownloadButton"] button {
        border-radius: 999px !important;
        border: 1px solid rgba(0, 0, 0, 0.055) !important;
        background: rgba(255, 255, 255, 0.7) !important;
        color: #293241 !important;
        box-shadow: 0 4px 22px rgba(0, 0, 0, 0.025) !important;
        transition: transform 140ms ease, box-shadow 140ms ease, background 140ms ease !important;
    }
    div[data-testid="stDownloadButton"] button:hover {
        transform: translateY(-2px);
        background: #ffffff !important;
        box-shadow: 0 10px 28px rgba(0, 0, 0, 0.06) !important;
    }
    div[data-testid="stMetric"] {
        background: rgba(255, 255, 255, 0.62) !important;
        border: 1px solid rgba(0, 0, 0, 0.035) !important;
        border-radius: 16px !important;
        padding: 0.8rem 0.9rem !important;
        box-shadow: 0 4px 24px rgba(0, 0, 0, 0.025) !important;
    }
    .mvp-scope {
        border-left: 4px solid #4f7cac;
        padding: 0.72rem 0.9rem;
        background: rgba(255, 255, 255, 0.66);
        border-radius: 0 8px 8px 0;
        margin: 0.4rem 0 1rem;
    }
    .demo-case-title {
        font-size: 1.04rem;
        font-weight: 680;
        margin-bottom: 0.35rem;
        color: #172033;
    }
    html,
    body,
    .stApp,
    [data-testid="stAppViewContainer"],
    [data-testid="stAppViewContainer"] > .main,
    [data-testid="stMain"],
    [data-testid="stMainBlockContainer"],
    main {
        background: #f6f7f9 !important;
        color: #18212f !important;
    }
    p,
    li {
        line-height: 1.58 !important;
        margin-bottom: 0.65rem;
    }
    h2,
    h3,
    h4 {
        color: #1c2736 !important;
        margin-top: 1rem !important;
        margin-bottom: 0.55rem !important;
    }
    code,
    pre,
    blockquote,
    .source-item,
    .graph-card,
    .kg-panel,
    .sidebar-metric-card,
    div[data-testid="stMetric"] {
        border-radius: 6px !important;
        box-shadow: none !important;
    }
    div[data-testid="stMetric"] {
        background: #ffffff !important;
        border: 1px solid #dce2e9 !important;
    }
    .source-item,
    .graph-card {
        background: #ffffff !important;
        border: 1px solid #dce2e9 !important;
    }
    div[data-testid="stMetric"] {
        min-width: 0 !important;
        padding: 0.65rem 0.72rem !important;
    }
    div[data-testid="stMetric"] [data-testid="stMetricLabel"] {
        color: #687386 !important;
        font-size: 0.72rem !important;
        line-height: 1.25 !important;
        white-space: normal !important;
    }
    div[data-testid="stMetric"] [data-testid="stMetricValue"] {
        color: #172033 !important;
        font-size: 1.2rem !important;
        line-height: 1.25 !important;
        overflow-wrap: anywhere !important;
    }
    div[data-testid="stDataFrame"] {
        border: 1px solid #dce2e9 !important;
        border-radius: 6px !important;
        overflow: hidden;
    }
    div[data-testid="stTabs"] button[role="tab"] {
        min-height: 2.35rem !important;
        padding: 0.35rem 0.7rem !important;
        font-size: 0.86rem !important;
    }
    div[data-testid="stButton"] button,
    div[data-testid="stDownloadButton"] button,
    div[data-testid="stFormSubmitButton"] button,
    div[data-baseweb="select"] > div,
    div[data-baseweb="input"] > div,
    div[data-baseweb="base-input"] {
        border-radius: 6px !important;
        box-shadow: none !important;
    }
    div[data-testid="stButton"] button:hover,
    div[data-testid="stDownloadButton"] button:hover {
        transform: none !important;
        box-shadow: none !important;
    }
    .mvp-scope {
        border: 1px solid #dce2e9 !important;
        border-left: 3px solid #18766f !important;
        border-radius: 0 6px 6px 0 !important;
        background: #ffffff !important;
        padding: 0.62rem 0.8rem !important;
    }
    .workflow-stepper {
        display: grid;
        grid-template-columns: repeat(9, minmax(0, 1fr));
        gap: 0;
        margin: 0.45rem 0 1rem;
        border: 1px solid #dce2e9;
        border-radius: 6px;
        overflow: hidden;
        background: #fff;
    }
    .workflow-step {
        min-width: 0;
        padding: 0.55rem 0.45rem;
        border-right: 1px solid #e4e8ed;
        color: #586577;
        font-size: 0.68rem;
        line-height: 1.25;
    }
    .workflow-step:last-child { border-right: 0; }
    .workflow-step b {
        display: block;
        color: #18766f;
        font-size: 0.66rem;
        margin-bottom: 0.2rem;
    }
    @media (max-width: 900px) {
.workflow-stepper { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    .workflow-step { border-bottom: 1px solid #e4e8ed; }
}
    @media (max-width: 620px) {
.workflow-stepper { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
    .algorithm-surface-title {
        max-width: 850px;
        margin: 0.85rem auto 0.45rem;
        color: #687386;
        font-size: 0.72rem;
        font-weight: 700;
        text-transform: uppercase;
    }
    .algorithm-grid {
        max-width: 850px;
        margin: 0 auto 0.8rem;
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 0.55rem;
    }
    .algorithm-card {
        min-width: 0;
        padding: 0.7rem 0.75rem;
        border: 1px solid #dce2e9;
        border-radius: 7px;
        background: #ffffff;
    }
    .algorithm-card .algorithm-name {
        color: #18212f;
        font-size: 0.9rem;
        font-weight: 700;
        margin-bottom: 0.32rem;
    }
    .algorithm-card .algorithm-meta {
        color: #687386;
        font-size: 0.72rem;
        line-height: 1.42;
        margin-top: 0.24rem;
    }
    .algorithm-card .algorithm-boundary {
        display: inline-block;
        margin-top: 0.48rem;
        color: #165d58;
        font-size: 0.66rem;
        font-weight: 700;
    }
    @media (max-width: 700px) {
.algorithm-grid { grid-template-columns: 1fr; }
}

    /* Product shell: one width owner per surface. Wide workbenches remain wide. */
    :root { --research-width: 850px; --workspace-gutter: 32px; }
    [data-testid="stHeader"] {
        background: transparent;
        pointer-events: none;
    }
    [data-testid="stHeader"] button { pointer-events: auto; }
    [data-testid="stDeployButton"], [data-testid="stAppDeployButton"],
    [data-testid="stMainMenu"], [data-testid="stDecoration"] { display: none; }
    [data-testid="stSidebarCollapseButton"] { display: flex; visibility: visible; }
    .block-container {
        max-width: 1320px;
        padding: 1.25rem var(--workspace-gutter) 3rem;
    }
    /* :has keeps routing and Streamlit's wide workbench layout independent. */
    .block-container:has(.research-chat-layout) {
        max-width: calc(var(--research-width) + 2 * var(--workspace-gutter));
    }
    .chat-app-header {
        margin: 0 0 0.35rem;
        padding: 0.15rem 0 0.9rem;
        border-bottom: 1px solid #dbe1e8;
    }
    .chat-app-kicker {
        color: #607086;
        font-size: 0.7rem;
        font-weight: 700;
        margin-bottom: 0.3rem;
        text-transform: uppercase;
    }
    .chat-app-title {
        color: #172033;
        font-size: clamp(1.45rem, 2vw, 1.85rem);
        font-weight: 680;
        line-height: 1.2;
    }
    .chat-app-subtitle {
        color: #687386;
        font-size: 0.9rem;
        line-height: 1.55;
        margin-top: 0.4rem;
        max-width: 850px;
    }
    .research-routing {
        color: #687386;
        font-size: 0.82rem;
        line-height: 1.5;
    }
    .research-routing strong { color: #165d58; margin-right: 0.6rem; }
    [data-testid="stMarkdownContainer"]:has(> .research-routing),
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] { margin-bottom: 0; }
    /* Native border=False containers must stay borderless. Only details own a frame. */
    [data-testid="stExpander"] details {
        border: 1px solid #dce2e9;
        border-radius: 8px;
        background: #fff;
    }
    [data-testid="stExpander"] summary p { margin: 0; font-size: 0.86rem; }
    .user-chat-row {
        display: flex;
        justify-content: flex-end;
        width: 100%;
        margin: 0.6rem 0 0.4rem;
    }
    .user-chat-bubble {
        max-width: min(88%, 740px);
        background: #eaf1f1;
        color: #20242c;
        border: 1px solid #dce7e6;
        border-radius: 14px 14px 4px 14px;
        padding: 0.75rem 1rem;
        line-height: 1.6;
        overflow-wrap: anywhere;
        white-space: pre-wrap;
    }
    .user-chat-attachments {
        color: #687386;
        font-size: 0.82rem;
        margin-top: 0.4rem;
        border-top: 1px solid #dce7e6;
        padding-top: 0.4rem;
    }
    [data-testid="stChatMessage"] {
        background: transparent;
        border: 0;
        padding: 0.5rem 0;
        margin: 0;
        min-width: 0;
    }
    [data-testid="stChatMessageContent"] {
        min-width: 0;
        color: #20242c;
        line-height: 1.62;
        overflow-wrap: anywhere;
    }
    [data-testid="stChatMessageContent"] h2,
    [data-testid="stChatMessageContent"] h3 { font-size: 1.05rem; }
    [data-testid="stChatMessageContent"] code { overflow-wrap: anywhere; }
    /* Streamlit 1.37 sizes the inner input from a measured parent width.
       Constrain that parent, and explicitly let the inner shell shrink with it. */
    [data-testid="stBottom"], [data-testid="stBottom"] > div {
        padding: 0;
        background: transparent;
    }
    [data-testid="stBottomBlockContainer"] {
        box-sizing: border-box;
        width: 100%;
        max-width: calc(var(--research-width) + 2 * var(--workspace-gutter));
        margin: 0 auto;
        padding: 0.75rem var(--workspace-gutter) 1rem;
        background: #f6f7f9;
    }
    [data-testid="stChatInput"] {
        width: 100%;
        max-width: 100%;
        min-width: 0;
        padding: 0;
        margin: 0;
        background: transparent;
        border: 0;
    }
    [data-testid="stChatInput"] > div {
        box-sizing: border-box;
        width: 100%;
        max-width: 100%;
        min-width: 0;
        min-height: 56px;
        background: #fff;
        border: 1px solid #cdd3da;
        border-radius: 14px;
        box-shadow: 0 2px 8px rgba(24, 33, 47, 0.04);
    }
    [data-testid="stChatInput"] [data-baseweb="textarea"],
    [data-testid="stChatInput"] [data-baseweb="base-input"] {
        min-width: 0;
        background: transparent;
        border: 0;
        box-shadow: none;
    }
    [data-testid="stChatInput"] textarea {
        min-height: 54px;
        background: transparent;
        color: #20242c;
        line-height: 1.5;
    }
    [data-testid="stChatInput"]:focus-within > div {
        border-color: #18766f;
        box-shadow: 0 0 0 2px rgba(24, 118, 111, 0.12);
    }
    /* One composer surface, including attachments and the add button.
       Match only the container that directly owns our marker (Streamlit 1.37). */
    [data-testid="stVerticalBlockBorderWrapper"]:has(> div > [data-testid="stVerticalBlock"] > [data-testid="element-container"] .research-composer-marker) {
        border: 1px solid #d6d3ce;
        border-radius: 20px;
        padding: 8px 12px;
        background: #fff;
        box-shadow: 0 3px 12px rgba(24, 33, 47, 0.04);
    }
    [data-testid="stVerticalBlock"]:has(> [data-testid="element-container"] .research-composer-marker) {
        gap: 4px;
    }
    [data-testid="element-container"]:has(.research-composer-marker),
    [data-testid="element-container"]:has(.research-upload-menu) { display: none; }
    [data-testid="stVerticalBlock"]:has(> [data-testid="element-container"] .research-composer-marker) > [data-testid="stHorizontalBlock"] {
        flex-wrap: nowrap;
        align-items: end;
        gap: 6px;
    }
    [data-testid="stVerticalBlock"]:has(> [data-testid="element-container"] .research-composer-marker) > [data-testid="stHorizontalBlock"] > [data-testid="column"]:first-child {
        flex: 0 0 38px;
        min-width: 38px;
        width: 38px;
        padding-bottom: 8px;
    }
    [data-testid="stVerticalBlock"]:has(> [data-testid="element-container"] .research-composer-marker) > [data-testid="stHorizontalBlock"] > [data-testid="column"]:last-child {
        flex: 1 1 0;
        min-width: 0;
        width: 0;
    }
    [data-testid="stVerticalBlock"]:has(> [data-testid="element-container"] .research-composer-marker) [data-testid="stChatInput"] > div {
        border: 0;
        border-radius: 0;
        box-shadow: none;
        background: transparent;
    }
    [data-testid="stVerticalBlockBorderWrapper"]:has(> div > [data-testid="stVerticalBlock"] > [data-testid="element-container"] .research-composer-marker):focus-within {
        border-color: #9aada9;
    }
    [data-testid="stVerticalBlock"]:has(> [data-testid="element-container"] .research-composer-marker) [data-testid="stPopover"] button {
        width: 38px;
        height: 38px;
        min-height: 38px;
        padding: 0;
        border: 0;
        border-radius: 50%;
        background: transparent;
    }
    [data-testid="stVerticalBlock"]:has(> [data-testid="element-container"] .research-composer-marker) [data-testid="stPopover"] button:hover { background: #f0efec; }
    [data-testid="stVerticalBlock"]:has(> [data-testid="element-container"] .research-composer-marker) [data-testid="stPopover"] button p { font-size: 26px; margin: 0; }
    [data-testid="stVerticalBlock"]:has(> [data-testid="element-container"] .research-composer-marker) [data-testid="stPopover"] button svg { display: none; }
    .research-attachment-list { display: flex; flex-wrap: wrap; gap: 6px; padding: 4px 4px 0; }
    .research-attachment-chip {
        max-width: 100%; padding: 5px 10px; border: 1px solid #e7e5e0;
        border-radius: 9px; background: #f7f7f5; font-size: 0.8rem;
        overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    }
    [data-testid="element-container"]:has(.research-attachments-marker) { display: none; }
    [data-testid="stVerticalBlock"]:has(> [data-testid="element-container"] .research-attachments-marker) > [data-testid="stHorizontalBlock"] { flex-wrap: nowrap; gap: 4px; align-items: center; }
    [data-testid="stVerticalBlock"]:has(> [data-testid="element-container"] .research-attachments-marker) [data-testid="column"]:first-child { flex: 1 1 0; min-width: 0; }
    [data-testid="stVerticalBlock"]:has(> [data-testid="element-container"] .research-attachments-marker) [data-testid="column"]:last-child { flex: 0 0 30px; min-width: 30px; }
    [data-testid="stVerticalBlock"]:has(> [data-testid="element-container"] .research-attachments-marker) button { border: 0; padding: 0; min-height: 30px; width: 30px; background: transparent; }
    [data-testid="stPopoverBody"]:has(.research-upload-menu) {
        box-sizing: border-box;
        width: min(340px, calc(100vw - 32px));
        min-width: 0;
        max-height: min(560px, calc(100dvh - 32px));
        overflow: auto;
        padding: 12px;
        border-radius: 14px;
    }
    [data-testid="stPopoverBody"]:has(.research-upload-menu) [data-testid="stVerticalBlock"] { gap: 10px; }
    [data-testid="stPopoverBody"]:has(.research-upload-menu) [data-testid="stFileUploaderDropzone"] {
        padding: 0; min-height: 40px; background: transparent;
    }
    [data-testid="stPopoverBody"]:has(.research-upload-menu) [data-testid="stFileUploaderDropzoneInstructions"] { display: none; }
    [data-testid="stPopoverBody"]:has(.research-upload-menu) [data-testid="stFileUploaderDropzone"] button {
        width: 100%; min-height: 40px; border-radius: 8px;
    }
    [data-testid="stPopoverBody"]:has(.research-upload-menu) [data-testid="stCaptionContainer"] p { font-size: 0.75rem; margin: 0; }
    [data-testid="stPopoverBody"]:has(.research-upload-menu) [data-testid="stExpander"] details { border: 0; }
    section[data-testid="stSidebar"] {
        width: 288px !important; /* Native resizable sidebar uses an inline width. */
        min-width: 288px;
        max-width: 288px;
        background: #fff;
        border-right: 1px solid #dce2e9;
    }
    /* The native collapse translation uses the pre-CSS sidebar width. Remove
       the collapsed panel from flow and translate its actual width. */
    section[data-testid="stSidebar"][aria-expanded="false"] {
        position: absolute !important;
        transform: translateX(-100%);
    }
    [data-testid="stSidebarHeader"] { height: 2.75rem; padding: 0.45rem 1rem; }
    [data-testid="stSidebarUserContent"] { padding: 0.25rem 1rem 1rem; }
    [data-testid="stSidebarUserContent"] [data-testid="stVerticalBlock"] { gap: 0.35rem; }
    .sidebar-brand {
        display: flex;
        align-items: center;
        gap: 0.6rem;
        margin: 0 0 0.45rem;
        min-height: 56px;
    }
    .sidebar-logo { width: 56px; height: 56px; overflow: hidden; flex-shrink: 0; }
    .sidebar-brand img { width: 88px; height: 88px; max-width: none; margin: -16px; object-fit: contain; }
    .sidebar-brand-title { font-size: 0.94rem; font-weight: 700; color: #172033; }
    .sidebar-brand-subtitle { font-size: 0.68rem; color: #687386; }
    .sidebar-section {
        color: #7b8798;
        font-size: 0.64rem;
        font-weight: 650;
        margin: 0;
        padding: 0.55rem 0 0.15rem;
        text-transform: uppercase;
    }
    [data-testid="stSidebar"] hr { margin: 0.65rem 0; }
    [data-testid="stSidebar"] [data-testid="stButton"] button {
        width: 100%;
        min-height: 2.25rem;
        padding: 0.35rem 0.5rem;
        border: 1px solid transparent;
        border-radius: 6px;
        background: transparent;
        color: #313b49;
        text-align: left;
        justify-content: flex-start;
        box-shadow: none;
    }
    [data-testid="stSidebar"] [data-testid="stButton"] button p {
        font-size: 0.84rem;
        line-height: 1.4;
        margin: 0;
        text-align: left;
    }
    [data-testid="stSidebar"] [data-testid="stButton"] button:hover { background: #f2f5f7; }
    [data-testid="stSidebar"] [data-testid="stButton"] button[kind="primary"] {
        background: #e8f2f0;
        border-color: #bcd8d3;
        color: #165d58;
    }
    [data-testid="stSidebar"] details { background: transparent; }
    [data-testid="stSidebar"] details summary { padding: 0.45rem 0.5rem; }
    /* Scope conversation columns to rows with a menu; settings columns remain usable. */
    [data-testid="stSidebar"] [data-testid="stHorizontalBlock"]:has([data-testid="stPopover"]) {
        gap: 0.25rem;
        flex-wrap: nowrap;
        align-items: center;
    }
    [data-testid="stSidebar"] [data-testid="stHorizontalBlock"]:has([data-testid="stPopover"]) > div:first-child {
        min-width: 0;
        flex: 1 1 0;
    }
    [data-testid="stSidebar"] [data-testid="stHorizontalBlock"]:has([data-testid="stPopover"]) > div:last-child {
        min-width: 32px;
        max-width: 32px;
        flex: 0 0 32px;
    }
    [data-testid="stSidebar"] [data-testid="stHorizontalBlock"]:has([data-testid="stPopover"]) [data-testid="stButton"] button p {
        display: -webkit-box;
        -webkit-line-clamp: 2;
        -webkit-box-orient: vertical;
        overflow: hidden;
        white-space: normal;
        overflow-wrap: anywhere;
    }
    [data-testid="stSidebar"] [data-testid="stPopover"] button {
        width: 32px;
        height: 32px;
        min-height: 32px;
        padding: 0;
        border: 0;
        background: transparent;
    }
    [data-testid="stSidebar"] [data-testid="stPopover"] button p { font-size: 0; margin: 0; }
    [data-testid="stSidebar"] [data-testid="stPopover"] button p::after {
        content: "\\22EF";
        font-size: 1.15rem;
        color: #687386;
    }
    [data-testid="stSidebar"] [data-testid="stPopover"] button svg { display: none; }
    [data-testid="stSidebar"] button:focus-visible {
        outline: 2px solid #18766f;
        outline-offset: 2px;
    }
    @media (max-width: 900px) { :root { --workspace-gutter: 20px; } }
    @media (max-width: 640px) {
        :root { --workspace-gutter: 16px; }
        .block-container { padding-top: 3rem; }
        section[data-testid="stSidebar"] {
            width: min(88vw, 288px) !important;
            min-width: min(88vw, 288px);
            max-width: min(88vw, 288px);
        }
        .user-chat-bubble { max-width: 95%; }
        [data-testid="stChatMessage"] { gap: 0.4rem; }
        [data-testid="stChatMessageAvatarAssistant"] { width: 24px; height: 24px; }
    }
"""

from observability.dashboard.research_shell import (
    render_app_styles, summary_model, stage_html, information_html, render_plan_overview, render_reply_overview, current_workspace_plan,
)
render_app_styles(_BASE_UI_CSS, current_view=st.session_state.current_view)


LANGGRAPH_AVAILABLE = importlib.util.find_spec("langgraph") is not None
from core.reflection_memory import reflect_agent_run
from core.privacy_policy import OutboundDisclosureService, PrivacyMode
from core.settings import get_settings
from core.tool_contract_registry import ToolContractRegistry
from core.user_store import (
    ApiConfigError,
    clear_conversation,
    create_session,
    delete_session,
    has_saved_api_config,
    init_store,
    list_sessions,
    load_api_config,
    load_conversation,
    load_project_memory,
    load_working_context,
    save_encrypted_api_config,
    save_message,
    save_project_memory,
    save_working_context,
    rename_session,
    set_session_pinned,
)
from engine.knowledge_graph_view import (
    build_catalog_landscape_html,
    build_decision_graph_neighborhood_view,
    build_decision_graph_workspace_view,
    build_knowledge_graph_html,
    build_knowledge_graph_view,
)
from engine.scientific_graph_viewer import (
    ScientificGraphViewerConfig,
    build_scientific_graph_viewer_html,
)
from engine.scientific_kg_admin import ScientificKGAdminSnapshotService
from engine.ontology_manager import (
    OntologyIntegrityError,
    OntologyManagerReadOnlyService,
    build_ontology_schema_graph_html,
)
from engine.scientific_knowledge_studio import (
    candidate_demo_view,
    load_studio_evaluation_snapshot,
    proposal_graph_view,
)
from ingestion.scientific_documents import ScientificDocumentIngestionService
from engine.decision_graph_query import DecisionGraphQuery
from engine.action_bundle_retriever import ActionBundleRetriever
from engine.evidence_graph_query import EvidenceGraphQuery
from execution.environment_registry import EnvironmentRegistry
from engine.workflow_decision import (
    DEFAULT_WORKFLOW_CANDIDATE_TOOLS,
    build_workflow_decision_response,
)
from observability.dashboard.services import (
    AgentLoopDemoService,
    DefenseDemoService,
    InterviewDemoService,
    Phase6EvaluationService,
    ReflectionService,
    TraceService,
)
from observability.dashboard.ui_presenters import (
    format_conversation_title,
    normalize_ui_status,
)




EXAMPLES = {
    "Doublet method": "我有一批 10x PBMC scRNA-seq 数据，应该用什么方法检测 doublet？请说明证据和限制。",
    "Doublet workflow": "请为 10x PBMC 数据生成一个 doublet detection workflow。",
    "Batch integration": "我有三个 scRNA-seq 批次，希望整合后保留细胞类型差异，应该选择 Harmony 还是 Scanorama？",
    "Top-3 caveats": "doublet detection 里 top-3 工具的 caveat 分别是什么？",
}


WELCOME_MESSAGE = (
    "你好！直接告诉我你的单细胞分析问题。我可以结合科学知识和原文证据讨论方法，"
    "也可以帮你准备分析计划；实际运行前会请你确认数据和计划。"
)


def _run_agent(
    user_query: str,
    offline_llm: bool,
    *,
    agent_mode: Optional[str] = None,
    user_id: str = "local-research-user",
    conversation_id: str = "local-conversation",
    artifact_id: Optional[str] = None,
    requested_tool: Optional[str] = None,
    conversation_context: Optional[List[Dict[str, Any]]] = None,
    project_memory: Optional[Dict[str, Any]] = None,
    uploaded_context: Optional[Dict[str, Any]] = None,
    user_runtime_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    runtime_config = dict(user_runtime_config or {})
    runtime_config["offline_llm"] = offline_llm
    if offline_llm:
        runtime_config["privacy_authorized"] = False
    state = _research_agent_backend().run(
        user_query,
        mode=agent_mode,
        user_id=user_id,
        conversation_id=conversation_id,
        artifact_id=artifact_id,
        requested_tool=requested_tool,
        project_memory=project_memory,
        uploaded_context=uploaded_context,
        conversation_context=conversation_context,
        user_runtime_config=runtime_config,
    )
    try:
        reflection = reflect_agent_run(
            state,
            str(state.get("canonical_trace_id") or ""),
        )
        state["reflection_event"] = reflection.model_dump(mode="json")
    except Exception as exc:
        state["reflection_error"] = f"{type(exc).__name__}: {exc}"
    return dict(state)


def _state_get_list(state: Dict[str, Any], key: str) -> List[Any]:
    value = state.get(key, [])
    return value if isinstance(value, list) else []


def _as_dict(item: Any) -> Dict[str, Any]:
    if isinstance(item, dict):
        return item
    if hasattr(item, "model_dump"):
        return item.model_dump(mode="json")
    return {}


def _context_pack(state: Dict[str, Any]) -> Dict[str, Any]:
    pack = state.get("context_pack") or state.get("evidence_context_pack") or {}
    if hasattr(pack, "model_dump"):
        pack = pack.model_dump(mode="json")
    return pack if isinstance(pack, dict) else {}


def _constraints(state: Dict[str, Any]) -> Dict[str, Any]:
    pack = _context_pack(state)
    constraints = pack.get("parsed_constraints") or state.get("extracted_constraints") or {}
    if hasattr(constraints, "model_dump"):
        constraints = constraints.model_dump(mode="json")
    return constraints if isinstance(constraints, dict) else {}


def _ranked_tools(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    pack = _context_pack(state)
    trusted = pack.get("trusted_recommendation_context") or {}
    tools = trusted.get("ranked_tools")
    if isinstance(tools, list) and tools:
        return [_as_dict(tool) for tool in tools]

    rows = []
    for item in _state_get_list(state, "scored_tools"):
        tool = _as_dict(item)
        rows.append(
            {
                "tool_name": tool.get("tool_name", "Unknown"),
                "rank": tool.get("rank"),
                "mcdm_score": tool.get("score"),
                "recommendation_confidence": tool.get("recommendation_confidence", "low"),
                "missing_evidence": (tool.get("evidence") or {}).get("missing_evidence", []),
            }
        )
    return rows


def _workflow_steps(state: Dict[str, Any]) -> List[str]:
    pack = _context_pack(state)
    trusted = pack.get("trusted_recommendation_context") or {}
    workflow = trusted.get("workflow") or {}
    if isinstance(workflow, dict):
        steps = workflow.get("steps") or []
        names = [str(step.get("name")) for step in steps if isinstance(step, dict) and step.get("name")]
        if names:
            return names
    return [str(item) for item in state.get("workflow_steps", []) if item]


def _migration_paths(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    pack = _context_pack(state)
    migration = pack.get("migration_context") or {}
    paths = migration.get("paths")
    if isinstance(paths, list):
        return [_as_dict(path) for path in paths]
    return [_as_dict(path) for path in _state_get_list(state, "migration_paths")]


def _rag_snippets(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    pack = _context_pack(state)
    retrieval = pack.get("retrieval_context") or {}
    formal_rag = retrieval.get("formal_rag_context") or {}
    snippets = formal_rag.get("snippets") or []
    return [_as_dict(snippet) for snippet in snippets if isinstance(snippet, dict)]


def _missing_evidence(state: Dict[str, Any]) -> List[str]:
    pack = _context_pack(state)
    missing = pack.get("missing_evidence") or state.get("missing_components") or []
    if not isinstance(missing, list):
        return []
    return [str(item) for item in missing if item]


def _audit_summary(state: Dict[str, Any]) -> Dict[str, Any]:
    audit = (
        state.get("claim_audit")
        or (_context_pack(state).get("grounded_answer_audit") or {})
        or state.get("hallucination_audit")
        or {}
    )
    if hasattr(audit, "model_dump"):
        audit = audit.model_dump(mode="json")
    return audit if isinstance(audit, dict) else {}


@st.cache_data(show_spinner=False)
def _graph_inventory() -> Dict[str, int]:
    data_dir = get_settings().data_dir
    publications = _count_tsv_rows(data_dir / "tool_publications.tsv")
    benchmarks = _count_tsv_rows(data_dir / "tool_benchmarks.tsv")
    tools = _count_unique_tsv_values(data_dir / "scrna_tools.tsv", "Tool")
    pub_tools = _count_unique_tsv_values(data_dir / "tool_publications.tsv", "tool_name")
    bench_tools = _count_unique_tsv_values(data_dir / "tool_benchmarks.tsv", "tool_name")
    candidate_rows = _count_candidate_evidence(data_dir / "evidence_candidates")
    graph_inventory = build_knowledge_graph_view(
        data_dir,
        selected_kinds=("Tool", "Task"),
        max_nodes=1,
    ).inventory
    task_values = set()
    for path in [data_dir / "tool_publications.tsv", data_dir / "tool_benchmarks.tsv"]:
        task_values.update(_unique_tsv_terms(path, "task"))
    return {
        "tools": max(tools, pub_tools, bench_tools),
        "tasks": len(task_values),
        "publications": publications,
        "benchmarks": benchmarks,
        "candidate_evidence": candidate_rows,
        "edges": graph_inventory.get("edges", 0),
    }


def _count_candidate_evidence(candidate_dir: Path) -> int:
    if not candidate_dir.exists():
        return 0
    candidate_ids = set()
    for path in _candidate_evidence_files(candidate_dir):
        if "publication_candidates" in path.name:
            id_field = "publication_id"
        elif "benchmark_candidates" in path.name:
            id_field = "benchmark_id"
        else:
            continue
        with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            for index, row in enumerate(reader):
                record_id = " ".join(str(row.get(id_field, "") or "").split())
                candidate_ids.add(record_id or f"{path.name}:{index}")
    return len(candidate_ids)


def _candidate_evidence_files(candidate_dir: Path) -> List[Path]:
    if not candidate_dir.exists():
        return []
    return [
        path
        for path in candidate_dir.glob("*.tsv")
        if "tool_publication_candidates" in path.name
        or "tool_benchmark_candidates" in path.name
    ]


@st.cache_data(show_spinner=False)
def _kg_view(selected_kinds: tuple[str, ...], search: str, max_nodes: int):
    return build_knowledge_graph_view(
        get_settings().data_dir,
        selected_kinds=selected_kinds,
        search=search,
        max_nodes=max_nodes,
    )


def _count_tsv_rows(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        return max(sum(1 for _ in handle) - 1, 0)


def _count_unique_tsv_values(path: Path, field: str) -> int:
    return len(_unique_tsv_values(path, field))


def _unique_tsv_values(path: Path, field: str) -> set[str]:
    if not path.exists():
        return set()
    values = set()
    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if not reader.fieldnames or field not in reader.fieldnames:
            return set()
        for row in reader:
            value = (row.get(field) or "").strip()
            if value:
                values.add(value)
    return values


def _unique_tsv_terms(path: Path, field: str) -> set[str]:
    if not path.exists():
        return set()
    values = set()
    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if not reader.fieldnames or field not in reader.fieldnames:
            return set()
        for row in reader:
            raw = str(row.get(field, "") or "")
            for part in raw.split(";"):
                value = " ".join(part.split()).strip()
                if value:
                    values.add(value)
    return values


def _render_chip(text: str, kind: str = "") -> None:
    safe_text = escape(str(text))
    st.markdown(
        f'<span class="status-chip {kind}">{safe_text}</span>',
        unsafe_allow_html=True,
    )


def _fmt_score(value: Any) -> str:
    try:
        return f"{float(value):.3f}"
    except Exception:
        return "NA"


def _compact(value: Any, limit: int = 220) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _clean_report(report: str) -> str:
    replacements = {
        "## scKG Hybrid KG-RAG Report": "## 分析结果",
        "## scKG Structured Scientific Output": "## 分析结果",
        "- report_status: offline_context_pack_report\n": "",
        "- report_status: offline_llm_structured_report\n": "",
        "- safety_note: generated without paid LLM calls from EvidenceContextPack only.": (
            "- 安全说明：当前回答由受控 EvidenceContextPack 生成，未调用付费 LLM。"
        ),
        "- safety_note: generated without LLM calls from structured evidence only.": (
            "- 安全说明：当前回答由结构化证据生成，未调用 LLM。"
        ),
    }
    cleaned = report or ""
    for old, new in replacements.items():
        cleaned = cleaned.replace(old, new)
    cleaned = cleaned.replace("- recommendation_type:", "- 推荐类型:")
    cleaned = cleaned.replace("- ranked_tools:", "- 推荐工具:")
    cleaned = cleaned.replace("- workflow_steps:", "- 工作流:")
    cleaned = cleaned.replace("- missing_evidence:", "- 缺失证据:")
    cleaned = cleaned.replace("- guardrails:", "- 安全边界:")
    cleaned = cleaned.replace("- retrieval_context:", "- 文献/协议补充:")
    cleaned = cleaned.replace("- rag_snippet:", "- 来源片段:")
    cleaned = cleaned.replace("- migration_hypotheses:", "- 探索性迁移假设:")
    cleaned = cleaned.replace("- migration_claim_boundary:", "- 迁移边界:")
    cleaned = cleaned.replace("- prompt_policy_forbidden:", "- 禁止外推:")
    return cleaned.strip()


def _conversation_context(
    messages: List[Dict[str, Any]],
    limit: int = 8,
) -> List[Dict[str, Any]]:
    usable: List[Dict[str, Any]] = []
    for item in messages:
        if item.get("role") not in {"user", "assistant"} or not item.get("content"):
            continue
        if item.get("role") == "assistant" and item.get("content") == WELCOME_MESSAGE:
            continue
        row: Dict[str, Any] = {
            "role": item.get("role", ""),
            "content": item.get("content", ""),
        }
        state = item.get("state")
        if isinstance(state, dict):
            context_pack = state.get("context_pack") or {}
            conversation_state = state.get("conversation_state") or (
                context_pack.get("conversation_state")
                if isinstance(context_pack, dict)
                else None
            )
            if isinstance(conversation_state, dict):
                row["conversation_state"] = conversation_state
            constraints = state.get("extracted_constraints") or {}
            canonical_task = constraints.get("canonical_task")
            if canonical_task and canonical_task != "Unknown":
                row["canonical_task"] = canonical_task
        usable.append(row)
    return usable[-limit:]


def _suggest_followups(state: Dict[str, Any], query: str = "") -> List[str]:
    constraints = _constraints(state)
    task = constraints.get("task", "这个任务")
    suggestions = [
        "这条推荐背后的 benchmark/DOI 证据有哪些？",
        "还有哪些关键证据缺口会影响这个结论？",
        "请把这个分析整理成一个可执行 workflow。",
    ]
    if _migration_paths(state):
        suggestions.insert(0, "这些迁移假设需要怎么设计验证实验？")
    elif _ranked_tools(state):
        suggestions.insert(0, f"{task} 里 top-3 工具的 caveat 分别是什么？")
    else:
        suggestions.insert(0, "我需要补充哪些信息才能得到更可靠推荐？")
    if "benchmark" not in " ".join(suggestions).lower():
        suggestions.append("只看有 benchmark 的工具，结果会怎么变？")
    return suggestions[:4]


def _summarize_upload(uploaded_file: Any) -> Dict[str, Any]:
    raw = uploaded_file.getvalue()
    name = uploaded_file.name
    suffix = Path(name).suffix.lower()
    summary: Dict[str, Any] = {
        "file_name": name,
        "file_type": suffix or "unknown",
        "size_bytes": len(raw),
        "status": "parsed",
    }
    if suffix in {".txt", ".md"}:
        text = raw.decode("utf-8", errors="replace")
        summary["text_preview"] = _compact(text, 1200)
        summary["line_count"] = len(text.splitlines())
    elif suffix in {".csv", ".tsv"}:
        delimiter = "," if suffix == ".csv" else "\t"
        text = raw.decode("utf-8", errors="replace")
        reader = csv.reader(io.StringIO(text), delimiter=delimiter)
        rows = []
        for idx, row in enumerate(reader):
            rows.append(row[:12])
            if idx >= 5:
                break
        summary["preview_rows"] = rows
        summary["columns"] = rows[0] if rows else []
    elif suffix in {".json", ".jsonl"}:
        text = raw.decode("utf-8", errors="replace")
        if suffix == ".jsonl":
            lines = [line for line in text.splitlines() if line.strip()]
            summary["record_count_preview"] = len(lines)
            summary["text_preview"] = _compact("\n".join(lines[:5]), 1200)
        else:
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    summary["top_level_keys"] = list(parsed.keys())[:20]
                elif isinstance(parsed, list):
                    summary["list_length"] = len(parsed)
                summary["text_preview"] = _compact(json.dumps(parsed, ensure_ascii=False)[:2000], 1200)
            except Exception as exc:
                summary["status"] = "parse_warning"
                summary["warning"] = f"JSON parse failed: {exc}"
                summary["text_preview"] = _compact(text, 1200)
    elif suffix == ".pdf":
        summary["status"] = "unsupported_preview_only"
        summary["warning"] = "PDF deep parsing is not enabled in v0.13; only file metadata is stored."
    else:
        summary["status"] = "unsupported"
        summary["warning"] = "This file type is not parsed in v0.13."
    return summary


def _render_sources_and_caveats(
    state: Dict[str, Any],
    *,
    runtime: Optional[float] = None,
    show_debug: bool = False,
) -> None:
    if not state:
        return

    with st.expander("Sources, caveats, and audit", expanded=False):
        constraints = _constraints(state)
        if constraints:
            cols = st.columns(3)
            with cols[0]:
                _render_chip(f"task: {constraints.get('task', 'Unknown')}")
            with cols[1]:
                _render_chip(f"modality: {constraints.get('modality', 'Unknown')}")
            with cols[2]:
                _render_chip(f"state: {constraints.get('clarification_state', 'Unknown')}")

        ranked = _ranked_tools(state)
        workflow_steps = _workflow_steps(state)
        migrations = _migration_paths(state)

        if ranked:
            st.markdown("**Recommended tools**")
            for tool in ranked[:5]:
                label = str(tool.get("tool_name", "Unknown"))
                rank = tool.get("rank")
                score = tool.get("mcdm_score", tool.get("score"))
                confidence = tool.get("recommendation_confidence", "unknown")
                prefix = f"{rank}. " if rank is not None else "- "
                st.markdown(
                    f"{prefix}`{label}` · score `{_fmt_score(score)}` · confidence `{confidence}`"
                )

        if workflow_steps:
            st.markdown("**Workflow**")
            st.markdown(" -> ".join(f"`{step}`" for step in workflow_steps[:8]))

        if migrations:
            st.markdown("**Exploratory migration hypotheses**")
            for path in migrations[:4]:
                source = path.get("source_tool", path.get("tool_name", "Unknown"))
                target = path.get("target_task", "Unknown task")
                score = path.get("migration_plausibility_score", path.get("score"))
                gaps = path.get("compatibility_gaps") or []
                st.markdown(
                    f"- `{source}` -> {target}; plausibility `{_fmt_score(score)}`; "
                    "not a formal recommendation."
                )
                if gaps:
                    st.caption("Compatibility gaps: " + "; ".join(map(str, gaps[:3])))

        snippets = _rag_snippets(state)
        if snippets:
            st.markdown("**RAG snippets**")
            st.caption("Reviewed publication or benchmark fragments for explanation only; they do not change ranking.")
            for snippet in snippets[:5]:
                source_kind = snippet.get("source_kind", "source")
                tool_name = snippet.get("tool_name", "Unknown")
                title = _compact(snippet.get("title", ""), 110)
                doi = snippet.get("doi") or snippet.get("source_url") or "no DOI/source URL"
                claim = _compact(
                    snippet.get("claim_span")
                    or snippet.get("result_text")
                    or snippet.get("claim_text")
                    or snippet.get("evaluation_protocol")
                    or "",
                    260,
                )
                st.markdown(
                    f"""
<div class="source-item">
  <div><strong>{escape(str(tool_name))}</strong> · {escape(str(source_kind))}</div>
  <div class="source-meta">{escape(str(doi))} · {escape(str(title))}</div>
  <div>{escape(str(claim))}</div>
</div>
""",
                    unsafe_allow_html=True,
                )

        missing = _missing_evidence(state)
        if missing:
            st.markdown("**Missing evidence or constraints**")
            st.markdown(", ".join(f"`{item}`" for item in missing[:16]))

        audit = _audit_summary(state)
        if audit:
            severity = audit.get("severity_counts") or {}
            passed = bool(audit.get("passed"))
            st.markdown("**Semantic audit**")
            _render_chip("audit pass" if passed else "needs review", "good" if passed else "bad")
            _render_chip(f"unsupported claims: {audit.get('unsupported_claim_count', 0)}")
            _render_chip(f"high: {severity.get('high', 0)}")
            _render_chip(f"critical: {severity.get('critical', 0)}")
        else:
            st.markdown('<div class="quiet-note">Audit status is unavailable for this run.</div>', unsafe_allow_html=True)

        if runtime is not None:
            st.caption(f"Runtime: {runtime:.2f}s")

        if show_debug:
            st.divider()
            st.json(state)


def _render_followups(
    suggestions: List[str],
    *,
    key_prefix: str,
    source_query: str = "",
) -> None:
    if not suggestions:
        return
    with st.expander("继续追问", expanded=False):
        for idx, suggestion in enumerate(suggestions):
            button_key = f"{key_prefix}_{idx}"
            if st.button(suggestion, key=button_key):
                st.session_state.pending_query = _contextualized_followup_query(
                    suggestion,
                    source_query=source_query,
                )
                st.session_state.pending_display_query = suggestion
                st.rerun()


def _contextualized_followup_query(suggestion: str, *, source_query: str = "") -> str:
    # The conversation history already carries the prior task. Repeating the source
    # query here contaminates intent routing (for example, a prior "top-3 caveat"
    # query can incorrectly turn a workflow follow-up into another caveat answer).
    return suggestion.strip()


def _is_greeting_query(query: str) -> bool:
    normalized = re.sub(r"[^\w\u4e00-\u9fff]+", "", (query or "").strip().lower())
    if not normalized or len(normalized) > 14:
        return False
    greeting_patterns = [
        r"hi+",
        r"hello+",
        r"hey+",
        r"嗨+",
        r"哈喽+",
        r"你好+",
        r"您好+",
        r"在吗",
        r"早上好",
        r"下午好",
        r"晚上好",
    ]
    return any(re.fullmatch(pattern, normalized) for pattern in greeting_patterns)


def _is_time_query(query: str) -> bool:
    normalized = re.sub(r"\s+", "", (query or "").lower())
    if not normalized:
        return False
    time_patterns = [
        "几点",
        "现在几点",
        "现在几点钟",
        "现在时间",
        "时间是几点",
        "今天几号",
        "日期",
        "星期几",
    ]
    return any(pattern in normalized for pattern in time_patterns)


def _time_reply() -> str:
    now = datetime.now().astimezone()
    return (
        f"当前时间是 {now.strftime('%Y-%m-%d %H:%M:%S %Z')}。\n\n"
        "如果你想看你所在时区的时间，告诉我城市或时区名，我可以按那个时区帮你换算。"
    )


def _chat_input_parts(value: Any) -> tuple[str, List[Any]]:
    if value is None:
        return "", []
    if isinstance(value, str):
        return value, []
    text = getattr(value, "text", "")
    files = getattr(value, "files", [])
    if not isinstance(files, list):
        files = []
    return str(text or "").strip(), files


def _summarize_uploaded_files(files: List[Any]) -> Dict[str, Any]:
    summaries = [_summarize_upload(file) for file in files]
    if not summaries:
        return {}
    return {
        "files": summaries,
        "file_count": len(summaries),
        "source": "chat_input_upload",
    }


def _upload_preview_text(upload_context: Dict[str, Any]) -> str:
    files = upload_context.get("files") if isinstance(upload_context, dict) else []
    if not files:
        return ""
    lines = ["已读取上传文件摘要："]
    for item in files[:4]:
        if not isinstance(item, dict):
            continue
        name = item.get("file_name", "uploaded file")
        status = item.get("status", "unknown")
        suffix = item.get("file_type", "unknown")
        columns = item.get("columns") or []
        if columns:
            detail = "字段：" + ", ".join(map(str, columns[:8]))
        elif item.get("top_level_keys"):
            detail = "键：" + ", ".join(map(str, item.get("top_level_keys", [])[:8]))
        elif item.get("line_count") is not None:
            detail = f"行数：{item.get('line_count')}"
        else:
            detail = item.get("warning") or "已保存为 working context"
        lines.append(f"- {name} ({suffix}, {status})：{detail}")
    lines.append("这些内容只作为本轮上下文，不会进入 trusted evidence，也不会改变工具排序分。")
    return "\n".join(lines)


def _format_user_display_query(text: str, files: List[Any]) -> str:
    clean_text = text.strip()
    file_names = [getattr(file, "name", "uploaded file") for file in files]
    if clean_text and file_names:
        return clean_text + "\n\n" + "附件：" + "，".join(file_names)
    if file_names:
        return "已上传文件：" + "，".join(file_names)
    return clean_text


def _render_user_message(content: str) -> None:
    safe = escape(str(content or "")).replace("\n", "<br />")
    st.markdown(
        f"""
<div class="user-chat-row">
  <div class="user-chat-bubble">{safe}</div>
</div>
""",
        unsafe_allow_html=True,
    )


def _render_assistant_report(report: str) -> None:
    st.markdown(report or "")


def _render_algorithm_surface(state: Dict[str, Any]) -> None:
    intent = str(state.get("response_intent") or "")
    bundle = state.get("workflow_code_bundle") or {}
    if (state.get("context_pack") or {}).get("answer_provenance") and intent != "workflow" and not bundle:
        return
    if intent == "workflow" or bundle:
        if not bundle:
            return
        smoke_status = str(bundle.get("smoke_status") or "not_run").upper()
        st.markdown(
            '<div class="algorithm-surface-title">' +
            ('已验证脚本' if bundle.get("smoke_tested") else '计划脚本 · 当前版本待验证') + '</div>',
            unsafe_allow_html=True,
        )
        status_style = "good" if bool(bundle.get("smoke_tested")) else "warn"
        _render_chip(f"{bundle.get('tool_name', 'Recipe')} · {smoke_status}", status_style)
        _render_chip(f"runtime pack · {bundle.get('runtime_pack', 'unknown')}")
        _render_chip(f"version · {bundle.get('recipe_version', 'unknown')}")
        with st.expander("Open full Python recipe", expanded=False):
            st.code(str(bundle.get("code") or ""), language="python", line_numbers=True)
            st.caption(
                "Maintainer-owned fixed recipe. Copying it does not create an ExecutionRequest or bypass approval gates."
            )
        return
    if intent == "tool_recommendation":
        cards = list(state.get("algorithm_cards") or [])[:3]
        if not cards:
            return
        rendered = []
        for card in cards:
            readiness = str(card.get("readiness") or "catalog_only").replace("_", " ")
            rendered.append(
                "".join(
                    [
                        '<article class="algorithm-card">',
                        f'<div class="algorithm-name">{escape(str(card.get("tool_name") or "Unknown"))}</div>',
                        f'<div class="algorithm-meta">{escape(str(card.get("mechanism") or ""))}</div>',
                        f'<div class="algorithm-meta"><strong>Input</strong> · {escape(str(card.get("input") or "unknown"))}</div>',
                        f'<span class="algorithm-boundary">{escape(readiness.upper())}</span>',
                        "</article>",
                    ]
                )
            )
        st.markdown(
            '<div class="algorithm-surface-title">Algorithm options</div>'
            f'<div class="algorithm-grid">{"".join(rendered)}</div>',
            unsafe_allow_html=True,
        )
        return
    if intent == "migration_exploration":
        paths = list(state.get("migration_paths") or [])[:3]
        if not paths:
            return
        rendered = []
        for path in paths:
            source = path.get("source_tool") or path.get("tool_name") or "Unknown"
            mechanism = path.get("transferable_mechanism") or path.get("mechanism") or "Mechanism review required"
            rendered.append(
                "".join(
                    [
                        '<article class="algorithm-card">',
                        f'<div class="algorithm-name">{escape(str(source))}</div>',
                        f'<div class="algorithm-meta">{escape(str(mechanism))}</div>',
                        '<span class="algorithm-boundary">EXPLORATORY HYPOTHESIS</span>',
                        "</article>",
                    ]
                )
            )
        st.markdown(
            '<div class="algorithm-surface-title">Migration hypotheses</div>'
            f'<div class="algorithm-grid">{"".join(rendered)}</div>',
            unsafe_allow_html=True,
        )


def _render_execution_handoff(state: Dict[str, Any], *, key: str) -> None:
    handoff = state.get("execution_handoff") or {}
    status = str(handoff.get("status") or "not_requested")
    if status == "not_requested":
        return
    st.markdown(
        '<div class="algorithm-surface-title">Execution handoff</div>',
        unsafe_allow_html=True,
    )
    _status_badge(status)
    blockers = list(handoff.get("blockers") or [])
    if blockers:
        st.caption("Blocked/waiting: " + " · ".join(map(str, blockers[:4])))
    st.caption(
        "No tool starts from this card. Data authorization and plan-specific approval remain mandatory."
    )
    if st.button("Open Runs & Results", key=key, type="primary"):
        st.session_state.current_view = "execution_ui"
        st.rerun()


def _research_input_binding() -> Dict[str, Any]:
    return dict(load_working_context(st.session_state.session_id).get("input_binding") or {})


def _bind_research_input(binding: Dict[str, Any]) -> None:
    from execution.research_input_binding import invalidate_delivery

    if binding != _research_input_binding():
        invalidate_delivery(st.session_state)
        _reset_workspace_from_stage("source")
    save_working_context(st.session_state.session_id, "input_binding", binding)
    st.session_state.workspace_artifact_id = binding.get("artifact_id")
    st.session_state.capability_workspace_artifact_id = binding.get("artifact_id")
    st.session_state.capability_workspace_pending_artifact = binding.get("artifact_id")
    handoff = dict(st.session_state.get("workspace_task_handoff") or {})
    if handoff:
        handoff["input_binding"] = binding
        handoff["conversation_id"] = st.session_state.session_id
        st.session_state.workspace_task_handoff = handoff


def _research_composer_draft() -> Dict[str, Any]:
    # Pending attachments belong to this browser session, never the saved task.
    key = f"research_composer_draft_{st.session_state.session_id}"
    return st.session_state.setdefault(key, {})


def _stage_research_input(binding: Dict[str, Any]) -> None:
    _research_composer_draft()["input_binding"] = dict(binding)


def _render_research_input() -> None:
    """Compact composer attachment menu; registration is not an execution grant."""
    from execution.execution_ui_service import configured_local_user_id
    from execution.research_input_binding import register_upload, register_sample, registered_input_options, select_registered_input, digest

    user_id = configured_local_user_id()
    execution = _execution_ui_backend()
    session = st.session_state.session_id
    with st.popover("＋", help="添加本地文件或选择系统样例"):
        st.markdown('<span class="research-upload-menu"></span>', unsafe_allow_html=True)
        generation = st.session_state.get(f"research_upload_generation_{session}", 0)
        files = st.file_uploader(
            "添加本地文件", type=None, accept_multiple_files=True, label_visibility="collapsed",
            key=f"research_files_{session}_{generation}",
            help="数据留在本机。.h5ad 可进入当前分析；文档和表格作为附件，不会自动当成 AnnData。",
        )
        data_files = [item for item in files or [] if item.name.lower().endswith(".h5ad")]
        selection = data_files[0] if len(data_files) == 1 else None
        if len(data_files) > 1:
            choice = st.selectbox("本次分析哪份数据？", options=[None, *range(len(data_files))],
                format_func=lambda i: "请选择，不自动合并" if i is None else
                f"{data_files[i].name} · {hashlib.sha256(data_files[i].getvalue()).hexdigest()[:8]}",
                key=f"research_upload_choice_{session}_{generation}")
            if choice is not None:
                selection = data_files[choice]
        batch = [(item.name, hashlib.sha256(item.getvalue()).hexdigest()) for item in files or []]
        signature = digest({"files": batch, "selected": selection.name if selection else None,
                            "selected_sha": hashlib.sha256(selection.getvalue()).hexdigest() if selection else None})
        working = _research_composer_draft()
        st.session_state.workspace_input_pending = len(data_files) > 1 and selection is None
        # Distinguish an explicit removal from an empty uploader after reload.
        observed_key = f"research_observed_files_{session}_{generation}"
        previous_files = st.session_state.get(observed_key, [])
        if signature != working.get("attachment_batch_digest") and (files or previous_files):
            try:
                if selection is not None:
                    binding = register_upload(execution.data_registry, user_id=user_id,
                        filename=selection.name, content=selection.getvalue())
                    _stage_research_input(binding)
                elif len(data_files) > 1:
                    # A new ambiguous data selection must not leave the previous
                    # conversation input silently active, even after navigation.
                    _stage_research_input({})
                elif any(name.lower().endswith(".h5ad") for name in previous_files):
                    _stage_research_input({})
                documents = [item for item in files or [] if not item.name.lower().endswith(".h5ad")]
                context = _summarize_uploaded_files(documents)
                working["uploaded_context"] = context
                working["attachment_batch_digest"] = signature
                working["attachment_names"] = [item.name for item in files or []]
                st.session_state[observed_key] = [item.name for item in files or []]
                st.rerun()
            except Exception as exc:
                st.session_state.workspace_input_pending = True
                st.error(execution.redact_text(str(exc)))
        st.session_state[observed_key] = [item.name for item in files or []]
        if st.session_state.workspace_input_pending:
            st.info("请先选择本次分析的数据，避免用错文件。")
        st.caption("可多选或拖入文件 · 上传不会运行分析")
        with st.expander("更多来源与数据详情", expanded=False):
            if st.button("使用系统样例 · 180 cells × 240 genes", key=f"research_sample_{session}"):
                try:
                    _stage_research_input(register_sample(execution.data_registry, user_id=user_id))
                    st.session_state.workspace_input_pending = False
                    st.session_state[f"research_upload_generation_{session}"] = generation + 1
                    working["attachment_names"] = []
                    working["uploaded_context"] = {}
                    working["attachment_batch_digest"] = ""
                    st.rerun()
                except Exception as exc:
                    st.error(execution.redact_text(str(exc)))
            st.caption("已登记文件 / 大文件本地关联")
            available, unavailable = registered_input_options(execution.data_registry, user_id=user_id)
            by_id = {record.artifact_id: record for record, _ in available}
            labels = {record.artifact_id: f"{name} · {record.size_bytes / (1024 * 1024):.1f} MB · {record.artifact_id[-8:]}"
                      for record, name in available}
            if unavailable:
                st.caption(f"已隐藏 {len(unavailable)} 条无法直接访问的旧登记；可重新上传或关联本地路径。")
            selected = st.selectbox("选择已登记文件", options=[None, *by_id],
                format_func=lambda value: "请选择" if value is None else labels[value],
                key=f"research_registered_{session}")
            path = st.text_input("本地数据路径（仅限已授权目录，无需重复上传）", type="password",
                key=f"research_associate_path_{session}")
            if st.button("使用此文件", disabled=not (selected or path.strip()), key=f"research_associate_{session}"):
                try:
                    if selected and path.strip():
                        raise ValueError("请选择一种方式：已登记文件或本地路径")
                    record = execution.register_local_artifact(user_id=user_id, local_path=path.strip()) if path.strip() else by_id[selected]
                    _stage_research_input(select_registered_input(execution.data_registry,
                        artifact_id=record.artifact_id, user_id=user_id))
                    st.session_state.workspace_input_pending = False
                    st.session_state[f"research_upload_generation_{session}"] = generation + 1
                    working["attachment_batch_digest"] = ""
                    st.rerun()
                except Exception as exc:
                    st.error("暂时无法使用这份已登记文件。服务重启后，请重新选择本地文件以恢复访问。"
                             if "re-authorized" in str(exc) else execution.redact_text(str(exc)))
            binding = _research_composer_draft().get("input_binding") or {}
            if binding:
                st.caption("数据绑定详情")
                st.json(binding)


def _clear_research_attachments() -> None:
    """Clear only the unsent draft; completed tasks keep their exact input identity."""
    session = st.session_state.session_id
    st.session_state.pop(f"research_composer_draft_{session}", None)
    generation_key = f"research_upload_generation_{session}"
    st.session_state[generation_key] = st.session_state.get(generation_key, 0) + 1
    st.session_state.workspace_input_pending = False


def _render_bound_input_card() -> None:
    working = _research_composer_draft()
    binding = working.get("input_binding") or {}
    labels = []
    if binding:
        shape = binding.get("shape") or []
        dimensions = f" · {shape[0]:,} cells × {shape[1]:,} genes" if len(shape) == 2 else ""
        kind = "系统样例" if binding.get("source") == "explicit_demo" else "当前数据"
        name = 'sample.h5ad' if binding.get('source') == 'explicit_demo' else binding['original_filename']
        if re.fullmatch(r"[0-9a-f]{64}\.h5ad", name):
            name = "已关联 AnnData（原文件名未记录）"
        labels.append(f"{name}{dimensions} · {kind}")
    documents = working.get("uploaded_context") or {}
    labels.extend(str(item["file_name"]) for item in documents.get("files", []))
    if not labels and st.session_state.get("workspace_input_pending"):
        labels = ["待选择分析数据 · 点击 ＋"]
    if not labels:
        return
    with st.container(border=False):
        st.markdown('<span class="research-attachments-marker"></span>', unsafe_allow_html=True)
        chips, clear = st.columns([12, 1])
        with chips:
            st.markdown('<div class="research-attachment-list">' + ''.join(
                f'<span class="research-attachment-chip" title="{escape(label, quote=True)}">📎 {escape(label)}</span>'
                for label in labels
            ) + '</div>', unsafe_allow_html=True)
        with clear:
            if st.button("×", key=f"research_clear_attachments_{st.session_state.session_id}",
                         help="移除全部附件（不删除原文件）"):
                _clear_research_attachments()
                st.rerun()


def _workspace_handoff_payload(
    state: Dict[str, Any], *, source_query: str
) -> Dict[str, Any] | None:
    governed_handoff = state.get("workspace_handoff") or {}
    bundle = state.get("workflow_code_bundle") or {}
    task = str(
        (state.get("extracted_constraints") or {}).get("canonical_task") or ""
    )
    tool_name = str(bundle.get("tool_name") or "")
    if governed_handoff.get("status") != "available":
        return None
    strategy = str(governed_handoff.get("notebook_strategy") or "none")
    if strategy == "fixed_shadow" and (
        task != "doublet_detection" or tool_name != "Scrublet"
    ):
        return None
    if strategy == "capability_renderer" and not governed_handoff.get("pack_id"):
        return None
    plan = state.get("workflow_plan") or {}
    return {
        "handoff_id": governed_handoff.get("handoff_id"),
        "origin_trace_id": governed_handoff.get("origin_trace_id"),
        "parent_request_id": governed_handoff.get("parent_request_id"),
        "original_plan_id": governed_handoff.get("original_plan_id"),
        "conversation_id": st.session_state.session_id,
        "input_binding": dict(state.get("ui_input_binding") or _research_input_binding()),
        "source_query": source_query.strip(),
        "task_family": task,
        "tool_name": tool_name,
        "agent_mode": str(state.get("agent_mode") or "PLAN"),
        "plan_id": governed_handoff.get("plan_id") or plan.get("plan_id"),
        "notebook_strategy": governed_handoff.get("notebook_strategy"),
        "pack_id": governed_handoff.get("pack_id"),
        "pack_version": governed_handoff.get("pack_version"),
        "target_representations": list(
            governed_handoff.get("target_representations") or []
        ),
        "preferred_method_ids": list(
            governed_handoff.get("preferred_method_ids") or []
        ),
        **{name: governed_handoff[name] for name in (
            "parameter_overrides", "batch_key", "enable_doublet_detection",
            "exclude_predicted_doublets", "doublet_selection_hash", "enable_batch_integration"
        ) if name in governed_handoff},
        "stepwise_preview_available": bool(
            governed_handoff.get("stepwise_preview_available")
        ),
        "recipe_version": bundle.get("recipe_version"),
        "smoke_status": bundle.get("smoke_status"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _render_workspace_handoff(
    state: Dict[str, Any], *, source_query: str, key: str
) -> None:
    payload = _workspace_handoff_payload(state, source_query=source_query)
    if payload is None:
        return
    # The just-produced answer and its history render must share widget identity.
    key = "workspace_handoff_" + hashlib.sha256(
        f"{st.session_state.session_id}:{payload.get('handoff_id')}".encode()
    ).hexdigest()[:20]
    st.markdown(
        '<div class="algorithm-surface-title">下一步 · Stepwise Analysis</div>',
        unsafe_allow_html=True,
    )
    capability_mode = payload.get("notebook_strategy") == "capability_renderer"
    stale_input = bool(state.get("ui_input_binding")) and state["ui_input_binding"] != _research_input_binding()
    if stale_input:
        st.warning("这条历史任务绑定的是另一份输入。请为当前数据重新发送计划请求，不能沿用旧交接。")
    st.caption(
        "当前对话的数据会自动带入 Stepwise。先检查数据状态并准备计划，再由你确认执行。"
        if capability_mode
        else "系统识别到这是已资格化的 Doublet Detection workflow。对话中的任务、工具和计划会一并带入 Stepwise Analysis。"
    )
    action_cols = st.columns(2)
    if not payload.get("input_binding") and action_cols[0].button(
        "用版本化模拟数据准备 Notebook"
        if capability_mode
        else "用模拟数据在 JupyterLab 试跑",
        key=f"{key}_demo",
        type="secondary",
        width="stretch",
    ):
        demo_payload = dict(payload)
        demo_payload["source_query"] = source_query.strip()
        demo_payload["fixture_type"] = "synthetic_engineering_demo"
        demo_payload["input_binding"] = {}
        try:
            if capability_mode:
                _activate_capability_demo_handoff(demo_payload)
            else:
                _activate_scrublet_demo_handoff(demo_payload)
            st.session_state.current_view = "data_preview"
            st.rerun()
        except Exception as exc:
            st.error(_execution_ui_backend().redact_text(str(exc)))
    if action_cols[1].button(
        "进入 Stepwise · 使用当前数据" if payload.get("input_binding") else "进入 Stepwise · 关联我的 .h5ad",
        key=f"{key}_data",
        type="primary",
        width="stretch",
        disabled=bool(st.session_state.get("workspace_input_pending")) or stale_input,
    ):
        from execution.research_input_binding import invalidate_delivery, planning_context
        prior = st.session_state.get("workspace_task_handoff") or {}
        if planning_context(prior, prior.get("input_binding") or {}, None) != planning_context(payload, payload.get("input_binding") or {}, None):
            invalidate_delivery(st.session_state)
            _reset_workspace_from_stage("source")
        st.session_state.workspace_task_handoff = payload
        binding = payload.get("input_binding") or {}
        artifact_id = binding.get("artifact_id")
        st.session_state.workspace_artifact_id = artifact_id
        st.session_state.capability_workspace_artifact_id = artifact_id
        st.session_state.capability_workspace_pending_artifact = artifact_id
        st.session_state.pop("capability_workspace_selected_artifact", None)
        st.session_state.current_view = "data_preview"
        st.rerun()


def _activate_scrublet_demo_handoff(payload: Dict[str, Any]) -> None:
    """Bind the maintained synthetic fixture to a contextual chat handoff."""

    from execution.demo_fixture import (
        SCRUBLET_PREVIEW_DEMO_FILENAME,
        ensure_scrublet_preview_demo,
    )
    from execution.execution_ui_service import configured_local_user_id

    service = _execution_ui_backend()
    user_id = configured_local_user_id()
    demo_path = ensure_scrublet_preview_demo(
        service.data_registry.approved_input_roots[0]
        / SCRUBLET_PREVIEW_DEMO_FILENAME
    )
    artifact = service.register_local_artifact(
        user_id=user_id,
        local_path=str(demo_path),
    )
    _reset_workspace_from_stage("source")
    for state_key in (
        "workspace_local_preview_enablement",
        "workspace_parameter_context",
        "workspace_parameter_draft",
    ):
        st.session_state.pop(state_key, None)
    st.session_state.workspace_artifact_id = artifact.artifact_id
    # The artifact selectbox may already exist in the current Streamlit run.
    # Apply its widget value at the start of the next render instead.
    st.session_state.workspace_pending_selected_artifact = artifact.artifact_id
    st.session_state.workspace_task_handoff = dict(payload)


def _activate_capability_demo_handoff(payload: Dict[str, Any]) -> None:
    """Register a pack-owned synthetic fixture without executing the workflow."""

    from execution.execution_ui_service import configured_local_user_id
    from execution.scanpy_synthetic_fixture import (
        generate_scanpy_core_synthetic_fixture,
    )

    pack_id = str(payload.get("pack_id") or "")
    if pack_id != "scanpy_core":
        raise ValueError("this capability pack has no registered synthetic demo fixture")
    service = _execution_ui_backend()
    fixture_root = (
        service.data_registry.approved_input_roots[0]
        / "capability-fixtures"
        / pack_id
        / str(payload.get("pack_version") or "1.0.0")
    )
    fixture_path = fixture_root / "scanpy_core_synthetic_v1.h5ad"
    manifest_path = fixture_root / "fixture_manifest.json"
    if not (fixture_path.is_file() and manifest_path.is_file()):
        generate_scanpy_core_synthetic_fixture(fixture_root)
    artifact = service.register_local_artifact(
        user_id=configured_local_user_id(), local_path=str(fixture_path)
    )
    _reset_workspace_from_stage("source")
    st.session_state.workspace_artifact_id = artifact.artifact_id
    st.session_state.workspace_pending_selected_artifact = artifact.artifact_id
    st.session_state.capability_workspace_artifact_id = artifact.artifact_id
    st.session_state.capability_workspace_pending_artifact = artifact.artifact_id
    st.session_state.pop("capability_workspace_result", None)
    st.session_state.workspace_task_handoff = dict(payload)


def _render_capability_stepwise_workspace(payload: Dict[str, Any]) -> None:
    """Render the existing registry-driven capability workspace in Stepwise Analysis."""

    from core.capability_workspace_models import (
        CapabilityWorkspaceRequest,
        CapabilityWorkspaceResult,
    )
    from execution.execution_ui_service import configured_local_user_id
    from execution.runtime_pack_resolver import RuntimePackResolver
    from execution.research_input_binding import (
        authorize_uploaded_binding, digest, invalidate_delivery, planning_context, publish_delivery,
    )

    execution = _execution_ui_backend()
    workspace = _capability_workspace_backend()
    user_id = configured_local_user_id()
    pack_id = str(payload.get("pack_id") or "")
    pack_version = str(payload.get("pack_version") or "")
    targets = [str(item) for item in payload.get("target_representations") or []]
    if payload.get("conversation_id") != st.session_state.session_id:
        st.error("交接属于另一对话，请从当前 Research 请求重新进入。")
        return
    if not payload.get("input_binding") and payload.get("fixture_type") != "synthetic_engineering_demo":
        st.warning("此交接没有输入绑定。请先上传或明确选择 .h5ad；不会默认使用 synthetic。")
        _render_research_input()
        return
    st.markdown(
        '<div class="data-workbench-section-title">Capability workflow</div>'
        '<div class="data-workbench-section-copy">同一条链路完成数据画像、Representation 复用、DAG 与维护者模板 Notebook。页面不会自动执行代码。</div>',
        unsafe_allow_html=True,
    )
    status_cols = st.columns(4)
    status_cols[0].metric("Pack", pack_id or "UNRESOLVED")
    status_cols[1].metric("Mode", "PLAN")
    status_cols[2].metric("Policy", "DISABLED")
    status_cols[3].metric("ExecutionRequest", "0")

    with st.expander("登记 approved input root 中的 .h5ad", expanded=False):
        local_path = st.text_input(
            "本地 .h5ad 路径",
            type="password",
            key="capability_workspace_local_path",
            help="完整路径仅用于本地登记，不发送给模型，也不写入页面历史。",
        )
        if st.button(
            "登记 AnnData",
            key="capability_workspace_register",
            disabled=not local_path.strip(),
        ):
            try:
                artifact = execution.register_local_artifact(
                    user_id=user_id,
                    local_path=local_path.strip(),
                )
                from execution.research_input_binding import validate_h5ad
                shape = validate_h5ad(execution.data_registry.resolve_path(artifact.artifact_id, user_id=user_id))
                _bind_research_input({"artifact_id": artifact.artifact_id, "sha256": artifact.sha256,
                    "original_filename": Path(local_path.strip()).name, "source": "explicit_registered_selection",
                    "owner_user_id": user_id, "shape": list(shape)})
                st.success(f"已登记：{artifact.redacted_path}")
                st.rerun()
            except Exception as exc:
                st.error(execution.redact_text(str(exc)))

    artifacts = execution.list_artifacts(user_id=user_id)
    if not artifacts:
        st.info("尚无已登记 AnnData。可返回对话选择版本化 synthetic fixture，或登记 approved input root 中的 .h5ad。")
        return
    labels = {
        item.artifact_id: f"{item.artifact_id} · {item.redacted_path}"
        for item in artifacts
    }
    if "capability_workspace_pending_artifact" in st.session_state:
        st.session_state.capability_workspace_selected_artifact = st.session_state.pop("capability_workspace_pending_artifact") or ""
    selected = st.selectbox(
        "当前 AnnData",
        options=["", *labels],
        format_func=lambda value: labels.get(value, "请选择当前输入（无默认数据）"),
        index=(
            list(labels).index(st.session_state.capability_workspace_artifact_id) + 1
            if st.session_state.get("capability_workspace_artifact_id") in labels
            else 0
        ),
        key="capability_workspace_selected_artifact",
    )
    if st.session_state.get("capability_workspace_artifact_id") != selected:
        if selected:
            record = execution.data_registry.get(selected, user_id=user_id)
            _bind_research_input({"artifact_id": selected, "sha256": record.sha256,
                "original_filename": record.redacted_path, "source": "explicit_registered_selection",
                "owner_user_id": user_id})
        else:
            _bind_research_input({})
        st.rerun()
    if not selected:
        st.info("请明确选择数据。")
        return
    binding = dict(payload.get("input_binding") or {})
    if payload.get("fixture_type") == "synthetic_engineering_demo" and not binding:
        record = execution.data_registry.get(selected, user_id=user_id)
        binding = {"artifact_id": selected, "sha256": record.sha256,
                   "source": "explicit_demo", "original_filename": record.redacted_path}
    try:
        if binding.get("artifact_id") != selected:
            raise ValueError("handoff 与选择的输入不一致，请重新关联数据")
        authorize_uploaded_binding(execution.data_registry, binding, user_id=user_id)
    except Exception as exc:
        st.error(execution.redact_text(str(exc)))
        return
    st.caption(f"本次输入：{binding.get('original_filename')} · {selected} · SHA-256 {binding['sha256']}")
    batch_key = st.text_input(
        "Batch metadata key（可选）",
        value=str(payload.get("batch_key") or ""),
        key="capability_workspace_batch_key",
    )
    context = planning_context(payload, binding, batch_key.strip())
    context_hash = digest(context)
    if st.session_state.get("capability_workspace_context_digest") != context_hash:
        invalidate_delivery(st.session_state)
        _reset_workspace_from_stage("source")
        st.session_state.capability_workspace_context_digest = context_hash
    st.caption("交接目标：" + ", ".join(targets) + "；方法约束：" + ", ".join(payload.get("preferred_method_ids") or []))
    st.caption("以上为当前已结构化的计划约束；未在此列出的自然语言参数/要求需要澄清，不能视为已经应用。")
    if st.button(
        "生成数据画像、Workflow 与 Notebook",
        key="capability_workspace_prepare",
        type="primary",
        width="stretch",
        disabled=not (pack_id and pack_version and targets),
    ):
        try:
            notebook_root = (
                _research_workspace_backend().workspace_root
                / user_id
                / "capability-notebooks"
            )
            notebook_path = notebook_root / f"{pack_id}-{uuid.uuid4().hex[:12]}.ipynb"
            prepared = workspace.prepare(
                CapabilityWorkspaceRequest(
                    request_id=f"workspace-{uuid.uuid4().hex}",
                    origin_trace_id=payload.get("origin_trace_id"),
                    handoff_id=payload.get("handoff_id"),
                    parent_request_id=payload.get("parent_request_id"),
                    original_plan_id=payload.get("original_plan_id"),
                    user_id=user_id,
                    artifact_id=selected,
                    pack_id=pack_id,
                    pack_version=pack_version,
                    mode="PLAN",
                    requirement_id=f"chat-handoff-{uuid.uuid4().hex[:12]}",
                    target_representations=targets,
                    preferred_method_ids=list(
                        payload.get("preferred_method_ids") or []
                    ),
                    batch_key=batch_key.strip() or None,
                    **{name: payload[name] for name in (
                        "parameter_overrides", "enable_doublet_detection", "exclude_predicted_doublets",
                        "doublet_selection_hash", "enable_batch_integration"
                    ) if name in payload},
                ),
                notebook_path=notebook_path,
            )
            if st.session_state.session_id != payload["conversation_id"] or not publish_delivery(
                st.session_state, expected_context=context_hash, result=prepared.model_dump(mode="json")
            ):
                st.warning("旧请求已失效，结果未替换当前对话。")
                return
            st.session_state.capability_workspace_request_binding = context
            st.rerun()
        except Exception as exc:
            st.error(execution.redact_text(str(exc)))

    result_payload = st.session_state.get("capability_workspace_result")
    if not result_payload:
        return
    if st.session_state.get("capability_workspace_result_context") != context_hash:
        return
    result = CapabilityWorkspaceResult.model_validate(result_payload)
    st.download_button(
        "下载数据绑定审计 JSON",
        data=execution.redact_text(json.dumps({
            "context_digest": context_hash,
            "request_binding": st.session_state.get("capability_workspace_request_binding"),
            "result": result_payload,
        }, ensure_ascii=False, indent=2)),
        file_name=f"{result.request_id}-binding.json", mime="application/json",
        key="capability_workspace_download_binding",
    )
    if result.status == "blocked":
        st.error("Workflow 被阻断：" + " · ".join(result.blockers))
        return
    profile = result.data_profile
    ledger = result.representation_ledger
    plan = result.workflow_plan
    if profile is not None:
        profile_cols = st.columns(4)
        profile_cols[0].metric("Cells", profile.n_cells)
        profile_cols[1].metric("Genes", profile.n_genes)
        profile_cols[2].metric("Count source", profile.selected_count_source or "UNRESOLVED")
        profile_cols[3].metric("Existing states", len(ledger.available_ids()) if ledger else 0)
    if ledger is not None:
        st.caption("可复用表示：" + " · ".join(sorted(ledger.available_ids())))
    if plan is not None:
        st.markdown("#### WorkflowPlan")
        st.dataframe(
            [
                {
                    "step": index + 1,
                    "method": item.operation,
                    "consumes": ", ".join(item.input_artifacts),
                    "produces": ", ".join(item.output_artifacts),
                    "parameters": json.dumps(item.parameters, sort_keys=True),
                    "parameter_source": ", ".join(
                        sorted(
                            {
                                provenance.origin_type
                                for provenance in item.parameter_provenance
                            }
                        )
                    ),
                }
                for index, item in enumerate(plan.steps)
            ],
            use_container_width=True,
            hide_index=True,
        )
        from observability.workflow_plan_presentation import parameter_source_rows
        with st.expander("参数来源与原文链接", expanded=True):
            st.caption("上表 parameter_source 是来源类别，不是链接。下表展示原有来源记录；内部合同/项目规则不虚构外部原文。API 文档不证明本数据上的参数最优。")
            source_rows = parameter_source_rows(plan.steps)
            if source_rows:
                for row in source_rows:
                    if row["source_url"]:
                        st.link_button(
                            f"步骤 {row['step']} · {row['method']} · {row['parameter']}={row['value']}：打开原文",
                            row["source_url"],
                        )
                st.dataframe(source_rows, hide_index=True, use_container_width=True,
                             column_config={"source_url": st.column_config.LinkColumn(
                                 "原文链接", display_text="打开原文")})
            else:
                st.caption("本计划没有登记参数来源；不生成推测性引用。")
    notebook = dict(result.notebook_artifact)
    notebook_path = Path(str(notebook.get("path") or ""))
    st.caption(f"Plan：{plan.plan_id if plan else '无'} · Notebook：{notebook_path.name} · SHA-256：{notebook.get('sha256', '无')}")
    if notebook_path.is_file():
        notebook_cols = st.columns(2)
        notebook_cols[0].download_button(
            "下载 tutorial notebook",
            data=notebook_path.read_bytes(),
            file_name=notebook_path.name,
            mime="application/x-ipynb+json",
            key="capability_workspace_download_notebook",
            width="stretch",
        )
        if notebook_cols[1].button(
            "在本地 JupyterLab 打开",
            key="capability_workspace_open_jupyter",
            width="stretch",
        ):
            try:
                manifest = workspace.pack_registry.load(pack_id, pack_version)
                adapter = next(
                    item
                    for item in manifest.execution_adapters
                    if item.runtime_kind == "python_module"
                )
                resolver = RuntimePackResolver()
                runtime_pack_id = resolver.pack_for_environment(adapter.environment_id)
                session = _local_jupyter_backend().start(
                    owner_user_id=user_id,
                    notebook_path=notebook_path,
                    expected_sha256=str(notebook["sha256"]),
                    runtime_python=resolver.python(runtime_pack_id),
                    runtime_pack_id=runtime_pack_id,
                    request_id=f"jupyter-launch:{uuid.uuid4().hex}",
                    parent_trace_id=result.canonical_trace_id,
                    handoff_id=payload.get("handoff_id"),
                    parent_request_id=result.request_id,
                    original_plan_id=(plan.plan_id if plan is not None else None),
                )
                st.session_state.capability_workspace_jupyter_url = session.launch_url
                st.session_state.capability_workspace_jupyter_binding = digest(
                    [context_hash, result.request_id, notebook, plan.plan_id if plan else None])
                st.session_state.capability_workspace_jupyter_trace_id = (
                    session.canonical_trace_id
                )
            except Exception as exc:
                st.error(execution.redact_text(str(exc)))
        launch_url = st.session_state.get("capability_workspace_jupyter_url")
        if launch_url and st.session_state.get("capability_workspace_jupyter_binding") == digest(
            [context_hash, result.request_id, notebook, plan.plan_id if plan else None]
        ):
            st.link_button(
                "打开已启动的 JupyterLab",
                launch_url,
                use_container_width=True,
            )

    st.info(
        "已生成计划与 Notebook，尚不代表代码已执行。当前页面不创建受控 ExecutionRequest。"
        "ExecutionPolicy=disabled 不阻止打开本地 JupyterLab；可通过现有 Notebook 开发渠道手动运行。"
        "若出现 Jupyter 启动错误，它是独立的启动故障，不是该权限提示导致。"
    )
    latest = _latest_scanpy_journey_summary()
    if latest is None:
        st.info("尚无 Post-S6 synthetic acceptance bundle 可供只读展示。")
        return
    st.markdown("#### 最新 synthetic engineering acceptance（只读）")
    st.caption(
        "下列结果用于证明工程链路和 artifact schema，不代表当前所选数据的分析结果。"
    )
    route_tabs = st.tabs(
        [str(route.get("route_id") or "route") for route in latest.get("routes") or []]
    )
    for tab, route in zip(route_tabs, latest.get("routes") or []):
        with tab:
            route_cols = st.columns(3)
            route_cols[0].metric("Validation", "PASSED" if route.get("validation_passed") else "FAILED")
            route_cols[1].metric("Output cells", int(route.get("output_cells") or 0))
            route_cols[2].metric("Marker candidates", int(route.get("marker_candidate_count") or 0))
            for plot_path in route.get("plot_paths") or []:
                candidate = Path(str(plot_path))
                if candidate.is_file():
                    st.image(
                        str(candidate),
                        caption=candidate.stem.replace("_", " ").title(),
                    )
    st.success(
        "Level 2 package: complete="
        f"{bool(latest.get('package_complete'))}, hashes_valid="
        f"{bool(latest.get('package_hashes_valid'))}."
    )


def _latest_scanpy_journey_summary() -> Dict[str, Any] | None:
    root = Path(__file__).resolve().parent / ".sckg_exec" / "scanpy-user-journeys"
    candidates = sorted(
        root.glob("*/summary.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("package_complete") and payload.get("package_hashes_valid"):
            return payload
    return None


def _greeting_reply(project_memory: Optional[Dict[str, Any]] = None) -> str:
    memory_bits = []
    project_memory = project_memory or {}
    for key in ("species", "platform", "strictness"):
        value = project_memory.get(key)
        if value:
            memory_bits.append(f"{key}: {value}")

    lines = [
        "你好！你可以直接告诉我你在做哪一步单细胞分析，或者把数据和问题发给我。",
    ]
    if memory_bits:
        lines.append("我记得你的项目偏好：" + "，".join(memory_bits) + "。")
    return "\n\n".join(lines)


def _greeting_followups() -> List[str]:
    return [
        "我有一批 10x PBMC 数据，应该如何检测 doublet？",
        "请生成一个经过 smoke 测试的 doublet detection workflow。",
        "Harmony 和 Scanorama 对我的多批次数据各有什么限制？",
        "RUN 模式为什么仍然需要单独审批？",
    ]


def _render_context_status(
    *,
    offline_llm: bool,
    run_live: bool,
) -> None:
    settings = get_settings()
    env_api_configured = bool(
        (settings.deepseek_api_key or settings.openai_api_key)
        and settings.model_name
    )
    memory = load_project_memory()
    working = load_working_context(st.session_state.session_id)
    upload_context = (
        st.session_state.get("uploaded_context")
        or working.get("uploaded_context")
        or {}
    )
    uploads = upload_context.get("files") if isinstance(upload_context, dict) else []
    st.markdown("### Context")
    if memory:
        _render_chip(f"memory: {len(memory)} saved", "good")
    else:
        _render_chip("memory: empty")
    if uploads:
        _render_chip(f"uploads: {len(uploads)} file(s)", "good")
    else:
        _render_chip("uploads: none")
    if st.session_state.get("user_api_config"):
        _render_chip("API key unlocked", "warn" if run_live and not offline_llm else "good")
    elif env_api_configured:
        _render_chip("environment API configured", "good")
    else:
        _render_chip("API key locked")
    if offline_llm or not run_live:
        _render_chip("DEGRADED LOCAL FALLBACK · no LLM call", "warn")
    else:
        model_name = str(
            (st.session_state.get("user_api_config") or {}).get("model_name")
            or settings.model_name
            or settings.extract_model
        )
        _render_chip(f"external reasoning · {model_name}", "warn")
    _render_chip(
        "LangGraph scheduler" if LANGGRAPH_AVAILABLE else "deterministic graph scheduler",
        "good",
    )
    st.markdown(
        '<div class="memory-note">AUTO routing classifies each message independently. LLM availability can improve language understanding, but never changes evidence or execution authority.</div>',
        unsafe_allow_html=True,
    )
    if uploads:
        names = [
            str(item.get("file_name", "file"))
            for item in uploads[:3]
            if isinstance(item, dict)
        ]
        st.markdown(
            f'<div class="memory-note">Uploaded context: {escape(", ".join(names))}</div>',
            unsafe_allow_html=True,
        )


def _render_response_details(state: Dict[str, Any]) -> None:
    context = state.get("context_pack") or {}
    build = state.get("runtime_build") or context.get("runtime_build") or {}
    if build:
        with st.expander("高级详情 · 运行版本", expanded=False):
            st.json(build)


def _render_response_runtime(state: Dict[str, Any]) -> None:
    from observability.research_answer_evidence import render_answer_evidence
    render_answer_evidence(st, state, source_manifest=Path(__file__).parent / "data/indexes/source_documents_v2.jsonl")
    context = state.get("context_pack") or {}
    if context.get("answer_provenance"):
        prose = context.get("external_reasoning") or {}
        if state.get("runtime_mode") == "external_reasoning_with_deterministic_governance":
            st.caption("Runtime: LLM ONLINE · " + str(prose.get("model_name") or "configured model"))
        else:
            st.caption("Runtime: Local fallback · 本轮回答使用本地逻辑")
        with st.expander("运行详情", expanded=False):
            st.write({"模型": prose.get("model_name"), "生成状态": prose.get("status"),
                      "来源检查": prose.get("support_check"),
                      "数据状态": (context.get("response_context") or {}).get("data_state"),
                      "追踪": state.get("canonical_trace_id")})
        return
    # Display links by stored source ID; never manufacture citations from titles.
    from observability.research_source_links import source_links
    links = source_links(state.get("references") or [],
                         Path(__file__).parent / "data/indexes/source_documents_v2.jsonl")
    if links:
        with st.expander("原文链接与引用位置", expanded=False):
            st.caption("打开登记来源；引用位置对应本地证据快照。链接本身不代表审核通过。")
            for item in links:
                st.link_button(f"[{item['index']}] {item['title']}", item["url"])
                st.caption(item["locator"])
    mode = str(state.get("runtime_mode") or "degraded_local_fallback")
    context = state.get("context_pack") or {}
    semantic = context.get("semantic_parse") or {}
    prose = context.get("external_reasoning") or {}
    audit = context.get("grounded_answer_audit") or {}
    rejected_external = context.get("rejected_external_answer_audit") or {}
    retrieval = context.get("retrieval_context") or {}
    tool_observations = [
        item
        for item in (context.get("research_tool_observations") or [])
        if isinstance(item, dict)
    ]
    completed_tool_names = list(
        dict.fromkeys(
            str(item.get("tool_name") or "")
            for item in tool_observations
            if item.get("status") == "completed" and item.get("tool_name")
        )
    )
    response_intent = str(state.get("response_intent") or "")
    workflow_bundle = state.get("workflow_code_bundle") or {}
    workspace_handoff = state.get("workspace_handoff") or {}
    execution_handoff = state.get("execution_handoff") or {}
    if (
        response_intent == "workflow"
        and workflow_bundle.get("smoke_tested")
        and state.get("workflow_plan")
    ):
        _render_chip("LOCAL DETERMINISTIC WORKFLOW", "good")
        _render_chip("WORKFLOW READY", "good")
        _render_chip("RECIPE SMOKE VERIFIED", "good")
        if not state.get("references") or (audit and not audit.get("passed", True)):
            _render_chip("SCIENTIFIC EVIDENCE PARTIAL", "warn")
            st.caption(
                "The fixed recipe and dry-run plan are available, but this response "
                "does not have complete source-bound scientific evidence."
            )
        if str(execution_handoff.get("status") or "") == "not_requested":
            st.caption("执行未请求 · 审批规则保持不变")
        return
    if (
        response_intent == "workflow"
        and workspace_handoff.get("status") == "available"
        and workspace_handoff.get("notebook_strategy") == "capability_renderer"
    ):
        st.markdown(
            '<div class="research-routing"><strong>当前状态 · 工作区可交接</strong>'
            '仍需检查真实数据状态，尚未完成分析。</div>',
            unsafe_allow_html=True,
        )
        if not state.get("references"):
            _render_chip("SCIENTIFIC EVIDENCE PARTIAL", "warn")
        if str(execution_handoff.get("status") or "") == "not_requested":
            st.caption("执行未请求 · 审批规则保持不变")
        return
    if mode == "system_info_local":
        _render_chip("SYSTEM INFO · local deterministic answer", "good")
        return
    if mode == "product_capabilities_local":
        _render_chip("CAPABILITY MANIFEST · local verified scope", "good")
        return
    if mode == "external_general_reasoning":
        model = prose.get("model_name") or "external model"
        _render_chip(f"LLM USED · {model}", "good")
        _render_chip("GENERAL CHAT · scRNA retrieval skipped", "good")
        return
    if mode == "general_local_fallback":
        _render_chip("GENERAL CHAT · LLM NOT USED", "warn")
        error = prose.get("error_type")
        if error:
            st.caption(f"External LLM failure: {error}. No scientific tool candidate was substituted.")
        return
    if mode == "unsupported_action_blocked":
        _render_chip("BLOCKED · outside qualified action space", "warn")
        return
    if mode == "clarification_required":
        _render_chip("WAITING · clarification required", "warn")
        return
    if mode == "external_reasoning_with_deterministic_governance":
        model = prose.get("model_name") or semantic.get("model_name") or "external model"
        _render_chip(f"LLM USED · {model}", "good")
        if retrieval.get("pipeline"):
            _render_chip("KG+RAG USED", "good")
        if completed_tool_names:
            _render_chip("TOOLS · " + " + ".join(completed_tool_names), "good")
        if audit.get("passed"):
            supported = audit.get("structurally_supported_claim_rate")
            if supported is None:
                supported = audit.get("supported_claim_rate")
            label = (
                f"CLAIM STRUCTURE · {float(supported):.0%} mapped"
                if supported is not None
                else "CLAIM AUDIT · passed"
            )
            _render_chip(label, "good")
        else:
            _render_chip("CLAIM AUDIT · rejected external prose", "warn")
        return
    if mode == "external_semantic_with_deterministic_governance":
        model = semantic.get("model_name") or "external model"
        _render_chip(f"LLM SEMANTIC PARSE · {model}", "good")
        if retrieval.get("pipeline"):
            _render_chip("KG+RAG USED", "good")
        if completed_tool_names:
            _render_chip("TOOLS · " + " + ".join(completed_tool_names), "good")
        if rejected_external:
            _render_chip("LLM PROSE REJECTED · governed fallback shown", "warn")
        else:
            _render_chip("deterministic answer", "warn")
        return
    _render_chip("DEGRADED LOCAL FALLBACK", "warn")
    error = prose.get("error_type") or semantic.get("error_type")
    if error:
        provider = prose.get("provider") or semantic.get("provider") or "not reached"
        model = prose.get("model_name") or semantic.get("model_name") or "not resolved"
        _render_chip(f"LLM FAILED · {model}", "warn")
        st.caption(
            f"Provider: {provider} · failure: {error}. "
            "The conservative local answer was used and no execution authority changed."
        )
    elif rejected_external:
        st.caption(
            "External answer was rejected by the grounded-answer audit; "
            "the displayed answer is the governed local fallback."
        )
    elif audit and not audit.get("passed", True):
        st.caption(
            "The local fallback has incomplete claim-to-source mapping. "
            "Treat it as degraded guidance, not a verified scientific answer."
        )


def _render_catalog_graph_v2_panel() -> None:
    st.markdown(
        """
<div class="chat-app-header">
  <div class="chat-app-kicker">Evidence-governed KG v2</div>
  <div class="chat-app-title">scKG Knowledge Workspace</div>
  <div class="chat-app-subtitle">同一张图连接 Tool、Task、ToolContract、Environment、原文 chunk 与科学 pilot。execution_verified、retrieval_only、frozen 和 quarantined 在数据层强制隔离，冻结证据不会进入推荐路径。</div>
</div>
""",
        unsafe_allow_html=True,
    )
    controls = st.columns([1.3, 1, 1])
    with controls[0]:
        search = st.text_input(
            "Search",
            value="",
            placeholder="cell2location, RNA Velocity, MOFA2...",
        )
    with controls[1]:
        selected_kinds = st.multiselect(
            "Node types",
            [
                "Tool",
                "Task",
                "Category",
                "ToolContract",
                "Environment",
                "Dataset",
                "Evaluation",
                "Modality",
                "AlgorithmFamily",
                "Language",
                "RuntimePlatform",
                "Hardware",
                "Resolution",
                "Publication",
                "Benchmark",
                "Source",
                "SourceChunk",
            ],
            default=[
                "Tool",
                "Task",
                "Category",
                "Modality",
                "AlgorithmFamily",
                "ToolContract",
                "Environment",
            ],
        )
    with controls[2]:
        max_nodes = st.slider("Max nodes", 40, 220, 130, step=10)

    graph = _kg_view(tuple(selected_kinds), search.strip(), max_nodes)
    metric_cols = st.columns(7)
    for column, label, key in [
        (metric_cols[0], "Tools", "tools"),
        (metric_cols[1], "Semantic coverage", "semantic_coverage_pct"),
        (metric_cols[2], "Components", "connected_components"),
        (metric_cols[3], "Verified", "execution_verified"),
        (metric_cols[4], "Source chunks", "source_chunks"),
        (metric_cols[5], "Frozen", "frozen"),
        (metric_cols[6], "Quarantined", "quarantined"),
    ]:
        with column:
            value = graph.inventory.get(key, 0)
            st.metric(label, f"{value}%" if key == "semantic_coverage_pct" else f"{value:,}")

    explorer_tab, explanation_tab, quality_tab = st.tabs(
        ["Graph Explorer", "Tool Evidence", "Quality Audit"]
    )
    with explorer_tab:
        st.caption(
            "Solid teal = execution-verified; light gray = retrieval-only; dashed gray = frozen; dashed red = quarantined."
        )
        if graph.truncated:
            st.caption(
                "This is a display-sized subgraph. A point can look isolated when its neighbor was removed by node-type filters or the Max nodes limit; use exact search to load that node's local neighborhood."
            )
        components.html(build_knowledge_graph_html(graph), height=790, scrolling=True)

    graph_dir = get_settings().data_dir / "knowledge_graph_v2"
    query_service = EvidenceGraphQuery(graph_dir)
    with explanation_tab:
        if not query_service.available:
            st.warning("KG v2 snapshot is not available. Run `python scripts/build_knowledge_graph_v2.py`.")
        else:
            st.markdown("#### Explainable GraphRAG planner")
            query_cols = st.columns(2)
            with query_cols[0]:
                graph_task = st.text_input(
                    "Task query", value="doublet detection", key="kg_v2_task_query"
                )
            with query_cols[1]:
                graph_modality = st.text_input(
                    "Modality query", value="scRNA-seq", key="kg_v2_modality_query"
                )
            graph_matches = query_service.rank_tools(
                task=graph_task,
                modality=graph_modality,
                limit=15,
            )
            if graph_matches:
                st.dataframe(
                    _safe_rows(
                        [
                            {
                                "tool": match.tool_name,
                                "basis": match.candidate_basis,
                                "graph score": match.graph_score,
                                "task path": match.paths[0].get("relation", ""),
                                "modality path": match.paths[1].get("relation", ""),
                                "source chunks": match.source_chunk_count,
                                "contract": match.contract_available,
                                "pilot": match.scientific_pilot_available,
                            }
                            for match in graph_matches
                        ]
                    ),
                    use_container_width=True,
                    hide_index=True,
                )
                st.caption(
                    "graph_hypothesis only triggers evidence discovery. It cannot support recommendation or execution."
                )
            else:
                st.info("No governed graph path matched both the normalized task and modality.")
            st.divider()
            st.markdown("#### Tool path inspector")
            tools = [node.label for node in query_service.search("", node_types=["Tool"], limit=200)]
            default_index = tools.index("Scrublet") if "Scrublet" in tools else 0
            selected_tool = st.selectbox("Tool", tools, index=default_index)
            explanation = query_service.explain_tool(selected_tool)
            summary_cols = st.columns(4)
            summary_cols[0].metric("Verified tasks", len(explanation.trusted_tasks))
            summary_cols[1].metric("Contracts", len(explanation.contracts))
            summary_cols[2].metric("Scientific pilots", len(explanation.evaluations))
            summary_cols[3].metric("Frozen / quarantined", len(explanation.frozen_or_quarantined))
            if explanation.catalog_categories:
                st.markdown(
                    "**scRNA-tools categories:** "
                    + ", ".join(item.get("label", "") for item in explanation.catalog_categories)
                )
            if explanation.catalog_references:
                st.caption(
                    f"Catalog references: {len(explanation.catalog_references)}. These improve discovery but do not count as reviewed full-text evidence."
                )
            if explanation.trusted_tasks:
                st.markdown("**Verified capability:** " + ", ".join(explanation.trusted_tasks))
            for warning in explanation.warnings:
                st.warning(warning)
            if explanation.contracts:
                st.markdown("#### Contract and execution boundary")
                contract_rows = []
                for item in explanation.contracts:
                    properties = item.get("properties", {})
                    contract_rows.append(
                        {
                            "tool/version": f"{properties.get('tool_name', '')} {properties.get('tool_version', '')}".strip(),
                            "contract": properties.get("contract_version", ""),
                            "environment": properties.get("environment_id", ""),
                            "input": properties.get("input_object", ""),
                            "execution status": properties.get("execution_status", ""),
                            "scientific status": properties.get("scientific_validation_status", ""),
                            "governance": item.get("governance_layer", ""),
                        }
                    )
                st.dataframe(_safe_rows(contract_rows), use_container_width=True, hide_index=True)
            if explanation.evaluations:
                st.markdown("#### Dataset-scoped evaluation")
                evaluation_rows = []
                for item in explanation.evaluations:
                    properties = item.get("properties", {})
                    evaluation_rows.append(
                        {
                            "candidate": properties.get("candidate_id", ""),
                            "AUPRC": properties.get("auprc", ""),
                            "AUROC": properties.get("auroc", ""),
                            "F1": properties.get("f1", ""),
                            "success rate": properties.get("execution_success_rate", ""),
                            "authority": properties.get("metric_authority", ""),
                        }
                    )
                st.dataframe(_safe_rows(evaluation_rows), use_container_width=True, hide_index=True)
            ontology_rows = []
            for category, items in [
                ("modality", explanation.modalities),
                ("language", explanation.languages),
                ("runtime platform", explanation.runtime_platforms),
                ("algorithm family", explanation.algorithm_families),
                ("hardware", explanation.hardware),
                ("resolution", explanation.resolutions),
            ]:
                ontology_rows.extend(
                    {
                        "category": category,
                        "value": item.get("label", ""),
                        "relation": item.get("relation", ""),
                        "governance": item.get("governance_layer", ""),
                        "source bound": item.get("source_bound", False),
                    }
                    for item in items
                )
            if ontology_rows:
                st.markdown("#### Ontology paths")
                st.dataframe(_safe_rows(ontology_rows), use_container_width=True, hide_index=True)
            if explanation.frozen_or_quarantined:
                st.markdown("#### Evidence blocked from recommendation")
                frozen_rows = [
                    {
                        "type": item.get("node_type", ""),
                        "record": item.get("label", ""),
                        "layer": item.get("governance_layer", ""),
                        "reason": ", ".join(item.get("reason_codes", [])),
                    }
                    for item in explanation.frozen_or_quarantined[:20]
                ]
                st.dataframe(_safe_rows(frozen_rows), use_container_width=True, hide_index=True)

    with quality_tab:
        quality = _read_json_artifact(graph_dir / "quality_report.json")
        manifest = _read_json_artifact(graph_dir / "manifest.json")
        if not quality:
            st.warning("No KG quality report is available.")
        else:
            audit_cols = st.columns(6)
            audit_cols[0].metric("Nodes", quality.get("node_count", 0))
            audit_cols[1].metric("Edges", quality.get("edge_count", 0))
            audit_cols[2].metric("Dangling edges", quality.get("dangling_edge_count", 0))
            audit_cols[3].metric(
                "Frozen leakage", quality.get("frozen_recommendation_leakage_count", 0)
            )
            audit_cols[4].metric(
                "Hypothesis leakage",
                quality.get("hypothesis_recommendation_leakage_count", 0),
            )
            audit_cols[5].metric(
                "Integrity", "PASS" if quality.get("integrity_passed") else "FAIL"
            )
            connectivity_cols = st.columns(4)
            connectivity_cols[0].metric(
                "Components", quality.get("connected_component_count", 0)
            )
            connectivity_cols[1].metric(
                "Largest component", _format_percent(quality.get("largest_component_ratio", 0))
            )
            connectivity_cols[2].metric(
                "Tool relation coverage",
                _format_percent(quality.get("tool_relation_coverage_rate", 0)),
            )
            connectivity_cols[3].metric(
                "Semantic coverage",
                _format_percent(quality.get("tool_semantic_coverage_rate", 0)),
            )
            catalog_cols = st.columns(4)
            catalog_cols[0].metric(
                "Catalog snapshot",
                "READY" if quality.get("catalog_snapshot_available") else "MISSING",
            )
            catalog_cols[1].metric(
                "Category coverage",
                _format_percent(quality.get("catalog_category_coverage_rate", 0)),
            )
            catalog_cols[2].metric(
                "Catalog publications", quality.get("catalog_publication_count", 0)
            )
            catalog_cols[3].metric(
                "Catalog preprints", quality.get("catalog_preprint_count", 0)
            )
            coverage_cols = st.columns(5)
            coverage_cols[0].metric(
                "Catalog records", quality.get("catalog_tool_count", 0)
            )
            coverage_cols[1].metric(
                "Canonical tools", quality.get("canonical_tool_node_count", 0)
            )
            coverage_cols[2].metric(
                "Full-text source coverage",
                _format_percent(quality.get("source_bound_semantic_coverage_rate", 0)),
            )
            coverage_cols[3].metric(
                "Contract coverage",
                _format_percent(quality.get("contract_qualified_coverage_rate", 0)),
            )
            coverage_cols[4].metric(
                "Formal evidence coverage",
                _format_percent(quality.get("formal_evidence_coverage_rate", 0)),
            )
            st.caption(
                "Catalog connectivity measures discoverability. Full-text, contract and formal evidence coverage are separate quality dimensions."
            )
            st.markdown("#### Governance inventory")
            layers = quality.get("node_counts_by_layer", {})
            st.dataframe(
                _safe_rows([{"layer": key, "nodes": value} for key, value in layers.items()]),
                use_container_width=True,
                hide_index=True,
            )
            st.markdown(
                "Formal promotion-ready evidence: "
                f"publication **{quality.get('formal_publication_allowed_count', 0)}**, "
                f"benchmark **{quality.get('formal_benchmark_allowed_count', 0)}**."
            )
            st.markdown(
                "Neo4j shadow namespace: **"
                + ("IMPORTED" if manifest.get("neo4j_imported") else "LOCAL JSONL ONLY")
                + "**. Local JSONL remains the canonical auditable snapshot."
            )
            evaluation = _read_json_artifact(
                get_settings().project_root / "eval" / "kg_v2" / "kg_v2_summary.json"
            )
            retrieval = evaluation.get("graph_retrieval", {}) if evaluation else {}
            if retrieval:
                st.markdown("#### Fixed retrieval regression")
                regression_cols = st.columns(4)
                regression_cols[0].metric("Gold cases", retrieval.get("case_count", 0))
                regression_cols[1].metric(
                    "Macro Recall@10", _format_percent(retrieval.get("macro_recall_at_k", 0))
                )
                regression_cols[2].metric(
                    "Path provenance", _format_percent(retrieval.get("path_provenance_coverage", 0))
                )
                regression_cols[3].metric(
                    "Execution violations",
                    retrieval.get("execution_admission_violation_count", 0),
                )
                st.caption(
                    "Positive-only core-task regression; it does not estimate full-catalog precision or formal evidence quality."
                )
            for warning in quality.get("warnings", []):
                st.info(str(warning))


def _render_graph_explorer_page() -> None:
    settings = get_settings()
    decision_dir = settings.data_dir / "decision_graph_v3"
    query = DecisionGraphQuery(decision_dir)
    st.markdown(
        """
<style>
  .block-container { max-width: 1680px !important; padding-top:.55rem !important; padding-left:.8rem !important; padding-right:.8rem !important; }
  .graph-page-bar { display:flex; align-items:baseline; justify-content:space-between; gap:1rem; margin:0 0 .45rem; }
  .graph-page-title { color:#172033; font-size:1.18rem; line-height:1.2; font-weight:680; }
  .graph-page-meta { color:#718096; font-size:.76rem; white-space:nowrap; }
  div[data-testid="stRadio"] { margin-top:-.25rem; }
  div[data-testid="stRadio"] > label { display:none; }
  @media(max-width:760px) {
    .graph-page-bar { align-items:flex-start; flex-direction:column; gap:.15rem; }
    .graph-page-meta { white-space:normal; }
  }
</style>
<div class="graph-page-bar">
  <div class="graph-page-title">Graph Explorer</div>
  <div class="graph-page-meta">Decision Graph 1,011 nodes · Catalog 1,847 tools</div>
</div>
""",
        unsafe_allow_html=True,
    )
    if not query.available:
        st.warning(
            "Decision Graph v3 尚未构建。运行 `python scripts/build_decision_graph_v3.py`。"
        )
        return

    graph_mode = st.radio(
        "Graph view",
        ["Decision network", "Tool neighborhood", "Catalog landscape", "Catalog search"],
        horizontal=True,
        key="graph_explorer_mode",
    )
    if graph_mode == "Decision network":
        decision_workspace = build_decision_graph_workspace_view(decision_dir)
        components.html(
            build_knowledge_graph_html(decision_workspace),
            height=980,
            scrolling=False,
        )
    elif graph_mode == "Catalog landscape":
        components.html(
            build_catalog_landscape_html(settings.data_dir), height=950, scrolling=False
        )
    elif graph_mode == "Tool neighborhood":
        tools = query.list_tools()
        default_tool = tools.index("Scrublet") if "Scrublet" in tools else 0
        selected_tool = st.selectbox(
            "Tool",
            tools,
            index=default_tool,
            key="graph_explorer_tool",
        )
        decision_graph = build_decision_graph_neighborhood_view(
            decision_dir,
            selected_tool,
        )
        components.html(
            build_knowledge_graph_html(decision_graph),
            height=950,
            scrolling=False,
        )
    else:
        controls = st.columns([1.35, 1.5, 0.8])
        with controls[0]:
            search = st.text_input(
                "Search graph", placeholder="CellTypist, RNA velocity, integration..."
            )
        with controls[1]:
            selected_kinds = st.multiselect(
                "Node types",
                ["Tool", "Task", "Category", "ToolContract", "Environment", "Dataset", "Evaluation", "Publication", "SourceChunk"],
                default=["Tool", "Task", "Category", "ToolContract", "Environment"],
            )
        with controls[2]:
            max_nodes = st.slider("Display nodes", 60, 600, 180, step=20)
        graph = _kg_view(tuple(selected_kinds), search.strip(), max_nodes)
        if graph.truncated:
            st.caption(
                "当前为可读子图。使用搜索加载目标节点邻域；完整快照仍保存在 JSONL/Neo4j shadow namespace。"
            )
        components.html(build_knowledge_graph_html(graph), height=980, scrolling=False)


def _render_knowledge_review_panel() -> None:
    settings = get_settings()
    decision_dir = settings.data_dir / "decision_graph_v3"
    quality = _read_json_artifact(decision_dir / "quality_report.json")
    catalog_quality = _read_json_artifact(
        settings.data_dir / "knowledge_graph_v2" / "quality_report.json"
    )
    catalog_types = catalog_quality.get("node_counts_by_type", {})
    query = DecisionGraphQuery(decision_dir)
    st.markdown(
        """
<style>
  .block-container { max-width: 1320px !important; padding-top: .85rem !important; padding-left:1.2rem !important; padding-right:1.2rem !important; }
  .kg-header { border-bottom:1px solid #d9e0e8; padding:0.25rem 0 1.15rem; margin-bottom:1rem; }
  .kg-eyebrow { color:#627188; font-size:.73rem; font-weight:700; text-transform:uppercase; margin-bottom:.35rem; }
  .kg-title-row { display:flex; align-items:flex-end; justify-content:space-between; gap:1.5rem; }
  .kg-title { color:#172033; font-size:1.75rem; line-height:1.14; font-weight:680; margin:0; }
  .kg-subtitle { color:#697586; font-size:.92rem; line-height:1.55; max-width:760px; margin:.45rem 0 0; }
  .kg-version { color:#49657f; border:1px solid #cbd6e2; border-radius:4px; padding:.28rem .52rem; font-size:.74rem; white-space:nowrap; }
  .kg-stat-strip { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); border:1px solid #d9e0e8; border-radius:6px; background:#fff; margin:.9rem 0 1.25rem; }
  .kg-stat { min-width:0; padding:.72rem .85rem; border-right:1px solid #e4e9ef; }
  .kg-stat:last-child { border-right:0; }
  .kg-stat b { display:block; color:#172033; font-size:1.32rem; font-weight:650; line-height:1.2; }
  .kg-stat span { display:block; color:#768195; font-size:.72rem; margin-top:.22rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .kg-boundary { border-left:3px solid #d9825b; padding:.58rem .75rem; color:#5c6676; font-size:.84rem; margin:.8rem 0 1rem; background:#fff; }
  .kg-section-title { color:#1f2937; font-size:1rem; font-weight:650; margin:.55rem 0 .25rem; }
  div[data-testid="stTabs"] button[role="tab"] { min-width:auto !important; padding-left:.7rem !important; padding-right:.7rem !important; }
  div[data-testid="stDataFrame"] { border:1px solid #dde3ea; border-radius:6px; overflow:hidden; }
  @media(max-width:800px) {
    .kg-title-row { align-items:flex-start; flex-direction:column; gap:.65rem; }
    .kg-stat-strip { grid-template-columns:repeat(2,minmax(0,1fr)); }
    .kg-stat { border-bottom:1px solid #e4e9ef; }
    .kg-stat:nth-child(2n) { border-right:0; }
  }
</style>
""",
        unsafe_allow_html=True,
    )
    st.markdown(
        """
<div class="kg-header">
  <div class="kg-eyebrow">Agent knowledge review</div>
  <div class="kg-title-row">
    <div><div class="kg-title">Knowledge Review</div><div class="kg-subtitle">审查 Parent Agent 可用于回答和规划的 ActionBundle、工具合同与治理边界。图谱浏览已移至独立 Graph Explorer。</div></div>
    <div class="kg-version">Decision Graph v3</div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )
    if not query.available:
        st.warning(
            "Decision Graph v3 尚未构建。运行 `python scripts/build_decision_graph_v3.py`。"
        )
        with st.expander("Advanced catalog projection"):
            _render_catalog_graph_v2_panel()
        return

    environment_registry = EnvironmentRegistry()
    action_retriever = ActionBundleRetriever(
        graph_query=query,
        contract_registry=ToolContractRegistry(
            environment_registry=environment_registry
        ),
        environment_registry=environment_registry,
    )

    task_tab, dossier_tab, audit_tab = st.tabs(
        ["Action Space", "Tool Dossier", "Governance"]
    )
    with task_tab:
        st.markdown(
            f"""
<div class="kg-stat-strip">
  <div class="kg-stat"><b>{quality.get('catalog_tool_count', 0):,}</b><span>Catalog tools</span></div>
  <div class="kg-stat"><b>{int(catalog_types.get('Category', 0)):,}</b><span>Catalog categories</span></div>
  <div class="kg-stat"><b>{int(catalog_types.get('Task', 0)):,}</b><span>Discovered task labels</span></div>
  <div class="kg-stat"><b>{int(quality.get('node_counts_by_type', {}).get('Task', 0)):,}</b><span>Qualified tasks</span></div>
  <div class="kg-stat"><b>{quality.get('decision_ready_tool_count', 0):,}</b><span>Decision-ready tools</span></div>
</div>
""",
            unsafe_allow_html=True,
        )
        st.caption(
            "Discovered task labels come from catalog metadata and chunk extraction, contain aliases/noise, and are not executable capabilities. Qualified tasks have contract, environment and validation paths."
        )
        action_rows = query.list_actions()
        st.markdown(
            '<div class="kg-section-title">Governed action inventory</div>',
            unsafe_allow_html=True,
        )
        if action_rows:
            st.dataframe(
                _safe_rows(
                    [
                        {
                            "action": row["action"],
                            "task": row["task"],
                            "status": (
                                "QUALIFIED"
                                if row["implementation_count"] > 0
                                else "PLANNING ONLY"
                            ),
                            "implementations": row["implementation_count"],
                            "tools": row["tools"],
                        }
                        for row in action_rows
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No governed action is available yet.")
        task_rows = query.list_tasks()
        task_names = [row["task"] for row in task_rows]
        default_task = next(
            (index for index, item in enumerate(task_names) if "doublet" in item.casefold()),
            0,
        )
        selected_task = st.selectbox(
            "Task",
            task_names,
            index=default_task,
            key="decision_graph_task",
        )
        candidates = query.find_tools(selected_task)
        action_context = action_retriever.retrieve(
            task=selected_task,
            modality="scRNA-seq",
        )
        st.markdown(
            '<div class="kg-section-title">Governed ActionBundles</div>',
            unsafe_allow_html=True,
        )
        if not action_context.bundles:
            st.info(
                "该任务只有目录级发现结果，尚未形成 contract-grounded ActionBundle。"
            )
        else:
            bundle_columns = st.columns(min(2, len(action_context.bundles)))
            for index, bundle in enumerate(action_context.bundles):
                with bundle_columns[index % len(bundle_columns)]:
                    with st.container(border=True):
                        st.markdown(f"#### {bundle.tool_name} {bundle.tool_version}")
                        st.caption(
                            f"{bundle.action_name} · {bundle.readiness.replace('_', ' ').upper()}"
                        )
                        st.markdown(
                            f"**Contract** `{bundle.contract_id}`  \n"
                            f"**Environment** `{bundle.environment_id}`  \n"
                            f"**Data state** `{bundle.data_compatibility}`"
                        )
                        st.markdown(
                            f"**Input** {', '.join(bundle.input_requirements[:2])}  \n"
                            f"**Outputs** {', '.join(item['artifact_id'] for item in bundle.output_artifacts)}"
                        )
                        counts = st.columns(3)
                        counts[0].metric("Failures", len(bundle.failure_modes))
                        counts[1].metric("Validators", len(bundle.validation_rules))
                        counts[2].metric("Sources", len(bundle.source_material))
                        st.warning("Execution requires policy, data grant and exact approval.")
                        with st.expander("ActionBundle details"):
                            st.write("Planning blockers", bundle.planning_blockers or "none")
                            st.write("Execution requirements", bundle.execution_requirements)
                            st.write("Limitations", bundle.limitations)
        st.markdown(
            '<div class="kg-section-title">Strict candidates</div>', unsafe_allow_html=True
        )
        if not candidates:
            st.info(
                "该任务暂时没有通过 contract capability gate 的候选。请在 Catalog Graph 中做发现，但不要据此直接执行。"
            )
        else:
            st.dataframe(
                _safe_rows(
                    [
                        {
                            "tool": item.tool_name,
                            "readiness": item.readiness,
                            "basis": item.match_basis,
                            "source material": item.source_chunk_count,
                            "contract": "verified" if item.contract_available else "missing",
                            "pilot": "available" if item.evaluation_available else "missing",
                        }
                        for item in candidates
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )
        st.markdown(
            '<div class="kg-boundary"><b>Action gate</b><br>只有版本化 contract 实现的 <code>Action</code> 才能生成 ActionBundle。ActionBundle 只提供规划上下文，不能创建 ExecutionRequest；catalog category、旧 LLM profile 与未经晋升的 chunk task 标签只用于发现。</div>',
            unsafe_allow_html=True,
        )

    with dossier_tab:
        tools = query.list_tools()
        default_tool = tools.index("Scrublet") if "Scrublet" in tools else 0
        selected_tool = st.selectbox(
            "Tool",
            tools,
            index=default_tool,
            key="decision_graph_dossier_tool",
        )
        dossier = query.tool_dossier(selected_tool)
        st.markdown(
            f"""
<div class="kg-stat-strip">
  <div class="kg-stat"><b>{escape(dossier.readiness.replace('_', ' ').upper())}</b><span>Readiness</span></div>
  <div class="kg-stat"><b>{len(dossier.inputs)}</b><span>Inputs</span></div>
  <div class="kg-stat"><b>{len(dossier.outputs)}</b><span>Outputs</span></div>
  <div class="kg-stat"><b>{len(dossier.source_material)}</b><span>Source chunks</span></div>
  <div class="kg-stat"><b>{len(dossier.evaluations)}</b><span>Scoped evaluations</span></div>
</div>
""",
            unsafe_allow_html=True,
        )
        if dossier.blockers:
            st.warning("Not decision ready: " + ", ".join(dossier.blockers))
        left, right = st.columns(2)
        with left:
            st.markdown("#### Inputs and assumptions")
            rows = [
                {"type": "input", "item": item["label"]}
                for item in dossier.inputs
            ] + [
                {
                    "type": "assumption",
                    "item": item["label"],
                }
                for item in dossier.assumptions
            ]
            if rows:
                st.dataframe(_safe_rows(rows), use_container_width=True, hide_index=True)
            else:
                st.info("No reviewed input contract yet.")
        with right:
            st.markdown("#### Outputs and environment")
            rows = [
                {"type": "output", "item": item["label"]}
                for item in dossier.outputs
            ] + [
                {
                    "type": "environment",
                    "item": item["label"],
                }
                for item in dossier.environments
            ]
            if rows:
                st.dataframe(_safe_rows(rows), use_container_width=True, hide_index=True)
            else:
                st.info("No qualified output/environment path yet.")
        if dossier.parameters:
            st.markdown("#### Contract parameters")
            st.dataframe(
                _safe_rows(
                    [
                        {
                            "parameter": item["label"],
                            "default": item["properties"].get("default"),
                            "searchable range": item["properties"].get("searchable_range"),
                            "type": item["properties"].get("schema", {}).get("type"),
                        }
                        for item in dossier.parameters
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )
        if dossier.failure_modes or dossier.validation_rules or dossier.know_how:
            st.markdown("#### Action safeguards")
            safeguard_rows = [
                {"type": "failure mode", "item": item["label"]}
                for item in dossier.failure_modes
            ] + [
                {"type": "validation rule", "item": item["label"]}
                for item in dossier.validation_rules
            ] + [
                {"type": "reviewed know-how", "item": item["label"]}
                for item in dossier.know_how
            ]
            st.dataframe(
                _safe_rows(safeguard_rows),
                use_container_width=True,
                hide_index=True,
            )
        if dossier.evaluations:
            st.markdown("#### Dataset-scoped evaluation")
            st.dataframe(
                _safe_rows(
                    [
                        {
                            "candidate": item["properties"].get("candidate_id"),
                            "AUPRC": item["properties"].get("metrics", {}).get("scientific_pilot_auprc"),
                            "F1": item["properties"].get("metrics", {}).get("scientific_pilot_f1"),
                            "runtime median": item["properties"].get("runtime_summary", {}).get("median"),
                            "memory median MB": item["properties"].get("peak_memory_summary", {}).get("median"),
                            "scope": item["scope"],
                        }
                        for item in dossier.evaluations
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )
        with st.expander("Source material and limitations"):
            st.write(f"Linked source chunks: {len(dossier.source_material)}")
            for limitation in dossier.limitations:
                st.caption(limitation)
            if dossier.source_material:
                st.dataframe(
                    _safe_rows(
                        [
                            {
                                "title": item["label"],
                                "kind": item["properties"].get("source_kind"),
                                "span": item["properties"].get("source_span"),
                                "provenance": item["provenance_refs"],
                            }
                            for item in dossier.source_material[:30]
                        ]
                    ),
                    use_container_width=True,
                    hide_index=True,
                )

    with audit_tab:
        st.markdown(
            f"""
<div class="kg-stat-strip">
  <div class="kg-stat"><b>{quality.get('hypothesis_edge_count', 0)}</b><span>Hypothesis edges</span></div>
  <div class="kg-stat"><b>{_format_percent(quality.get('edge_provenance_coverage', 0))}</b><span>Edge provenance</span></div>
  <div class="kg-stat"><b>{_format_percent(quality.get('decision_edge_source_bound_rate', 0))}</b><span>Source-bound</span></div>
  <div class="kg-stat"><b>{_format_percent(quality.get('contract_io_coverage_rate', 0))}</b><span>Contract I/O</span></div>
  <div class="kg-stat"><b>{quality.get('action_implementation_count', 0)}</b><span>Action implementations</span></div>
</div>
""",
            unsafe_allow_html=True,
        )
        st.success("Integrity PASS" if quality.get("integrity_passed") else "Integrity FAIL")
        st.markdown(
            "多个 component 在这里是正常结果：它表示工具之间尚无经过审核的决策关系。系统不会再用 `scRNA-seq` 或宽泛 category 把它们强行粘成一张连通图。"
        )
        st.dataframe(
            _safe_rows(
                [
                    {"task": row["task"], "contract tools": row["contract_verified_tools"]}
                    for row in task_rows
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )
        for warning in quality.get("warnings", []):
            st.info(str(warning))



def _safe_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    safe: List[Dict[str, str]] = []
    for row in rows:
        safe.append(
            {
                str(key): _safe_cell(value)
                for key, value in row.items()
            }
        )
    return safe


def _safe_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return str(value)


def _read_json_artifact(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _read_jsonl_artifact(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _read_tsv_artifact(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _format_percent(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except Exception:
        return "0.0%"


def _render_admin_header(kicker: str, title: str, subtitle: str) -> None:
    st.markdown(
        f"""
<div class="chat-app-header">
  <div class="chat-app-kicker">{escape(kicker)}</div>
  <div class="chat-app-title">{escape(title)}</div>
  <div class="chat-app-subtitle">{escape(subtitle)}</div>
</div>
""",
        unsafe_allow_html=True,
    )


def _workflow_candidate_tools_from_state(state: Dict[str, Any]) -> List[str]:
    names: List[str] = []
    for key in ("candidate_tools", "tool_candidates", "scored_tools"):
        for item in _state_get_list(state, key):
            if isinstance(item, str):
                names.append(item)
            else:
                row = _as_dict(item)
                name = row.get("tool_name") or row.get("name")
                if name:
                    names.append(str(name))
    if not names:
        names = list(DEFAULT_WORKFLOW_CANDIDATE_TOOLS)
    deduped: List[str] = []
    seen = set()
    for name in names:
        key = name.casefold()
        if key not in seen:
            deduped.append(name)
            seen.add(key)
    return deduped[:20]


def _attach_workflow_decision(
    *,
    query: str,
    state: Dict[str, Any],
    project_memory: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    constraints = {
        **project_memory,
        **_constraints(state),
    }
    if "output_goal" not in constraints:
        constraints["output_goal"] = "auditable workflow decision report"
    try:
        return build_workflow_decision_response(
            query=query,
            constraints=constraints,
            candidate_tools=_workflow_candidate_tools_from_state(state),
            max_snippets_per_step=4,
        )
    except Exception as exc:
        return {
            "response_type": "workflow_decision_error",
            "error": f"{type(exc).__name__}: {exc}",
            "query": query,
            "metrics": {
                "workflow_steps": 0,
                "retrieval_snippets": 0,
                "source_bound_retrieval_snippets": 0,
                "evidence_boundary_violation_count": 0,
            },
            "workflow_steps": [],
            "guardrail": "Workflow decision card failed to render; main agent answer is unchanged.",
        }


def _render_workflow_decision_card(response: Dict[str, Any]) -> None:
    if not response:
        return
    st.markdown("### Workflow Decision")
    if response.get("error"):
        st.warning(response.get("error"))
        return
    metrics = response.get("metrics") or {}
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Steps", metrics.get("workflow_steps", 0))
    c2.metric("Candidates", metrics.get("candidate_tool_count", 0))
    c3.metric("Snippets", metrics.get("retrieval_snippets", 0))
    c4.metric("Source Chunks", metrics.get("source_bound_retrieval_snippets", 0))
    c5.metric("Boundary", metrics.get("evidence_boundary_violation_count", 0))
    if metrics.get("evidence_boundary_violation_count", 0):
        st.error("Evidence boundary violation detected. Treat this workflow as invalid until fixed.")
    else:
        st.success("Plan-only workflow generated; evidence boundary is intact.")
    st.caption(response.get("guardrail", ""))

    steps = response.get("workflow_steps") or []
    if steps:
        st.dataframe(
            _safe_rows(
                [
                    {
                        "order": step.get("order"),
                        "step": step.get("name", ""),
                        "task": step.get("task", ""),
                        "candidate_tools": ", ".join(step.get("candidate_tools") or []),
                        "snippets": step.get("snippet_count", 0),
                        "source_chunks": step.get("source_bound_snippet_count", 0),
                        "status": step.get("status", ""),
                    }
                    for step in steps
                ]
            ),
            use_container_width=True,
        )
        for step in steps:
            with st.expander(f"{step.get('order')}. {step.get('name')}"):
                st.table(
                    _safe_rows(
                        [
                            {"field": "task", "value": step.get("task", "")},
                            {"field": "required_input", "value": ", ".join(step.get("required_input") or [])},
                            {"field": "produced_output", "value": ", ".join(step.get("produced_output") or [])},
                            {"field": "candidate_tools", "value": ", ".join(step.get("candidate_tools") or [])},
                            {"field": "rag_mode", "value": step.get("rag_mode", "")},
                        ]
                    )
                )
                snippets = step.get("snippets") or []
                if snippets:
                    st.dataframe(_safe_rows(snippets), use_container_width=True)
                else:
                    st.info("No retrieval snippets for this step yet.")
    with st.expander("Markdown decision report", expanded=False):
        st.code(response.get("markdown_report", ""), language="markdown")


def _render_evidence_admin_panel() -> None:
    _render_admin_header(
        "Admin · Evidence & RAG",
        "证据与混合 RAG 管线状态",
        "查看 source chunks、PDF/HTML 获取状态、source registry、metadata mismatch 和 extraction failure。",
    )
    from observability.dashboard.evidence_panel import render_evidence_panel

    render_evidence_panel(Path(__file__).resolve().parent, get_settings().data_dir)


def _render_evaluation_admin_panel() -> None:
    _render_admin_header(
        "Admin · Evaluation",
        "评测与失败队列",
        "把 workflow decision 的成功标准、失败场景和 evidence boundary 检查放在同一个用户应用里。",
    )
    phase6 = Phase6EvaluationService()
    unified = phase6.load_unified_evaluation(suite="release")
    if not unified:
        unified = phase6.load_unified_evaluation(suite="nightly")
    if not unified:
        unified = phase6.load_unified_evaluation(suite="pr")
    st.markdown("#### Evaluation-driven development")
    if unified:
        gate = unified.get("release_gate") or {}
        manifest = unified.get("manifest") or {}
        regression = unified.get("regression") or {}
        metrics = unified.get("metrics") or []
        failures = unified.get("failures") or []
        measured = [row for row in metrics if row.get("status") == "measured"]
        not_run = [row for row in metrics if row.get("status") == "not_run"]
        columns = st.columns(5)
        columns[0].metric("Suite", str(unified.get("suite") or "unknown").upper())
        columns[1].metric("Release gate", str(gate.get("status") or "unknown").upper())
        columns[2].metric("Measured", len(measured))
        columns[3].metric("Not run", len(not_run))
        columns[4].metric("Failures", len(failures))
        _status_badge("READY" if gate.get("status") == "passed" else "BLOCKED")
        st.caption(
            f"Experiment `{unified.get('experiment_id', '')}` · "
            f"Git `{str(manifest.get('git_head') or '')[:10]}` · "
            f"regression `{regression.get('reason') or ('comparable' if regression.get('comparable') else 'not_comparable')}`"
        )
        gate_rows = [
            {
                "gate": row.get("gate_id", ""),
                "status": row.get("status", ""),
                "observed": row.get("observed"),
                "requirement": row.get("requirement", ""),
                "reason": row.get("reason", ""),
            }
            for row in gate.get("checks") or []
        ]
        if gate_rows:
            st.dataframe(_safe_rows(gate_rows), use_container_width=True, hide_index=True)
        if not_run:
            with st.expander("Not run and evaluation blind spots"):
                st.dataframe(
                    _safe_rows(
                        [
                            {
                                "metric": row.get("metric_id", ""),
                                "reason": "; ".join(row.get("limitations") or []),
                            }
                            for row in not_run
                        ]
                    ),
                    use_container_width=True,
                    hide_index=True,
                )


        if failures:
            with st.expander("Failure clusters and root stages"):
                st.dataframe(_safe_rows(failures), use_container_width=True, hide_index=True)
        st.caption(
            "This page only reads immutable artifacts. It never calls an LLM, installs a package, "
            "changes gold data, or starts scientific execution."
        )
    else:
        st.info(
            "No unified experiment yet. Run `python eval/run_evaluation_pipeline.py --suite pr`."
        )
    system_quality_dir = Path("data/evaluation/system_quality_v1")
    system_quality = _read_json_artifact(system_quality_dir / "summary.json")
    st.markdown("#### System quality release gate")
    if system_quality:
        scenario_rows = system_quality.get("scenarios") or []
        usability = next(
            (
                item
                for item in system_quality.get("dimensions") or []
                if item.get("dimension") == "usability"
            ),
            {},
        )
        quality_metrics = st.columns(5)
        quality_metrics[0].metric(
            "Engineering gate",
            "PASS" if system_quality.get("engineering_gate_passed") else "FAIL",
        )
        quality_metrics[1].metric(
            "Operational cases",
            f"{sum(bool(item.get('passed')) for item in scenario_rows)}/{len(scenario_rows)}",
        )
        quality_metrics[2].metric(
            "Real participants",
            int((usability.get("metrics") or {}).get("participant_count") or 0),
        )
        quality_metrics[3].metric(
            "Unauthorized execution",
            int(
                next(
                    (
                        (item.get("metrics") or {}).get(
                            "unauthorized_execution_count", 0
                        )
                        for item in system_quality.get("dimensions") or []
                        if item.get("dimension") == "safety_and_isolation"
                    ),
                    0,
                )
            ),
        )
        quality_metrics[4].metric(
            "Phase 6 complete",
            "ELIGIBLE" if system_quality.get("phase6_complete_eligible") else "NOT YET",
        )
        _status_badge(
            "READY"
            if system_quality.get("recommended_status") == "PHASE6_TRIAL_READY"
            else "COMPLETED"
            if system_quality.get("recommended_status")
            == "PHASE6_COMPLETE_REVIEW_REQUIRED"
            else "BLOCKED"
        )
        st.caption(
            "Automated engineering evidence and real-user evidence are reported separately. "
            "Maintainer rehearsal never changes Phase 6 to complete."
        )
        st.dataframe(
            _safe_rows(
                [
                    {
                        "dimension": item.get("dimension", ""),
                        "status": item.get("status", ""),
                        "blockers": "; ".join(item.get("blockers") or []),
                        "warnings": "; ".join(item.get("warnings") or []),
                    }
                    for item in system_quality.get("dimensions") or []
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )
        with st.expander("Operational scenario results"):
            st.dataframe(
                _safe_rows(scenario_rows), use_container_width=True, hide_index=True
            )
    else:
        st.info(
            "Run `python eval/run_system_quality_evaluation.py` to generate the unified system gate."
        )

    agent_quality_dir = Path("data/evaluation/agent_quality_v2")
    agent_quality = _read_json_artifact(agent_quality_dir / "summary.json")
    st.markdown("#### Agent quality release gate")
    if agent_quality:
        metrics = st.columns(6)
        metrics[0].metric("Task completion", _format_percent(agent_quality.get("task_completion_rate")))
        metrics[1].metric("Tool correctness", _format_percent(agent_quality.get("tool_correctness")))
        metrics[2].metric("Intent accuracy", _format_percent(agent_quality.get("intent_accuracy")))
        metrics[3].metric("Hallucination", _format_percent(agent_quality.get("hallucination_rate")))
        metrics[4].metric("Compliance", _format_percent(agent_quality.get("compliance_pass_rate")))
        metrics[5].metric("Stability", _format_percent(agent_quality.get("stability_rate")))
        _status_badge("READY" if agent_quality.get("release_gate_passed") else "BLOCKED")
        st.caption(
            f"{agent_quality.get('case_count', 0)} cases × {agent_quality.get('repetition_count', 0)} repetitions · "
            f"p50 {float(agent_quality.get('latency_p50_ms') or 0):.1f} ms · "
            f"p95 {float(agent_quality.get('latency_p95_ms') or 0):.1f} ms"
        )
        domain_counts = agent_quality.get("failure_domain_counts") or {}
        if domain_counts:
            st.dataframe(
                _safe_rows(
                    [
                        {"failure owner": owner, "count": count}
                        for owner, count in domain_counts.items()
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )
        failure_queue = _read_jsonl_artifact(agent_quality_dir / "failure_queue.jsonl")
        if failure_queue:
            with st.expander("Agent failure attribution queue"):
                st.dataframe(_safe_rows(failure_queue), use_container_width=True, hide_index=True)
        else:
            st.success("Agent quality failure queue is empty for the current deterministic suite.")
    else:
        st.info("Run `python eval/run_agent_quality_evaluation.py` to generate the Agent quality gate.")

    eval_dir = Path("eval")
    summary = _read_json_artifact(eval_dir / "workflow_eval_v0_1_summary.json")
    if summary:
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Scenarios", summary.get("scenario_count", 0))
        c2.metric("Pass Rate", _format_percent(summary.get("pass_rate")))
        c3.metric("Step Recall", _format_percent(summary.get("required_step_recall")))
        c4.metric("Tool Recall", _format_percent(summary.get("candidate_tool_recall")))
        c5.metric("Boundary Violations", summary.get("evidence_boundary_violation_count", 0))
        st.caption(summary.get("guardrail", ""))
    else:
        st.info("No workflow eval summary found. Run `python eval/run_workflow_eval.py`.")
    per_rows = _read_tsv_artifact(eval_dir / "workflow_eval_v0_1_per_scenario.tsv")
    if per_rows:
        st.markdown("#### Per Scenario")
        st.dataframe(_safe_rows(per_rows), use_container_width=True)
    failure_rows = _read_tsv_artifact(eval_dir / "workflow_eval_v0_1_failure_queue.tsv")
    if failure_rows:
        st.markdown("#### Failure Queue")
        st.dataframe(_safe_rows(failure_rows), use_container_width=True)
    else:
        st.success("Failure queue is empty.")

    phase6_summary = phase6.load_summary()
    st.markdown("#### Phase 6 dual-track baselines")
    if phase6_summary:
        baselines = phase6_summary.get("baselines") or {}
        st.dataframe(
            _safe_rows(
                [
                    {
                        "baseline": baseline_id,
                        "track": item.get("track", ""),
                        "status": item.get("status", ""),
                        "cases": item.get("case_count", 0),
                        "reason": "; ".join(item.get("reasons") or []),
                    }
                    for baseline_id, item in baselines.items()
                ]
            ),
            use_container_width=True,
        )
        track_filter = st.selectbox("Track filter", ["all", "A", "B"], key="phase6_track_filter")
        phase6_cases = phase6.list_cases(track=None if track_filter == "all" else track_filter)
        if phase6_cases:
            st.dataframe(_safe_rows(phase6_cases), use_container_width=True)
    else:
        st.info("Run `python eval/run_phase6_baselines.py` to generate Phase 6 artifacts.")

    st.markdown("#### Phase 6 trace audit")
    trace_audit = phase6.load_trace_audit()
    if trace_audit:
        st.json(trace_audit)
    else:
        st.info("No Phase 6 trace audit artifact found.")

    st.markdown("#### Phase 6 failure queue")
    repair_filter = st.selectbox(
        "Repairable filter", ["all", "True", "False"], key="phase6_failure_repairable"
    )
    phase6_failures = phase6.list_failures(
        repairable=None if repair_filter == "all" else repair_filter
    )
    if phase6_failures:
        st.dataframe(_safe_rows(phase6_failures), use_container_width=True)
    else:
        st.success("Phase 6 failure queue is empty for this filter.")

    st.markdown("#### Group trial telemetry")
    telemetry = phase6.list_trial_events()
    st.caption("Anonymous operational feedback only; it is never scientific evidence.")
    if telemetry:
        st.dataframe(_safe_rows(telemetry), use_container_width=True)
    else:
        st.info("No real group trial feedback has been recorded.")


_CANDIDATE_RELATION_LABELS = {
    "revision_of": "is version of",
    "implements_method": "implements method",
    "supports_task": "supports task",
    "has_requirement": "has requirement",
    "output_type": "has output representation",
}


def _candidate_entity_display_label(packet: Dict[str, Any], canonical_id: str | None) -> str:
    if not canonical_id:
        return "—"
    for entity in packet.get("linked_entities") or []:
        if entity.get("candidate_id") == canonical_id and entity.get("mention"):
            label = str(entity["mention"]).replace("_", " ")
            return label[:1].upper() + label[1:]
    fallback = canonical_id.rsplit(":", 1)[-1].replace("__", "::").replace("_", " ")
    return fallback[:1].upper() + fallback[1:]


def _candidate_relation_display(packet: Dict[str, Any]) -> Dict[str, str]:
    canonical = packet.get("canonical_statement") or {}
    predicate_id = canonical.get("predicate")
    relation_label = _CANDIDATE_RELATION_LABELS.get(
        predicate_id,
        str(predicate_id).replace("_", " ") if predicate_id else "—",
    )
    if canonical.get("is_scientific_statement"):
        relation_class = "Scientific statement candidate"
    elif canonical.get("canonical_kind") == "STRUCTURAL_IDENTITY_BINDING":
        relation_class = "Structural identity relation"
    elif canonical.get("canonical_kind") == "STRUCTURAL_OUTPUT_BINDING":
        relation_class = "Structural output relation"
    else:
        relation_class = "Structural / provenance relation"
    return {
        "subject_label": _candidate_entity_display_label(packet, canonical.get("subject_id")),
        "relation_label": relation_label,
        "object_label": _candidate_entity_display_label(packet, canonical.get("object_id")),
        "relation_class": relation_class,
        "subject_id": canonical.get("subject_id") or "—",
        "predicate_id": predicate_id or "—",
        "object_id": canonical.get("object_id") or "—",
    }


def _render_hardened_document_ingestion_payload(
    summary: Dict[str, Any], packets: List[Dict[str, Any]]
) -> None:
    source = summary["source"]
    st.info(
        "Quality-hardened candidate ingestion · structural conformance only · "
        "not scientific validity, trust, approval, promotion, or execution authorization"
    )
    source_cols = st.columns(4)
    source_cols[0].metric("Document", source["filename"])
    source_cols[1].metric("Pages", source["page_count"])
    source_cols[2].metric("Ontology", summary["ontology_version"] if "ontology_version" in summary else "frozen")
    source_cols[3].metric("Hash", f"{source['sha256'][:12]}…")

    st.markdown("### Ingestion dispositions")
    st.caption(
        "These are processing/review states, not judgments that a scientific proposition is true or false."
    )
    disposition_order = [
        "RAW_PROPOSAL", "EVIDENCE_ONLY", "ABSTAINED", "DROPPED", "NEEDS_REVIEW", "CANDIDATE_READY"
    ]
    disposition_cols = st.columns(6)
    for index, status in enumerate(disposition_order):
        disposition_cols[index].metric(status, summary["counts"].get(status, 0))
    st.caption(
        f"CANDIDATE_READY whole-segment evidence: {summary['unbounded_ready_candidates']} · "
        f"hallucinated scope values: {summary['hallucinated_scope_count']}"
    )
    if not packets:
        st.warning("No review packets were produced from the text-extractable content.")
        return

    ready_packets = [packet for packet in packets if packet["final_disposition"] == "CANDIDATE_READY"]
    st.markdown("### Candidate KG Relations")
    st.caption(
        "Human-readable ontology labels are primary; canonical IDs are shown as secondary audit fields. "
        "This set includes structural/provenance relations as well as scientific statement candidates."
    )
    if ready_packets:
        ready_rows = []
        for packet in ready_packets:
            display = _candidate_relation_display(packet)
            ready_rows.append(
                {
                    "Subject": display["subject_label"],
                    "Relation": display["relation_label"],
                    "Object": display["object_label"],
                    "Relation class": display["relation_class"],
                    "Scope": packet["scope"]["core_scope_status"],
                    "EvidenceSpan": packet["evidence_span"]["locator"],
                    "SourceRevision": packet["source"]["source_revision_id"],
                    "Validation": packet["validation_report"]["stage_status"]["SEMANTIC_VALIDATION"],
                    "Governance": packet["governance"]["human_review_status"],
                    "Subject canonical ID": display["subject_id"],
                    "Predicate canonical ID": display["predicate_id"],
                    "Object canonical ID": display["object_id"],
                }
            )
        st.dataframe(
            ready_rows,
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.warning("No CANDIDATE_READY packet was produced.")

    ordered_packets = ready_packets + [packet for packet in packets if packet["final_disposition"] != "CANDIDATE_READY"]
    labels = {}
    for index, packet in enumerate(ordered_packets):
        if packet["final_disposition"] == "CANDIDATE_READY":
            display = _candidate_relation_display(packet)
            label = (
                f"{index + 1}. {display['subject_label']} — "
                f"{display['relation_label']} → {display['object_label']}"
            )
        else:
            label = f"{index + 1}. {packet['block_type']} → {packet['final_disposition']}"
        labels[label] = packet
    selected_label = st.selectbox("HumanReviewPacket", list(labels), key="hardened_ingestion_packet")
    packet = labels[selected_label]
    st.markdown("### Block → proposition → Candidate KG relation")
    raw_col, normalized_col = st.columns(2)
    raw_col.markdown("#### Raw block")
    raw_col.code(packet["raw_block"], language=None)
    normalized_col.markdown("#### Normalized block")
    normalized_col.code(packet["normalized_block"], language=None)
    canonical_display = _candidate_relation_display(packet)
    evidence = packet.get("evidence_span") or {}
    scope = packet.get("scope") or {}
    governance = packet["governance"]
    st.table(
        [
            {"Field": "Block type", "Value": packet["block_type"]},
            {"Field": "Final disposition", "Value": packet["final_disposition"]},
            {"Field": "Subject", "Value": canonical_display["subject_label"]},
            {"Field": "Subject canonical ID", "Value": canonical_display["subject_id"]},
            {"Field": "Relation", "Value": canonical_display["relation_label"]},
            {"Field": "Predicate canonical ID", "Value": canonical_display["predicate_id"]},
            {"Field": "Object", "Value": canonical_display["object_label"]},
            {"Field": "Object canonical ID", "Value": canonical_display["object_id"]},
            {"Field": "Relation class", "Value": canonical_display["relation_class"]},
            {"Field": "Scope", "Value": json.dumps(scope, ensure_ascii=False)},
            {"Field": "EvidenceSpan", "Value": evidence.get("locator", "—")},
            {"Field": "SourceRevision", "Value": packet["source"]["source_revision_id"]},
            {
                "Field": "Validation",
                "Value": packet["validation_report"]["stage_status"]["SEMANTIC_VALIDATION"],
            },
            {
                "Field": "Governance status",
                "Value": (
                    f"human_review_status={governance['human_review_status']}; "
                    f"trusted={governance['trusted']}; "
                    f"production_retrieval_eligible={governance['production_retrieval_eligible']}; "
                    f"execution_authorized={governance['execution_authorized']}"
                ),
            },
            {"Field": "Raw proposition", "Value": json.dumps(packet.get("raw_proposition"), ensure_ascii=False)},
            {"Field": "Canonical relation payload", "Value": json.dumps(packet.get("canonical_statement"), ensure_ascii=False)},
        ]
    )

    st.markdown("#### Stage status")
    stage_order = [
        "TEXT_QUALITY", "BLOCK_CLASSIFICATION", "CLAIM_LIKENESS", "ENTITY_LINKING",
        "CANONICALIZATION", "SCOPE_RESOLUTION", "EVIDENCE_BINDING", "SEMANTIC_VALIDATION",
    ]
    stage_status = packet["validation_report"]["stage_status"]
    stage_cols = st.columns(4)
    for index, stage in enumerate(stage_order):
        stage_cols[index % 4].metric(stage, stage_status[stage])
    st.caption("SEMANTIC_VALIDATION means frozen-registry structural conformance; scientific validity is not assessed.")

    detail_tabs = st.tabs(["Evidence", "Entities", "Scope + provenance", "Ontology gaps", "Governance"])
    with detail_tabs[0]:
        st.json(packet.get("evidence_span"))
    with detail_tabs[1]:
        st.json(packet.get("linked_entities") or [])
    with detail_tabs[2]:
        st.json(packet.get("scope"))
    with detail_tabs[3]:
        st.json(packet.get("evidence_gaps") or [])
    with detail_tabs[4]:
        st.json(packet["governance"])


def _render_hardened_document_ingestion(snapshot_dir: Path) -> None:
    summary_path = snapshot_dir / "summary.json"
    packet_path = snapshot_dir / "human_review_packets.jsonl"
    if not summary_path.is_file() or not packet_path.is_file():
        st.warning("The hardened scientific-document ingestion snapshot is unavailable.")
        return
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    packets = [json.loads(line) for line in packet_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    _render_hardened_document_ingestion_payload(summary, packets)


def _render_candidate_studio(
    scientific_summary: Dict[str, Any],
) -> None:
    st.markdown(
        """
<div style="border:2px solid #b45309;background:#fff7ed;padding:.8rem 1rem;border-radius:8px;margin:.2rem 0 1rem">
  <strong>PREVIEW ONLY · Scientific KG unchanged</strong><br/>
  <span style="font-size:.85rem;color:#6b4f2f">KG mutation: DISABLED · ReviewDecision: NOT AVAILABLE · Canonical promotion: NOT AVAILABLE</span>
</div>
""",
        unsafe_allow_html=True,
    )
    st.caption(
        "Exactly one text-extractable PDF · candidate_proposal only · no production RAG indexing or Planner consumption"
    )

    repository_root = Path(__file__).resolve().parent
    frozen = repository_root / "data/evaluation/scientific_knowledge_studio_v1"
    mode = st.radio(
        "Document source",
        [
            "Replay verified SoupX run",
            "Upload a PDF for local preview",
            "Replay hardened SoupX ingestion",
        ],
        horizontal=True,
        key="scientific_knowledge_studio_mode",
        help="Replay reads candidate-only artifacts. Upload runs the quality-hardened local ingestion pipeline for one PDF.",
    )

    run: Dict[str, Any] | None = None
    run_origin = ""
    if mode == "Replay hardened SoupX ingestion":
        _render_hardened_document_ingestion(
            repository_root / "data/evaluation/scientific_document_ingestion_v1"
        )
        return
    if mode == "Replay verified SoupX run":
        if (frozen / "manifest.json").is_file():
            run = load_studio_evaluation_snapshot(frozen)
            run_origin = "REPLAY"
            st.info(
                "Replay of previously generated real pipeline artifacts · SoupX 1.6.2 manual · no current re-inference"
            )
    else:
        studio = ScientificDocumentIngestionService(repository_root)
        upload_col, action_col = st.columns([3, 1])
        with upload_col:
            uploaded = st.file_uploader(
                "One scientific PDF",
                type=["pdf"],
                accept_multiple_files=False,
                key="scientific_knowledge_studio_pdf",
                help="The PDF is parsed locally. The binary and full text are not committed to the evaluation snapshot.",
            )
        with action_col:
            st.write("")
            run_clicked = st.button(
                "Build local preview",
                type="primary",
                disabled=uploaded is None,
                key="scientific_knowledge_studio_run",
            )
        if run_clicked and uploaded is not None:
            try:
                result = studio.run_pdf_bytes(uploaded.name, uploaded.getvalue())
                source = result["source"]
                run_summary = result["summary"]
                st.session_state.scientific_document_ingestion_run = {
                    "summary": {
                        "source": source.model_dump(mode="json"),
                        "ontology_version": run_summary["ontology_version"],
                        "counts": run_summary["counts"],
                        "unbounded_ready_candidates": run_summary["unbounded_ready_candidates"],
                        "hallucinated_scope_count": run_summary["hallucinated_scope_count"],
                    },
                    "packets": [packet.model_dump(mode="json") for packet in result["packets"]],
                }
                st.success("Hardened candidate review packets built. Scientific KG remains unchanged.")
            except Exception as exc:
                st.error(f"Studio preview blocked: {type(exc).__name__}: {exc}")
        runtime_value = st.session_state.get("scientific_document_ingestion_run")
        if runtime_value:
            _render_hardened_document_ingestion_payload(
                runtime_value["summary"], runtime_value["packets"]
            )
            return

    if run is None:
        st.info("Select the verified replay or upload one PDF. No Scientific KG mutation will occur.")
        return

    demo = candidate_demo_view(run)
    document = demo["document"]
    trace = run["trace"]
    evidence_rows = list(run["evidence"])
    segment_rows = {row["segment_id"]: row for row in run["segments"]}

    st.markdown("### Document")
    document_cols = st.columns([2.1, 1, 1, 1])
    document_cols[0].metric("Document", document["file"])
    document_cols[1].metric("Pages parsed", f"{document['parsed_pages']} / {document['page_count']}")
    document_cols[2].metric("Parse status", document["parse_status"])
    document_cols[3].metric("Run mode", run_origin)
    st.caption(
        f"{document['name']} · source: {document['source_type']} · parser: {document['parser']} · "
        f"parse gaps: {document['parse_gap_count']} · SHA256 {document['sha256'][:16]}…"
    )

    st.markdown("### PDF → Candidate KG Pipeline")
    st.caption("PDF → Parse → Evidence → Statement → Scope → Validate → Candidate KG")
    pipeline_cols = st.columns(len(demo["pipeline"]))
    for index, item in enumerate(demo["pipeline"]):
        pipeline_cols[index].metric(f"{index + 1} {item['stage']}", item["value"], item["status"])
    st.caption(
        "Legacy replay structural statuses: VALID / NEEDS_REVIEW / INVALID. "
        "They do not assert scientific truth. Counts are read from this run's artifacts."
    )

    with st.expander("Technical eight-stage run trace"):
        stage_labels = {
            "UPLOAD": "Upload", "SOURCE_IDENTITY": "Source", "PARSE": "Parse",
            "EVIDENCE_PROPOSAL": "Evidence", "SEMANTIC_EXTRACTION": "Extract",
            "IDENTITY_RESOLUTION": "Resolve", "VALIDATION": "Validate", "PREVIEW": "Preview",
        }
        step_cols = st.columns(8)
        for index, row in enumerate(trace):
            step_cols[index].metric(f"{index + 1} {stage_labels[row['stage']]}", row["status"])

    st.markdown("### Evidence → Candidate Statement")
    st.caption(
        "Every displayed statement is a Candidate / Proposal. Source binding does not mean trusted, canonical, promoted, or support-confirmed knowledge."
    )
    statements = demo["statements"]
    if statements:
        statement_labels = {
            f"{index + 1}. [STRUCTURAL {row['validation_status']}] {row['claim_text'][:110]}": row
            for index, row in enumerate(statements)
        }
        selected_statement_label = st.selectbox(
            "Candidate Statement / Claim proposal",
            list(statement_labels),
            key="studio_statement_selection",
        )
        statement = statement_labels[selected_statement_label]
        bound_evidence = statement["evidence_bindings"]
        evidence_col, statement_col = st.columns([1.05, 1])
        with evidence_col:
            st.markdown("#### EvidenceSpan")
            if bound_evidence:
                evidence_labels = {
                    f"Page {row['page_number']} · {row['proposal_id'][-8:]}": row
                    for row in bound_evidence
                }
                selected_evidence_label = st.selectbox(
                    "Bound EvidenceSpanProposal",
                    list(evidence_labels),
                    key="studio_evidence_selection",
                )
                selected = evidence_labels[selected_evidence_label]
                segment = segment_rows.get(selected["segment_id"], {})
                st.caption(
                    f"Page {selected['page_number']} · Segment {selected['segment_id']} · "
                    f"offsets {selected['start_offset']}:{selected['end_offset']} · source {document['file']}"
                )
                text = str(segment.get("exact_text") or selected["exact_text"])
                start = int(selected.get("start_offset") or 0)
                end = int(selected.get("end_offset") or len(text))
                if segment:
                    highlighted = (
                        escape(text[:start])
                        + '<mark style="background:#fde68a">'
                        + escape(text[start:end])
                        + "</mark>"
                        + escape(text[end:])
                    )
                    st.markdown(
                        f'<div style="border:1px solid #d9e0e8;border-radius:7px;padding:.85rem;line-height:1.55;max-height:360px;overflow:auto">{highlighted}</div>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.info(selected["exact_text"])
                st.caption(
                    f"Candidate EvidenceSpan · validation {selected['validation_status']} · "
                    f"issues: {'; '.join(selected.get('validation_reasons') or []) or 'none'}"
                )
            else:
                st.warning("The selected statement has no resolvable EvidenceSpan binding.")
        with statement_col:
            st.markdown("#### Candidate Statement / Claim")
            st.table(
                [
                    {"Field": "Status", "Value": "Candidate / Proposal"},
                    {"Field": "Subject", "Value": statement["subject_label"]},
                    {"Field": "Predicate / claim type", "Value": statement["predicate_label"]},
                    {"Field": "Object / value", "Value": statement.get("object_or_requirement", "")},
                    {"Field": "Polarity", "Value": statement["polarity_label"]},
                    {"Field": "Validation", "Value": statement["validation_status"]},
                    {"Field": "Reason / issue", "Value": "; ".join(statement.get("validation_reasons") or []) or "No validation issue recorded"},
                ]
            )
            scope = statement.get("scope") or {}
            scope_rows = [
                {"Dimension": name, "Status": value.get("status", ""), "Value": value.get("value") or "—"}
                for name, value in (scope.get("dimensions") or {}).items()
            ]
            st.markdown("##### ApplicabilityScope proposal")
            if scope_rows:
                st.dataframe(scope_rows, use_container_width=True, hide_index=True)
            else:
                st.info("No ApplicabilityScope proposal is bound to this statement.")
    else:
        st.warning("No Candidate Statement proposal was produced for this run.")

    st.markdown("### Scope + Ontology Validation")
    counts = demo["validation_counts"]
    validation_cols = st.columns(3)
    validation_cols[0].metric("STRUCTURAL VALID", counts["VALID"])
    validation_cols[1].metric("NEEDS_REVIEW", counts["NEEDS_REVIEW"])
    validation_cols[2].metric("STRUCTURAL INVALID", counts["INVALID"])
    st.caption(
        "Schema · Evidence · Identity · Governance conformance only; no scientific-validity judgment. "
        "Structurally invalid items are retained and never auto-repaired."
    )
    validation_filter = st.multiselect(
        "Validation status",
        ["VALID", "NEEDS_REVIEW", "INVALID"],
        default=["VALID", "NEEDS_REVIEW", "INVALID"],
        key="studio_validation_filter",
    )
    visible_validation = [row for row in demo["validation_rows"] if row["status"] in validation_filter]
    st.dataframe(_safe_rows(visible_validation), use_container_width=True, hide_index=True)

    st.markdown("### Candidate KG Preview")
    st.caption(
        f"Bounded to this PDF / extraction run · {demo['graph']['node_count']} nodes · "
        f"{demo['graph']['edge_count']} edges · click a node or edge for details"
    )
    st.caption(
        "Candidate states: CANDIDATE (proposal_status) · VALIDATED (ontology/conformance VALID only) · "
        "INVALID (retained failure). Never TRUSTED, CANONICAL, or PROMOTED."
    )
    st.caption(
        "Graph colors: blue = VALID candidate proposal · red = INVALID candidate proposal · "
        "yellow = EvidenceSpan · amber = SourceRevision · green = existing KG identity."
    )
    graph = proposal_graph_view(run["proposal_graph"])
    components.html(
        build_scientific_graph_viewer_html(
            graph,
            config=ScientificGraphViewerConfig(
                mode="candidate_kg",
                default_layout="force",
                default_density="standard",
                show_evidence_by_default=False,
                standard_node_cap=80,
                global_node_cap=120,
                canvas_height=700,
            ),
        ),
        height=710,
        scrolling=False,
    )

    diff = run["candidate_diff"]
    st.markdown("#### Current Scientific KG vs Proposed Delta")
    st.caption("If accepted, proposed delta would be… This preview does not perform that acceptance or write.")
    current_cols = st.columns(3)
    current_cols[0].metric("Current nodes", f"{diff['current_nodes']:,}")
    current_cols[1].metric("Current edges", f"{diff['current_edges']:,}")
    current_cols[2].metric("Current candidate claims", f"{diff['current_candidate_claims']:,}")
    if (
        diff["current_nodes"] != scientific_summary["scientific_kg_nodes"]
        or diff["current_edges"] != scientific_summary["scientific_kg_edges"]
        or diff["current_candidate_claims"] != scientific_summary["candidate_claims"]
    ):
        st.error("Frozen Studio diff does not match the current Scientific KG snapshot.")
    delta_cols = st.columns(4)
    delta_cols[0].metric("Entity proposals", f"+ {diff['entity_proposals']}")
    delta_cols[1].metric("Relation proposals", f"+ {diff['relation_proposals']}")
    delta_cols[2].metric("Claim proposals", f"+ {diff['atomic_claim_proposals']}")
    delta_cols[3].metric("Evidence proposals", f"+ {diff['evidence_span_proposals']}")

    with st.expander("All proposal artifacts and immutable run trace"):
        entities_tab, relations_tab, claims_tab, evidence_tab, trace_tab = st.tabs(
            ["Entities", "Relations", "Claims", "Evidence", "Run Trace"]
        )
        with entities_tab:
            st.dataframe(_safe_rows(run["entities"]), use_container_width=True, hide_index=True)
        with relations_tab:
            if run["relations"]:
                st.dataframe(_safe_rows(run["relations"]), use_container_width=True, hide_index=True)
            else:
                st.info("No relation proposal passed the constrained extractor in this run.")
        with claims_tab:
            st.dataframe(_safe_rows(run["claims"]), use_container_width=True, hide_index=True)
        with evidence_tab:
            st.dataframe(_safe_rows(evidence_rows), use_container_width=True, hide_index=True)
        with trace_tab:
            st.dataframe(
                _safe_rows([
                    {
                        "stage": row["stage"], "status": row["status"], "timestamp": row["timestamp"],
                        "reason": row["reason"], "hash": row["content_hash"],
                    }
                    for row in trace
                ]),
                use_container_width=True,
                hide_index=True,
            )


def _render_ontology_manager() -> None:
    """Render the verified, schema-only Ontology v2 design workspace."""

    try:
        service = OntologyManagerReadOnlyService(Path(__file__).resolve().parent)
    except OntologyIntegrityError as exc:
        st.error(f"Ontology Manager fail-closed: {exc}")
        return

    overview = service.overview()
    st.warning("DESIGN FROZEN · This is a read-only design registry, not a production KG.")
    st.info("PRODUCTION MIGRATION = NO")
    st.caption(
        "Authoritative source: data/ontology/scientific_decision_ontology_v2_core/ · "
        f"{service.integrity()['artifact_count']} manifest hashes verified"
    )

    (
        overview_tab,
        object_tab,
        link_tab,
        property_tab,
        schema_tab,
    ) = st.tabs(
        [
            "Ontology Overview",
            "Object Types",
            "Link Types",
            "Properties & Qualifiers",
            "Schema Graph",
        ]
    )

    with overview_tab:
        version_cols = st.columns(3)
        version_cols[0].metric("Ontology version", overview["ontology_version"])
        version_cols[1].metric("Schema version", overview["schema_version"])
        version_cols[2].metric("Freeze commit", overview["freeze_commit"][:12])
        count_cols = st.columns(4)
        count_cols[0].metric("Core object types", overview["core_object_type_count"])
        count_cols[1].metric("Authoritative links", overview["authoritative_link_count"])
        count_cols[2].metric("Derived projections", overview["derived_projection_count"])
        count_cols[3].metric("Properties", overview["property_count"])
        more_cols = st.columns(3)
        more_cols[0].metric("Qualifiers", overview["qualifier_count"])
        more_cols[1].metric("Extension count", overview["extension_count"])
        more_cols[2].metric("Deferred count", overview["deferred_count"])
        st.caption(
            f"Registry inventory: {overview['extension_registry_item_count']} extension items · "
            f"{overview['deferred_registry_item_count']} deferred/disposition items · "
            f"{overview['merged_compatibility_object_count']} compatibility object concepts merged, not active object types"
        )
        st.markdown("#### Design boundary")
        st.table(
            [
                {"Boundary": "Design state", "Value": "DESIGN FROZEN"},
                {"Boundary": "Production migration", "Value": "NO"},
                {"Boundary": "Scientific KG mutation", "Value": "DISABLED"},
                {"Boundary": "Ontology editing", "Value": "DISABLED"},
            ]
        )

    with object_tab:
        st.markdown("#### Object Types")
        controls = st.columns([1.5, 1.3, 1.2, 1.2])
        with controls[0]:
            object_query = st.text_input(
                "Search object types", key="ontology_object_search", placeholder="name or definition"
            )
        with controls[1]:
            object_modules = st.multiselect(
                "Module", service.modules(), key="ontology_object_modules"
            )
        with controls[2]:
            object_statuses = st.multiselect(
                "Core / Extension / Deferred",
                ["Core", "Extension", "Deferred"],
                key="ontology_object_statuses",
            )
        with controls[3]:
            object_layers = st.multiselect(
                "Display layer",
                service.layers(),
                key="ontology_object_layers",
            )
        object_rows = service.object_types(
            object_query,
            modules=object_modules,
            statuses=object_statuses,
            layers=object_layers,
        )
        st.caption(
            f"{len(object_rows)} active design object types · "
            "26 core / 7 extension / 8 deferred before filters"
        )
        st.dataframe(object_rows, use_container_width=True, hide_index=True, height=430)
        if object_rows:
            selected_object = st.selectbox(
                "Inspect object type",
                [row["Object Type"] for row in object_rows],
                key="ontology_object_detail",
            )
            detail = service.object_detail(selected_object)
            detail_cols = st.columns([1.0, 1.2])
            with detail_cols[0]:
                st.markdown(f"##### {detail['object_type']}")
                st.write(detail["definition"])
                st.table(
                    [
                        {"Field": "Module", "Value": detail["module"]},
                        {"Field": "Status", "Value": detail["status"]},
                        {"Field": "Layer", "Value": detail["layer"]},
                        {
                            "Field": "CQ support",
                            "Value": ", ".join(detail["cq_support"]) or "None declared",
                        },
                    ]
                )
                st.markdown("##### v1 compatibility status")
                st.json(detail["v1_compatibility"])
            with detail_cols[1]:
                st.markdown("##### Allowed / required fields")
                st.json(
                    {
                        "required_properties": detail["required_properties"],
                        "optional_properties": detail["optional_properties"],
                        "required_links": detail["required_links"],
                        "required_incoming_links": detail["required_incoming_links"],
                    }
                )
                st.markdown("##### Links in / out")
                st.json({"in": detail["links_in"], "out": detail["links_out"]})

    with link_tab:
        st.markdown("#### Link Types")
        st.caption(
            "AUTHORITATIVE links are frozen schema statements. DERIVED PROJECTION links are computed views and are not equivalent to authoritative statements."
        )
        link_controls = st.columns([1.6, 1.2, 1.3])
        link_modules_available = sorted(
            {row["module"] for row in service.schema_graph()["edges"]}
        )
        with link_controls[0]:
            link_query = st.text_input(
                "Search link types", key="ontology_link_search", placeholder="predicate or definition"
            )
        with link_controls[1]:
            link_modules = st.multiselect(
                "Link module", link_modules_available, key="ontology_link_modules"
            )
        with link_controls[2]:
            link_classes = st.multiselect(
                "Authority",
                ["AUTHORITATIVE", "DERIVED_PROJECTION"],
                key="ontology_link_classifications",
            )
        link_rows = service.link_types(
            link_query, modules=link_modules, classifications=link_classes
        )
        st.caption(f"{len(link_rows)} core link types")
        st.dataframe(link_rows, use_container_width=True, hide_index=True, height=440)
        if link_rows:
            selected_link = st.selectbox(
                "Inspect link type",
                [row["Predicate"] for row in link_rows],
                key="ontology_link_detail",
            )
            link_detail = service.link_detail(selected_link)
            if link_detail["classification"] == "DERIVED_PROJECTION":
                st.warning("DERIVED PROJECTION · non-authoritative computed view")
            else:
                st.info("AUTHORITATIVE LINK")
            link_detail_cols = st.columns([1.0, 1.2])
            with link_detail_cols[0]:
                st.markdown(f"##### {link_detail['predicate']}")
                st.write(link_detail["definition"])
                st.json(
                    {
                        "domain": link_detail["domain"],
                        "range": link_detail["range"],
                        "module": link_detail["module"],
                        "status": link_detail["status"],
                        "CQ support": link_detail["cq_support"],
                    }
                )
            with link_detail_cols[1]:
                st.markdown("##### Evidence policy")
                st.json(link_detail["evidence_policy"])
                st.markdown("##### Qualifier policy")
                st.json(link_detail["qualifier_policy"])

    with property_tab:
        properties_tab, qualifiers_tab = st.tabs(["Properties", "Qualifiers"])
        with properties_tab:
            property_query = st.text_input(
                "Search properties", key="ontology_property_search", placeholder="name or owner"
            )
            property_rows = service.properties(property_query)
            effect = next(row for row in property_rows if row["Name"] == "effect_description") if any(
                row["Name"] == "effect_description" for row in property_rows
            ) else None
            if effect:
                st.warning(
                    "effect_description → DISPLAY ONLY / NO MACHINE AUTHORITY · "
                    "never decision evidence or an assertion predicate"
                )
            st.caption(f"{len(property_rows)} properties")
            st.dataframe(property_rows, use_container_width=True, hide_index=True, height=500)
        with qualifiers_tab:
            qualifier_query = st.text_input(
                "Search qualifiers", key="ontology_qualifier_search", placeholder="name or context"
            )
            qualifier_rows = service.qualifiers(qualifier_query)
            st.caption(f"{len(qualifier_rows)} qualifiers")
            st.dataframe(qualifier_rows, use_container_width=True, hide_index=True, height=500)

    with schema_tab:
        st.markdown("#### Bounded schema graph")
        st.caption(
            "Object Types and Core Link Types only · 0 Scientific KG instance nodes loaded"
        )
        graph_controls = st.columns([1.8, 1.0, 1.1])
        with graph_controls[0]:
            graph_modules = st.multiselect(
                "Graph modules", service.schema_modules(), key="ontology_graph_modules"
            )
        with graph_controls[1]:
            authoritative_only = st.checkbox(
                "Authoritative only", value=False, key="ontology_graph_authoritative_only"
            )
        with graph_controls[2]:
            show_derived = st.checkbox(
                "Show derived projections", value=True, key="ontology_graph_show_derived"
            )
        graph = service.schema_graph(
            modules=graph_modules,
            authoritative_only=authoritative_only,
            show_derived=show_derived,
        )
        st.caption(
            f"Bounded: {graph['node_count']} object types · {graph['edge_count']} endpoint edges · "
            f"instance nodes loaded: {graph['instance_nodes_loaded']}"
        )
        components.html(build_ontology_schema_graph_html(graph), height=730, scrolling=False)


def _render_scientific_kg_admin_page() -> None:
    """Render the read-only Scientific KG checkpoint snapshot."""

    _render_admin_header(
        "Admin · Scientific KG",
        "Candidate knowledge, direct evidence, readiness, and integrity",
        "Read-only view of the frozen Scientific KG inventory. Candidate claims remain separate from reviewed or trusted knowledge.",
    )
    service = ScientificKGAdminSnapshotService(Path(__file__).resolve().parent)
    summary = service.summary()
    status = summary["snapshot_status"]
    if status != "IDENTITY_MATCH":
        st.error(f"Frozen snapshot identity check failed: {status}")
        return

    st.caption(
        "SCIENTIFIC_KG only · checkpoint-1 physical layer counts · "
        "candidate ≠ reviewed ≠ trusted ≠ execution-authorized"
    )
    overview_tab, graph_tab, readiness_tab, studio_tab, ontology_tab = st.tabs(
        ["Overview", "Scientific Graph", "Readiness & Integrity", "Candidate Studio", "Ontology"]
    )

    with overview_tab:
        metrics = st.columns(5)
        metrics[0].metric("Scientific nodes", f"{summary['scientific_kg_nodes']:,}")
        metrics[1].metric("Scientific edges", f"{summary['scientific_kg_edges']:,}")
        metrics[2].metric("Candidate claims", f"{summary['candidate_claims']:,}")
        metrics[3].metric("Evidence spans", f"{summary['evidence_spans']:,}")
        metrics[4].metric("Evidence gaps", f"{summary['evidence_gaps']:,}")
        governance_metrics = st.columns(4)
        governance_metrics[0].metric("Reviewed claims", summary["reviewed_claims"])
        governance_metrics[1].metric("Trusted claims", summary["trusted_claims"])
        governance_metrics[2].metric(
            "Readiness L4",
            f"{summary['readiness_highest_exclusive'].get('L4', 0)}/{summary['audited_operator_revisions']}",
        )
        governance_metrics[3].metric(
            "Integrity", f"{summary['hard_issues']} hard · {summary['warnings']} warning"
        )
        st.info(
            "Trusted source evidence describes provenance quality. It does not promote a candidate scientific claim. No knowledge record can be changed from this page."
        )

        st.markdown("#### Separate graph layers")
        st.dataframe(
            service.layer_boundaries(),
            use_container_width=True,
            hide_index=True,
        )
        st.caption(
            "Counting policy: DO_NOT_SUM_ACROSS_LAYERS. Legacy Tool KG, Decision Graph, and Scientific KG have different semantics and owners."
        )

        semantic_col, relation_col = st.columns(2)
        with semantic_col:
            st.markdown("#### Scientific semantic inventory")
            st.dataframe(
                service.semantic_inventory(),
                use_container_width=True,
                hide_index=True,
                height=430,
            )
        with relation_col:
            st.markdown("#### Scientific relation inventory")
            st.dataframe(
                service.relation_inventory(),
                use_container_width=True,
                hide_index=True,
                height=430,
            )
        st.caption(
            "Evaluation framework context: scKG-Eval v1 defines 9 suites and 117 metrics; this page reports the frozen KG/readiness slice only."
        )

    with graph_tab:
        st.markdown("#### Scientific graph workbench")
        st.caption(
            "Explore a focused real subgraph or the complete frozen Scientific KG. SourceRevision display nodes in focused examples come from frozen source manifests and are excluded from physical graph totals."
        )
        graph_scope = st.radio(
            "Graph scope",
            ["Focused subgraph", "Full Scientific KG"],
            horizontal=True,
            key="scientific_kg_graph_scope",
        )
        controls = st.columns([1.0, 1.6, 1.4, 0.8, 0.8])
        with controls[0]:
            example = st.selectbox(
                "Example", ["PCA", "neighbors", "Leiden"], key="scientific_kg_example"
            )
        with controls[1]:
            search = st.text_input(
                "Search",
                value="",
                placeholder="operator, claim, evidence span...",
                key="scientific_kg_search",
            )
        node_type_options = sorted(
            {row["type"] for row in service.semantic_inventory()}
            | {"EvidenceReference", "InputPort", "OutputPort", "Requirement"}
        )
        with controls[2]:
            node_types = st.multiselect(
                "Node types", node_type_options, key="scientific_kg_node_types"
            )
        with controls[3]:
            hops = st.selectbox("Hops", [1, 2], index=1, key="scientific_kg_hops")
        with controls[4]:
            max_nodes = st.select_slider(
                "Node cap", options=[50, 75, 100], value=75, key="scientific_kg_cap"
            )

        selected_seed: str | None = None
        matches: list[dict[str, Any]] = []
        if search.strip():
            matches = service.search_nodes(
                search,
                node_types=set(node_types) if node_types else None,
                limit=50,
            )
            if matches:
                labels = {
                    f"{row['label']} · {row['node_type']} · {row['layer']}": row["graph_node_id"]
                    for row in matches
                }
                selected_label = st.selectbox(
                    "Search result", list(labels), key="scientific_kg_search_result"
                )
                selected_seed = labels[selected_label]
            else:
                st.warning("No Scientific KG nodes match the current search and type filter.")

        if graph_scope == "Full Scientific KG":
            graph = service.global_graph()
        elif selected_seed:
            graph = service.neighborhood_graph(
                selected_seed, hops=int(hops), max_nodes=int(max_nodes)
            )
        else:
            graph = service.example_graph(example, max_nodes=int(max_nodes))
        if graph.truncated:
            st.caption("Node cap reached; the canvas is a deterministic local projection.")
        components.html(
            build_scientific_graph_viewer_html(
                graph,
                config=ScientificGraphViewerConfig(
                    mode="scientific_kg",
                    default_layout="force",
                    default_density=(
                        "global" if graph_scope == "Full Scientific KG" else "standard"
                    ),
                    show_evidence_by_default=False,
                    standard_node_cap=260,
                    global_node_cap=2000,
                    canvas_height=700,
                ),
            ),
            height=710,
            scrolling=False,
        )

        node_options = {
            f"{graph.nodes[node_id].label} · {graph.nodes[node_id].kind}": node_id
            for node_id in graph.visible_node_ids
        } if graph_scope == "Focused subgraph" else {}
        if node_options:
            detail_label = st.selectbox(
                "Inspect node", list(node_options), key="scientific_kg_inspect_node"
            )
            detail = service.get_node(node_options[detail_label])
            if detail:
                detail_col, record_col = st.columns([0.9, 1.5])
                with detail_col:
                    st.markdown("##### Identity & governance")
                    st.table(
                        [
                            {"field": "canonical_id", "value": detail["canonical_id"]},
                            {"field": "node_type", "value": detail["node_type"]},
                            {"field": "layer", "value": detail["layer"]},
                            {"field": "status", "value": detail["status"]},
                            {"field": "knowledge_status", "value": detail["knowledge_status"]},
                        ]
                    )
                with record_col:
                    st.markdown("##### Frozen record")
                    st.json(detail["record"])
                if detail["node_type"] == "AtomicClaimRevision":
                    chain = service.get_claim_evidence_chain(detail["graph_node_id"])
                    st.markdown("##### Claim → EvidenceAssessment → EvidenceSpan → SourceRevision")
                    if chain["complete"]:
                        st.success("All referenced evidence and source records resolve in this frozen layer.")
                    else:
                        st.warning("Evidence chain is incomplete: " + "; ".join(chain["incomplete_reasons"]))
                    st.dataframe(
                        [
                            {
                                "evidence_span_id": row["evidence_span_id"],
                                "materialized": row["materialized"],
                                "source_revision": (
                                    (row["source_revision"] or {}).get("source_revision_id")
                                    or (row["source_revision"] or {}).get("source_id")
                                    or "MISSING"
                                ),
                                "source_status": row["source_status"],
                            }
                            for row in chain["evidence"]
                        ],
                        use_container_width=True,
                        hide_index=True,
                    )

    with readiness_tab:
        st.markdown("#### Production UAT direct-evidence readiness")
        st.caption(
            "L0 identity · L1 claim/scope · L2 verified span/source · L3 frozen corpus mapping · L4 public-filter survival"
        )
        st.dataframe(
            service.readiness_rows(),
            use_container_width=True,
            hide_index=True,
        )
        source_cols = st.columns(4)
        source_cols[0].metric("Audited revisions", summary["audited_operator_revisions"])
        source_cols[1].metric("L4", summary["readiness_highest_exclusive"].get("L4", 0))
        source_cols[2].metric("SourceRevision physical", summary["source_revision_physical"])
        source_cols[3].metric("SourceRevision unique", summary["source_revision_unique"])
        st.caption(
            "Physical 6 / unique 5 is expected because frozen layers overlap and are not identity-merged without adjudication."
        )
        st.markdown("#### Integrity findings")
        if summary["hard_issues"] == 0:
            st.success("0 hard issues. Referential and schema gates passed for the frozen inventory.")
        st.dataframe(
            service.integrity_groups(),
            use_container_width=True,
            hide_index=True,
        )
        st.caption(
            "Warnings preserve declared coverage gaps and unreferenced materialized spans. They are visible evidence boundaries, not hidden successes."
        )

    with studio_tab:
        _render_candidate_studio(summary)

    with ontology_tab:
        _render_ontology_manager()

def _render_memory_admin_panel() -> None:
    _render_admin_header(
        "Admin · Memory",
        "受控自进化记忆",
        "查看 reflection events、private operational memory 和 review-only skill candidates。",
    )
    service = ReflectionService()
    reflections = service.list_reflections()
    memory_events = service.list_memory_events()
    skill_candidates = service.list_skill_candidates()
    c1, c2, c3 = st.columns(3)
    c1.metric("Reflections", len(reflections))
    c2.metric("Memory Events", len(memory_events))
    c3.metric("Skill Candidates", len(skill_candidates))
    st.info(
        "记忆板块已经加入：聊天主流程每次正式 agent run 后会执行 reflect。"
        "这些 memory 只能影响 operational context，不能成为 scientific authority。"
    )
    st.markdown("#### Memory Events")
    if memory_events:
        st.dataframe(_safe_rows(memory_events), use_container_width=True)
    else:
        st.info("No memory events yet. Run a normal chat query first.")
    st.markdown("#### Recent Reflections")
    for event in reflections[:8]:
        with st.expander(f"{event.get('created_at', '')[:19]} · {event.get('trace_id', '')}"):
            st.json(event)
    st.markdown("#### Skill Candidates")
    if skill_candidates:
        st.dataframe(_safe_rows(skill_candidates), use_container_width=True)
    else:
        st.info("No skill candidates yet.")
    st.markdown("#### Memory Control")
    from core.unified_memory import UnifiedMemoryStore

    memory_store = UnifiedMemoryStore()
    exported = memory_store.export_user_memory("local")
    pending_inferences = exported.get("pending_inferences") or []
    if pending_inferences:
        st.caption("Inferred preferences remain inactive until confirmed.")
        for item in pending_inferences:
            cols = st.columns([3, 1])
            cols[0].write(f"{item.get('key')}: {item.get('value')}")
            if cols[1].button(
                "Confirm",
                key=f"confirm_memory_{item.get('key')}",
            ):
                memory_store.confirm_inferred_preference(
                    "local", str(item.get("key"))
                )
                st.rerun()
    conflicts = [
        item for item in memory_store.list_conflicts("local") if item["status"] == "pending"
    ]
    if conflicts:
        st.caption("Conflicting values require an explicit accept or reject decision.")
        for item in conflicts:
            st.write(
                f"{item['key']}: current={item['existing']} · proposed={item['proposed']}"
            )
            accept_col, reject_col, _ = st.columns([1, 1, 3])
            if accept_col.button("Accept", key=f"accept_conflict_{item['conflict_id']}"):
                memory_store.resolve_conflict("local", item["conflict_id"], accept=True)
                st.rerun()
            if reject_col.button("Reject", key=f"reject_conflict_{item['conflict_id']}"):
                memory_store.resolve_conflict("local", item["conflict_id"], accept=False)
                st.rerun()
    st.download_button(
        "Export local memory",
        data=json.dumps(exported, indent=2, ensure_ascii=False),
        file_name="sckg_local_memory.json",
        mime="application/json",
    )
    with st.expander("Delete local operational memory", expanded=False):
        st.caption("This removes preferences, episodic summaries, reflections and skill candidates from the unified store. It does not delete scientific evidence or user data.")
        confirmation = st.text_input(
            "Type DELETE LOCAL MEMORY",
            key="delete_local_memory_confirmation",
        )
        if st.button(
            "Delete memory",
            disabled=confirmation != "DELETE LOCAL MEMORY",
            key="delete_local_memory_button",
        ):
            memory_store.delete_user_memory("local")
            st.success("Local operational memory deleted.")
            st.rerun()


def _render_architecture_admin_panel() -> None:
    _render_admin_header(
        "Admin · Architecture",
        "有边界的中心化 Agent 路线图",
        "明确当前已经实现什么、还没实现什么，以及多智能体后续如何进入系统。",
    )
    rows = [
        {
            "component": "Current user app",
            "status": "implemented",
            "notes": "Original chat app + KG view + workflow decision card + admin panels.",
        },
        {
            "component": "Hybrid RAG",
            "status": "implemented discovery layer",
            "notes": "Evidence chunks JSONL, sparse retrieval, optional dense vectors, governance rerank.",
        },
        {
            "component": "PDF/source acquisition",
            "status": "semi-automated",
            "notes": "Open sources can be discovered/acquired; wrong DOI, paywall, login, extraction failure remain manual review tasks.",
        },
        {
            "component": "Memory",
            "status": "implemented operational memory",
            "notes": "Reflection writes private memory and skill candidates; cannot update formal evidence.",
        },
        {
            "component": "Subagents",
            "status": "contract/test exists; runtime default off",
            "notes": "Next step: read-only evidence-search/critique subagents under Parent Agent budget.",
        },
        {
            "component": "MCP",
            "status": "planned",
            "notes": "Useful later for tool/service packaging; not required before workflow decision + evidence recovery are stable.",
        },
    ]
    st.dataframe(_safe_rows(rows), use_container_width=True)
    st.markdown("#### Recommended Implementation Order")
    st.markdown(
        """
1. Attach trace logging to the integrated workflow decision card.
2. Expand workflow eval from 8 to 20-30 scenarios.
3. Continue source acquisition for core tools and keep source registry validation strict.
4. Add read-only subagents for evidence search and report critique.
5. Only after local workflow is stable, package selected capabilities as MCP tools/server.
"""
    )


@st.cache_resource
def _status_badge(status: Any) -> None:
    normalized = normalize_ui_status(status)
    style = {
        "READY": "good",
        "COMPLETED": "good",
        "WAITING": "warn",
        "RUNNING": "warn",
        "STALE": "warn",
        "BLOCKED": "bad",
        "FAILED": "bad",
    }[normalized]
    st.markdown(
        f'<span class="status-chip {style}">{normalized}</span>',
        unsafe_allow_html=True,
    )


def _render_home_page() -> None:
    st.markdown(
        """
<div class="chat-app-header compact-top">
  <div class="chat-app-kicker">scKG-Agent 2.0 local MVP</div>
  <div class="chat-app-title">受控的单细胞分析执行工作台</div>
  <div class="chat-app-subtitle">当前完成 Doublet Detection 与 Batch Integration 两个任务族，覆盖 Scrublet、scDblFinder、Harmony 和 Scanorama。所有运行都受数据画像、精确审批、contract、environment 和 ownership gate 约束。</div>
</div>
<div class="mvp-scope"><strong>MVP scope</strong><br/>scRNA-seq AnnData / .h5ad · Doublet Detection + Batch Integration · 4 qualified tools · controlled local execution</div>
""",
        unsafe_allow_html=True,
    )
    with st.container(border=True):
        agent_cols = st.columns([3, 1])
        with agent_cols[0]:
            st.markdown("### Bounded Parent Agent Loop")
            st.write(
                "查看自然语言需求如何依次调用 GraphRAG、ToolContract、DataProfiler、Planner 与 policy Router，并在授权边界前停止。"
            )
        with agent_cols[1]:
            if st.button("Open Agent Loop", type="primary", width="stretch"):
                st.session_state.current_view = "agent_loop_demo"
                st.rerun()
    left, middle, right = st.columns(3)
    with left:
        with st.container(border=True):
            st.markdown("### Restricted Execution")
            st.write(
                "查看 DataProfile 与 dry-run plan，完成 plan-specific approval 后再运行固定工具。"
            )
            if st.button("Open Restricted Execution", type="primary", width="stretch"):
                st.session_state.current_view = "execution_ui"
                st.rerun()
    with middle:
        with st.container(border=True):
            st.markdown("### Defense Demo")
            st.write("只读查看成功执行、有界修复与正确阻断三个预生成案例。")
            if st.button("Open Defense Demo", width="stretch"):
                st.session_state.current_view = "defense_demo"
                st.rerun()
    with right:
        with st.container(border=True):
            st.markdown("### Graph Explorer")
            st.write("独立探索 Decision Network、工具邻域与 1,847 项完整目录。")
            if st.button("Open Graph Explorer", width="stretch"):
                st.session_state.current_view = "graph_explorer"
                st.rerun()

    with st.container(border=True):
        review_cols = st.columns([3, 1])
        with review_cols[0]:
            st.markdown("### Knowledge Review")
            st.write(
                "面向 Agent 问答与规划，审查 Action Space、Tool Dossier 和治理边界。"
            )
        with review_cols[1]:
            if st.button("Open Knowledge Review", width="stretch"):
                st.session_state.current_view = "knowledge_review"
                st.rerun()

    with st.container(border=True):
        pack_cols = st.columns([3, 1])
        with pack_cols[0]:
            st.markdown("### Runtime Packs")
            st.write(
                "按任务族查看、审批、安装或卸载工具环境。核心图谱、RAG 和 dry-run 规划不依赖这些环境。"
            )
        with pack_cols[1]:
            if st.button("Open Runtime Packs", width="stretch"):
                st.session_state.current_view = "runtime_packs"
                st.rerun()

    st.markdown("### Research Chat")
    st.caption(
        "统一完成 source-bound 检索、研究问答与 dry-run 规划；只有通过合同、环境、数据和审批 gate 的路径才可能进入受控执行。"
    )
    if st.button("Open Research Chat", width="content"):
        st.session_state.current_view = "chat"
        st.rerun()


def _render_agent_loop_demo_page() -> None:
    st.markdown(
        """
<div class="chat-app-header compact-top">
  <div class="chat-app-kicker">scKG-Agent 2.0 control plane</div>
  <div class="chat-app-title">Bounded Parent Agent Loop</div>
  <div class="chat-app-subtitle">同一个 Parent Agent 负责理解任务和组织工具调用；GraphRAG、contract、authorization 与 Router 保留各自的确定性权限。此页面只读取预生成 trace，不执行工具。</div>
</div>
""",
        unsafe_allow_html=True,
    )
    bundle = AgentLoopDemoService().latest_bundle()
    if not bundle:
        st.warning(
            "No complete Agent Loop demo was found. Run `python scripts/run_bounded_parent_agent_demo.py` first."
        )
        return
    metrics = st.columns(4)
    metrics[0].metric("Cases", len(bundle["cases"]))
    metrics[1].metric("Tool calls", bundle["tool_call_count"])
    metrics[2].metric("Execution requests", bundle["execution_request_count"])
    metrics[3].metric("Boundary violations", bundle["evidence_boundary_violations"])
    st.caption(bundle["architecture"] + " · " + bundle["llm_mode"])

    st.markdown("### Try the plan-only Agent")
    trial_cols = st.columns([3, 1])
    with trial_cols[0]:
        trial_query = st.text_input(
            "Natural-language request",
            value="Plan doublet detection for an scRNA-seq AnnData dataset",
            key="bounded_agent_trial_query",
        )
    with trial_cols[1]:
        trial_tool = st.selectbox(
            "Tool preference",
            ["Auto", "Scrublet", "scDblFinder"],
            key="bounded_agent_trial_tool",
        )
    if st.button("Run plan-only Agent", type="primary", width="content"):
        from agent.bounded_parent_agent import BoundedParentAgent, ParentAgentRequest

        result = BoundedParentAgent().run(
            ParentAgentRequest(
                request_id=f"ui-agent-{uuid.uuid4().hex}",
                query=trial_query,
                requested_tool=None if trial_tool == "Auto" else trial_tool,
            )
        )
        st.session_state.bounded_agent_trial_result = result.model_dump(mode="json")
    live_result = st.session_state.get("bounded_agent_trial_result")
    if live_result:
        with st.container(border=True):
            live_cols = st.columns(4)
            live_cols[0].metric("Status", live_result.get("status", "FAILED"))
            live_cols[1].metric("Route", live_result.get("route", "BLOCKED"))
            live_cols[2].metric("Selected tool", live_result.get("selected_tool") or "none")
            live_cols[3].metric(
                "Execution requests", live_result.get("execution_request_count", 0)
            )
            st.write(live_result.get("final_summary", ""))
            st.dataframe(
                _safe_rows(
                    [
                        {
                            "stage": item.get("stage"),
                            "capability": item.get("capability"),
                            "status": item.get("status"),
                            "elapsed_ms": item.get("elapsed_ms"),
                        }
                        for item in live_result.get("tool_calls") or []
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )
            st.caption(
                "This trial accepts no file path, creates no approval and cannot create an ExecutionRequest."
            )

    for row_start in range(0, len(bundle["cases"]), 2):
        columns = st.columns(2)
        for column, case in zip(columns, bundle["cases"][row_start : row_start + 2]):
            with column:
                with st.container(border=True):
                    st.markdown(f"### {escape(case['title'])}")
                    _status_badge(case["status"])
                    st.write(case["summary"])
                    state_cols = st.columns(2)
                    state_cols[0].metric("Route", case["route"])
                    state_cols[1].metric("Tool calls", case["tool_call_count"])
                    st.caption(
                        f"selected tool: {case['selected_tool'] or 'none'} · "
                        f"profile: {'yes' if case['profile_created'] else 'no'} · "
                        f"plan steps: {case['plan_steps']} · "
                        f"ExecutionRequest: {case['execution_request_count']}"
                    )
                    if case["count_source"]:
                        st.caption(f"count source: {case['count_source']}")
                    if case["candidates"]:
                        st.markdown("**Graph candidates**")
                        st.dataframe(
                            _safe_rows(case["candidates"]),
                            use_container_width=True,
                            hide_index=True,
                        )
                    if case["blockers"]:
                        st.markdown("**Gate result**")
                        for blocker in case["blockers"][:4]:
                            st.caption(f"- {blocker}")
                    with st.expander("Tool-call trace"):
                        st.dataframe(
                            _safe_rows(
                                [
                                    {
                                        "stage": item.get("stage"),
                                        "capability": item.get("capability"),
                                        "status": item.get("status"),
                                        "elapsed_ms": item.get("elapsed_ms"),
                                    }
                                    for item in case["tool_calls"]
                                ]
                            ),
                            use_container_width=True,
                            hide_index=True,
                        )
    st.markdown("### Limitations")
    for limitation in bundle["limitations"]:
        st.caption(f"- {limitation}")


def _render_defense_demo_cases(bundle: Dict[str, Any]) -> None:
    summary_cols = st.columns(4)
    summary_cols[0].metric("Bundle", bundle["bundle_id"].replace("phase6-defense-", ""))
    summary_cols[1].metric("Fixture", "synthetic" if bundle["synthetic_fixture"] else "unknown")
    summary_cols[2].metric("User data", "no" if not bundle["user_data_used"] else "yes")
    summary_cols[3].metric("Trace", f"{float(bundle.get('trace_completeness') or 0):.0%}")

    columns = st.columns(3)
    for column, case in zip(columns, bundle["cases"]):
        with column:
            with st.container(border=True):
                st.markdown(
                    f'<div class="demo-case-title">{escape(case["title"])}</div>',
                    unsafe_allow_html=True,
                )
                _status_badge(case["status"])
                st.markdown("**What happened**")
                st.write(case["what_happened"])
                st.markdown("**Key state**")
                for key, value in case["key_state"].items():
                    st.caption(f"{key.replace('_', ' ')}: {value}")
                st.markdown("**Conclusion**")
                st.write(case["conclusion"])
                st.markdown("**Trace / lineage**")
                st.caption(
                    f"completeness={case['trace'].get('applicable_stage_completeness')} · {case['lineage']}"
                )
                integrity = case["package_integrity"]
                st.markdown("**Package integrity**")
                st.caption("not applicable" if integrity is None else ("complete" if integrity else "incomplete"))
                st.markdown("**Limitations**")
                for item in case["limitations"]:
                    st.caption(f"- {item}")
                with st.expander("Advanced details"):
                    st.json({"trace": case["trace"], "case": case["advanced"]})


def _render_interview_demo_bundle(bundle: Dict[str, Any]) -> None:
    metrics = st.columns(5)
    metrics[0].metric("Bundle", bundle["bundle_id"].replace("interview-", ""))
    metrics[1].metric("Agent trace", f"{float(bundle.get('trace_completeness') or 0):.0%}")
    metrics[2].metric("Blocked requests", bundle.get("blocked_execution_request_count", 0))
    metrics[3].metric(
        "LLM baselines",
        f"{bundle.get('benchmark_completed_calls', 0)}/{bundle.get('benchmark_requested_calls', 0)}",
    )
    metrics[4].metric("Policy default", bundle.get("execution_policy_default", "disabled"))
    st.caption(bundle.get("architecture", ""))

    columns = st.columns(2)
    for index, case in enumerate(bundle.get("cases") or []):
        with columns[index % 2]:
            with st.container(border=True):
                st.markdown(f"#### {escape(case['title'])}")
                _status_badge(case["status"])
                if case.get("task"):
                    st.write(case["task"])
                facts = st.columns(3)
                facts[0].metric("Tool", case.get("selected_tool") or "gate only")
                facts[1].metric("Route", case.get("parent_route") or case["status"])
                facts[2].metric("Requests", case.get("execution_request_count", 0))
                st.write(case.get("conclusion", ""))
                st.caption(f"trace: {case.get('trace_id') or 'not created'}")
                with st.expander("Advanced audit details"):
                    st.json(case.get("advanced") or {})

    st.markdown("### A2 / A3 / A4 benchmark")
    baseline_rows = []
    for row in bundle.get("benchmark_baselines") or []:
        metrics_row = row.get("metric_means") or {}
        raw_metrics = row.get("raw_metric_means") or metrics_row
        baseline_rows.append(
            {
                "baseline": row.get("baseline_id"),
                "status": row.get("status"),
                "cases": f"{row.get('completed_cases', 0)}/{row.get('total_cases', 0)}",
                "routing": metrics_row.get("task_routing_accuracy"),
                "raw Recall@k": raw_metrics.get("tool_workflow_recall_at_k"),
                "admitted Recall@k": metrics_row.get("tool_workflow_recall_at_k"),
                "raw blocker": raw_metrics.get("blocker_correctness"),
                "admitted blocker": metrics_row.get("blocker_correctness"),
                "parameter legal": metrics_row.get("parameter_legality"),
                "hard gate": row.get("hard_gate_passed"),
            }
        )
    if baseline_rows:
        st.dataframe(baseline_rows, use_container_width=True, hide_index=True)
        safety = bundle.get("benchmark_safety") or {}
        governance = st.columns(4)
        governance[0].metric(
            "Raw execution asks", safety.get("raw_execution_request_count", 0)
        )
        governance[1].metric(
            "Execution vetoes", safety.get("execution_request_veto_count", 0)
        )
        governance[2].metric(
            "Parameter adjudications",
            safety.get("contract_parameter_adjudication_count", 0),
        )
        governance[3].metric(
            "Admitted unauthorized",
            safety.get("unauthorized_execution_request_count", 0),
        )
        st.caption(
            "A4 scores the admitted system response after deterministic governance; "
            "the raw model response and every intervention remain in advanced artifacts."
        )
        for failure in bundle.get("benchmark_failure_analysis") or []:
            st.warning(failure)
        examples = bundle.get("benchmark_governance_examples") or []
        if examples:
            st.markdown("#### Raw proposal -> admitted response")
            example_rows = [
                {
                    "case": row.get("case_id"),
                    "raw route": (row.get("raw_response") or {}).get("route"),
                    "admitted route": (row.get("admitted_response") or {}).get("route"),
                    "interventions": len(row.get("governance_interventions") or []),
                    "unauthorized admitted": (row.get("metrics") or {}).get(
                        "unauthorized_execution_request_count"
                    ),
                }
                for row in examples
            ]
            st.dataframe(example_rows, use_container_width=True, hide_index=True)
            selected_example = st.selectbox(
                "Governance example",
                options=examples,
                format_func=lambda row: row.get("case_id", "case"),
                key="interview_governance_example",
            )
            with st.expander("Raw and admitted details"):
                st.markdown("**Raw model proposal**")
                st.json(selected_example.get("raw_response") or {})
                st.markdown("**Admitted system response**")
                st.json(selected_example.get("admitted_response") or {})
                st.markdown("**Interventions**")
                st.json(selected_example.get("governance_interventions") or [])
    else:
        st.info("No portfolio benchmark artifact is available yet.")

    integrity = bundle.get("package_integrity") or {}
    if integrity.get("all_complete"):
        st.success("Doublet, repair and Batch Integration reproducibility packages passed integrity checks.")
    else:
        st.warning("One or more reproducibility package checks are incomplete.")
    with st.expander("Known boundaries"):
        for item in bundle.get("limitations") or []:
            st.caption(f"- {item}")


def _render_phase6_trial_runner(*, demo_available: bool) -> None:
    from core.trial_telemetry import Phase6TrialStore

    store = Phase6TrialStore()
    st.markdown("### Anonymous Trial Task Runner")
    st.caption(
        "只记录匿名任务结果、耗时和求助次数。不要填写 query、路径、矩阵内容或 barcode。"
    )
    if not demo_available:
        st.info("Trial Runner requires a complete Defense Demo bundle.")
        return

    active_id = st.session_state.get("phase6_trial_session_id")
    active = None
    if active_id:
        try:
            active = store.get_session(active_id)
        except KeyError:
            st.session_state.pop("phase6_trial_session_id", None)
            active_id = None

    if active is None:
        start_cols = st.columns(3)
        if start_cols[0].button(
            "Start Level 1 trial", type="primary", width="stretch"
        ):
            active = store.start_session(level="level_1")
            st.session_state.phase6_trial_session_id = active.session_id
            st.rerun()
        if start_cols[1].button("Start supervised Level 2", width="stretch"):
            active = store.start_session(level="level_2")
            st.session_state.phase6_trial_session_id = active.session_id
            st.rerun()
        if start_cols[2].button("Start maintainer rehearsal", width="stretch"):
            active = store.start_session(
                level="level_1", actor_type="maintainer_rehearsal"
            )
            st.session_state.phase6_trial_session_id = active.session_id
            st.rerun()

        resumable = [row for row in store.list_sessions() if row.status == "in_progress"]
        if resumable:
            labels = {
                row.session_id: (
                    f"{row.level} · {row.actor_type.replace('_', ' ')} · "
                    f"session …{row.session_id[-8:]}"
                )
                for row in resumable
            }
            resume_id = st.selectbox(
                "Resume an interrupted local trial",
                options=list(labels),
                format_func=lambda value: labels[value],
                key="phase6_trial_resume_id",
            )
            if st.button("Resume selected trial"):
                st.session_state.phase6_trial_session_id = resume_id
                st.rerun()
        st.info(
            "Use maintainer rehearsal for self-testing. Rehearsals are excluded from the real participant count."
        )
        return

    task_rows = store.task_bank(active.level)
    task_by_id = {row["task_id"]: row for row in task_rows}
    latest = store.latest_task_results()
    active_results = {
        task_id: latest.get((active.session_id, task_id))
        for task_id in active.assigned_task_ids
    }
    completed_count = sum(
        result is not None and result.completion is not None
        for result in active_results.values()
    )
    status_cols = st.columns(4)
    status_cols[0].metric("Level", active.level.replace("_", " "))
    status_cols[1].metric("Actor", active.actor_type.replace("_", " "))
    status_cols[2].metric("Completed", f"{completed_count}/{len(active.assigned_task_ids)}")
    status_cols[3].metric(
        "ExecutionRequest", active.execution_request_count if active.level == "level_2" else 0
    )
    st.progress(completed_count / len(active.assigned_task_ids))
    st.caption(
        f"Anonymous participant …{active.participant_id[-8:]} · session …{active.session_id[-8:]}"
    )

    if active.level == "level_2":
        has_execution_result = st.session_state.get("execution_result") is not None
        st.info(
            "Level 2 uses the existing Restricted Execution backend. This page cannot change policy, allowlist, approval, contract or environment."
        )
        if st.button("Open Restricted Execution for supervised synthetic run"):
            st.session_state.current_view = "execution_ui"
            st.rerun()
        st.caption(
            "Controlled execution result detected in this browser session."
            if has_execution_result
            else "No controlled execution result detected yet. Level 2 cannot be completed."
        )

    incomplete = [
        task_id
        for task_id in active.assigned_task_ids
        if active_results[task_id] is None
        or active_results[task_id].completion is None
    ]
    default_task = incomplete[0] if incomplete else active.assigned_task_ids[0]
    selected_task_id = st.selectbox(
        "Trial task",
        options=active.assigned_task_ids,
        index=active.assigned_task_ids.index(default_task),
        format_func=lambda value: f"{value} · {task_by_id[value]['instruction']}",
        key=f"phase6_trial_task_{active.session_id}",
    )
    task = task_by_id[selected_task_id]
    result = active_results[selected_task_id]
    with st.container(border=True):
        st.markdown(f"#### {escape(selected_task_id)}")
        st.write(task["instruction"])
        if result is None:
            if st.button(
                "Start task timer",
                type="primary",
                key=f"phase6_start_task_{active.session_id}_{selected_task_id}",
            ):
                store.begin_task(
                    session_id=active.session_id, task_id=selected_task_id
                )
                st.rerun()
        elif result.completion is not None:
            _status_badge("COMPLETED" if result.completion else "FAILED")
            st.caption(
                f"time={result.time_seconds:.1f}s · help={result.help_count} · "
                f"critical error={'yes' if result.critical_error else 'no'}"
            )
            if result.observer_notes:
                st.write(result.observer_notes)
        else:
            help_key = f"phase6_expected_visible_{active.session_id}_{selected_task_id}"
            if st.button(
                "Show expected answer (counts as help)",
                key=f"phase6_help_{active.session_id}_{selected_task_id}",
            ):
                store.record_help(
                    session_id=active.session_id, task_id=selected_task_id
                )
                st.session_state[help_key] = True
                st.rerun()
            if st.session_state.get(help_key):
                st.info(task["expected_answer"])
            outcome = st.segmented_control(
                "Outcome",
                options=["Completed", "Could not complete"],
                default="Completed",
                key=f"phase6_outcome_{active.session_id}_{selected_task_id}",
            ) or "Completed"
            critical_error = st.checkbox(
                "Critical error observed",
                key=f"phase6_critical_{active.session_id}_{selected_task_id}",
            )
            with st.expander("Observer-only safety check"):
                safety_codes = st.multiselect(
                    "Safety violation",
                    options=[
                        "unauthorized_execution",
                        "path_leak_or_escape",
                        "cross_user_access",
                        "uncontrolled_repair",
                    ],
                    key=f"phase6_safety_{active.session_id}_{selected_task_id}",
                )
            observer_notes = st.text_area(
                "Observer notes (optional, no sensitive content)",
                max_chars=500,
                key=f"phase6_notes_{active.session_id}_{selected_task_id}",
            )
            if st.button(
                "Submit task result",
                type="primary",
                key=f"phase6_submit_{active.session_id}_{selected_task_id}",
            ):
                store.submit_task(
                    session_id=active.session_id,
                    task_id=selected_task_id,
                    completion=outcome == "Completed",
                    critical_error=critical_error,
                    safety_violation_codes=safety_codes,
                    observer_notes=observer_notes,
                )
                st.rerun()

    all_recorded = completed_count == len(active.assigned_task_ids)
    level_2_execution_ready = (
        active.level != "level_2" or st.session_state.get("execution_result") is not None
    )
    finish_cols = st.columns([1, 3])
    if finish_cols[0].button(
        "Complete trial",
        disabled=not all_recorded or not level_2_execution_ready,
        width="stretch",
    ):
        store.complete_session(
            active.session_id,
            execution_request_count=1 if active.level == "level_2" else 0,
        )
        st.session_state.pop("phase6_trial_session_id", None)
        st.success("Trial recorded locally. Project status was not changed automatically.")
        st.rerun()
    finish_cols[1].caption(
        "Completion writes anonymous telemetry only. Maintainer confirmation is still required for Phase 6 closure."
    )


def _render_phase6_trial_summary() -> None:
    from core.trial_telemetry import Phase6TrialStore

    store = Phase6TrialStore()
    summary = store.summary()
    gate = store.gate_result(summary)
    st.markdown("### Phase 6 Trial Summary")
    summary_cols = st.columns(5)
    summary_cols[0].metric("Real participants", summary.participant_count)
    summary_cols[1].metric("Level 1", summary.level_1_participant_count)
    summary_cols[2].metric("Level 2", summary.level_2_participant_count)
    summary_cols[3].metric("Rehearsals", summary.maintainer_rehearsal_count)
    summary_cols[4].metric("Critical errors", summary.critical_error_count)
    rates = st.columns(3)
    rates[0].metric("Level 1 completion", f"{summary.level_1_completion_rate:.0%}")
    rates[1].metric("Critical task completion", f"{summary.critical_task_completion_rate:.0%}")
    rates[2].metric("Help rate", f"{summary.help_rate:.0%}")
    _status_badge(
        "READY"
        if gate.gate_passed
        else ("BLOCKED" if gate.recommended_status == "PHASE6_BLOCKED" else "WAITING")
    )
    if gate.gate_passed:
        st.success("Trial gate passed. Maintainer review is required before any status change.")
    else:
        st.info("Phase 6 remains TRIAL_READY until real participant requirements are met.")
        st.dataframe(
            [{"remaining condition": blocker} for blocker in gate.blockers],
            use_container_width=True,
            hide_index=True,
        )
    if summary.safety_violation_counts:
        st.error("Safety violation reported. Phase 6 must remain blocked pending review.")
    st.caption(
        "Maintainer rehearsals are deliberately excluded from participant and completion-rate gates. Telemetry is operational feedback, not scientific evidence."
    )


def _render_defense_demo_page() -> None:
    st.markdown(
        """
<div class="chat-app-header compact-top">
  <div class="chat-app-kicker">Phase 6 read-only trial</div>
  <div class="chat-app-title">Defense Demo</div>
  <div class="chat-app-subtitle">预生成 synthetic 案例与匿名 Trial Runner 用于验证执行、修复和阻断是否可理解。页面渲染不会创建 ExecutionRequest。</div>
</div>
""",
        unsafe_allow_html=True,
    )
    bundle = DefenseDemoService().latest_bundle()
    interview_bundle = InterviewDemoService().latest_bundle()
    interview_tab, demo_tab, runner_tab, summary_tab = st.tabs(
        ["Interview Demo", "Demo Cases", "Trial Task Runner", "Trial Summary"]
    )
    with interview_tab:
        if interview_bundle:
            _render_interview_demo_bundle(interview_bundle)
        else:
            st.warning(
                "No interview bundle was found. Run `python scripts/run_interview_demo.py` first."
            )
    with demo_tab:
        if bundle:
            _render_defense_demo_cases(bundle)
        else:
            st.warning(
                "No complete Phase 6 defense demo bundle was found. Run `python scripts/run_phase6_defense_demo.py` first."
            )
    with runner_tab:
        _render_phase6_trial_runner(demo_available=bool(bundle))
    with summary_tab:
        _render_phase6_trial_summary()


_BACKEND_IMPLEMENTATION_FILES = (
    "agent/research_chat_service.py",
    "agent/research_chat_reasoner.py",
    "agent/scientific_response_context.py",
    "agent/research_runtime.py",
    "engine/approved_scientific_kg.py",
    "agent/conversation_state.py",
    "execution/research_input_binding.py",
    "core/capability_composition_models.py",
    "core/capability_pack_models.py",
    "core/capability_pack_registry.py",
    "core/capability_workspace_models.py",
    "core/execution_models.py",
    "core/representation_models.py",
    "engine/capability_composer.py",
    "engine/capability_planner.py",
    "engine/capability_workspace_service.py",
    "engine/data_profiler.py",
    "engine/representation_profiler.py",
    "execution/capability_notebook.py",
    "execution/execution_ui_service.py",
    "execution/interactive_step_runtime.py",
    "execution/local_jupyter_service.py",
    "execution/notebook_shadow.py",
    "execution/preview_execution_service.py",
    "execution/research_workspace_service.py",
    "execution/renderers/scanpy_core.py",
    "execution/workspace_checkpoint.py",
)


def _backend_implementation_digest() -> str:
    digest = hashlib.sha256()
    root = Path(__file__).resolve().parent
    for relative_path in _BACKEND_IMPLEMENTATION_FILES:
        path = root / relative_path
        digest.update(relative_path.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


@st.cache_resource
def _cached_execution_ui_backend(implementation_digest: str):
    from execution.execution_ui_service import build_execution_ui_service

    _ = implementation_digest
    return build_execution_ui_service()


def _execution_ui_backend():
    return _cached_execution_ui_backend(_backend_implementation_digest())


@st.cache_resource
def _cached_research_agent_backend(implementation_digest: str):
    from agent.bounded_parent_agent import BoundedParentAgent
    from agent.research_chat_service import ResearchChatService

    execution = _cached_execution_ui_backend(implementation_digest)
    parent = BoundedParentAgent(
        contract_registry=execution.contract_registry,
        environment_registry=execution.environment_registry,
        orchestrator=execution.orchestrator,
    )
    from agent.research_runtime import build_chat_retrieval
    return ResearchChatService(parent_agent=parent, data_registry=execution.data_registry,
                               retrieval=build_chat_retrieval(), dense_default_enabled=False)


def _research_agent_backend():
    return _cached_research_agent_backend(_backend_implementation_digest())


@st.cache_resource
def _cached_research_workspace_backend(implementation_digest: str):
    from execution.research_workspace_service import build_research_workspace_service

    execution = _cached_execution_ui_backend(implementation_digest)
    return build_research_workspace_service(
        data_registry=execution.data_registry,
        approval_service=execution.approval_service,
    )


def _research_workspace_backend():
    return _cached_research_workspace_backend(_backend_implementation_digest())


@st.cache_resource
def _cached_capability_workspace_backend(implementation_digest: str):
    from engine.capability_workspace_service import CapabilityWorkspaceService
    from execution.capability_notebook import (
        GenericNotebookCompiler,
        NotebookRendererRegistry,
    )
    from execution.renderers.scanpy_core import ScanpyCoreNotebookRenderer

    execution = _cached_execution_ui_backend(implementation_digest)
    return CapabilityWorkspaceService(
        data_registry=execution.data_registry,
        notebook_compiler=GenericNotebookCompiler(
            NotebookRendererRegistry([ScanpyCoreNotebookRenderer()])
        ),
    )


def _capability_workspace_backend():
    return _cached_capability_workspace_backend(_backend_implementation_digest())


@st.cache_resource
def _cached_local_jupyter_backend(implementation_digest: str):
    from execution.local_jupyter_service import LocalJupyterService

    workspace = _cached_research_workspace_backend(implementation_digest)
    return LocalJupyterService(
        allowed_workspace_root=workspace.workspace_root,
        state_root=Path(__file__).resolve().parent / ".sckg_exec" / "jupyter",
    )


def _local_jupyter_backend():
    return _cached_local_jupyter_backend(_backend_implementation_digest())


@st.cache_resource
def _cached_preview_execution_backend(implementation_digest: str):
    from execution.preview_execution_service import PreviewExecutionService

    execution = _cached_execution_ui_backend(implementation_digest)
    return PreviewExecutionService(
        research_workspace=_cached_research_workspace_backend(
            implementation_digest
        ),
        data_registry=execution.data_registry,
        approval_service=execution.approval_service,
        allowlist=execution.allowlist,
        workspace=execution.workspace,
        execution_policy=execution.execution_policy,
        contract_registry=execution.contract_registry,
        environment_registry=execution.environment_registry,
        router=execution.orchestrator.router,
        wrapper_registry=execution.orchestrator.executor.wrapper_registry,
    )


def _preview_execution_backend():
    return _cached_preview_execution_backend(_backend_implementation_digest())


@st.cache_resource
def _outbound_disclosure_backend() -> OutboundDisclosureService:
    return OutboundDisclosureService(
        audit_path=Path(".sckg_user") / "outbound_disclosure_audit.jsonl"
    )


def _format_storage_size(value: int) -> str:
    size = float(max(0, value))
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} TiB"


def _render_preview_interpretation(interpretation, *, key_prefix: str) -> None:
    _status_badge(interpretation.status)
    st.markdown(f"#### {interpretation.headline}")
    for item in interpretation.plain_language_summary:
        st.markdown(f"- {item}")

    if interpretation.observed_metrics:
        visible_metrics = interpretation.observed_metrics[:4]
        metric_cols = st.columns(len(visible_metrics))
        for column, metric in zip(metric_cols, visible_metrics):
            column.metric(metric.label, metric.display_value)

    for warning in interpretation.warnings:
        st.warning(warning)

    if interpretation.error_diagnosis is not None:
        diagnosis = interpretation.error_diagnosis
        st.error(
            f"{diagnosis.stage.upper()} · {diagnosis.error_code} · "
            f"{diagnosis.category.replace('_', ' ')}"
        )
        for cause in diagnosis.likely_causes:
            st.markdown(f"- {cause}")

    if interpretation.next_actions:
        st.markdown("**Recommended next steps**")
        for action in sorted(interpretation.next_actions, key=lambda item: item.priority):
            approval_note = " · new approval required" if action.requires_new_approval else ""
            st.markdown(
                f"{action.priority}. **{action.label}**{approval_note}  \n{action.reason}"
            )

    with st.popover("How to read this result"):
        if interpretation.plot_explanation is not None:
            plot = interpretation.plot_explanation
            st.markdown(f"**{plot.title}**")
            st.markdown(f"- **X axis:** {plot.x_axis}")
            st.markdown(f"- **Y axis:** {plot.y_axis}")
            for item in plot.how_to_read:
                st.markdown(f"- {item}")
            st.warning(plot.caution)
        if interpretation.parameter_explanations:
            st.markdown("**Parameter effects**")
            st.dataframe(
                [
                    {
                        "parameter": item.parameter_name,
                        "value": str(item.value),
                        "effect": item.effect,
                        "review guidance": item.review_guidance,
                        "automatic adjustment": "No",
                    }
                    for item in interpretation.parameter_explanations
                ],
                use_container_width=True,
                hide_index=True,
            )
        st.markdown("**What this result cannot establish**")
        for item in interpretation.limitations:
            st.markdown(f"- {item}")
        st.caption(
            "Authority: preview_engineering_metric · scientific_claim_allowed=false"
        )


def _render_preview_result_history(*, user_id: str) -> None:
    preview_service = _preview_execution_backend()
    summaries = preview_service.list_results(user_id=user_id)
    st.markdown("### Representative Preview results")
    st.caption(
        "刷新页面后仍可恢复的受控 Preview 记录。这里只证明工程兼容性，不构成科学准确率结论。"
    )
    if not summaries:
        st.info("No representative Preview run has been recorded for this local user.")
        return

    labels = {
        item.run_id: (
            f"{item.status} · {item.tool_name} {item.tool_version} · "
            f"{item.artifact_id} · {item.completed_at:%Y-%m-%d %H:%M}"
        )
        for item in summaries
    }
    selected_run_id = st.selectbox(
        "Preview run history",
        options=list(labels),
        format_func=lambda value: labels[value],
        key="preview_result_history_selection",
    )
    summary = next(item for item in summaries if item.run_id == selected_run_id)
    _status_badge(summary.status)
    metrics = st.columns(5)
    metrics[0].metric("Tool", summary.tool_name)
    metrics[1].metric("Validation", "PASSED" if summary.validation_passed else "FAILED")
    metrics[2].metric("Integrity", "VALID" if summary.integrity.passed else "INVALID")
    metrics[3].metric("Runtime", f"{summary.runtime_seconds:.2f}s")
    metrics[4].metric("Peak memory", f"{summary.peak_memory_mb or 0:.1f} MiB")
    st.caption(
        f"Artifact {summary.artifact_id} · {summary.artifact_count} output artifacts · "
        "scientific authority=false"
    )
    if summary.checkpoint is not None:
        checkpoint = summary.checkpoint
        if checkpoint.overall_status == "STALE":
            st.warning(
                f"STALE from {checkpoint.first_invalid_stage}: {checkpoint.user_action}"
            )
        elif checkpoint.overall_status in {"BLOCKED", "FAILED", "WAITING"}:
            st.info(
                f"{checkpoint.overall_status}: {checkpoint.user_action}"
            )
        st.dataframe(
            [
                {
                    "checkpoint": item.stage,
                    "status": item.status,
                    "reason": ", ".join(item.reasons) or "current",
                    "propagated": item.propagated,
                }
                for item in checkpoint.nodes
            ],
            use_container_width=True,
            hide_index=True,
        )
    if summary.failures:
        st.error(" | ".join(summary.failures))
    for warning in summary.warnings:
        st.warning(warning)
    if not summary.integrity.result_digest_valid:
        st.error("The persisted result record failed its digest check and cannot be opened.")
        with st.popover("Integrity details"):
            st.json(summary.integrity.model_dump(mode="json"))
        return

    try:
        result = preview_service.load_result(
            user_id=user_id,
            artifact_id=summary.artifact_id,
            run_id=summary.run_id,
        )
    except Exception as exc:
        st.error(_execution_ui_backend().redact_text(str(exc)))
        return

    try:
        interpretation = preview_service.interpret_result(result=result)
        _render_preview_interpretation(
            interpretation,
            key_prefix=f"preview_history_{summary.run_id}",
        )
    except Exception as exc:
        st.error(_execution_ui_backend().redact_text(str(exc)))

    if summary.integrity.passed:
        try:
            histogram_path = preview_service.resolve_result_artifact(
                user_id=user_id,
                artifact_id=summary.artifact_id,
                run_id=summary.run_id,
                artifact_name="doublet_score_histogram.png",
            )
            st.image(
                str(histogram_path),
                caption="Scrublet score distribution · representative Preview only",
            )
        except FileNotFoundError:
            st.caption("No diagnostic plot was recorded for this Preview run.")
        except Exception as exc:
            st.error(_execution_ui_backend().redact_text(str(exc)))
    else:
        st.error("Output artifacts failed integrity validation; visual artifacts are withheld.")

    if result.error_context is not None:
        st.error(f"{result.error_context.error_code}: {result.error_context.message}")
        st.info(result.error_context.user_action)
    with st.popover("Advanced Preview details"):
        st.caption(f"Run {summary.run_id} · trace {result.execution_run.trace_id}")
        st.json(result.validation_result.model_dump(mode="json"))
        st.json(
            {
                "integrity": summary.integrity.model_dump(mode="json"),
                "checkpoint": (
                    summary.checkpoint.model_dump(mode="json")
                    if summary.checkpoint is not None
                    else None
                ),
                "artifact_manifest": [
                    {
                        "name": name,
                        "sha256": result.execution_run.artifact_hashes.get(name),
                    }
                    for name in sorted(result.execution_run.artifact_paths)
                ],
                "input_data_copied": result.original_data_copied,
                "scientific_claim_allowed": result.scientific_claim_allowed,
                "output_authority": result.output_authority,
            }
        )


_WORKSPACE_STATE_KEYS_BY_STAGE = {
    "source": (
        "workspace_grant_id",
        "workspace_profile",
        "workspace_preview",
        "workspace_notebook",
        "workspace_preview_approval_id",
        "workspace_preview_run_result",
        "workspace_parameter_patch",
        "workspace_stale_result",
    ),
    "profile": (
        "workspace_profile",
        "workspace_preview",
        "workspace_notebook",
        "workspace_preview_approval_id",
        "workspace_preview_run_result",
        "workspace_parameter_patch",
        "workspace_stale_result",
    ),
    "preview": (
        "workspace_preview",
        "workspace_notebook",
        "workspace_preview_approval_id",
        "workspace_preview_run_result",
        "workspace_parameter_patch",
        "workspace_stale_result",
    ),
    "notebook": (
        "workspace_notebook",
        "workspace_preview_approval_id",
        "workspace_preview_run_result",
        "workspace_parameter_patch",
        "workspace_stale_result",
    ),
    "approval": (
        "workspace_preview_approval_id",
        "workspace_preview_run_result",
    ),
    "result": ("workspace_preview_run_result",),
}


def _reset_workspace_from_stage(stage: str) -> None:
    if stage in {"source", "profile", "preview", "notebook"}:
        for key in list(st.session_state):
            if key.startswith("workspace_jupyter"):
                st.session_state.pop(key, None)
    for key in _WORKSPACE_STATE_KEYS_BY_STAGE.get(stage, ()):
        st.session_state.pop(key, None)


def _render_managed_step_runtime(snapshot) -> None:
    status_class = {
        "CURRENT": "done",
        "COMPLETED": "done",
        "READY": "ready",
        "WAITING": "waiting",
        "RUNNING": "running",
        "STALE": "stale",
        "BLOCKED": "blocked",
        "FAILED": "failed",
    }
    items = []
    for index, node in enumerate(snapshot.steps, start=1):
        items.append(
            "".join(
                [
                    f'<div class="managed-step {status_class.get(node.status, "waiting")}">',
                    f'<span>{index:02d} · {escape(node.status)}</span>',
                    f'<strong>{escape(node.label)}</strong>',
                    "</div>",
                ]
            )
        )
    st.markdown(
        '<div class="managed-step-strip">' + "".join(items) + "</div>",
        unsafe_allow_html=True,
    )
    if snapshot.parameter_patch_required:
        st.warning("参数草案已变化：旧 Notebook、审批和结果不能继续使用。")
    st.caption("下一步：" + snapshot.next_action)


def _render_runtime_packs_page() -> None:
    from execution.execution_ui_service import configured_local_user_id

    service = _execution_ui_backend()
    user_id = configured_local_user_id()
    st.markdown(
        """
<div class="chat-app-header compact-top">
  <div class="chat-app-kicker">Local runtime control plane</div>
  <div class="chat-app-title">Runtime Packs</div>
  <div class="chat-app-subtitle">工具环境按任务族独立安装到用户缓存。环境安装审批只允许维护者审核过的 manifest，不授予数据访问或工具执行权限。</div>
</div>
""",
        unsafe_allow_html=True,
    )
    probes = service.list_runtime_packs()
    if not probes:
        st.warning("No Runtime Pack manifests are available in this release.")
        return
    manifests = {
        item.pack_id: service.runtime_pack_manager.registry.get(item.pack_id)
        for item in probes
    }
    ready_count = sum(1 for item in probes if item.ready)
    total_logical = sum(item.logical_size_bytes for item in probes)
    metrics = st.columns(4)
    metrics[0].metric("Packs", len(probes))
    metrics[1].metric("Ready", ready_count)
    metrics[2].metric("Logical size", _format_storage_size(total_logical))
    metrics[3].metric(
        "Disk quota",
        _format_storage_size(service.runtime_pack_manager.disk_quota_bytes),
    )
    st.caption(
        "Core app remains usable without these packs. Catalog/KG, local sparse retrieval, data registration and dry-run planning do not install tool environments."
    )
    st.caption("Ready 是已发现可用环境的数量，不是 Logical size。Logical size 是文件逻辑字节数，allocated size 是磁盘分配量；两者都不是有效性评分。missing / 0 B 表示未发现该 pack 的已登记环境，不代表用户数据为空。单独模型资格化不等于 Runtime Pack 已安装；signature 仅指 manifest 验证。")
    from observability.workflow_plan_presentation import runtime_probe_display
    st.dataframe(
        [
            {
                "pack": probe.pack_id,
                "task family": manifests[probe.pack_id].task_family,
                "tools": ", ".join(
                    item.tool_name
                    for item in manifests[probe.pack_id].supported_tools
                ),
                **runtime_probe_display(probe),
                "logical size": _format_storage_size(probe.logical_size_bytes),
                "allocated size": _format_storage_size(probe.physical_size_bytes),
                "last used": probe.last_used_at.isoformat()[:19] if probe.last_used_at else "never",
                "runtime network": str(
                    manifests[probe.pack_id].runtime_network_policy
                ),
                "signature": "verified",
            }
            for probe in probes
        ],
        use_container_width=True,
        hide_index=True,
    )

    doublet_probe = next(
        (item for item in probes if item.pack_id == "doublet-python"), None
    )
    with st.container(border=True):
        demo_left, demo_right = st.columns([4, 1])
        with demo_left:
            st.markdown("### 无需安装：Scrublet 合成数据 Preview")
            st.write(
                "使用本机已经验证的 Python 环境和 240 × 500 固定合成 AnnData，"
                "逐步体验数据画像、参数确认、Notebook、审批、运行与验证。"
            )
            st.caption(
                "0 B 下载 · 不访问网络 · 不使用私人数据 · 不自动执行 · 结果仅是工程 Preview"
            )
        with demo_right:
            _status_badge(
                "READY" if doublet_probe is not None and doublet_probe.ready else "BLOCKED"
            )
        if st.button(
            "直接体验 Scrublet Preview",
            type="primary",
            disabled=doublet_probe is None or not doublet_probe.ready,
            key="runtime_quick_scrublet_demo",
            width="stretch",
        ):
            try:
                _activate_scrublet_demo_handoff(
                    {
                        "handoff_id": f"quick-demo-{uuid.uuid4().hex}",
                        "conversation_id": st.session_state.session_id,
                        "source_query": "无需安装，运行 Scrublet synthetic Preview 示例",
                        "task_family": "doublet_detection",
                        "tool_name": "Scrublet",
                        "agent_mode": "PLAN",
                        "plan_id": None,
                        "notebook_strategy": "fixed_shadow",
                        "stepwise_preview_available": True,
                        "fixture_type": "synthetic_engineering_demo",
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
                st.session_state.current_view = "data_preview"
                st.rerun()
            except Exception as exc:
                st.error(service.redact_text(str(exc)))
        if doublet_probe is None or not doublet_probe.ready:
            st.warning(
                "当前没有通过能力检查的 Scrublet Runtime Pack，因此不能伪造零安装运行。"
            )
        else:
            st.caption(
                "本入口复用现有环境，不会创建或批准上方 Annotation Runtime Pack 安装计划。"
            )

    selected_pack = st.selectbox(
        "Runtime Pack",
        options=[item.pack_id for item in probes],
        format_func=lambda value: manifests[value].display_name,
    )
    probe = next(item for item in probes if item.pack_id == selected_pack)
    manifest = manifests[selected_pack]
    left, right = st.columns([2, 1])
    with left:
        st.markdown(f"### {manifest.display_name}")
        st.write(
            f"Task family: `{manifest.task_family}` · Environment: `{manifest.environment_id}`"
        )
        st.write(
            "Tools: "
            + ", ".join(
                f"{item.tool_name} {item.tool_version}"
                for item in manifest.supported_tools
            )
        )
        st.success("Maintainer Ed25519 signature verified")
        st.caption(
            f"Install network: {', '.join(manifest.allowed_install_hosts) or 'none'} · Runtime: {manifest.runtime_network_policy}"
        )
    with right:
        _status_badge("READY" if probe.ready else "WAITING")
        st.metric("Estimated download", _format_storage_size(manifest.estimated_download_size_bytes))
        st.metric("Estimated install", _format_storage_size(manifest.estimated_installed_size_bytes))
        st.caption(
            "Current allocated: " + _format_storage_size(probe.physical_size_bytes)
        )

    if probe.warnings:
        st.warning(" · ".join(probe.warnings))
    if probe.ready:
        source = str(probe.source)
        if source == "legacy_conda_environment":
            st.success(
                "An existing Conda environment satisfies this manifest. It is resolved as a legacy pack and is not copied into the repository."
            )
        else:
            st.success("Managed Runtime Pack is verified and ready.")
            remove_confirmation = st.text_input(
                f"Type REMOVE {selected_pack} to uninstall",
                key=f"remove_pack_confirmation_{selected_pack}",
            )
            if st.button(
                "Remove managed pack",
                disabled=remove_confirmation != f"REMOVE {selected_pack}",
                key=f"remove_pack_{selected_pack}",
            ):
                try:
                    service.remove_runtime_pack(
                        pack_id=selected_pack,
                        confirmation_text=remove_confirmation,
                    )
                    st.session_state.pop("runtime_environment_plan", None)
                    st.success("Managed pack removed. Core assets and user data were untouched.")
                    st.rerun()
                except Exception as exc:
                    st.error(service.redact_text(str(exc)))
        return

    st.markdown("### Environment approval")
    st.info(
        "Creating a plan does not install anything. Installation and later data execution require separate approvals."
    )
    if st.button("Prepare reviewed installation plan", type="primary"):
        try:
            st.session_state.runtime_environment_plan = service.create_environment_plan(
                user_id=user_id,
                pack_id=selected_pack,
            )
            st.session_state.pop("runtime_environment_approval", None)
        except Exception as exc:
            st.error(service.redact_text(str(exc)))
    plan = st.session_state.get("runtime_environment_plan")
    if plan is None or plan.pack_id != selected_pack:
        return
    st.dataframe(
        [
            {"field": "pack", "value": plan.pack_id},
            {"field": "manifest digest", "value": plan.manifest_digest[:16] + "..."},
            {"field": "install location", "value": plan.install_path_redacted},
            {"field": "download", "value": _format_storage_size(plan.estimated_download_size_bytes)},
            {"field": "installed", "value": _format_storage_size(plan.estimated_installed_size_bytes)},
            {"field": "free disk", "value": _format_storage_size(plan.disk_free_bytes)},
            {"field": "pack quota", "value": _format_storage_size(plan.disk_quota_bytes)},
            {"field": "allowed install hosts", "value": ", ".join(plan.allowed_install_hosts)},
            {"field": "runtime network", "value": str(plan.runtime_network_policy)},
        ],
        use_container_width=True,
        hide_index=True,
    )
    if plan.blockers:
        _status_badge("BLOCKED")
        st.dataframe(
            [{"blocker": item} for item in plan.blockers],
            use_container_width=True,
            hide_index=True,
        )
        return
    with st.expander("Advanced immutable command preview"):
        st.caption("These argv lists come from the versioned manifest; no shell string is accepted.")
        st.code("\n".join(" ".join(command) for command in plan.command_preview))
    confirmation = service.runtime_pack_manager.approvals.confirmation_text(plan)
    typed = st.text_input(
        f"Type {confirmation}",
        key=f"approve_pack_confirmation_{plan.plan_id}",
    )
    if st.button(
        "Approve this Runtime Pack",
        disabled=typed != confirmation,
        key=f"approve_pack_{plan.plan_id}",
    ):
        try:
            st.session_state.runtime_environment_approval = service.approve_environment_plan(
                user_id=user_id,
                plan_id=plan.plan_id,
                confirmation_text=typed,
            )
            st.success("Environment approval created. No data or execution approval was created.")
        except Exception as exc:
            st.error(service.redact_text(str(exc)))
    approval = st.session_state.get("runtime_environment_approval")
    if approval is None or approval.plan_id != plan.plan_id:
        return
    if st.button("Install and verify reviewed pack", type="primary"):
        with st.status("Installing Runtime Pack", expanded=True) as status:
            try:
                record = service.install_environment_plan(
                    plan_id=plan.plan_id,
                    approval_id=approval.approval_id,
                )
                if str(record.state) == "ready":
                    status.update(label="Runtime Pack ready", state="complete")
                    st.success("Import smoke passed. Execution approval is still required separately.")
                    st.rerun()
                else:
                    status.update(label="Runtime Pack verification failed", state="error")
                    st.error(record.error_code or "runtime_pack_install_failed")
            except Exception as exc:
                status.update(label="Runtime Pack installation blocked", state="error")
                st.error(service.redact_text(str(exc)))


def _render_restricted_execution_page() -> None:
    from execution.execution_ui_service import configured_local_user_id

    service = _execution_ui_backend()
    user_id = configured_local_user_id()
    st.markdown(
        """
<div class="chat-app-header compact-top">
  <div class="chat-app-kicker">Governed run lifecycle</div>
  <div class="chat-app-title">Runs &amp; Results</div>
  <div class="chat-app-subtitle">承接 Research Workspace 形成的任务：查看 DataProfile 与 dry-run plan，完成精确审批，再检查运行、验证、修复、决策和复现包。</div>
</div>
""",
        unsafe_allow_html=True,
    )
    checkpoint_labels = [
        "DataProfile",
        "WorkflowPlan",
        "Approval",
        "Run",
        "Validation",
        "Repair / Blocked",
        "Decision",
        "Package",
        "Audit",
    ]
    st.markdown(
        '<div class="workflow-stepper">'
        + "".join(
            f'<div class="workflow-step"><b>{index:02d}</b>{escape(label)}</div>'
            for index, label in enumerate(checkpoint_labels, start=1)
        )
        + "</div>",
        unsafe_allow_html=True,
    )
    policy = str(service.execution_policy.mode)
    allowlisted = service.user_allowlisted(user_id=user_id)
    first, second, third = st.columns(3)
    first.metric("Execution policy", policy)
    second.metric("Local user", user_id)
    third.metric("Allowlisted", "yes" if allowlisted else "no")
    if policy == "disabled":
        st.warning("全局执行策略为 disabled。UI 无权修改该策略。")
    if not allowlisted:
        st.warning("当前本地用户不在维护者 allowlist 中。")
    if st.button("Manage Runtime Packs", width="content"):
        st.session_state.current_view = "runtime_packs"
        st.rerun()
    st.info(
        "network_not_os_isolated: 当前控制是应用层路径、权限、wrapper 和进程约束，不是操作系统级 sandbox。"
    )

    _render_preview_result_history(user_id=user_id)

    artifacts = service.list_artifacts(user_id=user_id)
    if not artifacts:
        st.info("当前用户没有已登记 artifact。请由维护者先完成本地数据登记和路径授权。")
        return
    labels = {
        item.artifact_id: f"{item.artifact_id} · {item.redacted_path} · {item.size_bytes:,} bytes"
        for item in artifacts
    }
    artifact_id = st.selectbox(
        "Registered artifact",
        options=list(labels),
        format_func=lambda value: labels[value],
    )
    tool_label = st.selectbox(
        "Tool",
        options=[
            "Scrublet 0.2.3",
            "scDblFinder 1.24.0",
            "Harmony 2.0.0",
            "Scanorama 1.7.4",
        ],
        index=0,
    )
    if tool_label.startswith("Scrublet"):
        tool_name, tool_version = "Scrublet", "0.2.3"
        p1, p2, p3 = st.columns(3)
        parameters = {
            "expected_doublet_rate": p1.number_input(
                "Expected doublet rate", 0.001, 0.25, 0.1, 0.001
            ),
            "n_prin_comps": p2.number_input("Principal components", 2, 100, 10, 1),
            "random_state": p3.number_input("Random seed", 0, 2**31 - 1, 0, 1),
        }
    else:
        if tool_label.startswith("scDblFinder"):
            tool_name, tool_version = "scDblFinder", "1.24.0"
            p1, p2, p3 = st.columns(3)
            parameters = {
                "dbr": p1.number_input("Expected doublet rate", 0.001, 0.5, 0.1, 0.001),
                "n_cores": p2.number_input("Worker cores", 1, 4, 1, 1),
                "random_state": p3.number_input("Random seed", 0, 2**31 - 1, 0, 1),
            }
        elif tool_label.startswith("Harmony"):
            tool_name, tool_version = "Harmony", "2.0.0"
            p1, p2, p3 = st.columns(3)
            parameters = {
                "theta": p1.number_input("Theta", 0.0, 20.0, 2.0, 0.5),
                "sigma": p2.number_input("Sigma", 0.01, 2.0, 0.1, 0.01),
                "max_iter_harmony": p3.number_input("Harmony iterations", 1, 50, 10, 1),
                "max_iter_kmeans": 4,
                "epsilon_harmony": 0.01,
                "ncores": 1,
            }
        else:
            tool_name, tool_version = "Scanorama", "1.7.4"
            p1, p2, p3 = st.columns(3)
            parameters = {
                "knn": p1.number_input("Neighbors", 1, 200, 20, 1),
                "sigma": p2.number_input("Sigma", 0.1, 100.0, 15.0, 0.5),
                "approx": p3.checkbox("Approximate neighbors", value=True),
                "alpha": 0.1,
                "batch_size": 5000,
            }

    selection_key = f"{user_id}:{artifact_id}:{tool_name}:{tool_version}"
    if st.session_state.get("execution_selection_key") != selection_key:
        st.session_state.execution_selection_key = selection_key
        st.session_state.execution_request_id = f"ui-{uuid.uuid4().hex}"
        for key in (
            "execution_grant_id",
            "execution_approval_id",
            "execution_job_id",
            "execution_result",
        ):
            st.session_state.pop(key, None)
    request_id = st.session_state.execution_request_id
    task_label = (
        "batch integration"
        if tool_name in {"Harmony", "Scanorama"}
        else "doublet detection"
    )
    query = f"run approved local {tool_name} {task_label}"

    if st.button("Authorize profile and planning", width="content"):
        try:
            grant = service.grant_profile_access(
                user_id=user_id, artifact_id=artifact_id
            )
            st.session_state.execution_grant_id = grant.grant_id
            st.session_state.pop("execution_approval_id", None)
            st.rerun()
        except Exception as exc:
            st.error(service.redact_text(str(exc)))
    grant_id = st.session_state.get("execution_grant_id")
    if not grant_id:
        st.info("尚未授权读取该 artifact 的 metadata 和表达矩阵画像。")
        return

    approval_id = st.session_state.get("execution_approval_id")
    try:
        context = service.prepare(
            user_id=user_id,
            artifact_id=artifact_id,
            data_grant_id=grant_id,
            execution_approval_id=approval_id,
            request_id=request_id,
            query=query,
            parameters=parameters,
            tool_name=tool_name,
            tool_version=tool_version,
        )
    except Exception as exc:
        st.error(service.redact_text(str(exc)))
        return

    st.markdown("### Runtime Pack")
    if context.runtime_pack is not None:
        runtime_cols = st.columns(3)
        runtime_cols[0].metric("Pack", context.runtime_pack.pack_id)
        runtime_cols[1].metric(
            "State", "READY" if context.runtime_pack.ready else "WAITING"
        )
        runtime_cols[2].metric(
            "Logical size",
            _format_storage_size(context.runtime_pack.logical_size_bytes),
        )
        if not context.runtime_pack.ready:
            st.warning(
                f"{context.runtime_route}: install approval is required before any ExecutionRequest can be created."
            )

    st.markdown("### Data profile")
    if context.profile is not None:
        metrics = st.columns(4)
        metrics[0].metric("Cells", context.profile.n_cells)
        metrics[1].metric("Genes", context.profile.n_genes)
        metrics[2].metric(
            "Batch field" if tool_name in {"Harmony", "Scanorama"} else "Count source",
            (
                context.profile.batch_key or "unresolved"
                if tool_name in {"Harmony", "Scanorama"}
                else context.profile.selected_count_source or "unresolved"
            ),
        )
        metrics[3].metric("Blocked", "yes" if context.profile.is_blocked else "no")
        with st.expander("DataProfile details"):
            st.json(context.profile.model_dump(mode="json"))

    st.markdown("### Dry-run plan")
    if context.plan is not None:
        _status_badge("READY" if context.plan.plan_status == "dry_run" else context.plan.plan_status)
        st.dataframe(
            [
                {
                    "node": node.node_id,
                    "operation": node.operation,
                    "tool": node.tool_name,
                    "failure_policy": node.failure_policy,
                }
                for node in context.plan.steps
            ],
            use_container_width=True,
            hide_index=True,
        )
        st.caption(
            f"Plan {context.plan.plan_id} · {context.plan.plan_status} · environment {context.environment_id}"
        )
    st.markdown("### Execution gate")
    if context.button_blockers:
        _status_badge("BLOCKED")
        st.dataframe(
            [{"blocker": item} for item in context.button_blockers],
            use_container_width=True,
            hide_index=True,
        )
    else:
        _status_badge("READY")
        st.success("所有后端 gate 均已满足。")
    if approval_id and context.execution_approval and not context.execution_approval.allowed:
        st.warning("审批已经失效或 scope 已变化，需要重新确认。")
    with st.expander("Advanced approval details"):
        st.caption("Approval fingerprint")
        st.code(context.approval_fingerprint or "not-created", language=None)
        if context.approval_scope is not None:
            st.json(context.approval_scope.model_dump(mode="json"))

    confirmation_text = service.confirmation_text(context)
    st.markdown("### Explicit approval")
    c1 = st.checkbox("确认数据 artifact", key="execution_confirm_data")
    c2 = st.checkbox("确认工具与版本", key="execution_confirm_tool")
    c3 = st.checkbox("确认参数快照", key="execution_confirm_parameters")
    c4 = st.checkbox("确认执行环境", key="execution_confirm_environment")
    typed = st.text_input(
        "Confirmation text", placeholder=confirmation_text or "Build a plan first"
    )
    if st.button(
        "Create plan-specific approval",
        disabled=not bool(context.approval_scope and confirmation_text),
    ):
        try:
            approval = service.create_plan_approval(
                context=context,
                data_grant_id=grant_id,
                confirmations={
                    "data_confirmed": c1,
                    "tool_confirmed": c2,
                    "parameters_confirmed": c3,
                    "environment_confirmed": c4,
                },
                confirmation_text=typed,
                max_uses=2,
            )
            st.session_state.execution_approval_id = approval.approval_id
            st.rerun()
        except Exception as exc:
            st.error(service.redact_text(str(exc)))

    st.markdown("### Run")
    run_cols = st.columns([1, 1, 3])
    if run_cols[0].button(
        "Execute",
        disabled=not context.button_enabled
        or bool(st.session_state.get("execution_job_id")),
        type="primary",
    ):
        try:
            job = service.start_execution(
                context=context,
                data_grant_id=grant_id,
                execution_approval_id=approval_id,
                request_id=request_id,
                query=query,
                parameters=parameters,
                package_id=f"ui-package-{uuid.uuid4().hex}",
                requested_runs=2,
            )
            st.session_state.execution_job_id = job.job_id
            st.rerun()
        except Exception as exc:
            st.error(service.redact_text(str(exc)))

    job_id = st.session_state.get("execution_job_id")
    if job_id:
        try:
            job = service.poll_job(user_id=user_id, job_id=job_id)
            _status_badge(job.state)
            run_cols[2].caption(f"Job {job.job_id} · {job.state}")
            if job.state in {"queued", "running", "cancel_requested"}:
                if run_cols[1].button(
                    "Cancel", disabled=job.state == "cancel_requested"
                ):
                    service.cancel_job(user_id=user_id, job_id=job_id)
                    st.rerun()
                time.sleep(0.5)
                st.rerun()
            elif job.state == "failed":
                st.error(job.error_summary or "Execution failed")
            elif job.result is not None:
                st.session_state.execution_result = job.result
                st.session_state.pop("execution_job_id", None)
                st.rerun()
        except Exception as exc:
            st.error(service.redact_text(str(exc)))

    result = st.session_state.get("execution_result")
    if result is None:
        return
    try:
        view = service.result_view(user_id=user_id, result=result)
    except Exception as exc:
        st.error(service.redact_text(str(exc)))
        return
    st.markdown("### Validation and decision")
    st.dataframe(
        [
            {
                "run_id": item["run_id"],
                "status": normalize_ui_status(item["status"]),
                "runtime_seconds": item["runtime_seconds"],
                "peak_memory_mb": item["peak_memory_mb"],
            }
            for item in view.run_statuses
        ],
        use_container_width=True,
        hide_index=True,
    )
    for run in view.run_statuses:
        with st.expander(f"{run['run_id']} logs"):
            st.caption("stdout")
            st.code(run["stdout_summary"] or "(empty)")
            st.caption("stderr")
            st.code(run["stderr_summary"] or "(empty)")
    with st.expander("ValidationResult"):
        st.json(view.validation_results)
    with st.expander("CandidateEvaluation"):
        st.json(view.candidate_evaluations)
    with st.expander("Repair history"):
        if view.repair_history:
            st.json(view.repair_history)
        else:
            st.caption("No repair action was applied.")
    recommended = view.decision_result.get("recommended_candidate_id")
    _status_badge("COMPLETED" if recommended else "BLOCKED")
    decision_cols = st.columns(3)
    decision_cols[0].metric("Recommended", _compact(recommended or "none", 30))
    decision_cols[1].metric(
        "Pareto candidates", len(view.decision_result.get("pareto_candidate_ids") or [])
    )
    decision_cols[2].metric(
        "Alternatives", len(view.decision_result.get("alternative_candidate_ids") or [])
    )
    limitations = view.decision_result.get("limitations") or []
    if limitations:
        st.caption("Limitations: " + " | ".join(str(item) for item in limitations))
    with st.expander("Advanced DecisionResult"):
        st.json(view.decision_result)
    package_status = "complete" if view.package_complete else "incomplete"
    st.success(
        f"Package {package_status} · hashes valid={view.manifest_hashes_valid} · {view.package_path_redacted}"
    )
    st.download_button(
        "Export package manifest",
        data=json.dumps(view.package_manifest, ensure_ascii=False, indent=2),
        file_name=f"{view.package_manifest.get('package_id', 'package')}_manifest.json",
        mime="application/json",
    )
    with st.expander("Advanced package manifest"):
        st.json(view.package_manifest)

    st.markdown("### Trial feedback")
    st.caption("Optional and anonymous. Query text, paths, matrices and barcodes are never recorded.")
    usefulness = st.selectbox(
        "Usefulness", ["not provided", 1, 2, 3, 4, 5], key="trial_usefulness"
    )
    incorrect_claim = st.selectbox(
        "Incorrect claim reported", ["not provided", "no", "yes"], key="trial_incorrect_claim"
    )
    package_opened = st.checkbox("I opened the reproducibility package", key="trial_package_opened")
    if st.button("Submit anonymous trial feedback"):
        from core.trial_telemetry import (
            TrialTelemetryEvent,
            TrialTelemetryStore,
            new_trial_participant_id,
        )

        participant_id = st.session_state.setdefault(
            "trial_participant_id", new_trial_participant_id()
        )
        TrialTelemetryStore().append(
            TrialTelemetryEvent(
                participant_id=participant_id,
                task_completion=all(item.get("passed", False) for item in view.validation_results),
                user_intervention_count=1,
                execution_success=all(item.get("status") == "succeeded" for item in view.run_statuses),
                repair_result="succeeded" if view.repair_history else "not_applicable",
                reproducibility_package_opened=package_opened,
                user_rated_usefulness=None if usefulness == "not provided" else int(usefulness),
                user_reported_incorrect_claim=(
                    None if incorrect_claim == "not provided" else incorrect_claim == "yes"
                ),
            )
        )
        st.success("Anonymous feedback recorded.")


def _render_legacy_preview_workbench(*, data_preview_view: bool) -> None:
    """Render only on the explicit Stepwise route, never during chat reruns."""
    workflow_container = (
        st.container(border=False)
        if data_preview_view
        else st.expander("数据与逐步分析 · 高级工作台", expanded=False)
    )
    with workflow_container:
        if not data_preview_view:
            st.markdown('<span class="research-advanced-workbench"></span>', unsafe_allow_html=True)
        from execution.execution_ui_service import (
            configured_local_user_id,
            local_preview_allowance_can_be_reissued,
        )
        from execution.interactive_step_runtime import InteractiveStepRuntime

        execution_service = _execution_ui_backend()
        workspace_service = _research_workspace_backend()
        preview_execution = _preview_execution_backend()
        step_runtime = InteractiveStepRuntime()
        workspace_user_id = configured_local_user_id()
        workspace_artifacts = execution_service.list_artifacts(
            user_id=workspace_user_id
        )
        if data_preview_view:
            st.markdown(
                '<div class="data-workbench-section-title">1. 选择 AnnData 数据</div>'
                '<div class="data-workbench-section-copy">第一次体验直接使用准备好的演示数据；也可以登记 approved 文件夹中的 .h5ad。系统只在原位置读取，不复制原始数据。</div>',
                unsafe_allow_html=True,
            )
        active_workspace_task = st.session_state.get("workspace_task_handoff")
        workspace_enabled = not data_preview_view or bool(
            active_workspace_task
            and active_workspace_task.get("task_family") == "doublet_detection"
            and active_workspace_task.get("tool_name") == "Scrublet"
        )
        prepared_files = sorted(
            {
                candidate.resolve()
                for root in execution_service.data_registry.approved_input_roots
                for candidate in root.glob("*.h5ad")
                if candidate.is_file() and not candidate.is_symlink()
            },
            key=lambda item: (
                item.name != "scrublet_preview_demo.h5ad",
                item.name != "ui_preview_acceptance.h5ad",
                item.name.casefold(),
            ),
        )
        prepared_path = None
        if data_preview_view and prepared_files:
            prepared_path = st.selectbox(
                "可用的本地数据",
                options=prepared_files,
                index=None,
                format_func=lambda value: value.name,
                key="workspace_prepared_path",
                help="这里只列出维护者已批准文件夹中的本地文件。",
            )
            st.caption("仅在明确选择文件并登记后使用；不自动选择演示数据。")
        custom_path_container = (
            st.expander("使用其他 approved .h5ad", expanded=not bool(prepared_files))
            if data_preview_view
            else st.container()
        )
        with custom_path_container:
            local_path = st.text_input(
                "本地 .h5ad 路径",
                type="password",
                placeholder="文件必须位于维护者批准的输入目录中",
                key="workspace_local_path",
                help="路径仅在本地用于登记；页面历史、模型上下文和日志不保存完整路径。",
            )
        registration_path = (
            Path(local_path.strip()) if local_path.strip() else prepared_path
        )
        register_label = (
            "登记这个 AnnData" if local_path.strip() else "使用选中的演示数据"
        )
        if st.button(
            register_label,
            key="workspace_register_artifact",
            disabled=registration_path is None or not workspace_enabled,
            type="primary",
            width="stretch" if data_preview_view else "content",
        ):
            try:
                artifact = execution_service.register_local_artifact(
                    user_id=workspace_user_id, local_path=str(registration_path)
                )
                from execution.research_input_binding import validate_h5ad
                shape = validate_h5ad(execution_service.data_registry.resolve_path(artifact.artifact_id, user_id=workspace_user_id))
                _bind_research_input({"artifact_id": artifact.artifact_id, "sha256": artifact.sha256,
                    "original_filename": registration_path.name, "source": "explicit_registered_selection",
                    "owner_user_id": workspace_user_id, "shape": list(shape)})
                st.session_state.workspace_artifact_id = artifact.artifact_id
                st.session_state.workspace_selected_artifact = artifact.artifact_id
                for key in (
                    "workspace_grant_id",
                    "workspace_profile",
                    "workspace_preview",
                    "workspace_notebook",
                    "workspace_local_preview_enablement",
                    "workspace_preview_approval_id",
                    "workspace_preview_run_result",
                    "workspace_parameter_context",
                    "workspace_parameter_draft",
                    "workspace_parameter_patch",
                    "workspace_stale_result",
                ):
                    st.session_state.pop(key, None)
                st.success(f"数据已登记：{artifact.redacted_path}")
                st.rerun()
            except Exception as exc:
                st.error(execution_service.redact_text(str(exc)))

        workspace_artifacts = execution_service.list_artifacts(user_id=workspace_user_id)
        # The legacy preview must not silently attach the registry's first item.
        bound_id = ((active_workspace_task or {}).get("input_binding") or _research_input_binding()).get("artifact_id")
        if (active_workspace_task or {}).get("fixture_type") == "synthetic_engineering_demo":
            bound_id = st.session_state.get("workspace_artifact_id")
        workspace_artifacts = [item for item in workspace_artifacts if item.artifact_id == bound_id]
        if workspace_artifacts:
            if data_preview_view:
                st.markdown(
                    '<div class="data-workbench-section-title">2. 检查数据画像</div>'
                    '<div class="data-workbench-section-copy">先授权只读画像，再确认细胞数、基因数、矩阵状态和 raw-count 来源。无法识别 counts 时，后续步骤会被正确阻断。</div>',
                    unsafe_allow_html=True,
                )
            artifact_labels = {
                item.artifact_id: f"{item.artifact_id} · {item.redacted_path}"
                for item in workspace_artifacts
            }
            selected_workspace_artifact = st.selectbox(
                "当前数据",
                options=list(artifact_labels),
                format_func=lambda value: artifact_labels[value],
                index=(
                    list(artifact_labels).index(st.session_state.workspace_artifact_id)
                    if st.session_state.get("workspace_artifact_id") in artifact_labels
                    else 0
                ),
                key="workspace_selected_artifact",
            )
            if st.session_state.get("workspace_artifact_id") != selected_workspace_artifact:
                st.session_state.workspace_artifact_id = selected_workspace_artifact
                for key in (
                    "workspace_grant_id",
                    "workspace_profile",
                    "workspace_preview",
                    "workspace_notebook",
                    "workspace_local_preview_enablement",
                    "workspace_preview_approval_id",
                    "workspace_preview_run_result",
                    "workspace_parameter_context",
                    "workspace_parameter_draft",
                    "workspace_parameter_patch",
                    "workspace_stale_result",
                ):
                    st.session_state.pop(key, None)

            workspace_path_authorized = execution_service.artifact_path_authorized(
                user_id=workspace_user_id,
                artifact_id=selected_workspace_artifact,
            )
            if not workspace_path_authorized:
                st.warning(
                    "应用重启后不会持久化完整本地路径。请先在上方重新选择同一个文件并点击“使用选中的演示数据”或“登记这个 AnnData”；内容 hash 一致时会恢复原 artifact，不会复制数据。"
                )

            action_cols = st.columns(2)
            if action_cols[0].button(
                "授权只读画像",
                key="workspace_authorize",
                width="stretch",
                disabled=not workspace_path_authorized,
            ):
                try:
                    grant = execution_service.grant_profile_access(
                        user_id=workspace_user_id,
                        artifact_id=selected_workspace_artifact,
                    )
                    st.session_state.workspace_grant_id = grant.grant_id
                    st.success("已授权读取数据结构和元数据。")
                except Exception as exc:
                    st.error(execution_service.redact_text(str(exc)))
            grant_id = st.session_state.get("workspace_grant_id")
            if action_cols[1].button(
                "生成数据画像",
                key="workspace_profile_button",
                disabled=not bool(grant_id) or not workspace_path_authorized,
                width="stretch",
            ):
                try:
                    st.session_state.workspace_profile = workspace_service.profile(
                        user_id=workspace_user_id,
                        artifact_id=selected_workspace_artifact,
                        data_grant_id=grant_id,
                    )
                    st.session_state.pop("workspace_preview", None)
                    st.session_state.pop("workspace_notebook", None)
                    st.session_state.pop("workspace_preview_approval_id", None)
                    st.session_state.pop("workspace_preview_run_result", None)
                    st.session_state.pop("workspace_parameter_patch", None)
                    st.session_state.pop("workspace_stale_result", None)
                    st.rerun()
                except Exception as exc:
                    st.error(execution_service.redact_text(str(exc)))

            profile = st.session_state.get("workspace_profile")
            if profile is not None:
                profile_metrics = st.columns(5)
                profile_metrics[0].metric("细胞", profile.n_cells)
                profile_metrics[1].metric("基因", profile.n_genes)
                profile_metrics[2].metric(
                    "Counts 来源", profile.selected_count_source or "未识别"
                )
                profile_metrics[3].metric("读取方式", "只读")
                profile_metrics[4].metric(
                    "下一步", "可预览" if profile.preview_capability == "supported" else "已阻断"
                )
                profile_detail_surface = (
                    st.expander("高级详情：数据画像", expanded=False)
                    if data_preview_view
                    else st.popover("Profile details")
                )
                with profile_detail_surface:
                    st.json(profile.model_dump(mode="json"))
                preview_limit = st.number_input(
                    "Preview 细胞数",
                    min_value=20,
                    max_value=5000,
                    value=min(500, max(20, profile.n_cells)),
                    step=20,
                    key="workspace_preview_limit",
                )
                batch_options = ["Auto", *profile.batch_candidates]
                stratify_choice = st.selectbox(
                    "分层抽样字段",
                    options=batch_options,
                    key="workspace_stratify_key",
                )
                if data_preview_view:
                    st.markdown(
                        '<div class="data-workbench-section-title">3. 构建代表性 Preview</div>'
                        '<div class="data-workbench-section-copy">选择一个小规模细胞预算，检查代码、数据结构与运行环境。这个子集仅用于兼容性验证，不代表全量数据性能。</div>',
                        unsafe_allow_html=True,
                    )
                if st.button(
                    "构建代表性 Preview",
                    key="workspace_preview_button",
                    disabled=profile.preview_capability != "supported",
                    type="primary",
                ):
                    try:
                        built_preview = workspace_service.build_preview(
                            user_id=workspace_user_id,
                            artifact_id=selected_workspace_artifact,
                            profile=profile,
                            data_grant_id=grant_id,
                            max_cells=int(preview_limit),
                            stratify_key=None if stratify_choice == "Auto" else stratify_choice,
                        )
                        st.session_state.workspace_preview = built_preview
                        st.session_state.workspace_parameter_context = built_preview.preview_id
                        st.session_state.workspace_parameter_draft = (
                            step_runtime.default_parameters()
                        )
                        st.session_state.pop("workspace_parameter_patch", None)
                        st.session_state.pop("workspace_stale_result", None)
                        st.session_state.pop("workspace_notebook", None)
                        st.session_state.pop("workspace_preview_approval_id", None)
                        st.session_state.pop("workspace_preview_run_result", None)
                        st.rerun()
                    except Exception as exc:
                        st.error(execution_service.redact_text(str(exc)))

            preview = st.session_state.get("workspace_preview")
            if preview is not None:
                if data_preview_view:
                    st.markdown(
                        '<div class="data-workbench-section-title">4. 检查代码并决定是否在线验证</div>'
                        '<div class="data-workbench-section-copy">对话任务会自动选择维护者验证过的 Notebook 模板。Notebook 用于检查和复现；在线运行始终调用固定 wrapper，并逐步显示审批、执行与 Validation。</div>',
                        unsafe_allow_html=True,
                    )
                _status_badge("READY")
                st.write(
                    f"代表性 Preview：{preview.n_preview_cells:,}/{preview.n_source_cells:,} 个细胞 · "
                    f"抽样策略={preview.policy} · 源文件未修改={'是' if preview.source_unchanged else '否'}"
                )
                st.caption("这是工程预览，不是全量科学结论，也不会自动创建执行请求。")
                notebook_bundle = st.session_state.get("workspace_notebook")
                from execution.notebook_shadow import scrublet_step_contract

                current_template_digest = scrublet_step_contract().template_digest
                notebook_template_stale = bool(
                    notebook_bundle is not None
                    and notebook_bundle.step_template_digest
                    != current_template_digest
                )
                if (
                    st.session_state.get("workspace_parameter_context")
                    != preview.preview_id
                ):
                    st.session_state.workspace_parameter_context = preview.preview_id
                    st.session_state.workspace_parameter_draft = (
                        dict(notebook_bundle.parameter_snapshot)
                        if notebook_bundle is not None
                        and notebook_bundle.parameter_snapshot
                        else step_runtime.default_parameters()
                    )
                draft_parameters = dict(
                    st.session_state.get("workspace_parameter_draft")
                    or step_runtime.default_parameters()
                )
                parameter_surface = (
                    st.expander(
                        "参数与代码",
                        expanded=not bool(notebook_bundle) or notebook_template_stale,
                    )
                    if data_preview_view
                    else st.container(border=True)
                )
                with parameter_surface:
                    if not data_preview_view:
                        st.markdown("#### 参数与代码")
                    st.caption(
                        "参数来自 Scrublet 0.2.3 ToolContract。修改只形成草案；提交后会重建 Notebook，并使旧审批与旧结果失效。"
                    )
                    if notebook_template_stale:
                        st.warning(
                            "Notebook 模板已更新，当前文件仍是旧版本。请点击下面的更新按钮，生成包含分步讲解和新版诊断图的 Notebook。"
                        )
                    parameter_cols = st.columns(4)
                    draft_parameters["expected_doublet_rate"] = parameter_cols[0].number_input(
                        "Expected doublet rate",
                        min_value=0.001,
                        max_value=0.2,
                        value=float(draft_parameters["expected_doublet_rate"]),
                        step=0.01,
                        format="%.3f",
                        key=f"workspace_expected_rate_{preview.preview_id}",
                    )
                    draft_parameters["n_prin_comps"] = parameter_cols[1].number_input(
                        "Principal components",
                        min_value=2,
                        max_value=100,
                        value=int(draft_parameters["n_prin_comps"]),
                        step=1,
                        key=f"workspace_n_prin_{preview.preview_id}",
                    )
                    draft_parameters["sim_doublet_ratio"] = parameter_cols[2].number_input(
                        "Synthetic ratio",
                        min_value=1.0,
                        max_value=10.0,
                        value=float(draft_parameters["sim_doublet_ratio"]),
                        step=0.25,
                        key=f"workspace_sim_ratio_{preview.preview_id}",
                    )
                    draft_parameters["use_approx_neighbors"] = parameter_cols[3].toggle(
                        "Approximate neighbors",
                        value=bool(draft_parameters["use_approx_neighbors"]),
                        key=f"workspace_approx_{preview.preview_id}",
                    )
                    st.session_state.workspace_parameter_draft = draft_parameters
                    try:
                        parameter_patch = step_runtime.propose_parameter_patch(
                            notebook=notebook_bundle,
                            proposed_parameters=draft_parameters,
                        )
                        st.session_state.workspace_parameter_patch = parameter_patch
                    except ValueError as exc:
                        parameter_patch = None
                        st.error(execution_service.redact_text(str(exc)))
                    if parameter_patch is not None and parameter_patch.changes:
                        st.dataframe(
                            [
                                {
                                    "parameter": item.parameter_name,
                                    "current": item.old_value,
                                    "proposed": item.new_value,
                                    "effect": "Notebook + approval + result become stale",
                                }
                                for item in parameter_patch.changes
                            ],
                            width="stretch",
                            hide_index=True,
                        )
                    patch_confirmed = st.checkbox(
                        "我确认这些参数用于当前代表性 Preview；修改后需要重新审批。",
                        key=f"workspace_parameter_confirmation_{preview.preview_id}",
                        disabled=not bool(parameter_patch and parameter_patch.requires_rebuild),
                    )
                    if notebook_template_stale:
                        rebuild_label = "更新 Notebook（包含新版诊断图）"
                    elif notebook_bundle is not None:
                        rebuild_label = "按当前参数更新 Notebook"
                    else:
                        rebuild_label = "生成可交互分析 Notebook"
                    if st.button(
                        rebuild_label,
                        key="workspace_notebook_button",
                        type="primary",
                        disabled=bool(
                            parameter_patch
                            and parameter_patch.requires_rebuild
                            and not patch_confirmed
                        ),
                    ):
                        try:
                            old_approval_id = st.session_state.get(
                                "workspace_preview_approval_id"
                            )
                            if old_approval_id:
                                try:
                                    execution_service.approval_service.revoke_execution_approval(
                                        old_approval_id
                                    )
                                except KeyError:
                                    pass
                            old_result = st.session_state.get(
                                "workspace_preview_run_result"
                            )
                            if old_result is not None:
                                st.session_state.workspace_stale_result = old_result
                            st.session_state.workspace_notebook = (
                                workspace_service.compile_notebook(
                                    user_id=workspace_user_id,
                                    artifact_id=selected_workspace_artifact,
                                    profile=profile,
                                    preview=preview,
                                    data_grant_id=grant_id,
                                    parameters=(
                                        parameter_patch.parameters
                                        if parameter_patch is not None
                                        else draft_parameters
                                    ),
                                    task_context={
                                        "handoff_id": str(
                                            (active_workspace_task or {}).get(
                                                "handoff_id"
                                            )
                                            or ""
                                        ),
                                        "conversation_id": str(
                                            (active_workspace_task or {}).get(
                                                "conversation_id"
                                            )
                                            or ""
                                        ),
                                        "source_query": str(
                                            (active_workspace_task or {}).get(
                                                "source_query"
                                            )
                                            or ""
                                        ),
                                        "task_family": "doublet_detection",
                                        "tool_name": "Scrublet",
                                    },
                                )
                            )
                            st.session_state.pop("workspace_preview_approval_id", None)
                            st.session_state.pop("workspace_preview_run_result", None)
                            st.rerun()
                        except Exception as exc:
                            st.error(execution_service.redact_text(str(exc)))
            notebook_bundle = st.session_state.get("workspace_notebook")
            active_checkpoint = None
            if profile is not None:
                active_checkpoint = preview_execution.checkpoints.inspect_active(
                    user_id=workspace_user_id,
                    artifact_id=selected_workspace_artifact,
                    profile=profile,
                    preview=preview,
                    notebook=notebook_bundle,
                    approval_id=st.session_state.get("workspace_preview_approval_id"),
                    result=st.session_state.get("workspace_preview_run_result"),
                    result_integrity=(
                        preview_execution.result_store.inspect_integrity(
                            st.session_state.workspace_preview_run_result
                        )
                        if st.session_state.get("workspace_preview_run_result") is not None
                        else None
                    ),
                )
                checkpoint_surface = (
                    st.expander("高级详情：检查点与 lineage", expanded=False)
                    if data_preview_view
                    else st.container()
                )
                with checkpoint_surface:
                    st.markdown("#### 工作区检查点")
                    checkpoint_cols = st.columns(3)
                    for checkpoint_col, checkpoint_node in zip(
                        checkpoint_cols * 2, active_checkpoint.nodes
                    ):
                        checkpoint_col.metric(
                            checkpoint_node.stage.title(), checkpoint_node.status
                        )
                    st.json(active_checkpoint.model_dump(mode="json"))
                if active_checkpoint.overall_status == "STALE":
                    st.warning(
                        f"STALE from {active_checkpoint.first_invalid_stage}: "
                        f"{active_checkpoint.user_action}"
                    )
                    if st.button(
                        f"Reset from {active_checkpoint.rebuild_from}",
                        key="workspace_reset_stale_lineage",
                    ):
                        _reset_workspace_from_stage(active_checkpoint.rebuild_from or "source")
                        st.rerun()
                elif active_checkpoint.overall_status in {"BLOCKED", "FAILED"}:
                    st.error(active_checkpoint.user_action)
                elif (
                    active_checkpoint.overall_status in {"INCOMPLETE", "WAITING"}
                    and not data_preview_view
                ):
                    st.caption(active_checkpoint.user_action)
            if profile is not None and notebook_bundle is None:
                runtime_snapshot = step_runtime.inspect(
                    artifact_id=selected_workspace_artifact,
                    profile=profile,
                    preview=preview,
                    notebook=notebook_bundle,
                    approval_id=st.session_state.get("workspace_preview_approval_id"),
                    result=st.session_state.get("workspace_preview_run_result"),
                    parameter_patch=st.session_state.get("workspace_parameter_patch"),
                )
                _render_managed_step_runtime(runtime_snapshot)
            if notebook_bundle is not None:
                notebook_trust = workspace_service.inspect_notebook_trust(
                    user_id=workspace_user_id,
                    artifact_id=selected_workspace_artifact,
                    bundle=notebook_bundle,
                )
                notebook_path = (
                    workspace_service.notebook_path(
                        user_id=workspace_user_id,
                        artifact_id=selected_workspace_artifact,
                        bundle=notebook_bundle,
                    )
                    if notebook_trust.system_verified
                    else None
                )
                st.success(
                    f"Notebook 已生成 · {notebook_bundle.cell_count} 个单元格 · "
                    "未创建执行请求"
                )
                _render_chip(
                    "Notebook verified"
                    if notebook_trust.system_verified
                    else "Notebook modified / untrusted",
                    "good" if notebook_trust.system_verified else "bad",
                )
                if not notebook_trust.system_verified:
                    st.error(
                        "Notebook 已被修改，当前在线执行不会使用它。请从 Notebook 步骤重新构建。"
                    )
                if notebook_path is not None:
                    from execution.local_notebook_launcher import LocalNotebookLauncher

                    notebook_launcher = LocalNotebookLauncher(
                        allowed_workspace_root=workspace_service.workspace_root
                    )
                    jupyter_service = _local_jupyter_backend()
                    st.markdown("### 在浏览器 Notebook 中逐步分析")
                    st.write(
                        "使用已经安装并验证的 `doublet-python` 环境；不安装依赖、不自动运行。"
                        "你可以修改参数，按顺序逐格执行，并立即查看表格、图和报错。"
                    )
                    active_jupyter_session = None
                    active_jupyter_id = st.session_state.get(
                        "workspace_jupyter_session_id"
                    )
                    if (
                        active_jupyter_id
                        and st.session_state.get("workspace_jupyter_notebook_hash")
                        == notebook_bundle.notebook_hash
                    ):
                        try:
                            active_jupyter_session = jupyter_service.get(
                                session_id=active_jupyter_id,
                                owner_user_id=workspace_user_id,
                            )
                        except Exception:
                            active_jupyter_session = None

                    if active_jupyter_session is None and st.button(
                        "启动本地 JupyterLab",
                        key="workspace_start_jupyter",
                        type="primary",
                        width="stretch",
                        disabled=not jupyter_service.available,
                    ):
                        try:
                            runtime_python = execution_service.runtime_pack_manager.resolve_entrypoint(
                                "doublet-python", "python"
                            )
                            launched = jupyter_service.start(
                                owner_user_id=workspace_user_id,
                                notebook_path=notebook_path,
                                expected_sha256=notebook_bundle.notebook_hash,
                                runtime_python=runtime_python,
                                runtime_pack_id="doublet-python",
                                request_id=f"jupyter-launch:{uuid.uuid4().hex}",
                                parent_trace_id=(
                                    (active_workspace_task or {}).get("origin_trace_id")
                                ),
                                handoff_id=(
                                    (active_workspace_task or {}).get("handoff_id")
                                ),
                                parent_request_id=(
                                    (active_workspace_task or {}).get("parent_request_id")
                                ),
                                original_plan_id=(
                                    (active_workspace_task or {}).get("original_plan_id")
                                ),
                            )
                            st.session_state.workspace_jupyter_session_id = (
                                launched.session_id
                            )
                            st.session_state.workspace_jupyter_notebook_hash = (
                                notebook_bundle.notebook_hash
                            )
                            st.session_state.workspace_jupyter_trace_id = (
                                launched.canonical_trace_id
                            )
                            st.rerun()
                        except Exception as exc:
                            st.error(execution_service.redact_text(str(exc)))
                    if active_jupyter_session is not None:
                        st.success(
                            "本地 JupyterLab 已就绪 · 已绑定 scKG Doublet Python · "
                            "尚未执行任何单元格"
                        )
                        jupyter_actions = st.columns([2, 1])
                        jupyter_actions[0].link_button(
                            "打开 JupyterLab 工作区",
                            active_jupyter_session.launch_url,
                            type="primary",
                            use_container_width=True,
                        )
                        if jupyter_actions[1].button(
                            "停止 JupyterLab",
                            key="workspace_stop_jupyter",
                            width="stretch",
                        ):
                            jupyter_service.stop(
                                session_id=active_jupyter_session.session_id,
                                owner_user_id=workspace_user_id,
                            )
                            st.session_state.pop(
                                "workspace_jupyter_session_id", None
                            )
                            st.session_state.pop(
                                "workspace_jupyter_notebook_hash", None
                            )
                            st.rerun()
                    elif not jupyter_service.available:
                        st.warning(
                            "本机未发现 JupyterLab 控制面；系统没有自动安装任何依赖。"
                        )

                    show_external_notebook = st.toggle(
                        "其他打开方式与下载",
                        value=False,
                        key="workspace_show_external_notebook",
                    )
                    if show_external_notebook:
                        if notebook_launcher.editor_name == "Cursor":
                            st.info(
                                "当前 Cursor 命令行会把 `.ipynb` 当作 JSON 文本打开。"
                                "建议使用上面的浏览器 JupyterLab；或在编辑器中启用 Jupyter Notebook renderer。"
                            )
                        elif notebook_launcher.available and st.button(
                            f"在 {notebook_launcher.editor_name} 打开",
                            key="workspace_open_notebook_editor",
                            width="stretch",
                        ):
                            try:
                                runtime_python = execution_service.runtime_pack_manager.resolve_entrypoint(
                                    "doublet-python", "python"
                                )
                                launched = notebook_launcher.launch(
                                    notebook_path=notebook_path,
                                    expected_sha256=notebook_bundle.notebook_hash,
                                    runtime_python=runtime_python,
                                )
                                st.success(
                                    f"已在 {launched.editor_name} 打开；内核为 `{launched.kernel_name}`。"
                                )
                            except Exception as exc:
                                st.error(execution_service.redact_text(str(exc)))
                        st.download_button(
                            "下载完整 Notebook bundle (.zip)",
                            data=workspace_service.notebook_bundle_bytes(
                                user_id=workspace_user_id,
                                artifact_id=selected_workspace_artifact,
                                bundle=notebook_bundle,
                            ),
                            file_name="sckg_scrublet_preview_bundle.zip",
                            mime="application/zip",
                            key="workspace_download_notebook_bundle",
                            width="stretch",
                        )
                        st.caption(
                            "ZIP 同时包含 Notebook、representative_preview.h5ad、参数和合同；"
                            "请保持这些文件在同一目录。"
                        )
                    st.caption(
                        "JupyterLab 只监听 127.0.0.1，并使用随机访问令牌。"
                        "交互式单元由你控制；修改后的 Notebook 不会自动取得 scKG 受控执行资格。"
                    )
                show_preview_run = st.toggle(
                    "需要审计记录时，使用受控验证运行",
                    value=False,
                    key="workspace_show_preview_run",
                    help="可选：不执行 Notebook 中的任意代码，只调用审核过的固定 Scrublet wrapper 并生成 Validation 记录。",
                )
                preview_preparation = None
                if show_preview_run:
                    try:
                        local_enablement = st.session_state.get(
                            "workspace_local_preview_enablement"
                        ) or {}
                        enabled_until = local_enablement.get("expires_at")
                        enablement_active = bool(
                            local_enablement.get("artifact_id")
                            == selected_workspace_artifact
                            and enabled_until
                            and datetime.fromisoformat(str(enabled_until))
                            > datetime.now(timezone.utc)
                        )
                        if enablement_active and (
                            str(execution_service.execution_policy.mode)
                            == "disabled"
                            or not execution_service.user_allowlisted(
                                user_id=workspace_user_id
                            )
                        ):
                            restored = execution_service.enable_local_preview(
                                user_id=workspace_user_id,
                                artifact_id=selected_workspace_artifact,
                                actor_role="maintainer",
                                ttl_minutes=30,
                                max_runs=1,
                            )
                            if restored.enabled:
                                st.session_state.workspace_local_preview_enablement = (
                                    restored.model_dump(mode="json")
                                )
                                _cached_preview_execution_backend.clear()
                        preview_execution = _preview_execution_backend()
                        preview_preparation = preview_execution.prepare(
                            user_id=workspace_user_id,
                            artifact_id=selected_workspace_artifact,
                            data_grant_id=grant_id,
                            execution_approval_id=st.session_state.get(
                                "workspace_preview_approval_id"
                            ),
                            profile=profile,
                            preview=preview,
                            notebook=notebook_bundle,
                        )
                    except Exception as exc:
                        st.error(execution_service.redact_text(str(exc)))

                if preview_preparation is not None:
                    runtime_snapshot = step_runtime.inspect(
                        artifact_id=selected_workspace_artifact,
                        profile=profile,
                        preview=preview,
                        notebook=notebook_bundle,
                        approval_id=st.session_state.get(
                            "workspace_preview_approval_id"
                        ),
                        result=st.session_state.get(
                            "workspace_preview_run_result"
                        ),
                        preparation=preview_preparation,
                        parameter_patch=st.session_state.get(
                            "workspace_parameter_patch"
                        ),
                    )
                    _render_managed_step_runtime(runtime_snapshot)
                    st.markdown("#### 最后一步：批准并运行 Preview")
                    approval_blockers = set(preview_preparation.approval_blockers)
                    non_approval_blockers = [
                        item
                        for item in preview_preparation.blockers
                        if item not in approval_blockers
                    ]
                    active_patch = st.session_state.get("workspace_parameter_patch")
                    if active_patch is not None and active_patch.requires_rebuild:
                        non_approval_blockers.append("parameter_patch_not_committed")
                    recoverable_allowance = local_preview_allowance_can_be_reissued(
                        non_approval_blockers
                    )
                    if preview_preparation.ready:
                        st.success("当前数据、参数、环境和一次性审批均已就绪，可以运行。")
                    elif recoverable_allowance or (
                        not non_approval_blockers and approval_blockers
                    ):
                        st.info(
                            "当前 Preview 已准备好。确认本次运行后，系统会更新旧审批并仅授权这一份合成数据。"
                        )
                    if non_approval_blockers:
                        blocker_labels = {
                            "execution_policy_disabled": "全局本地执行策略尚未为当前会话启用",
                            "local_user_not_allowlisted": "当前本地用户尚未获准运行这个数据和工具",
                            "local_user_allowance_expired": "当前数据的临时本地运行资格已过期",
                            "local_user_allowance_revoked": "当前数据的临时本地运行资格已撤销",
                            "tool_environment_pair_not_allowed_for_user": "旧资格未绑定当前 Scrublet 与环境",
                            "artifact_not_allowed_for_user": "旧资格未绑定当前数据",
                            "data_scope_not_allowed_for_user": "旧资格未包含 representative Preview 范围",
                            "local_user_run_budget_exceeded": "当前单次运行资格已经使用",
                            "runtime_pack_not_ready": "Scrublet Runtime Pack 尚未通过当前环境检查",
                            "contract_execution_disabled": "Scrublet ToolContract 尚未开放执行",
                            "environment_execution_disabled": "scRNAseq 环境尚未开放执行",
                            "parameter_patch_not_committed": "参数草案尚未确认并重建 Notebook",
                        }
                        st.warning(
                            "暂时不能运行："
                            + "；".join(
                                blocker_labels.get(item, item)
                                for item in non_approval_blockers
                            )
                        )
                        if recoverable_allowance:
                            st.caption(
                                "确认后只重新签发当前数据、Scrublet 和环境的 30 分钟单次资格，不会开放全局执行。"
                            )
                    approval_detail_surface = (
                        st.expander("高级详情：运行边界与审批指纹", expanded=False)
                        if data_preview_view
                        else st.popover("Approval details")
                    )
                    with approval_detail_surface:
                        detail_cols = st.columns(4)
                        detail_cols[0].metric(
                            "Policy", preview_preparation.policy_mode.upper()
                        )
                        detail_cols[1].metric(
                            "Runtime",
                            "READY" if preview_preparation.runtime_ready else "BLOCKED",
                        )
                        detail_cols[2].metric(
                            "Approval",
                            "READY" if preview_preparation.approval_ready else "WAITING",
                        )
                        detail_cols[3].metric(
                            "Run", "READY" if preview_preparation.ready else "WAITING"
                        )
                        st.caption(
                            "固定 Scrublet wrapper 通过 LocalControlledExecutor 运行；"
                            "可编辑 Notebook 永远不会被此按钮执行。"
                        )
                        st.code(preview_preparation.approval_fingerprint)
                        st.caption(
                            "Bound to Preview, notebook template, parameters, tool contract, "
                            "environment, artifact and local user."
                        )
                        if preview_preparation.blockers:
                            st.json({"blockers": preview_preparation.blockers})
                    preview_confirmation = (
                        f"APPROVE PREVIEW {preview_preparation.approval_fingerprint[:12]}"
                    )
                    synthetic_demo = bool(
                        (active_workspace_task or {}).get("fixture_type")
                        == "synthetic_engineering_demo"
                    )
                    if not preview_preparation.ready:
                        if synthetic_demo:
                            approval_confirmed = st.checkbox(
                                "我确认仅在本机使用这份合成数据运行固定 Scrublet Preview。",
                                key="workspace_preview_scope_confirmation",
                            )
                            typed_preview_confirmation = (
                                preview_confirmation if approval_confirmed else ""
                            )
                        else:
                            st.caption(
                                "为真实数据创建一次性审批，请复制并粘贴下面的确认文本。"
                            )
                            st.code(preview_confirmation)
                            typed_preview_confirmation = st.text_input(
                                "粘贴确认文本",
                                placeholder=preview_confirmation,
                                key="workspace_preview_approval_confirmation",
                            )
                        if st.button(
                            "1. 确认并批准当前 Preview",
                            key="workspace_preview_approval_button",
                            type="primary",
                            width="stretch",
                            disabled=(
                                bool(non_approval_blockers)
                                and not recoverable_allowance
                            )
                            or typed_preview_confirmation.strip()
                            != preview_confirmation,
                        ):
                            try:
                                old_approval_id = st.session_state.get(
                                    "workspace_preview_approval_id"
                                )
                                if old_approval_id and not preview_preparation.approval_ready:
                                    try:
                                        execution_service.approval_service.revoke_execution_approval(
                                            old_approval_id
                                        )
                                    except KeyError:
                                        pass
                                if recoverable_allowance:
                                    approved_preview = execution_service.approve_local_preview(
                                        scope=preview_preparation.approval_scope,
                                        data_grant_id=grant_id,
                                        confirmation_text=typed_preview_confirmation,
                                        actor_role="maintainer",
                                        ttl_minutes=30,
                                    )
                                    st.session_state.workspace_local_preview_enablement = (
                                        approved_preview.enablement.model_dump(mode="json")
                                    )
                                    approval = approved_preview.approval
                                    _cached_preview_execution_backend.clear()
                                else:
                                    approval = execution_service.approval_service.create_execution_approval(
                                        scope=preview_preparation.approval_scope,
                                        data_grant_id=grant_id,
                                        max_uses=1,
                                    )
                                st.session_state.workspace_preview_approval_id = (
                                    approval.approval_id
                                )
                                st.rerun()
                            except Exception as exc:
                                st.error(execution_service.redact_text(str(exc)))

                    run_confirmation = st.checkbox(
                        "我理解这是代表性 Preview，不是全量数据科学结论。",
                        key="workspace_preview_run_confirmation",
                    )
                    if st.button(
                        "2. 运行并验证 Preview",
                        key="workspace_preview_run_button",
                        type="primary" if preview_preparation.ready else "secondary",
                        width="stretch",
                        disabled=(
                            not preview_preparation.ready
                            or bool(non_approval_blockers)
                            or not run_confirmation
                        ),
                    ):
                        try:
                            with st.spinner("Running fixed Scrublet Preview and validating artifacts..."):
                                st.session_state.workspace_preview_run_result = (
                                    preview_execution.execute(
                                        user_id=workspace_user_id,
                                        artifact_id=selected_workspace_artifact,
                                        data_grant_id=grant_id,
                                        execution_approval_id=st.session_state.workspace_preview_approval_id,
                                        profile=profile,
                                        preview=preview,
                                        notebook=notebook_bundle,
                                        request_id=f"preview-{uuid.uuid4().hex}",
                                    )
                                )
                            st.rerun()
                        except Exception as exc:
                            st.error(execution_service.redact_text(str(exc)))

                preview_result = st.session_state.get("workspace_preview_run_result")
                if preview_result is not None:
                    validation = preview_result.validation_result
                    if validation.passed:
                        st.success("Preview run validated. Scientific authority remains false.")
                    else:
                        st.error("Preview run failed validation.")
                    result_cols = st.columns(4)
                    result_cols[0].metric("Status", preview_result.status.upper())
                    result_cols[1].metric(
                        "Runtime", f"{preview_result.execution_run.runtime_seconds:.2f}s"
                    )
                    result_cols[2].metric(
                        "Peak memory",
                        f"{preview_result.execution_run.peak_memory_mb or 0:.1f} MiB",
                    )
                    result_cols[3].metric(
                        "Call rate",
                        f"{float(validation.task_metrics.get('preview_predicted_doublet_call_rate') or 0):.1%}",
                    )
                    try:
                        interpretation = preview_execution.interpret_result(
                            result=preview_result
                        )
                        _render_preview_interpretation(
                            interpretation,
                            key_prefix=f"workspace_preview_{preview_result.execution_run.run_id}",
                        )
                    except Exception as exc:
                        st.error(execution_service.redact_text(str(exc)))
                    histogram_path = preview_result.execution_run.artifact_paths.get(
                        "doublet_score_histogram.png"
                    )
                    if histogram_path and Path(histogram_path).is_file():
                        st.image(histogram_path, caption="Scrublet score distribution · Preview only")
                    for warning in validation.warnings:
                        st.caption(warning)
                    if preview_result.step_events:
                        st.markdown("#### 步骤记录")
                        st.dataframe(
                            [
                                {
                                    "step": item.step_id,
                                    "status": item.status,
                                    "message": item.message,
                                }
                                for item in preview_result.step_events
                            ],
                            width="stretch",
                            hide_index=True,
                        )
                    if preview_result.error_context is not None:
                        error = preview_result.error_context
                        st.error(f"{error.error_code}: {error.message}")
                        st.info(error.user_action)
                    validation_detail_surface = (
                        st.expander("高级详情：ValidationResult", expanded=False)
                        if data_preview_view
                        else st.popover("Validation details")
                    )
                    with validation_detail_surface:
                        st.json(validation.model_dump(mode="json"))
        else:
            st.caption("Choose a dataset above to begin. No data has been registered for this local user yet.")



def _render_sidebar_brand() -> None:
    logo = get_settings().logo_path
    if logo.exists():
        suffix = logo.suffix.lower()
        mime = "image/svg+xml" if suffix == ".svg" else "image/png"
        encoded = base64.b64encode(logo.read_bytes()).decode("ascii")
        logo_html = f'<span class="sidebar-logo"><img src="data:{mime};base64,{encoded}" alt="scKG Agent logo" /></span>'
        title_html = (
            '<div><div class="sidebar-brand-title">scKG Agent</div>'
            '<div class="sidebar-brand-subtitle">Evidence-governed research</div></div>'
        )
    else:
        logo_html = ""
        title_html = '<div class="sidebar-brand-title">scKG Agent</div>'
    st.markdown(
        f"""
<div class="sidebar-brand">
  {logo_html}
  {title_html}
</div>
""",
        unsafe_allow_html=True,
    )


def _render_research_shell(*, offline: bool) -> None:
    sessions = list_sessions(limit=1000)
    session = next((item for item in sessions if item["session_id"] == st.session_state.session_id), {})
    model = summary_model(st.session_state.messages, _research_input_binding())
    prepared_plan = current_workspace_plan(st.session_state, model["state"])
    if prepared_plan:
        model["plan"] = prepared_plan
        model["outputs"] = [str(item.get("artifact_type") or item.get("artifact_id") or "")
                            for item in prepared_plan.get("expected_outputs", [])]
    from agent.research_runtime import runtime_configuration_status
    runtime_status = runtime_configuration_status(st.session_state.get("user_api_config"))
    latest = next((m.get("state") for m in reversed(st.session_state.messages) if m.get("state")), {})
    last_mode = str(latest.get("runtime_mode", ""))
    runtime_label = ("Local fallback · 外部模型关闭" if offline else
        f"LLM ONLINE · {runtime_status['model']}" if last_mode in {"external_general_reasoning", "external_reasoning_with_deterministic_governance"}
        else f"{runtime_status['model']} · 已授权，等待本轮验证")
    details = information_html(model, session, runtime_label)
    with st.container():
        st.markdown('<span class="shell-toolbar-marker"></span>', unsafe_allow_html=True)
        menu = st.columns(4)
        with menu[0].popover("文档", use_container_width=True):
            st.markdown("**使用指南**")
            st.markdown("1. 通过输入框内的 **＋** 选择文件。\n2. 描述问题，或要求生成分析计划。\n3. 进入 **Stepwise** 检查数据与计划。\n4. 确认参数与审批后，执行并查看结果。")
            st.caption("ASK：咨询 · PLAN：准备计划 · RUN：提出执行请求。模式本身不代表已运行。")
        with menu[1].popover("数据", use_container_width=True):
            st.markdown("**当前任务数据**")
            binding = model["binding"]
            st.write(binding.get("original_filename") or "尚未绑定数据")
            st.caption("选择新文件请使用输入框内的 ＋。发送后，文件会归入任务，输入框附件会清空。")
            if st.button("打开数据与运行工作台", key="shell_datasets"):
                st.session_state.current_view = "execution_ui"
                st.rerun()
        with menu[2].popover("工具", use_container_width=True):
            for label, view in [("Research 对话", "chat"), ("运行与结果", "execution_ui"), ("知识图谱", "graph_explorer"), ("证据与文献", "evidence_admin")]:
                if st.button(label, key=f"shell_nav_{view}"):
                    st.session_state.current_view = view
                    st.rerun()
        with menu[3].popover("详情", use_container_width=True):
            st.markdown(details, unsafe_allow_html=True)
            title = st.text_input("会话标题", value=session.get("title") or "新对话", key=f"shell_title_{st.session_state.session_id}")
            if st.button("保存标题", key="shell_rename", disabled=not title.strip()):
                rename_session(st.session_state.session_id, title.strip())
                st.rerun()
    st.markdown('<aside class="research-info-rail" aria-label="当前任务详情">' + details + '</aside>', unsafe_allow_html=True)
    title = session.get("title") or "新对话"
    if title == "New research chat":
        title = "新对话"
    st.markdown('<div class="research-chat-layout research-conversation-header">'
                f'<h1 title="{escape(title)}">{escape(title)}</h1>{stage_html(model["mode"])}</div>', unsafe_allow_html=True)


def _reset_chat() -> None:
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": WELCOME_MESSAGE,
        }
    ]
    st.session_state.pop("latest_state", None)


def _load_session_messages(session_id: str) -> None:
    from execution.research_input_binding import switch_conversation
    switch_conversation(st.session_state, session_id)
    stored = load_conversation(session_id, limit=80)
    messages = [
        {
            "role": item["role"],
            "content": item["content"],
            "state": item.get("metadata", {}).get("state"),
            "runtime": item.get("metadata", {}).get("runtime"),
            "followups": item.get("metadata", {}).get("followups", []),
            "source_query": item.get("metadata", {}).get("source_query", ""),
        }
        for item in stored
    ]
    if not messages:
        messages = [{"role": "assistant", "content": WELCOME_MESSAGE}]
    st.session_state.messages = messages


def _ensure_session_state() -> None:
    init_store()
    if "session_id" not in st.session_state:
        sessions = list_sessions(limit=1)
        st.session_state.session_id = sessions[0]["session_id"] if sessions else create_session()
    if "messages" not in st.session_state:
        _load_session_messages(st.session_state.session_id)
    if "current_view" not in st.session_state:
        st.session_state.current_view = "chat"


_ensure_session_state()
from execution.research_input_binding import switch_conversation
switch_conversation(st.session_state, st.session_state.session_id)


def _switch_to_valid_session() -> None:
    sessions = list_sessions(limit=1)
    st.session_state.session_id = sessions[0]["session_id"] if sessions else create_session()
    _load_session_messages(st.session_state.session_id)


with st.sidebar:
    if st.session_state.current_view not in {"home", "chat"}:
        _render_sidebar_brand()

    if st.session_state.current_view in {"home", "chat"}:
        with st.container():
            st.markdown('<span class="new-conversation-marker"></span>', unsafe_allow_html=True)
            new_chat_clicked = st.button("＋ 新建对话", width="stretch", type="primary")
        if new_chat_clicked:
            st.session_state.session_id = create_session()
            _load_session_messages(st.session_state.session_id)
            st.session_state.current_view = "chat"
            st.rerun()

        from observability.dashboard.research_shell import conversation_group
        search = st.text_input("搜索对话", placeholder="搜索对话…", label_visibility="collapsed", key="conversation_search")
        sessions = list_sessions(limit=100)
        sessions = [item for item in sessions if search.casefold() in str(item.get("title") or "").casefold()]
        previous_group = None
        if sessions:
            for session_index, item in enumerate(sessions[:30], start=1):
                group = conversation_group(item)
                if group != previous_group:
                    st.markdown(f'<div class="sidebar-section">{group}</div>', unsafe_allow_html=True)
                    previous_group = group
                is_current = item["session_id"] == st.session_state.session_id
                title = format_conversation_title(
                    "新对话" if item.get("title") == "New research chat" else item.get("title"), item["session_id"],
                    limit=max(34, len(str(item.get("title") or ""))),
                )
                row_cols = st.columns([5, 1], gap="small", vertical_alignment="center")
                with row_cols[0]:
                    if st.button(
                        "◯  " + title,
                        help=datetime.fromtimestamp(item["updated_at"]).astimezone().strftime("%Y-%m-%d %H:%M"),
                        key=f"session_{item['session_id']}",
                        width="stretch",
                        type="primary" if is_current else "tertiary",
                    ):
                        if item["session_id"] != st.session_state.session_id:
                            st.session_state.session_id = item["session_id"]
                            _load_session_messages(item["session_id"])
                        st.session_state.current_view = "chat"
                        st.rerun()
                with row_cols[1]:
                    with st.popover(
                        f"More actions for chat {session_index}: {title}",
                        type="tertiary",
                        width="content",
                    ):
                        st.markdown("**完整对话标题**")
                        st.write(title)
                        if st.button(
                            "Pin chat" if not item.get("pinned") else "Unpin chat",
                            key=f"pin_{item['session_id']}",
                            width="stretch",
                            type="tertiary",
                        ):
                            set_session_pinned(item["session_id"], not bool(item.get("pinned")))
                            st.rerun()
                        rename_value = st.text_input(
                            "Rename conversation",
                            value=title,
                            key=f"rename_title_{item['session_id']}",
                        )
                        if st.button(
                            "Save name",
                            key=f"rename_save_{item['session_id']}",
                            width="stretch",
                            disabled=not rename_value.strip() or rename_value.strip() == title,
                        ):
                            rename_session(item["session_id"], rename_value.strip())
                            st.rerun()
                        st.divider()
                        delete_confirmed = st.checkbox(
                            "Confirm deletion",
                            key=f"delete_check_{item['session_id']}",
                        )
                        if st.button(
                            "Delete conversation",
                            key=f"delete_{item['session_id']}",
                            width="stretch",
                            disabled=not delete_confirmed,
                        ):
                            deleting_current = item["session_id"] == st.session_state.session_id
                            delete_session(item["session_id"])
                            if deleting_current:
                                _switch_to_valid_session()
                            st.session_state.current_view = "chat"
                            st.rerun()
        else:
            st.markdown('<div class="chat-list-note">没有匹配的会话。</div>', unsafe_allow_html=True)

        if st.button("清空当前会话", width="stretch"):
            clear_conversation(st.session_state.session_id)
            _load_session_messages(st.session_state.session_id)
            st.session_state.current_view = "chat"
            st.rerun()

    if st.session_state.current_view in {"home", "chat"}:
        st.markdown('<div class="sidebar-section">示例提问 · 点击发送</div>', unsafe_allow_html=True)
        for idx, question in enumerate([
            "如何分析 PBMC3k 数据？",
            "比较不同的细胞注释工具",
            "单细胞与空间转录组整合",
        ]):
            if st.button("◯  " + question, key=f"shell_example_{idx}", width="stretch"):
                st.session_state.pending_query = question
                st.rerun()

    with st.expander("工作台与管理", expanded=False):
        nav_groups = [
            (
                "工作台",
                [
                    ("Research Workspace", "chat"),
                    ("Runs & Results", "execution_ui"),
                    ("Graph Explorer", "graph_explorer"),
                ],
            ),
        ]
        for section_label, section_items in nav_groups:
            st.markdown(
                f'<div class="sidebar-section">{escape(section_label)}</div>',
                unsafe_allow_html=True,
            )
            for label, view_name in section_items:
                is_current = st.session_state.current_view == view_name
                if st.button(
                    label,
                    key=f"nav_{view_name}",
                    width="stretch",
                    type="primary" if is_current else "tertiary",
                ):
                    st.session_state.current_view = view_name
                    st.rerun()

        with st.container():
            secondary_nav = [
                ("Legacy Agent Baseline", "agent_loop_demo"),
                ("Knowledge Review", "knowledge_review"),
                ("Defense Demo", "defense_demo"),
                ("Evidence & RAG", "evidence_admin"),
                ("Evaluation", "evaluation_admin"),
                ("Scientific KG", "scientific_kg_admin"),
                ("Runtime Packs", "runtime_packs"),
                ("Memory", "memory_admin"),
                ("Architecture", "architecture_admin"),
            ]
            for label, view_name in secondary_nav:
                if st.button(
                    label,
                    key=f"nav_{view_name}",
                    width="stretch",
                    type="primary" if st.session_state.current_view == view_name else "tertiary",
                ):
                    st.session_state.current_view = view_name
                    st.rerun()


    st.divider()
    with st.expander("Settings", expanded=False):
        saved_config = has_saved_api_config()
        if saved_config:
            _render_chip("saved API config", "good")
        if st.session_state.get("user_api_config"):
            _render_chip("API key unlocked", "good")
        elif saved_config:
            _render_chip("API config saved but locked", "warn")

        with st.container():
            st.markdown("**User API key**")
            st.caption(
                "API key 保存后不会再次显示。请自行设置一个本地加密口令；完整刷新页面后，"
                "只需重新输入该口令并点击“解锁已保存配置”，不需要再次粘贴 API key。"
            )
            settings = get_settings()
            api_base = st.text_input("API base", value=settings.chat_api_base)
            model_name = st.text_input(
                "Model name",
                value=str(settings.model_name or settings.extract_model),
            )
            api_key = st.text_input(
                "API key",
                type="password",
                placeholder="Only needed when saving or replacing the key",
            )
            passphrase = st.text_input(
                "本地加密口令（由你自己设置）",
                type="password",
                placeholder="建议至少 8 位；它不是 API key，也不是 DeepSeek 密码",
                help=(
                    "该口令只用于在本机加密和解锁 API key，系统不会保存口令本身。"
                    "请自行记住；忘记后需要用 API key 重新保存配置。"
                ),
            )
            save_cols = st.columns(2)
            if save_cols[0].button(
                "加密保存并解锁",
                width="stretch",
                disabled=not api_key or not passphrase,
            ):
                try:
                    save_encrypted_api_config(
                        "openai_compatible",
                        api_base,
                        model_name,
                        api_key,
                        passphrase,
                    )
                    st.session_state.user_api_config = {
                        "provider": "openai_compatible",
                        "api_base": api_base,
                        "model_name": model_name,
                        "api_key": api_key,
                    }
                    st.success("API config saved encrypted and unlocked for this session.")
                    st.info(
                        "还需在下方显式勾选“本会话启用 DeepSeek”，之后普通问答才会真正调用外部模型。"
                    )
                except Exception as exc:
                    st.error(f"Could not save config: {exc}")
            if save_cols[1].button(
                "解锁已保存配置",
                width="stretch",
                disabled=not saved_config or not passphrase,
            ):
                try:
                    st.session_state.user_api_config = load_api_config(passphrase)
                    st.success("API config unlocked for this session.")
                except ApiConfigError as exc:
                    st.error(str(exc))

        privacy_mode = st.selectbox(
            "Privacy mode",
            options=[
                PrivacyMode.STRICT_OFFLINE.value,
                PrivacyMode.LOCAL_HYBRID.value,
                PrivacyMode.CLOUD_ASSISTED.value,
            ],
            index=1,
            format_func=lambda value: {
                PrivacyMode.STRICT_OFFLINE.value: "STRICT_OFFLINE",
                PrivacyMode.LOCAL_HYBRID.value: "LOCAL_HYBRID (default)",
                PrivacyMode.CLOUD_ASSISTED.value: "CLOUD_ASSISTED",
            }[value],
            help="矩阵、barcode、完整路径和上传文件不会外发。STRICT_OFFLINE 禁止全部外部模型调用。",
        )
        offline_llm = privacy_mode == PrivacyMode.STRICT_OFFLINE.value or settings.offline_llm
        env_llm_configured = bool(
            (settings.deepseek_api_key or settings.openai_api_key)
            and (settings.model_name or settings.extract_model)
        )
        from agent.research_runtime import startup_chat_consent
        run_live = st.checkbox(
            "本会话启用 DeepSeek（发送脱敏后的问题与受控上下文）",
            value=startup_chat_consent(),
            key="research_external_reasoning_consent",
            disabled=(
                offline_llm
                or not (
                    bool(st.session_state.get("user_api_config"))
                    or env_llm_configured
                )
            ),
            help="一次授权后本会话持续生效。每次请求仍生成 disclosure hash；矩阵、barcode、完整路径与上传文件不会发送。",
        )
        st.caption(
            "DeepSeek 使用条件：保存并解锁配置；Privacy mode 不是 STRICT_OFFLINE；"
            "然后勾选上面的本会话授权。保存 key 本身不等于允许外发。"
        )
        if saved_config and not st.session_state.get("user_api_config"):
            st.warning("配置已保存但当前页面尚未解锁：输入本地加密口令并点击“解锁已保存配置”。")
        elif st.session_state.get("user_api_config") and not run_live and not offline_llm:
            st.warning("配置已解锁，但 DeepSeek 尚未启用；普通问题仍不会调用 LLM。")
        if privacy_mode == PrivacyMode.LOCAL_HYBRID.value:
            st.caption(
                "KG、检索、Profiler、Router、合同和验证保持本地；启用后 DeepSeek 只处理脱敏问题与 governed context。"
            )
        show_sources = st.checkbox("Show retrieval diagnostics", value=False)
        attach_workflow_card = st.checkbox(
            "Attach workflow decision card",
            value=False,
            help="只在明确请求 workflow 时附加高级 plan-only 决策卡。",
        )
        debug_visible = st.checkbox("Show raw debug state", value=False)

    if st.session_state.current_view in {"home", "chat"}:
        with st.expander("连接与运行状态", expanded=False):
            _render_context_status(offline_llm=offline_llm, run_live=run_live)

    if st.session_state.current_view in {"home", "chat"}:
        memory_surface = st.expander("Project memory", expanded=False)
    else:
        memory_surface = None

    if memory_surface is not None:
      with memory_surface:
        memory = load_project_memory()
        species = st.text_input("Common species", value=str(memory.get("species", "")))
        platform = st.text_input("Common platform", value=str(memory.get("platform", "")))
        strictness = st.selectbox(
            "Recommendation style",
            ["conservative", "balanced", "exploratory"],
            index=["conservative", "balanced", "exploratory"].index(
                str(memory.get("strictness", "conservative"))
                if str(memory.get("strictness", "conservative")) in {"conservative", "balanced", "exploratory"}
                else "conservative"
            ),
        )
        if st.button("Save memory", width="stretch"):
            if species:
                save_project_memory("species", species, "user")
            if platform:
                save_project_memory("platform", platform, "user")
            save_project_memory("strictness", strictness, "user")
            st.success("Project memory saved.")

        selected_example = st.selectbox("Example query", ["Custom", *EXAMPLES.keys()])
        if selected_example != "Custom" and st.button("Use example", width="stretch"):
            st.session_state.pending_query = EXAMPLES[selected_example]
            st.session_state.current_view = "chat"
            st.rerun()


if st.session_state.current_view in {"home", "chat", "data_preview"}:
    data_preview_view = st.session_state.current_view == "data_preview"
    pending_workspace_artifact = st.session_state.pop(
        "workspace_pending_selected_artifact", None
    )
    if pending_workspace_artifact:
        st.session_state.workspace_artifact_id = pending_workspace_artifact
        st.session_state.workspace_selected_artifact = pending_workspace_artifact
    workspace_title = "Stepwise Analysis" if data_preview_view else "Research Workspace"
    workspace_subtitle = (
        "承接 Research Chat 已确认的任务，逐步检查数据、参数、代码、审批、运行与结果；Notebook 是同一受控步骤的可复现影子。"
        if data_preview_view
        else "直接描述科研问题。系统会逐条识别问答、工作流或运行意图；执行仍由授权、合同和验证后端控制。"
    )
    if data_preview_view:
        st.markdown(
            f"""
    <div class="{'chat-app-header' if data_preview_view else 'research-chat-layout chat-app-header'}">
      <div class="chat-app-kicker">scKG governed Parent Agent</div>
      <div class="chat-app-title">{workspace_title}</div>
      <div class="chat-app-subtitle">{workspace_subtitle}</div>
    </div>
    """,
            unsafe_allow_html=True,
        )
    else:
        _render_research_shell(offline=offline_llm or not run_live)

    agent_mode = None
    run_artifact_id = None
    run_requested_tool = None
    if not data_preview_view:
        st.markdown(
            '<div class="research-routing"><strong>AUTO · 自动识别意图</strong>'
            '逐条识别当前问题；数据授权与执行审批仍需单独确认。</div>',
            unsafe_allow_html=True,
        )
        from execution.execution_ui_service import configured_local_user_id
        from execution.research_input_binding import authorize_uploaded_binding
        local_user_id = configured_local_user_id()
    else:
        task_handoff = st.session_state.get("workspace_task_handoff")
        if task_handoff:
            st.markdown(
                f"""
<div class="data-workbench-boundary">
<strong>来自当前 Research Chat</strong><br>
任务：<code>{escape(str(task_handoff.get('task_family') or 'unknown'))}</code> ·
工具：<code>{escape(str(task_handoff.get('tool_name') or 'unknown'))}</code> ·
来源问题：{escape(str(task_handoff.get('source_query') or ''))}
</div>
""",
                unsafe_allow_html=True,
            )
            task_action_cols = st.columns([1, 3])
            if task_action_cols[0].button(
                "返回对话",
                key="workspace_return_to_chat",
                width="stretch",
            ):
                st.session_state.current_view = "chat"
                st.rerun()
            task_action_cols[1].caption(
                "本页只执行该对话确定的任务；更换任务或算法请回到 Research Chat。"
            )
        else:
            st.warning(
                "当前没有来自对话的分析任务。下面仅是 Scrublet Preview 演示，不代表 Agent 已根据你的问题选择了算法。"
            )
            if st.button(
                "使用 Scrublet 演示任务",
                key="workspace_use_demo_handoff",
            ):
                st.session_state.workspace_task_handoff = {
                    "handoff_id": f"demo-{uuid.uuid4().hex}",
                    "conversation_id": st.session_state.session_id,
                    "source_query": "本地 Scrublet Preview 演示",
                    "task_family": "doublet_detection",
                    "tool_name": "Scrublet",
                    "agent_mode": "PLAN",
                    "plan_id": None,
                    "notebook_strategy": "fixed_shadow",
                    "stepwise_preview_available": True,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                st.rerun()
        st.markdown(
            """
<div class="data-workbench-intro">
  <div class="data-workbench-step"><span>步骤 1</span><strong>承接任务与数据</strong></div>
  <div class="data-workbench-step"><span>步骤 2</span><strong>检查数据画像</strong></div>
  <div class="data-workbench-step"><span>步骤 3</span><strong>准备 Preview</strong></div>
  <div class="data-workbench-step"><span>步骤 4</span><strong>审批、运行与验证</strong></div>
</div>
<div class="data-workbench-boundary">
这里承接对话中已经确认的分析任务。先用只读小样本检查数据、代码和环境，再由你决定是否在本机逐步运行；源文件不会被修改。
</div>
""",
            unsafe_allow_html=True,
        )

    capability_stepwise_handoff = st.session_state.get("workspace_task_handoff") or {}
    if (
        data_preview_view
        and capability_stepwise_handoff.get("notebook_strategy")
        == "capability_renderer"
    ):
        _render_capability_stepwise_workspace(capability_stepwise_handoff)
        st.stop()

    if data_preview_view and not capability_stepwise_handoff:
        st.info("请从当前对话的 Research 任务进入 Stepwise；不会继承另一对话的数据或计划。")
        _render_research_input()
        st.stop()

    if data_preview_view:
        _render_legacy_preview_workbench(data_preview_view=True)

    if data_preview_view:
        st.stop()

    for message_index, message in enumerate(st.session_state.messages):
        if message.get("role") == "user":
            _render_user_message(message.get("content", ""))
            continue
        if message.get("content") == WELCOME_MESSAGE and not message.get("state"):
            st.markdown('<div class="research-welcome"><div class="welcome-symbol">✧</div>'
                        '<h2>从一个科研问题开始</h2><p>探索方法、准备分析计划，让每一步都有据可循。</p></div>', unsafe_allow_html=True)
            continue
        with st.chat_message("assistant", avatar="🔬"):
            title_id = ' id="research-latest-reply"' if message_index == len(st.session_state.messages) - 1 else ''
            st.markdown(f'<div{title_id}><strong>scKG-Agent</strong></div>', unsafe_allow_html=True)
            if isinstance(message.get("state"), dict):
                render_reply_overview(message["state"])
            _render_assistant_report(message.get("content", ""))
            if message.get("state") and isinstance(message.get("state"), dict):
                if "WorkflowPlan" not in message.get("content", ""):
                    display_state = dict(message["state"])
                    prepared_plan = current_workspace_plan(st.session_state, display_state)
                    if prepared_plan:
                        display_state["workflow_plan"] = prepared_plan
                    render_plan_overview(display_state)
                _render_response_runtime(message["state"])
                _render_algorithm_surface(message["state"])
                _render_execution_handoff(
                    message["state"],
                    key=f"history_handoff_{st.session_state.session_id}_{message_index}",
                )
                _render_workspace_handoff(
                    message["state"],
                    source_query=str(message.get("source_query") or ""),
                    key=f"history_workspace_{st.session_state.session_id}_{message_index}",
                )
                _render_response_details(message["state"])
            if (
                show_sources
                and message.get("state")
                and isinstance(message.get("state"), dict)
            ):
                _render_sources_and_caveats(
                    message["state"],
                    runtime=message.get("runtime"),
                    show_debug=debug_visible,
                )
            if (
                attach_workflow_card
                and message.get("state")
                and isinstance(message.get("state"), dict)
                and message["state"].get("workflow_decision")
            ):
                _render_workflow_decision_card(message["state"]["workflow_decision"])
            if message.get("followups"):
                message_key = f"history_{st.session_state.session_id}_{message_index}"
                _render_followups(
                    message["followups"],
                    key_prefix=message_key,
                    source_query=message.get("source_query", ""),
                )
            if message_index == len(st.session_state.messages) - 1 and message.get("state"):
                st.download_button(
                    "Download report", data=message.get("content", ""),
                    file_name="scKG_Agent_Report.md", mime="text/markdown",
                    key=f"history_report_{st.session_state.session_id}_{message_index}",
                )

    default_query = st.session_state.pop("pending_query", "")
    default_display_query = st.session_state.pop("pending_display_query", "")
    # Reserve the reply position before the composer, including the live turn.
    live_response = st.container()
    # Keep Streamlit's native input/uploader events, inside one visual composer.
    with st.container(border=True):
        st.markdown('<span class="research-composer-marker"></span>', unsafe_allow_html=True)
        attachment_preview = st.empty()
        attachment_col, composer_col = st.columns([1, 14])
        # Render the text widget before uploader-triggered reruns so Streamlit
        # keeps the mounted input (and the user's unsent draft) during upload.
        with composer_col:
            submission = st.chat_input(
                "描述科研问题或下一步需求…",
                height=68,
                disabled=bool(st.session_state.get("workspace_input_pending")),
            )
        with attachment_col:
            _render_research_input()
        with attachment_preview.container():
            _render_bound_input_card()
        st.markdown('<div class="composer-hint">＋ 添加文件 · Enter 发送 · Shift + Enter 换行</div>', unsafe_allow_html=True)
    if st.session_state.pop("research_scroll_latest", False):
        # The native input is nested to keep attachments together. Restore chat
        # scrolling after a completed turn without moving the fixed composer.
        components.html("""<script>
        const showReply = () => window.parent.document
          .getElementById('research-latest-reply')?.scrollIntoView({block:'start'});
        requestAnimationFrame(() => requestAnimationFrame(showReply));
        </script>""", height=0)
    query, submitted_files = _chat_input_parts(submission)
    if default_query and not query and not submitted_files:
        query = default_query

    with live_response:
        if query or submitted_files:
            request_conversation_id = st.session_state.session_id
            request_draft = dict(_research_composer_draft())
            request_input_binding = dict(request_draft.get("input_binding") or _research_input_binding())
            request_uploaded_context = dict(
                (request_draft.get("uploaded_context") if request_draft
                 else load_working_context(st.session_state.session_id).get("uploaded_context")) or {}
            )
            if request_input_binding:
                try:
                    authorize_uploaded_binding(_execution_ui_backend().data_registry, request_input_binding, user_id=local_user_id)
                    run_artifact_id = request_input_binding["artifact_id"]
                except Exception as exc:
                    st.warning("之前绑定的数据暂时无法访问，普通问答仍可继续；涉及该数据时需要重新选择文件。")
                    run_artifact_id = None
            request_binding_stale = bool(request_input_binding and not run_artifact_id)
            if request_draft.get("input_binding"):
                _bind_research_input(request_input_binding)
            _clear_research_attachments()
            attachment_preview.empty()
            request_ui_token = uuid.uuid4().hex
            st.session_state.workspace_research_request_token = request_ui_token
            from execution.research_input_binding import invalidate_delivery
            invalidate_delivery(st.session_state)
            _reset_workspace_from_stage("source")
            st.session_state.pop("workspace_task_handoff", None)
            upload_context = _summarize_uploaded_files(submitted_files)
            if upload_context:
                request_uploaded_context = upload_context
            # Saved task context supports follow-ups; only the composer draft is cleared.
            save_working_context(st.session_state.session_id, "uploaded_context", request_uploaded_context)

            display_query = default_display_query or _format_user_display_query(query, submitted_files)
            if submitted_files and not query:
                query = "请先读取我上传的文件上下文，概括字段/内容，并说明这些内容能怎样辅助后续推荐。"
            attachment_names = list(request_draft.get("attachment_names") or [])
            if request_draft.get("input_binding"):
                name = request_input_binding.get("original_filename", "sample.h5ad")
                if name not in attachment_names:
                    attachment_names.insert(0, name)
            if attachment_names:
                display_query += "\n\n附件：" + "、".join(attachment_names)
            st.session_state.messages.append({"role": "user", "content": display_query})
            save_message(
                st.session_state.session_id,
                "user",
                display_query,
                metadata={"actual_query": query} if display_query != query else {},
            )
            _render_user_message(display_query)

            with st.chat_message("assistant"):
                project_memory = load_project_memory()
                uploaded_context = request_uploaded_context

                if _is_time_query(query):
                    report = _time_reply()
                    followups = [
                        "我想做一个单细胞分析任务，你需要哪些信息？",
                        "帮我解释一下这个系统的证据边界。",
                        "打开图谱后我应该怎么看工具和证据关系？",
                    ]
                    state = None
                    elapsed = 0.0
                    _render_assistant_report(report)
                    live_key = f"live_{st.session_state.session_id}_{int(time.time() * 1000)}"
                    _render_followups(followups, key_prefix=live_key, source_query=query)
                elif _is_greeting_query(query) and (not run_live or offline_llm):
                    report = _greeting_reply(project_memory)
                    followups = _greeting_followups()
                    state = None
                    elapsed = 0.0
                    _render_assistant_report(report)
                    live_key = f"live_{st.session_state.session_id}_{int(time.time() * 1000)}"
                    _render_followups(followups, key_prefix=live_key, source_query=query)
                elif submitted_files and query.startswith("请先读取我上传的文件上下文"):
                    report = _upload_preview_text(upload_context) or "我没有读到可解析的上传文件。"
                    followups = [
                        "基于这个文件，我需要补充哪些字段才能做工具推荐？",
                        "请根据上传表格判断更像哪类单细胞分析任务。",
                        "这些文件内容能不能作为 evidence？",
                    ]
                    state = None
                    elapsed = 0.0
                    _render_assistant_report(report)
                    live_key = f"live_{st.session_state.session_id}_{int(time.time() * 1000)}"
                    _render_followups(followups, key_prefix=live_key, source_query=query)
                else:
                    started = time.perf_counter()
                    with st.status("Running evidence-governed analysis", expanded=False) as status:
                        try:
                            runtime_config = dict(
                                st.session_state.get("user_api_config") or {}
                            )
                            if request_binding_stale:
                                runtime_config["input_binding_status"] = "stale"
                            live_query = query
                            live_conversation = _conversation_context(
                                st.session_state.messages[:-1]
                            )
                            live_memory = project_memory
                            live_uploads = uploaded_context
                            if run_live and not offline_llm:
                                disclosure_service = _outbound_disclosure_backend()
                                sanitized = disclosure_service.prepare(
                                    {
                                        "query": query,
                                        "conversation_context": live_conversation,
                                        "project_memory": project_memory,
                                        "uploaded_context": uploaded_context,
                                    },
                                    purpose="research_chat_reasoning",
                                    provider=str(
                                        runtime_config.get("api_base")
                                        or get_settings().chat_api_base
                                    ),
                                )
                                consent = disclosure_service.grant(
                                    disclosure_hash=sanitized.disclosure.disclosure_hash,
                                    session_id=st.session_state.session_id,
                                    scope="session",
                                )
                                authorization = disclosure_service.authorize(
                                    mode=PrivacyMode(privacy_mode),
                                    disclosure_hash=sanitized.disclosure.disclosure_hash,
                                    session_id=st.session_state.session_id,
                                    consent_id=consent.consent_id,
                                )
                                if not authorization.allowed:
                                    raise PermissionError(
                                        ";".join(authorization.reasons)
                                    )
                                live_query = str(sanitized.payload.get("query", ""))
                                live_conversation = list(
                                    sanitized.payload.get("conversation_context", [])
                                )
                                live_memory = dict(
                                    sanitized.payload.get("project_memory", {})
                                )
                                live_uploads = {}
                                runtime_config.update(
                                    {
                                        "privacy_authorized": True,
                                        "outbound_authorized": True,
                                        "privacy_mode": privacy_mode,
                                        "disclosure_hash": sanitized.disclosure.disclosure_hash,
                                    }
                                )
                            state = _run_agent(
                                live_query,
                                offline_llm=(offline_llm or not run_live),
                                agent_mode=agent_mode,
                                user_id=(
                                    local_user_id
                                    if run_artifact_id
                                    else "local-research-user"
                                ),
                                conversation_id=st.session_state.session_id,
                                artifact_id=run_artifact_id,
                                requested_tool=run_requested_tool,
                                conversation_context=live_conversation,
                                project_memory=live_memory,
                                uploaded_context=live_uploads,
                                user_runtime_config=runtime_config,
                            )
                            if (st.session_state.session_id != request_conversation_id
                                or _research_input_binding() != request_input_binding
                                or st.session_state.get("workspace_research_request_token") != request_ui_token):
                                st.warning("请求期间数据或对话已改变；旧响应未发布到当前上下文。")
                                st.stop()
                            state["ui_input_binding"] = request_input_binding
                            if (
                                attach_workflow_card
                                and state.get("response_intent") == "workflow"
                            ):
                                state["workflow_decision"] = _attach_workflow_decision(
                                    query=query,
                                    state=state,
                                    project_memory=project_memory,
                                )
                            status.update(label="本轮答复已生成", state="complete")
                        except Exception as exc:
                            state = {
                                "final_report": f"Execution failed: {exc}",
                                "error_message": str(exc),
                                "hallucination_audit": {},
                                "context_pack": {},
                            }
                            status.update(label="Analysis failed", state="error")

                    elapsed = time.perf_counter() - started
                    report = _clean_report(state.get("final_report", "") or "No report was generated.")
                    followups = _suggest_followups(state, query)
                    save_working_context(
                        st.session_state.session_id,
                        "last_constraints",
                        _constraints(state),
                    )
                    save_working_context(
                        st.session_state.session_id,
                        "last_recommended_tools",
                        [tool.get("tool_name") for tool in _ranked_tools(state)],
                    )
                    _render_assistant_report(report)
                    _render_response_runtime(state)
                    _render_algorithm_surface(state)
                    _render_execution_handoff(
                        state,
                        key=f"live_handoff_{st.session_state.session_id}_{int(time.time() * 1000)}",
                    )
                    _render_workspace_handoff(
                        state,
                        source_query=query,
                        key=f"live_workspace_{st.session_state.session_id}_{int(time.time() * 1000)}",
                    )
                    _render_response_details(state)
                    if show_sources:
                        _render_sources_and_caveats(state, runtime=elapsed, show_debug=debug_visible)
                    if attach_workflow_card and state.get("workflow_decision"):
                        _render_workflow_decision_card(state["workflow_decision"])
                    live_key = f"live_{st.session_state.session_id}_{int(time.time() * 1000)}"
                    _render_followups(followups, key_prefix=live_key, source_query=query)

                    st.download_button(
                        "Download report",
                        data=report,
                        file_name="scKG_Agent_Report.md",
                        mime="text/markdown",
                        width="content",
                    )

            st.session_state.latest_state = state
            assistant_message = {
                "role": "assistant",
                "content": report,
                "state": state,
                "runtime": elapsed,
                "followups": followups,
                "source_query": query,
            }
            st.session_state.messages.append(assistant_message)
            save_message(
                st.session_state.session_id,
                "assistant",
                report,
                metadata={
                    "state": state,
                    "runtime": elapsed,
                    "followups": followups,
                    "source_query": query,
                },
            )
            st.session_state.research_scroll_latest = True
            st.rerun()

elif st.session_state.current_view == "graph_explorer":
    _render_graph_explorer_page()
elif st.session_state.current_view == "knowledge_review":
    _render_knowledge_review_panel()
elif st.session_state.current_view == "execution_ui":
    _render_restricted_execution_page()
elif st.session_state.current_view == "runtime_packs":
    _render_runtime_packs_page()
elif st.session_state.current_view == "defense_demo":
    _render_defense_demo_page()
elif st.session_state.current_view == "agent_loop_demo":
    _render_agent_loop_demo_page()
elif st.session_state.current_view == "evidence_admin":
    _render_evidence_admin_panel()
elif st.session_state.current_view == "evaluation_admin":
    _render_evaluation_admin_panel()
elif st.session_state.current_view == "scientific_kg_admin":
    _render_scientific_kg_admin_page()
elif st.session_state.current_view == "memory_admin":
    _render_memory_admin_panel()
elif st.session_state.current_view == "architecture_admin":
    _render_architecture_admin_panel()
