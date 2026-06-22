import csv
import base64
import io
import json
import os
import re
import time
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any, Dict, List, Optional

import streamlit as st
import streamlit.components.v1 as components

from agent.workflow import build_sckg_graph
from core.settings import get_settings
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
    build_knowledge_graph_html,
    build_knowledge_graph_view,
)


st.set_page_config(
    page_title="scKG-Atlas Agent",
    layout="centered",
    initial_sidebar_state="expanded",
)

if "current_view" not in st.session_state:
    st.session_state.current_view = "chat"


st.markdown(
    """
<style>
    :root {
        color-scheme: light;
    }
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    [data-testid="stHeader"] {
        visibility: hidden !important;
        background: transparent !important;
        border: 0 !important;
        box-shadow: none !important;
    }
    [data-testid="stDecoration"] {
        display: none !important;
        height: 0 !important;
        min-height: 0 !important;
        max-height: 0 !important;
        overflow: hidden !important;
    }
    [data-testid="stToolbar"] {
        display: flex !important;
        visibility: visible !important;
        opacity: 1 !important;
    }
    [data-testid="stSidebarCollapseButton"],
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
    .block-container {
        max-width: 940px;
        padding-top: 0.9rem;
        padding-bottom: 7rem;
    }
    h1, h2, h3, p, li {
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
    .chat-app-header {
        max-width: 820px;
        margin: 0.35rem auto 1.7rem auto;
        padding: 0.2rem 0;
    }
    .chat-app-kicker {
        color: #cc785c;
        font-size: 0.76rem;
        font-weight: 650;
        letter-spacing: 0;
        margin-bottom: 0.25rem;
    }
    .chat-app-title {
        color: #141413;
        font-size: clamp(1.35rem, 1.8vw, 1.82rem);
        font-weight: 620;
        line-height: 1.2;
        letter-spacing: 0;
        margin: 0;
    }
    .chat-app-subtitle {
        color: #6c6a64;
        font-size: 0.94rem;
        line-height: 1.55;
        margin-top: 0.44rem;
        max-width: 640px;
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
    .quiet-note {
        color: #6b7280;
        font-size: 0.9rem;
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
    .user-chat-row {
        display: flex;
        justify-content: flex-end;
        width: 100%;
        margin: 0.65rem 0 0.85rem 0;
    }
    .user-chat-bubble {
        max-width: min(72%, 620px);
        background: #252523;
        color: #faf9f5;
        border-radius: 16px 16px 4px 16px;
        padding: 0.72rem 0.9rem;
        line-height: 1.55;
        font-size: 0.96rem;
        box-shadow: 0 1px 2px rgba(20, 20, 19, 0.08);
        overflow-wrap: anywhere;
        white-space: pre-wrap;
    }
    .user-chat-attachments {
        color: #e8e0d2;
        font-size: 0.84rem;
        margin-top: 0.42rem;
        border-top: 1px solid rgba(250, 249, 245, 0.18);
        padding-top: 0.42rem;
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
    .sidebar-brand {
        text-align: center;
        margin: 0.2rem 0 0.95rem;
    }
    .sidebar-brand img {
        display: block;
        width: min(132px, 76%);
        max-height: 92px;
        object-fit: contain;
        height: auto;
        margin: 0 auto;
        border-radius: 8px;
    }
    .sidebar-brand-title {
        font-size: 0.92rem;
        font-weight: 650;
        line-height: 1.2;
        color: #252523;
        margin: 0;
    }
    [data-testid="stBottom"],
    [data-testid="stBottom"] > div,
    [data-testid="stBottomBlockContainer"] {
        background: #f8f9fa !important;
        padding-top: 0.25rem !important;
    }
    [data-testid="stBottomBlockContainer"] > div {
        background: transparent !important;
    }
    [data-testid="stChatInput"] {
        max-width: 820px !important;
        margin: 0 auto 0.78rem auto !important;
        background: transparent !important;
        border: 0 !important;
        padding-left: 0.75rem !important;
        padding-right: 0.75rem !important;
    }
    [data-testid="stChatInput"] > div {
        min-height: 72px !important;
        background: #ffffff !important;
        border: 1px solid #d3cec6 !important;
        border-radius: 16px !important;
        box-shadow: 0 8px 28px rgba(20, 20, 19, 0.06) !important;
        overflow: visible !important;
    }
    [data-testid="stChatInput"] textarea {
        min-height: 52px !important;
        line-height: 1.45 !important;
        background: #ffffff !important;
        color: #252523 !important;
    }
    [data-testid="stChatInput"] textarea,
    [data-testid="stChatInput"] textarea:focus,
    [data-testid="stChatInput"] div,
    [data-testid="stChatInput"] [contenteditable="true"] {
        background-color: #ffffff !important;
    }
    [data-testid="stChatInput"] [data-baseweb="textarea"],
    [data-testid="stChatInput"] [data-baseweb="base-input"],
    [data-testid="stChatInput"] [data-baseweb="input"] {
        background: #ffffff !important;
    }
    [data-testid="stChatInput"] button {
        border-radius: 10px !important;
    }
    section[data-testid="stSidebar"] {
        background: #f5f1ec;
        border-right: 1px solid #e3ded7;
    }
    div[data-testid="stSidebar"] .block-container {
        padding: 0.8rem 0.72rem 1.1rem;
    }
    .sidebar-section {
        color: #7b7b78;
        font-size: 0.68rem;
        font-weight: 600;
        margin: 0.75rem 0 0.22rem;
        text-transform: uppercase;
    }
    div[data-testid="stSidebar"] div[data-testid="stButton"] button {
        width: 100% !important;
        min-height: 2rem !important;
        height: auto !important;
        border-radius: 8px !important;
        padding: 0.34rem 0.5rem !important;
        margin: 0.03rem 0 !important;
        font-size: 0.84rem !important;
        line-height: 1.22 !important;
        text-align: left !important;
        justify-content: flex-start !important;
        border: 1px solid transparent !important;
        background: transparent !important;
        color: #313130 !important;
        box-shadow: none !important;
    }
    div[data-testid="stSidebar"] div[data-testid="stButton"] button:hover {
        background: #ebe7e1 !important;
        color: #111111 !important;
        border-color: #e0d8ce !important;
    }
    div[data-testid="stSidebar"] div[data-testid="stButton"] button:focus {
        box-shadow: none;
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
    div[data-testid="stSidebar"] details {
        border: 0 !important;
        background: transparent !important;
        box-shadow: none !important;
    }
    div[data-testid="stSidebar"] details summary {
        padding: 0.42rem 0.4rem !important;
        border-radius: 8px !important;
        font-size: 0.86rem !important;
        color: #252523 !important;
    }
    div[data-testid="stSidebar"] details summary:hover {
        background: #ebe7e1 !important;
    }
    div[data-testid="stSidebar"] details summary *,
    div[data-testid="stSidebar"] details summary svg {
        color: #252523 !important;
        fill: #626260 !important;
    }
    div[data-testid="stSidebar"] hr {
        margin: 0.75rem 0;
    }
    div[data-testid="stChatMessage"] {
        background: transparent;
        padding: 0.32rem 0 !important;
    }
    div[data-testid="stChatMessageContent"] {
        line-height: 1.58;
    }
    .chat-active {
        color: #111827;
        font-weight: 650;
    }
    .chat-muted {
        color: #475569;
    }
    .followup-row div[data-testid="stButton"] button {
        border-radius: 999px;
        min-height: 2rem;
        padding: 0.2rem 0.75rem;
        font-size: 0.86rem;
    }
    .kg-panel {
        border: 1px solid #e3ded7;
        border-radius: 12px;
        background: #ffffff;
        padding: 0.9rem 0.9rem 0.4rem;
        margin: 0.3rem 0 1.2rem 0;
    }
    .sidebar-graph-card.kg-panel {
        background: linear-gradient(180deg, rgba(255, 255, 255, 0.94), rgba(245, 248, 252, 0.92)) !important;
        border-color: rgba(134, 154, 178, 0.22) !important;
        box-shadow: 0 10px 28px rgba(22, 34, 51, 0.08) !important;
        padding-bottom: 0.75rem !important;
    }
    .kg-panel h4 {
        margin: 0 0 0.2rem 0;
        font-size: 1rem;
    }
    .kg-panel .kg-subtitle {
        color: #6c6a64;
        font-size: 0.86rem;
        margin-bottom: 0.6rem;
    }
    .kg-card-glow {
        display: inline-flex;
        align-items: center;
        border-radius: 999px;
        padding: 0.18rem 0.58rem;
        margin: 0.1rem 0 0.55rem 0;
        font-size: 0.72rem;
        color: #5a6d84;
        background: rgba(230, 237, 246, 0.88);
        border: 1px solid rgba(134, 154, 178, 0.18);
    }
    .kg-chip-row {
        margin: 0.25rem 0 0.55rem 0;
    }
    .sidebar-metric-card {
        min-height: 4rem;
        display: flex;
        flex-direction: column;
        justify-content: center;
        gap: 0.15rem;
        border-radius: 12px !important;
        padding: 0.7rem 0.75rem !important;
        background: rgba(255, 255, 255, 0.78) !important;
        border: 1px solid rgba(134, 154, 178, 0.14) !important;
        box-shadow: 0 4px 16px rgba(22, 34, 51, 0.05) !important;
        margin-bottom: 0.52rem;
    }
    .sidebar-metric-card strong {
        font-size: 1.08rem;
        line-height: 1.1;
        color: #172033;
    }
    .sidebar-metric-card .source-meta {
        font-size: 0.76rem;
        color: #6b7b8f;
    }
    /* v0.14 breathing-room visual reset inspired by awesome-design-md. */
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
    [data-testid="stHeader"] {
        visibility: hidden !important;
        background: transparent !important;
        border: 0 !important;
        box-shadow: none !important;
    }
    [data-testid="stToolbar"] {
        display: flex !important;
        visibility: visible !important;
        opacity: 1 !important;
    }
    [data-testid="stDecoration"] {
        display: none !important;
    }
    .block-container {
        max-width: 980px !important;
        padding-top: 2.2rem !important;
        padding-bottom: 8.2rem !important;
    }
    h1, h2, h3, h4, p, li {
        letter-spacing: 0 !important;
    }
    p, li {
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
    .chat-app-header {
        max-width: 840px !important;
        margin: 1.1rem auto 2.25rem auto !important;
        padding: 1.1rem 0.3rem 0.4rem !important;
    }
    .chat-app-kicker {
        color: #7b8da8 !important;
        font-size: 0.76rem !important;
        font-weight: 700 !important;
        letter-spacing: 0.02em !important;
        margin-bottom: 0.55rem !important;
    }
    .chat-app-title {
        color: #172033 !important;
        font-size: clamp(1.85rem, 3vw, 2.62rem) !important;
        font-weight: 680 !important;
        line-height: 1.13 !important;
        margin-bottom: 0.82rem !important;
    }
    .chat-app-subtitle {
        max-width: 720px !important;
        color: #667085 !important;
        font-size: 1.02rem !important;
        line-height: 1.72 !important;
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
    .user-chat-bubble {
        background: linear-gradient(135deg, #293241, #202938) !important;
        color: #ffffff !important;
        border-radius: 18px 18px 6px 18px !important;
        padding: 0.82rem 1rem !important;
        box-shadow: 0 8px 28px rgba(30, 41, 59, 0.12) !important;
    }
    div[data-testid="stChatMessage"] {
        background: rgba(255, 255, 255, 0.54) !important;
        border: 1px solid rgba(0, 0, 0, 0.035) !important;
        border-radius: 18px !important;
        padding: 0.85rem 1rem !important;
        margin: 0.85rem auto !important;
        box-shadow: 0 4px 24px rgba(0, 0, 0, 0.026) !important;
    }
    div[data-testid="stChatMessageAvatar"] {
        filter: saturate(0.82);
    }
    section[data-testid="stSidebar"] {
        background: rgba(247, 249, 252, 0.86) !important;
        border-right: 1px solid rgba(0, 0, 0, 0.04) !important;
        box-shadow: 8px 0 28px rgba(0, 0, 0, 0.025);
    }
    div[data-testid="stSidebar"] .block-container {
        padding: 1.1rem 0.95rem 1.35rem !important;
    }
    .sidebar-brand {
        margin: 0.35rem 0 1.25rem !important;
    }
    .sidebar-brand img {
        max-height: 80px !important;
        box-shadow: none !important;
    }
    .sidebar-section {
        color: #8a98aa !important;
        font-size: 0.68rem !important;
        letter-spacing: 0.04em !important;
        margin: 1.1rem 0 0.45rem !important;
    }
    div[data-testid="stSidebar"] div[data-testid="stButton"] button {
        min-height: 2.38rem !important;
        border: 1px solid transparent !important;
        border-radius: 14px !important;
        background: transparent !important;
        color: #293241 !important;
        font-weight: 520 !important;
        transition: background 140ms ease, transform 140ms ease, box-shadow 140ms ease !important;
    }
    div[data-testid="stSidebar"] div[data-testid="stButton"] button:hover {
        background: rgba(255, 255, 255, 0.72) !important;
        border-color: rgba(0, 0, 0, 0.04) !important;
        box-shadow: 0 4px 18px rgba(0, 0, 0, 0.03) !important;
        transform: translateY(-1px);
    }
    div[data-testid="stSidebar"] details {
        border-radius: 16px !important;
        background: rgba(255, 255, 255, 0.58) !important;
        border: 1px solid rgba(0, 0, 0, 0.035) !important;
        box-shadow: 0 4px 24px rgba(0, 0, 0, 0.025) !important;
        margin-bottom: 0.72rem !important;
    }
    div[data-testid="stSidebar"] details summary {
        border-radius: 14px !important;
        padding: 0.68rem 0.72rem !important;
    }
    [data-testid="stBottom"],
    [data-testid="stBottom"] > div,
    [data-testid="stBottomBlockContainer"] {
        background: linear-gradient(180deg, rgba(248, 249, 250, 0), rgba(248, 249, 250, 0.94) 30%) !important;
        padding-top: 1.2rem !important;
    }
    [data-testid="stChatInput"] {
        max-width: 840px !important;
    }
    [data-testid="stChatInput"] > div {
        min-height: 76px !important;
        background: rgba(255, 255, 255, 0.86) !important;
        border: 1px solid rgba(0, 0, 0, 0.055) !important;
        border-radius: 22px !important;
        box-shadow: 0 18px 48px rgba(22, 34, 51, 0.09) !important;
        backdrop-filter: blur(12px);
    }
    [data-testid="stChatInput"] textarea,
    [data-testid="stChatInput"] [data-baseweb="textarea"],
    [data-testid="stChatInput"] [data-baseweb="base-input"],
    [data-testid="stChatInput"] [data-baseweb="input"] {
        background: transparent !important;
        background-color: transparent !important;
        color: #293241 !important;
    }
    [data-testid="stChatInput"] button {
        border-radius: 16px !important;
        transition: transform 140ms ease, box-shadow 140ms ease !important;
    }
    [data-testid="stChatInput"] button:hover {
        transform: translateY(-1px);
        box-shadow: 0 8px 22px rgba(0, 0, 0, 0.08) !important;
    }
    .followup-row div[data-testid="stButton"] button,
    div[data-testid="stDownloadButton"] button {
        border-radius: 999px !important;
        border: 1px solid rgba(0, 0, 0, 0.055) !important;
        background: rgba(255, 255, 255, 0.7) !important;
        color: #293241 !important;
        box-shadow: 0 4px 22px rgba(0, 0, 0, 0.025) !important;
        transition: transform 140ms ease, box-shadow 140ms ease, background 140ms ease !important;
    }
    .followup-row div[data-testid="stButton"] button:hover,
    div[data-testid="stDownloadButton"] button:hover {
        transform: translateY(-2px);
        background: #ffffff !important;
        box-shadow: 0 10px 28px rgba(0, 0, 0, 0.06) !important;
    }
    div[data-testid="stExpander"] {
        border: 1px solid rgba(0, 0, 0, 0.04) !important;
        border-radius: 16px !important;
        background: rgba(255, 255, 255, 0.58) !important;
        box-shadow: 0 4px 24px rgba(0, 0, 0, 0.025) !important;
    }
    div[data-testid="stMetric"] {
        background: rgba(255, 255, 255, 0.62) !important;
        border: 1px solid rgba(0, 0, 0, 0.035) !important;
        border-radius: 16px !important;
        padding: 0.8rem 0.9rem !important;
        box-shadow: 0 4px 24px rgba(0, 0, 0, 0.025) !important;
    }
    div[data-testid="stPopover"] > button,
    div[data-testid="stPopover"] button[data-testid="stPopoverButton"] {
        width: 1.86rem !important;
        min-width: 1.86rem !important;
        max-width: 1.86rem !important;
        height: 1.86rem !important;
        min-height: 1.86rem !important;
        max-height: 1.86rem !important;
        padding: 0 !important;
        border: 0 !important;
        border-radius: 999px !important;
        background: transparent !important;
        color: #6b7280 !important;
        box-shadow: none !important;
        font-size: 1.08rem !important;
        font-weight: 650 !important;
        line-height: 1 !important;
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
        margin: 0.24rem 0 0 0 !important;
        transition: background 120ms ease, color 120ms ease !important;
        overflow: hidden !important;
    }
    div[data-testid="stPopover"] > button:hover,
    div[data-testid="stPopover"] button[data-testid="stPopoverButton"]:hover {
        background: rgba(31, 41, 55, 0.085) !important;
        color: #172033 !important;
        transform: none !important;
        box-shadow: none !important;
        border: 0 !important;
    }
    div[data-testid="stPopover"] > button:focus,
    div[data-testid="stPopover"] > button:active,
    div[data-testid="stPopover"] button[data-testid="stPopoverButton"]:focus,
    div[data-testid="stPopover"] button[data-testid="stPopoverButton"]:active {
        border: 0 !important;
        box-shadow: none !important;
        outline: none !important;
        background: rgba(31, 41, 55, 0.11) !important;
    }
    div[data-testid="stPopover"] div[data-testid="stButton"] button {
        justify-content: flex-start !important;
        text-align: left !important;
        border-radius: 10px !important;
        min-height: 2.25rem !important;
        background: transparent !important;
        white-space: nowrap !important;
    }
    button[data-testid="stPopover"] > div > span[data-testid="stPopoverArrow"] {
        display: none !important;
    }
    div[data-testid="stPopover"] button[data-testid="stPopoverButton"] svg,
    div[data-testid="stPopover"] button[data-testid="stPopoverButton"] > div > div:last-child {
        display: none !important;
    }
    div[data-testid="stPopover"] button[data-testid="stPopoverButton"] > div {
        gap: 0 !important;
        margin-right: 0 !important;
    }
    div[data-testid="stSidebar"] [data-testid="stHorizontalBlock"] {
        gap: 0.18rem !important;
    }
    div[data-testid="stSidebar"] [data-testid="stHorizontalBlock"] > div:last-child {
        min-width: 2.05rem !important;
        max-width: 2.15rem !important;
    }
    div[data-testid="stSidebar"] div[data-testid="stButton"] button[kind="secondary"] {
        overflow: hidden !important;
        white-space: nowrap !important;
        text-overflow: ellipsis !important;
    }
    div[data-testid="stSidebar"] div[data-testid="stButton"] button p {
        overflow: hidden !important;
        white-space: nowrap !important;
        text-overflow: ellipsis !important;
        margin: 0 !important;
    }
</style>
""",
    unsafe_allow_html=True,
)


EXAMPLES = {
    "Doublet detection": "我有一批 10x scRNA-seq PBMC 数据，需要去除 doublet，最好有 benchmark 依据。",
    "Spatial deconvolution": "我有 Visium 空间转录组和 scRNA-seq reference，想估计每个 spot 的细胞类型组成。",
    "RNA velocity": "我有 spliced/unspliced count，想做 RNA velocity 并了解方法局限。",
    "Multiome integration": "我有同一个细胞的 RNA 和 ATAC 数据，想做联合表示和聚类，不想把两个模态完全分开处理。",
    "Perturbation response": "我有 Perturb-seq 扰动前后单细胞数据，想分析扰动响应和差异表达。",
}


WELCOME_MESSAGE = (
    "你好，我是 scKG Agent。你可以直接描述单细胞、空间组学或 multiome 分析需求，"
    "我会返回证据约束下的推荐、必要 caveat 和可追溯来源。"
)


def _initial_state(
    user_query: str,
    *,
    conversation_context: Optional[List[Dict[str, Any]]] = None,
    project_memory: Optional[Dict[str, Any]] = None,
    uploaded_context: Optional[Dict[str, Any]] = None,
    user_runtime_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "user_query": user_query,
        "extracted_constraints": {},
        "candidate_tools": [],
        "tool_candidates": [],
        "retrieval_results": [],
        "scored_tools": [],
        "migration_paths": [],
        "workflow_recommendations": [],
        "decision_report": None,
        "final_report": "",
        "hallucination_audit": {},
        "context_pack": {},
        "conversation_context": conversation_context or [],
        "project_memory": project_memory or {},
        "uploaded_context": uploaded_context or {},
        "user_runtime_config": user_runtime_config or {},
        "current_step": "init",
        "error_message": None,
    }


def _run_agent(
    user_query: str,
    offline_llm: bool,
    *,
    conversation_context: Optional[List[Dict[str, Any]]] = None,
    project_memory: Optional[Dict[str, Any]] = None,
    uploaded_context: Optional[Dict[str, Any]] = None,
    user_runtime_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    previous = os.environ.get("SCKG_OFFLINE_LLM")
    if offline_llm:
        os.environ["SCKG_OFFLINE_LLM"] = "true"
        get_settings.cache_clear()
    try:
        app = build_sckg_graph()
        return dict(
            app.invoke(
                _initial_state(
                    user_query,
                    conversation_context=conversation_context,
                    project_memory=project_memory,
                    uploaded_context=uploaded_context,
                    user_runtime_config=user_runtime_config,
                )
            )
        )
    finally:
        if offline_llm:
            if previous is None:
                os.environ.pop("SCKG_OFFLINE_LLM", None)
            else:
                os.environ["SCKG_OFFLINE_LLM"] = previous
            get_settings.cache_clear()


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
    audit = state.get("hallucination_audit") or {}
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


def _conversation_context(messages: List[Dict[str, Any]], limit: int = 8) -> List[Dict[str, str]]:
    usable = [
        {"role": item.get("role", ""), "content": item.get("content", "")}
        for item in messages
        if item.get("role") in {"user", "assistant"} and item.get("content")
    ]
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
    st.markdown("**你可以继续问：**")
    st.markdown('<div class="followup-row">', unsafe_allow_html=True)
    for idx, suggestion in enumerate(suggestions):
        button_key = f"{key_prefix}_{idx}"
        if st.button(suggestion, key=button_key):
            st.session_state.pending_query = _contextualized_followup_query(
                suggestion,
                source_query=source_query,
            )
            st.session_state.pending_display_query = suggestion
            st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)


def _contextualized_followup_query(suggestion: str, *, source_query: str = "") -> str:
    if not source_query:
        return suggestion
    return (
        f"基于上一轮用户问题：{source_query}\n"
        f"请继续回答这个追问：{suggestion}"
    )


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


def _greeting_reply(project_memory: Optional[Dict[str, Any]] = None) -> str:
    memory_bits = []
    project_memory = project_memory or {}
    for key in ("species", "platform", "strictness"):
        value = project_memory.get(key)
        if value:
            memory_bits.append(f"{key}: {value}")

    lines = [
        "你好，我在。你可以直接把单细胞、空间组学或 multiome 的分析需求发给我。",
        "为了让推荐更可靠，最好带上任务、模态、数据对象、规模、物种、平台和目标输出。信息不全也没关系，我会先问关键缺口。",
    ]
    if memory_bits:
        lines.append("我记得你的项目偏好：" + "，".join(memory_bits) + "。")
    return "\n\n".join(lines)


def _greeting_followups() -> List[str]:
    return [
        "我有一批 scRNA-seq 数据，想去除 doublet。",
        "我有 Visium + scRNA reference，想做空间反卷积。",
        "我有 spliced/unspliced count，想做 RNA velocity。",
        "我有 RNA + ATAC multiome，想做联合分析。",
    ]


def _render_context_status(
    *,
    offline_llm: bool,
    run_live: bool,
) -> None:
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
    else:
        _render_chip("API key locked")
    if offline_llm or not run_live:
        _render_chip("offline mode", "good")
    else:
        _render_chip("paid LLM enabled", "warn")
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


def _render_knowledge_graph_panel() -> None:
    st.markdown(
        """
<div class="chat-app-header">
  <div class="chat-app-kicker">scKG Graph Explorer</div>
  <div class="chat-app-title">🌐 scKG-Atlas 知识图谱探索器（正式证据与候选证据深度隔离）</div>
  <div class="chat-app-subtitle">默认仅展示 trusted_core + approved review_status 的 Tool-Task 主干；搜索或切换筛选时再展开 Paper / Benchmark 证据节点。Candidate evidence 只保留计数，不进入主图。</div>
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
            ["Tool", "Task", "Publication", "Benchmark"],
            default=["Tool", "Task"],
        )
    with controls[2]:
        max_nodes = st.slider("Max nodes", 40, 220, 130, step=10)

    graph = _kg_view(tuple(selected_kinds), search.strip(), max_nodes)
    metric_cols = st.columns(6)
    for column, label, key in [
        (metric_cols[0], "Tools", "tools"),
        (metric_cols[1], "Tasks", "tasks"),
        (metric_cols[2], "Papers", "publications"),
        (metric_cols[3], "Benchmarks", "benchmarks"),
        (metric_cols[4], "Edges", "edges"),
        (metric_cols[5], "Candidates", "candidate_evidence"),
    ]:
        with column:
            st.metric(label, f"{graph.inventory.get(key, 0):,}")

    if graph.truncated:
        st.caption("Graph is truncated for readability. Use search or raise Max nodes to inspect more.")
    components.html(build_knowledge_graph_html(graph), height=790, scrolling=True)


def _render_graph_dashboard_card() -> None:
    st.markdown(
        """
<div class="kg-panel sidebar-graph-card">
  <h4>Knowledge graph</h4>
  <div class="kg-subtitle">Formal evidence and candidate evidence remain isolated.</div>
  <div class="kg-card-glow">scKG-Atlas evidence workspace</div>
</div>
""",
        unsafe_allow_html=True,
    )
    if st.button("查看完整知识图谱 ➔", width="stretch", key="sidebar_graph_view"):
        st.session_state.current_view = "graph"
        st.rerun()

    inventory = _graph_inventory()
    first, second = st.columns(2, gap="small")
    cards = [
        (first, "Tools", "tools"),
        (second, "Tasks", "tasks"),
        (first, "Papers", "publications"),
        (second, "Benchmarks", "benchmarks"),
        (first, "Candidates", "candidate_evidence"),
        (second, "Edges", "edges"),
    ]
    for column, label, key in cards:
        with column:
            st.markdown(
                f"""
<div class="graph-card sidebar-metric-card">
  <strong>{inventory.get(key, 0):,}</strong>
  <span class="source-meta">{escape(label)}</span>
</div>
""",
                unsafe_allow_html=True,
            )


def _render_sidebar_brand() -> None:
    logo = get_settings().logo_path
    if logo.exists():
        suffix = logo.suffix.lower()
        mime = "image/svg+xml" if suffix == ".svg" else "image/png"
        encoded = base64.b64encode(logo.read_bytes()).decode("ascii")
        logo_html = f'<img src="data:{mime};base64,{encoded}" alt="scKG Agent logo" />'
        title_html = ""
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


def _reset_chat() -> None:
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": WELCOME_MESSAGE,
        }
    ]
    st.session_state.pop("latest_state", None)


def _load_session_messages(session_id: str) -> None:
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


def _switch_to_valid_session() -> None:
    sessions = list_sessions(limit=1)
    st.session_state.session_id = sessions[0]["session_id"] if sessions else create_session()
    _load_session_messages(st.session_state.session_id)


with st.sidebar:
    _render_sidebar_brand()

    if st.button("+ New chat", width="stretch"):
        st.session_state.session_id = create_session()
        _load_session_messages(st.session_state.session_id)
        st.session_state.current_view = "chat"
        st.rerun()

    sessions = list_sessions(limit=30)
    st.markdown('<div class="sidebar-section">🕒 最近对话</div>', unsafe_allow_html=True)
    if sessions:
        for item in sessions[:18]:
            is_current = item["session_id"] == st.session_state.session_id
            title = _compact(item["title"], 38) or "Untitled chat"
            row_cols = st.columns([1, 0.12], gap="small", vertical_alignment="center")
            with row_cols[0]:
                pin_marker = "Pinned · " if item.get("pinned") else ""
                button_label = f"{'● ' if is_current else ''}{pin_marker}{title}"
                if st.button(
                    button_label,
                    key=f"session_{item['session_id']}",
                    width="stretch",
                    type="tertiary",
                ):
                    if item["session_id"] != st.session_state.session_id:
                        st.session_state.session_id = item["session_id"]
                        _load_session_messages(item["session_id"])
                    st.session_state.current_view = "chat"
                    st.rerun()
            with row_cols[1]:
                with st.popover(
                    "⋮",
                    type="tertiary",
                    width="content",
                    key=f"session_menu_{item['session_id']}",
                ):
                    if st.button(
                        "Pin chat" if not item.get("pinned") else "Unpin chat",
                        key=f"pin_{item['session_id']}",
                        width="stretch",
                        type="tertiary",
                    ):
                        set_session_pinned(item["session_id"], not bool(item.get("pinned")))
                        st.rerun()
                    if st.button(
                        "Rename",
                        key=f"rename_{item['session_id']}",
                        width="stretch",
                        type="tertiary",
                    ):
                        st.session_state.editing_session_id = item["session_id"]
                        st.rerun()
                    if st.button(
                        "Delete",
                        key=f"delete_{item['session_id']}",
                        width="stretch",
                        type="tertiary",
                    ):
                        st.session_state.deleting_session_id = item["session_id"]
                        st.rerun()
            if st.session_state.get("editing_session_id") == item["session_id"]:
                new_title = st.text_input(
                    "Rename chat",
                    value=item["title"],
                    key=f"rename_title_{item['session_id']}",
                    label_visibility="collapsed",
                )
                action_cols = st.columns(2)
                if action_cols[0].button("Save", key=f"rename_save_{item['session_id']}", width="stretch"):
                    rename_session(item["session_id"], new_title)
                    st.session_state.pop("editing_session_id", None)
                    st.rerun()
                if action_cols[1].button("Cancel", key=f"rename_cancel_{item['session_id']}", width="stretch"):
                    st.session_state.pop("editing_session_id", None)
                    st.rerun()
            if st.session_state.get("deleting_session_id") == item["session_id"]:
                st.caption("Delete this chat history?")
                action_cols = st.columns(2)
                if action_cols[0].button("Confirm", key=f"delete_confirm_{item['session_id']}", width="stretch"):
                    deleting_current = item["session_id"] == st.session_state.session_id
                    delete_session(item["session_id"])
                    st.session_state.pop("deleting_session_id", None)
                    if deleting_current:
                        _switch_to_valid_session()
                    st.session_state.current_view = "chat"
                    st.rerun()
                if action_cols[1].button("Cancel", key=f"delete_cancel_{item['session_id']}", width="stretch"):
                    st.session_state.pop("deleting_session_id", None)
                    st.rerun()
    else:
        st.markdown('<div class="chat-list-note">No saved chats yet.</div>', unsafe_allow_html=True)

    if st.button("Clear current chat", width="stretch"):
        clear_conversation(st.session_state.session_id)
        _load_session_messages(st.session_state.session_id)
        st.session_state.current_view = "chat"
        st.rerun()

    st.divider()
    _render_graph_dashboard_card()

    st.divider()
    with st.expander("Settings", expanded=False):
        saved_config = has_saved_api_config()
        if saved_config:
            _render_chip("saved API config", "good")
        if st.session_state.get("user_api_config"):
            _render_chip("API key unlocked", "good")

        with st.expander("User API key", expanded=False):
            api_base = st.text_input("API base", value="https://api.deepseek.com")
            model_name = st.text_input("Model name", value="deepseek-chat")
            api_key = st.text_input("API key", type="password")
            passphrase = st.text_input("Passphrase", type="password")
            save_cols = st.columns(2)
            if save_cols[0].button("Save encrypted", width="stretch"):
                try:
                    save_encrypted_api_config(
                        "openai_compatible",
                        api_base,
                        model_name,
                        api_key,
                        passphrase,
                    )
                    st.success("Saved encrypted API config locally.")
                except Exception as exc:
                    st.error(f"Could not save config: {exc}")
            if save_cols[1].button("Unlock", width="stretch"):
                try:
                    st.session_state.user_api_config = load_api_config(passphrase)
                    st.success("API config unlocked for this session.")
                except ApiConfigError as exc:
                    st.error(str(exc))

        offline_llm = st.toggle(
            "Offline LLM mode",
            value=not bool(st.session_state.get("user_api_config")),
            help="开发阶段默认不调用 DeepSeek/OpenAI。",
        )
        run_live = st.checkbox(
            "Allow paid LLM calls",
            value=False,
            disabled=offline_llm,
            help="只有关闭 Offline LLM mode 后才可启用。",
        )
        show_sources = st.checkbox("Show sources under answers", value=True)
        debug_visible = st.checkbox("Show raw debug state", value=False)

    _render_context_status(offline_llm=offline_llm, run_live=run_live)

    with st.expander("Project memory", expanded=False):
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


if st.session_state.current_view == "chat":
    st.markdown(
        """
<div class="chat-app-header">
  <div class="chat-app-kicker">scKG-Atlas Agent</div>
  <div class="chat-app-title">证据约束下的单细胞与空间组学研究助手</div>
  <div class="chat-app-subtitle">围绕工具推荐、文献证据、benchmark caveat 与探索性迁移假设，保持结论可追溯。</div>
</div>
""",
        unsafe_allow_html=True,
    )

    for message_index, message in enumerate(st.session_state.messages):
        if message.get("role") == "user":
            _render_user_message(message.get("content", ""))
            continue
        with st.chat_message("assistant"):
            _render_assistant_report(message.get("content", ""))
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
            if message.get("followups"):
                message_key = f"history_{st.session_state.session_id}_{message_index}"
                _render_followups(
                    message["followups"],
                    key_prefix=message_key,
                    source_query=message.get("source_query", ""),
                )

    default_query = st.session_state.pop("pending_query", "")
    default_display_query = st.session_state.pop("pending_display_query", "")
    submission = st.chat_input(
        "描述你的分析需求，或拖入 TXT/MD/CSV/TSV/JSON/JSONL/PDF...",
        accept_file="multiple",
        file_type=["txt", "md", "csv", "tsv", "json", "jsonl", "pdf"],
        height=68,
    )
    query, submitted_files = _chat_input_parts(submission)
    if default_query and not query and not submitted_files:
        query = default_query

    if query or submitted_files:
        upload_context = _summarize_uploaded_files(submitted_files)
        if upload_context:
            save_working_context(st.session_state.session_id, "uploaded_context", upload_context)
            st.session_state.uploaded_context = upload_context

        display_query = default_display_query or _format_user_display_query(query, submitted_files)
        if submitted_files and not query:
            query = "请先读取我上传的文件上下文，概括字段/内容，并说明这些内容能怎样辅助后续推荐。"
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
            working_context = load_working_context(st.session_state.session_id)
            uploaded_context = (
                st.session_state.get("uploaded_context")
                or working_context.get("uploaded_context")
                or {}
            )

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
            elif _is_greeting_query(query):
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
                        runtime_config = st.session_state.get("user_api_config") or {}
                        state = _run_agent(
                            query,
                            offline_llm=(offline_llm or not run_live),
                            conversation_context=_conversation_context(st.session_state.messages),
                            project_memory=project_memory,
                            uploaded_context=uploaded_context,
                            user_runtime_config=runtime_config,
                        )
                        status.update(label="Analysis complete", state="complete")
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
                if show_sources:
                    _render_sources_and_caveats(state, runtime=elapsed, show_debug=debug_visible)
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
elif st.session_state.current_view == "graph":
    _render_knowledge_graph_panel()
