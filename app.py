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

LANGGRAPH_AVAILABLE = importlib.util.find_spec("langgraph") is not None
from core.reflection_memory import reflect_agent_run
from core.privacy_policy import OutboundDisclosureService, PrivacyMode
from core.settings import get_settings
from core.tool_contract_registry import ToolContractRegistry
from core.trace_context import TraceCollector, TraceContext
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
    EvidenceRecoveryService,
    InterviewDemoService,
    Phase6EvaluationService,
    ReflectionService,
    TraceService,
)
from observability.dashboard.ui_presenters import (
    format_conversation_title,
    normalize_ui_status,
)


st.set_page_config(
    page_title="scKG-Atlas Agent",
    layout="wide",
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
    .managed-step.blocked, .managed-step.failed {border-color: #efb9b1; background: #fff1ef;}
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
        section[data-testid="stSidebar"] {
            transform: translateX(-100%);
            position: fixed !important;
        }
        section[data-testid="stSidebar"][aria-expanded="true"] {
            transform: translateX(0);
        }
        .chat-app-header,
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
        width: 300px !important;
        min-width: 280px !important;
        max-width: 320px !important;
    }
    [data-testid="stSidebar"] .block-container {
        padding: 0.8rem 0.72rem 1.1rem;
    }
    .sidebar-section {
        color: #7b7b78;
        font-size: 0.68rem;
        font-weight: 600;
        margin: 0.75rem 0 0.22rem;
        text-transform: uppercase;
    }
    [data-testid="stSidebar"] div[data-testid="stButton"] button {
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
    [data-testid="stSidebar"] div[data-testid="stButton"] button:hover {
        background: #ebe7e1 !important;
        color: #111111 !important;
        border-color: #e0d8ce !important;
    }
    [data-testid="stSidebar"] div[data-testid="stButton"] button:focus {
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
    [data-testid="stSidebar"] details {
        border: 0 !important;
        background: transparent !important;
        box-shadow: none !important;
    }
    [data-testid="stSidebar"] details summary {
        padding: 0.42rem 0.4rem !important;
        border-radius: 8px !important;
        font-size: 0.86rem !important;
        color: #252523 !important;
    }
    [data-testid="stSidebar"] details summary:hover {
        background: #ebe7e1 !important;
    }
    [data-testid="stSidebar"] details summary *,
    [data-testid="stSidebar"] details summary svg {
        color: #252523 !important;
        fill: #626260 !important;
    }
    [data-testid="stSidebar"] hr {
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
        max-width: 1280px !important;
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
    [data-testid="stSidebar"] .block-container {
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
    [data-testid="stSidebar"] div[data-testid="stButton"] button {
        min-height: 2.38rem !important;
        border: 1px solid transparent !important;
        border-radius: 14px !important;
        background: transparent !important;
        color: #293241 !important;
        font-weight: 520 !important;
        transition: background 140ms ease, transform 140ms ease, box-shadow 140ms ease !important;
    }
    [data-testid="stSidebar"] div[data-testid="stButton"] button:hover {
        background: rgba(255, 255, 255, 0.72) !important;
        border-color: rgba(0, 0, 0, 0.04) !important;
        box-shadow: 0 4px 18px rgba(0, 0, 0, 0.03) !important;
        transform: translateY(-1px);
    }
    [data-testid="stSidebar"] div[data-testid="stButton"] button[kind="primary"] {
        background: #e7eef7 !important;
        border-color: #cbd9e9 !important;
        color: #173b63 !important;
        box-shadow: none !important;
    }
    [data-testid="stSidebar"] details {
        border-radius: 16px !important;
        background: rgba(255, 255, 255, 0.58) !important;
        border: 1px solid rgba(0, 0, 0, 0.035) !important;
        box-shadow: 0 4px 24px rgba(0, 0, 0, 0.025) !important;
        margin-bottom: 0.72rem !important;
    }
    [data-testid="stSidebar"] details summary {
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
    div[data-testid="stPopover"] > button p,
    div[data-testid="stPopover"] button[data-testid="stPopoverButton"] p {
        font-size: 0 !important;
        overflow: visible !important;
    }
    div[data-testid="stPopover"] > button p::after,
    div[data-testid="stPopover"] button[data-testid="stPopoverButton"] p::after {
        content: "\\22EF";
        font-size: 1.08rem !important;
        line-height: 1 !important;
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
    [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] {
        gap: 0.18rem !important;
    }
    [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] > div:last-child {
        min-width: 2.05rem !important;
        max-width: 2.15rem !important;
    }
    [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] > div:last-child button {
        width: 1.86rem !important;
        min-width: 1.86rem !important;
        max-width: 1.86rem !important;
        height: 1.86rem !important;
        min-height: 1.86rem !important;
        padding: 0 !important;
        border: 0 !important;
        border-radius: 999px !important;
        background: transparent !important;
        box-shadow: none !important;
        overflow: hidden !important;
    }
    [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] > div:last-child button p {
        font-size: 0 !important;
        overflow: visible !important;
    }
    [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] > div:last-child button p::after {
        content: "\\22EF";
        color: #6b7280 !important;
        font-size: 1.08rem !important;
        line-height: 1 !important;
    }
    [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] > div:last-child button svg {
        display: none !important;
    }
    [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] > div:first-child,
    [data-testid="stSidebar"] div[data-testid="stButton"],
    [data-testid="stSidebar"] div[data-testid="stButton"] button,
    [data-testid="stSidebar"] div[data-testid="stButton"] button > div {
        min-width: 0 !important;
        max-width: 100% !important;
        overflow: hidden !important;
    }
    [data-testid="stSidebar"] div[data-testid="stButton"] button {
        overflow: hidden !important;
        white-space: nowrap !important;
        text-overflow: ellipsis !important;
        word-break: normal !important;
        overflow-wrap: normal !important;
    }
    [data-testid="stSidebar"] div[data-testid="stButton"] button p {
        display: block !important;
        width: 100% !important;
        min-width: 0 !important;
        overflow: hidden !important;
        white-space: nowrap !important;
        text-overflow: ellipsis !important;
        word-break: normal !important;
        overflow-wrap: normal !important;
        margin: 0 !important;
    }
    [data-testid="stSidebar"] div[data-testid="stPopover"] > div > button {
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
        box-shadow: none !important;
        overflow: hidden !important;
    }
    [data-testid="stSidebar"] div[data-testid="stPopover"] > div > button p {
        font-size: 0 !important;
        overflow: visible !important;
    }
    [data-testid="stSidebar"] div[data-testid="stPopover"] > div > button p::after {
        content: "\\22EF";
        color: #6b7280 !important;
        font-size: 1.08rem !important;
        line-height: 1 !important;
    }
    [data-testid="stSidebar"] div[data-testid="stPopover"] > div > button > div:last-child {
        display: none !important;
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
    @media (max-width: 760px) {
        section[data-testid="stSidebar"] {
            width: min(86vw, 310px) !important;
            min-width: min(86vw, 280px) !important;
            max-width: min(86vw, 310px) !important;
        }
        [data-testid="stSidebar"] .block-container {
            padding-left: 0.72rem !important;
            padding-right: 0.72rem !important;
        }
    }
    /* Product shell v2: compact, neutral, and consistent across every workspace. */
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
    .block-container {
        max-width: 1320px !important;
        padding: 1.25rem 2rem 7rem !important;
    }
    .chat-app-header,
    .chat-app-header.compact-top {
        max-width: none !important;
        margin: 0 0 1rem !important;
        padding: 0.15rem 0 0.9rem !important;
        border-bottom: 1px solid #dbe1e8;
    }
    .chat-app-kicker {
        color: #607086 !important;
        font-size: 0.7rem !important;
        font-weight: 700 !important;
        letter-spacing: 0 !important;
        margin: 0 0 0.3rem !important;
        text-transform: uppercase;
    }
    .chat-app-title {
        color: #172033 !important;
        font-size: clamp(1.45rem, 2vw, 1.85rem) !important;
        font-weight: 680 !important;
        line-height: 1.18 !important;
        margin: 0 !important;
    }
    .chat-app-subtitle {
        max-width: 850px !important;
        color: #687386 !important;
        font-size: 0.9rem !important;
        line-height: 1.55 !important;
        margin: 0.38rem 0 0 !important;
    }
    p, li {
        line-height: 1.58 !important;
        margin-bottom: 0.65rem;
    }
    h2, h3, h4 {
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
    div[data-testid="stChatMessage"],
    div[data-testid="stExpander"],
    div[data-testid="stMetric"],
    div[data-testid="stVerticalBlockBorderWrapper"] {
        border-radius: 6px !important;
        box-shadow: none !important;
    }
    div[data-testid="stVerticalBlockBorderWrapper"],
    div[data-testid="stExpander"],
    div[data-testid="stMetric"],
    div[data-testid="stChatMessage"] {
        background: #ffffff !important;
        border: 1px solid #dce2e9 !important;
    }
    .source-item,
    .graph-card {
        background: #ffffff !important;
        border: 1px solid #dce2e9 !important;
    }
    .user-chat-bubble {
        background: #273240 !important;
        border-radius: 8px 8px 3px 8px !important;
        box-shadow: none !important;
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
    section[data-testid="stSidebar"] {
        width: 268px !important;
        min-width: 250px !important;
        max-width: 285px !important;
        background: #ffffff !important;
        border-right: 1px solid #dce2e9 !important;
        box-shadow: none !important;
    }
    [data-testid="stSidebar"] .block-container {
        padding: 0.75rem 0.68rem 1rem !important;
    }
    .sidebar-brand {
        margin: 0.15rem 0 0.65rem !important;
    }
    .sidebar-brand img {
        width: min(108px, 62%) !important;
        max-height: 62px !important;
        border-radius: 4px !important;
    }
    .sidebar-section {
        color: #7b8798 !important;
        font-size: 0.64rem !important;
        letter-spacing: 0 !important;
        margin: 0.72rem 0 0.2rem !important;
    }
    [data-testid="stSidebar"] div[data-testid="stButton"] button {
        min-height: 2.02rem !important;
        border-radius: 5px !important;
        padding: 0.32rem 0.48rem !important;
        font-size: 0.82rem !important;
        transition: background 100ms ease, border-color 100ms ease !important;
    }
    [data-testid="stSidebar"] div[data-testid="stButton"] button:hover {
        transform: none !important;
        background: #f2f5f7 !important;
        border-color: #dce2e9 !important;
        box-shadow: none !important;
    }
    [data-testid="stSidebar"] div[data-testid="stButton"] button[kind="primary"] {
        background: #e8f2f0 !important;
        border-color: #bcd8d3 !important;
        color: #165d58 !important;
    }
    [data-testid="stSidebar"] details {
        border-radius: 6px !important;
        background: #ffffff !important;
        border: 1px solid #dce2e9 !important;
        box-shadow: none !important;
        margin-bottom: 0.45rem !important;
    }
    [data-testid="stBottom"],
    [data-testid="stBottom"] > div,
    [data-testid="stBottomBlockContainer"] {
        background: #f6f7f9 !important;
    }
    [data-testid="stChatInput"] > div {
        min-height: 68px !important;
        background: #ffffff !important;
        border: 1px solid #cfd7e1 !important;
        border-radius: 8px !important;
        box-shadow: none !important;
        backdrop-filter: none !important;
    }
    [data-testid="stChatInput"] button {
        border-radius: 6px !important;
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
        .block-container { padding-left: 1rem !important; padding-right: 1rem !important; }
        .workflow-stepper { grid-template-columns: repeat(3, minmax(0, 1fr)); }
        .workflow-step { border-bottom: 1px solid #e4e8ed; }
    }
    @media (max-width: 620px) {
        section[data-testid="stSidebar"] {
            width: min(88vw, 280px) !important;
            min-width: min(88vw, 250px) !important;
            max-width: min(88vw, 280px) !important;
        }
        .workflow-stepper { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        .chat-app-title { font-size: 1.38rem !important; }
    }
    /* Product shell v3: readable chat and stable single-line conversation rows. */
    .research-chat-layout {
        max-width: 850px;
        margin: 0 auto;
    }
    .research-chat-layout.chat-app-header {
        max-width: 850px !important;
        margin: 0 auto 1.25rem !important;
        padding: 0.25rem 0 0.85rem !important;
    }
    .research-chat-layout.chat-app-header .chat-app-title {
        font-size: 1.55rem !important;
    }
    .research-chat-layout.chat-app-header .chat-app-subtitle {
        max-width: 720px !important;
    }
    div[data-testid="stChatMessage"] {
        max-width: 850px !important;
        background: transparent !important;
        border: 0 !important;
        border-radius: 0 !important;
        padding: 0.55rem 0 !important;
        margin: 0.25rem auto 0.75rem !important;
    }
    div[data-testid="stChatMessageContent"] {
        color: #20242c !important;
        font-size: 0.96rem !important;
        line-height: 1.62 !important;
    }
    div[data-testid="stChatMessageContent"] h2,
    div[data-testid="stChatMessageContent"] h3 {
        font-size: 1rem !important;
        margin: 1rem 0 0.42rem !important;
    }
    .user-chat-row {
        max-width: 850px;
        margin: 0.35rem auto 0.8rem !important;
    }
    .user-chat-bubble {
        max-width: min(76%, 650px) !important;
        background: #eef0f2 !important;
        color: #20242c !important;
        border: 1px solid #e2e5e9 !important;
        border-radius: 15px !important;
        padding: 0.68rem 0.88rem !important;
        line-height: 1.52 !important;
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
    [data-testid="stChatInput"] {
        max-width: 850px !important;
    }
    [data-testid="stChatInput"] > div {
        border-radius: 17px !important;
        border-color: #cdd3da !important;
        box-shadow: 0 4px 18px rgba(24, 33, 47, 0.06) !important;
    }
    [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] {
        width: 100% !important;
        align-items: center !important;
        gap: 0.12rem !important;
    }
    [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] > div:first-child {
        flex: 1 1 auto !important;
        width: calc(100% - 2.15rem) !important;
    }
    [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] > div:last-child {
        flex: 0 0 2rem !important;
        width: 2rem !important;
        min-width: 2rem !important;
        max-width: 2rem !important;
    }
    [data-testid="stSidebar"] div[data-testid="stButton"] button,
    [data-testid="stSidebar"] div[data-testid="stButton"] button p {
        white-space: nowrap !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
        overflow-wrap: normal !important;
        word-break: keep-all !important;
    }
    [data-testid="stSidebar"] div[data-testid="stPopover"] > button,
    [data-testid="stSidebar"] div[data-testid="stPopover"] button[data-testid="stPopoverButton"] {
        font-size: 1.15rem !important;
        font-family: Arial, sans-serif !important;
        letter-spacing: 0 !important;
    }
    [data-testid="stSidebar"] div[data-testid="stPopover"] button svg,
    [data-testid="stSidebar"] div[data-testid="stPopover"] button [data-testid="stPopoverArrow"] {
        display: none !important;
    }
    [data-testid="stSidebar"] div[data-testid="stPopover"] button > div {
        gap: 0 !important;
        justify-content: center !important;
    }
    section[data-testid="stSidebar"] [data-testid="stHorizontalBlock"] {
        width: 100% !important;
        align-items: center !important;
        gap: 0.12rem !important;
    }
    section[data-testid="stSidebar"] [data-testid="stHorizontalBlock"] > div:first-child {
        min-width: 0 !important;
        flex: 1 1 auto !important;
    }
    section[data-testid="stSidebar"] [data-testid="stHorizontalBlock"] > div:last-child {
        flex: 0 0 1.9rem !important;
        width: 1.9rem !important;
        min-width: 1.9rem !important;
        max-width: 1.9rem !important;
    }
    section[data-testid="stSidebar"] div[data-testid="stButton"] button,
    section[data-testid="stSidebar"] div[data-testid="stButton"] button p {
        min-width: 0 !important;
        max-width: 100% !important;
        white-space: nowrap !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
        overflow-wrap: normal !important;
        word-break: keep-all !important;
        margin: 0 !important;
        text-align: left !important;
        justify-content: flex-start !important;
    }
    section[data-testid="stSidebar"] div[data-testid="stPopover"] > div > button {
        width: 1.8rem !important;
        min-width: 1.8rem !important;
        max-width: 1.8rem !important;
        height: 1.8rem !important;
        min-height: 1.8rem !important;
        padding: 0 !important;
        border: 0 !important;
        background: transparent !important;
        box-shadow: none !important;
    }
    section[data-testid="stSidebar"] div[data-testid="stPopover"] button svg {
        display: none !important;
    }
    section[data-testid="stSidebar"] div[data-testid="stPopover"] button p {
        width: auto !important;
        text-align: center !important;
        font-size: 1.1rem !important;
        line-height: 1 !important;
        overflow: visible !important;
    }
    @media (max-width: 700px) {
        .user-chat-bubble { max-width: 88% !important; }
        .algorithm-grid { grid-template-columns: 1fr; }
        div[data-testid="stChatMessageAvatar"] { display: none !important; }
        div[data-testid="stChatMessageContent"] { width: 100% !important; }
    }
</style>
""",
    unsafe_allow_html=True,
)


EXAMPLES = {
    "Doublet method": "我有一批 10x PBMC scRNA-seq 数据，应该用什么方法检测 doublet？请说明证据和限制。",
    "Doublet workflow": "请为 10x PBMC 数据生成一个 doublet detection workflow。",
    "Batch integration": "我有三个 scRNA-seq 批次，希望整合后保留细胞类型差异，应该选择 Harmony 还是 Scanorama？",
    "Top-3 caveats": "doublet detection 里 top-3 工具的 caveat 分别是什么？",
}


WELCOME_MESSAGE = (
    "这是统一 Research Chat。你可以查询工具、输入要求、参数、输出、失败模式与原文定位，"
    "也可以为已资格化任务生成 dry-run plan；真正执行仍需数据登记与 plan-specific approval。"
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
    previous = os.environ.get("SCKG_OFFLINE_LLM")
    previous_network = os.environ.get("SCKG_EXTERNAL_NETWORK_ALLOWED")
    previous_privacy = os.environ.get("SCKG_PRIVACY_MODE")
    runtime_config = user_runtime_config or {}
    privacy_authorized = bool(runtime_config.get("privacy_authorized"))
    if offline_llm:
        os.environ["SCKG_OFFLINE_LLM"] = "true"
    os.environ["SCKG_EXTERNAL_NETWORK_ALLOWED"] = (
        "true" if privacy_authorized and not offline_llm else "false"
    )
    os.environ["SCKG_PRIVACY_MODE"] = str(
        runtime_config.get("privacy_mode") or PrivacyMode.LOCAL_HYBRID.value
    )
    get_settings.cache_clear()
    trace = TraceContext(
        trace_type="agent_run",
        metadata={
            "query": user_query,
            "source": "streamlit",
            "offline_llm": offline_llm,
            "architecture": "bounded_centralized_parent_agent",
        },
    )
    try:
        with trace.stage_timer(
            "gateway",
            method="agent.research_chat_service.ResearchChatService",
            provider="local_governed_parent_agent",
            input_summary={"query_chars": len(user_query), "mode": agent_mode or "AUTO"},
        ) as payload:
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
            payload["output_summary"] = {
                "runtime_mode": state.get("runtime_mode"),
                "candidate_count": len(state.get("tool_candidates") or []),
                "execution_request_count": (
                    state.get("deterministic_parent_result") or {}
                ).get("execution_request_count", 0),
                "application_graph": (
                    state.get("context_pack", {}).get("application_graph", {})
                ).get("runtime"),
            }
        for timing in (
            (state.get("context_pack") or {}).get("chat_stage_timings") or []
        ):
            stage_name = str(timing.get("stage") or "")
            if not stage_name:
                continue
            trace.record_stage(
                stage_name,
                status=str(timing.get("status") or "completed"),
                method="agent.research_chat_service",
                provider=str(state.get("runtime_mode") or "degraded_local_fallback"),
                output_summary={"detail": str(timing.get("detail") or "")},
                elapsed_ms=float(timing.get("elapsed_ms") or 0.0),
            )
        try:
            with trace.stage_timer(
                "reflect",
                method="core.reflection_memory.reflect_agent_run",
                provider="local_sqlite_jsonl",
                input_summary={
                    "has_final_report": bool(state.get("final_report")),
                    "has_audit": bool(state.get("hallucination_audit")),
                },
            ) as payload:
                reflection = reflect_agent_run(state, trace)
                state["reflection_event"] = reflection.model_dump(mode="json")
                payload["output_summary"] = {
                    "memory_event_count": len(reflection.memory_events),
                    "skill_candidate_count": len(reflection.skill_candidates),
                    "missing_evidence_count": len(reflection.missing_evidence),
                }
                payload["warnings"] = reflection.warnings
        except Exception as exc:
            state["reflection_error"] = f"{type(exc).__name__}: {exc}"
        return dict(state)
    except Exception as exc:
        trace.metadata["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        trace.finish()
        TraceCollector().collect(trace)
        if previous is None:
            os.environ.pop("SCKG_OFFLINE_LLM", None)
        else:
            os.environ["SCKG_OFFLINE_LLM"] = previous
        if previous_network is None:
            os.environ.pop("SCKG_EXTERNAL_NETWORK_ALLOWED", None)
        else:
            os.environ["SCKG_EXTERNAL_NETWORK_ALLOWED"] = previous_network
        if previous_privacy is None:
            os.environ.pop("SCKG_PRIVACY_MODE", None)
        else:
            os.environ["SCKG_PRIVACY_MODE"] = previous_privacy
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
    if intent == "workflow" or bundle:
        if not bundle:
            return
        smoke_status = str(bundle.get("smoke_status") or "not_run").upper()
        st.markdown(
            '<div class="algorithm-surface-title">Verified runnable recipe</div>',
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


def _workspace_handoff_payload(
    state: Dict[str, Any], *, source_query: str
) -> Dict[str, Any] | None:
    governed_handoff = state.get("workspace_handoff") or {}
    bundle = state.get("workflow_code_bundle") or {}
    task = str(
        (state.get("extracted_constraints") or {}).get("canonical_task") or ""
    )
    tool_name = str(bundle.get("tool_name") or "")
    if (
        governed_handoff.get("status") != "available"
        or task != "doublet_detection"
        or tool_name != "Scrublet"
    ):
        return None
    plan = state.get("workflow_plan") or {}
    return {
        "handoff_id": f"workspace-{uuid.uuid4().hex}",
        "conversation_id": st.session_state.session_id,
        "source_query": source_query.strip(),
        "task_family": task,
        "tool_name": tool_name,
        "agent_mode": str(state.get("agent_mode") or "PLAN"),
        "plan_id": governed_handoff.get("plan_id") or plan.get("plan_id"),
        "notebook_strategy": governed_handoff.get("notebook_strategy"),
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
    st.markdown(
        '<div class="algorithm-surface-title">从对话继续到数据验证</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "系统识别到这是已资格化的 Doublet Detection workflow。对话中的任务、工具和计划会一并带入 Stepwise Analysis。"
    )
    action_cols = st.columns(2)
    if action_cols[0].button(
        "用模拟数据在 JupyterLab 试跑",
        key=f"{key}_demo",
        type="primary",
        width="stretch",
    ):
        demo_payload = dict(payload)
        demo_payload["source_query"] = source_query.strip()
        demo_payload["fixture_type"] = "synthetic_engineering_demo"
        try:
            _activate_scrublet_demo_handoff(demo_payload)
            st.session_state.current_view = "data_preview"
            st.rerun()
        except Exception as exc:
            st.error(_execution_ui_backend().redact_text(str(exc)))
    if action_cols[1].button(
        "关联我的 .h5ad",
        key=f"{key}_data",
        width="stretch",
    ):
        st.session_state.workspace_task_handoff = payload
        artifact_id = (state.get("execution_handoff") or {}).get("artifact_id")
        if artifact_id:
            st.session_state.workspace_artifact_id = artifact_id
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


def _greeting_reply(project_memory: Optional[Dict[str, Any]] = None) -> str:
    memory_bits = []
    project_memory = project_memory or {}
    for key in ("species", "platform", "strictness"):
        value = project_memory.get(key)
        if value:
            memory_bits.append(f"{key}: {value}")

    lines = [
        "你好，我在。当前正式支持 scRNA-seq 的 Doublet Detection 与 Batch Integration。",
        "直接描述问题即可：我会逐条识别问答、工作流或运行意图；真正执行仍需数据授权和 plan-specific approval。",
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


def _render_response_runtime(state: Dict[str, Any]) -> None:
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
    build = state.get("runtime_build") or context.get("runtime_build") or {}
    source_fingerprint = str(build.get("source_fingerprint") or "")
    if source_fingerprint:
        _render_chip(f"BUILD · {source_fingerprint[:10]}", "good")
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
    service = EvidenceRecoveryService()
    core = service.load_source_coverage()
    literature = service.load_literature_source_coverage()
    registry = service.load_source_registry_status()
    chunks_path = get_settings().data_dir / "indexes" / "evidence_chunks.jsonl"
    vector_metadata_path = get_settings().data_dir / "indexes" / "evidence_vector_metadata.json"
    v2_coverage = _read_json_artifact(
        get_settings().data_dir / "indexes" / "retrieval_coverage_v2.json"
    )
    chunk_count = sum(1 for _ in chunks_path.open("r", encoding="utf-8")) if chunks_path.exists() else 0
    vector_metadata = _read_json_artifact(vector_metadata_path)
    vector_count = int((vector_metadata.get("shape") or [0])[0]) if vector_metadata else 0

    core_summary = core.get("summary") or {}
    literature_summary = literature.get("summary") or {}
    acquisition = registry.get("acquisition_summary") or {}
    extraction = registry.get("extraction_summary") or {}
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Evidence Chunks", chunk_count)
    c2.metric("Dense Vectors", vector_count)
    c3.metric("Core Source Coverage", _format_percent(v2_coverage.get("core_tool_source_coverage_rate", 0)))
    c4.metric("Qualified Coverage", _format_percent(v2_coverage.get("qualified_tool_source_coverage_rate", 0)))
    c5.metric("Quarantine", acquisition.get("candidate_quarantine_rows", 0))
    st.info(
        "当前主检索为 canonical task/entity normalization + KG hard filter + SQLite FTS5 BM25 + governance rerank。"
        "本地 BAAI/bge-m3 是可删除的可选 model pack；未安装时自动回退，不调用云 embedding API。"
    )
    retrieval_eval = _read_json_artifact(
        get_settings().data_dir / "evaluation" / "retrieval_eval_v2" / "summary.json"
    )
    kg_bm25 = (retrieval_eval.get("profiles") or {}).get("kg_bm25") or {}
    if kg_bm25:
        st.markdown("#### Retrieval Evaluation v2")
        eval_cols = st.columns(6)
        eval_cols[0].metric("Cases", retrieval_eval.get("case_count", 0))
        eval_cols[1].metric("Recall@10", _format_percent(kg_bm25.get("recall_at_10", 0)))
        eval_cols[2].metric("Precision@10", _format_percent(kg_bm25.get("precision_at_10", 0)))
        eval_cols[3].metric("MRR", _format_percent(kg_bm25.get("mrr", 0)))
        eval_cols[4].metric("p95", f"{kg_bm25.get('latency_p95_ms', 0):.1f} ms")
        eval_cols[5].metric("False support", _format_percent(kg_bm25.get("false_support_rate", 0)))
        st.caption(
            f"KG+BM25 status: {kg_bm25.get('status', 'unknown')}. Dense and RAGAS remain optional and are reported as not_run when unavailable."
        )

    st.markdown("#### Core Tool Source Coverage")
    rows = core.get("rows") or []
    if rows:
        st.dataframe(_safe_rows(rows), use_container_width=True)
    else:
        st.info("No core source coverage manifest found.")

    st.markdown("#### Paper / Benchmark Source Coverage")
    lit_rows = literature.get("rows") or []
    if lit_rows:
        st.dataframe(_safe_rows(lit_rows), use_container_width=True)
    else:
        st.info("No literature source coverage artifact found.")

    st.markdown("#### Source Registry / Validation")
    c6, c7, c8 = st.columns(3)
    c6.metric("Source Records", acquisition.get("source_records", len(registry.get("registry_rows") or [])))
    c7.metric("Text Sources", extraction.get("source_text_available", 0))
    c8.metric("Extract Failures", extraction.get("pdf_extraction_failed", 0))
    validation_rows = registry.get("validation_rows") or []
    if validation_rows:
        st.dataframe(_safe_rows(validation_rows), use_container_width=True)
    with st.expander("PDF acquisition policy"):
        st.markdown(
            """
- 自动：只做候选发现、开放 PDF/HTML 获取、标题/DOI 校验、抽取、入 source chunk index。
- 手动：paywall、登录、metadata mismatch、PDF 抽取失败、题文不一致。
- 下载后仍需检查：PDF/HTML title、DOI、source span、tool/source 映射、是否可晋升 formal evidence。
- RAG chunk 永远只是 evidence discovery，不能直接改推荐排名。
"""
        )


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
    "execution/execution_ui_service.py",
    "execution/interactive_step_runtime.py",
    "execution/local_jupyter_service.py",
    "execution/notebook_shadow.py",
    "execution/preview_execution_service.py",
    "execution/research_workspace_service.py",
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
    return ResearchChatService(parent_agent=parent)


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
    st.dataframe(
        [
            {
                "pack": probe.pack_id,
                "task family": manifests[probe.pack_id].task_family,
                "tools": ", ".join(
                    item.tool_name
                    for item in manifests[probe.pack_id].supported_tools
                ),
                "state": str(probe.state),
                "source": str(probe.source),
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

    nav_groups = [
        (
            "Workspace",
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

    with st.expander("More", expanded=False):
        secondary_nav = [
            ("Legacy Agent Baseline", "agent_loop_demo"),
            ("Knowledge Review", "knowledge_review"),
            ("Defense Demo", "defense_demo"),
            ("Evidence & RAG", "evidence_admin"),
            ("Evaluation", "evaluation_admin"),
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

    if st.session_state.current_view in {"home", "chat"}:
        st.divider()
        st.markdown('<div class="sidebar-section">Conversations</div>', unsafe_allow_html=True)
        if st.button("+ New chat", width="stretch"):
            st.session_state.session_id = create_session()
            _load_session_messages(st.session_state.session_id)
            st.session_state.current_view = "chat"
            st.rerun()

        sessions = list_sessions(limit=30)
        st.markdown('<div class="sidebar-section">Recent</div>', unsafe_allow_html=True)
        if sessions:
            for session_index, item in enumerate(sessions[:10], start=1):
                is_current = item["session_id"] == st.session_state.session_id
                title = format_conversation_title(
                    item.get("title"), item["session_id"], limit=34
                )
                row_cols = st.columns([5, 1], gap="small", vertical_alignment="center")
                with row_cols[0]:
                    if st.button(
                        title,
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
                        f"More actions for chat {session_index}",
                        type="tertiary",
                        width="content",
                    ):
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
            st.markdown('<div class="chat-list-note">No saved chats yet.</div>', unsafe_allow_html=True)

        if st.button("Clear current chat", width="stretch"):
            clear_conversation(st.session_state.session_id)
            _load_session_messages(st.session_state.session_id)
            st.session_state.current_view = "chat"
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
        offline_llm = privacy_mode == PrivacyMode.STRICT_OFFLINE.value
        env_llm_configured = bool(
            (settings.deepseek_api_key or settings.openai_api_key)
            and settings.model_name
        )
        run_live = st.checkbox(
            "本会话启用 DeepSeek（发送脱敏后的问题与受控上下文）",
            value=False,
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
    st.markdown(
        f"""
<div class="research-chat-layout chat-app-header">
  <div class="chat-app-kicker">scKG governed Parent Agent</div>
  <div class="chat-app-title">{workspace_title}</div>
  <div class="chat-app-subtitle">{workspace_subtitle}</div>
</div>
""",
        unsafe_allow_html=True,
    )

    agent_mode = None
    run_artifact_id = None
    run_requested_tool = None
    if not data_preview_view:
        _render_chip("AUTO intent routing", "good")
        st.caption("模式只由当前消息与明确的省略型追问决定，不会粘住后续对话。")
        with st.expander("Optional execution context", expanded=False):
            from execution.execution_ui_service import configured_local_user_id

            local_user_id = configured_local_user_id()
            run_artifacts = _execution_ui_backend().list_artifacts(user_id=local_user_id)
            if run_artifacts:
                attach_run_context = st.checkbox(
                    "Attach a registered artifact when this message requests execution",
                    value=False,
                    key="research_attach_run_context",
                )
                run_cols = st.columns([3, 2])
                artifact_labels = {
                    item.artifact_id: f"{item.artifact_id} · {item.redacted_path}"
                    for item in run_artifacts
                }
                selected_artifact_id = run_cols[0].selectbox(
                    "Registered data",
                    options=list(artifact_labels),
                    format_func=lambda value: artifact_labels[value],
                    key="research_run_artifact",
                )
                selected_tool = run_cols[1].selectbox(
                    "Qualified tool",
                    options=["Auto", "Scrublet", "scDblFinder", "Harmony", "Scanorama"],
                    key="research_run_tool",
                )
                if attach_run_context:
                    run_artifact_id = selected_artifact_id
                    run_requested_tool = None if selected_tool == "Auto" else selected_tool
                st.caption(
                    "附加数据只提供执行上下文；明确审批与启动仍在 Runs & Results 中进行。"
                )
            else:
                st.info(
                    "当前本地用户尚无已登记数据。执行请求会返回登记要求，并保持 ExecutionRequest=0。"
                )
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

    workflow_container = (
        st.container(border=False)
        if data_preview_view
        else st.expander("Data & Preview workflow", expanded=False)
    )
    with workflow_container:
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
                format_func=lambda value: value.name,
                key="workspace_prepared_path",
                help="这里只列出维护者已批准文件夹中的本地文件。",
            )
            st.caption(
                "首次体验建议使用 scrublet_preview_demo.h5ad，然后点击下方主按钮。"
            )
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
                            )
                            st.session_state.workspace_jupyter_session_id = (
                                launched.session_id
                            )
                            st.session_state.workspace_jupyter_notebook_hash = (
                                notebook_bundle.notebook_hash
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
                            width="stretch",
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

    if data_preview_view:
        st.stop()

    for message_index, message in enumerate(st.session_state.messages):
        if message.get("role") == "user":
            _render_user_message(message.get("content", ""))
            continue
        with st.chat_message("assistant"):
            _render_assistant_report(message.get("content", ""))
            if message.get("state") and isinstance(message.get("state"), dict):
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
                        runtime_config = dict(
                            st.session_state.get("user_api_config") or {}
                        )
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
                        if (
                            attach_workflow_card
                            and state.get("response_intent") == "workflow"
                        ):
                            state["workflow_decision"] = _attach_workflow_decision(
                                query=query,
                                state=state,
                                project_memory=project_memory,
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
elif st.session_state.current_view == "memory_admin":
    _render_memory_admin_panel()
elif st.session_state.current_view == "architecture_admin":
    _render_architecture_admin_panel()
