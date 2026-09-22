"""
SmartLogix - NiceGUI web UI.

Pure Python UI (no HTML/CSS/JS files to hand-write) on top of the same
coordinator/agents backend used by the group system. Run with:

    python app.py

Login: demo / Demo@123 (seeded automatically on first run).
"""

import json
import re
import uuid
from pathlib import Path

from nicegui import ui, app, run

from src.config import UI_STORAGE_SECRET
from src.security.auth import seed_demo_user, verify_credentials, create_access_token
from src.coordinator import handle_request, get_session_history, call_policy_agent

seed_demo_user()

BRAND_PRIMARY = "#2563eb"
BRAND_DARK = "#1e3a8a"

EXAMPLE_PROMPTS = [
    "My order ORD10017 arrived damaged, the plates were broken",
    "What is your refund policy?",
    "Can you ship a lithium battery power bank?",
    "Is my order ORD10052 delayed?",
]

FAQ_PATH = Path(__file__).parent / "data" / "policies" / "05_faq.md"


def _load_faq() -> list[tuple[str, str]]:
    """Parses the '**Q: ...**\\nA: ...' pairs out of the FAQ policy document
    so the UI can show them as an instant static lookup, without spending an
    LLM call on questions that already have a fixed answer."""
    text = FAQ_PATH.read_text(encoding="utf-8")
    pairs = re.findall(r"\*\*Q:\s*(.+?)\*\*\s*\nA:\s*(.+?)(?=\n\*\*Q:|\Z)", text, re.DOTALL)
    return [(q.strip(), " ".join(a.split())) for q, a in pairs]


FAQ_ITEMS = _load_faq()

_THEME_HEAD_HTML = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
  body, .q-field, .q-btn, .q-item, .q-chat-message, .q-chip { font-family: 'Inter', -apple-system, sans-serif !important; }
  body { background: linear-gradient(180deg, #f8fafc 0%, #eef2ff 100%); }
  ::-webkit-scrollbar { width: 8px; height: 8px; }
  ::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 8px; }
  ::-webkit-scrollbar-track { background: transparent; }
  .sl-header { box-shadow: 0 2px 16px rgba(30, 58, 138, 0.25); }
  .sl-card { transition: all 0.15s ease; }
  .sl-card:hover { background: #eef2ff !important; border-color: #c7d2fe !important; transform: translateX(2px); }
  .q-message-text { border-radius: 16px !important; max-width: 75%; }
  .q-message-name { font-weight: 600 !important; }
</style>
"""


def _inject_theme() -> None:
    ui.add_head_html(_THEME_HEAD_HTML)


def _logout():
    app.storage.user.clear()
    ui.navigate.to("/")


@ui.page("/")
def login_page():
    ui.colors(primary=BRAND_PRIMARY)

    if app.storage.user.get("auth_token"):
        ui.navigate.to("/chat")
        return

    _inject_theme()

    with ui.column().classes("absolute-center items-center gap-1"):
        with ui.card().classes("w-96 p-8 rounded-3xl shadow-2xl border border-slate-100"):
            with ui.column().classes("items-center w-full mb-2"):
                with ui.row().classes(
                    "w-16 h-16 rounded-2xl items-center justify-center text-3xl mb-3"
                ).style(f"background: linear-gradient(135deg, {BRAND_PRIMARY}, {BRAND_DARK})"):
                    ui.label("📦")
                ui.label("SmartLogix").classes("text-3xl font-extrabold text-center w-full").style(
                    f"color:{BRAND_DARK}"
                )
                ui.label("Sri Lanka Delivery Exception Assistant").classes(
                    "text-sm text-slate-400 text-center w-full"
                )

            username = ui.input("Username").classes("w-full mt-4").props("outlined dense")
            password = ui.input("Password", password=True).classes("w-full mt-2").props(
                "outlined dense"
            )
            error_label = ui.label("").classes("text-red-500 text-xs mt-1")

            def do_login():
                if verify_credentials(username.value or "", password.value or ""):
                    app.storage.user["auth_token"] = create_access_token(username.value)
                    app.storage.user["username"] = username.value
                    app.storage.user["session_id"] = str(uuid.uuid4())
                    ui.navigate.to("/chat")
                else:
                    error_label.text = "Invalid username or password."

            password.on("keydown.enter", lambda: do_login())
            ui.button("Log in", on_click=do_login).classes(
                "w-full mt-4 rounded-xl"
            ).props("color=primary unelevated size=lg")
            ui.label("Demo account: demo / Demo@123").classes(
                "text-xs text-gray-400 text-center w-full mt-4"
            )


@ui.page("/chat")
def chat_page():
    ui.colors(primary=BRAND_PRIMARY)
    _inject_theme()

    if not app.storage.user.get("auth_token"):
        ui.navigate.to("/")
        return

    username = app.storage.user["username"]
    session_id = app.storage.user["session_id"]
    auth_token = app.storage.user["auth_token"]
    history = get_session_history(session_id)

    with ui.header().classes("items-center justify-between px-4 sl-header").style(
        f"background:{BRAND_DARK}"
    ):
        with ui.row().classes("items-center gap-3"):
            with ui.row().classes("w-9 h-9 rounded-xl items-center justify-center bg-white/15"):
                ui.label("📦").classes("text-lg")
            ui.label("SmartLogix").classes("text-xl font-bold tracking-tight")
        with ui.row().classes("items-center gap-4"):
            ui.button(
                "Knowledge Base", icon="menu_book", on_click=lambda: ui.navigate.to("/knowledge")
            ).props("flat color=white dense no-caps")
            ui.label(f"Signed in as {username}").classes("text-sm text-blue-100")
            ui.button("Log out", icon="logout", on_click=_logout).props(
                "flat color=white dense no-caps"
            )

    with ui.left_drawer().classes("bg-slate-50 p-4").style("border-right: 1px solid #e2e8f0"):
        ui.label("TRY AN EXAMPLE").classes(
            "font-bold text-[11px] tracking-wider text-slate-400 mb-2"
        )
        for example in EXAMPLE_PROMPTS:
            with ui.row().classes(
                "sl-card w-full items-start gap-2 p-3 rounded-xl bg-white cursor-pointer mb-2 "
                "border border-slate-100 shadow-sm"
            ).on("click", lambda e=example: send_message(e)):
                ui.icon("chat_bubble_outline", color="primary").classes("text-sm mt-0.5")
                ui.label(example).classes("text-xs text-slate-600 leading-snug")

        ui.separator().classes("my-4")
        ui.label("Every reply includes an expandable agent trace — useful for the "
                  "security audit assignment too.").classes("text-xs text-slate-400")

    scroll_area = ui.scroll_area().classes("w-full h-[calc(100vh-160px)]")
    with scroll_area:
        chat_container = ui.column().classes("w-full max-w-3xl mx-auto gap-1 p-4")

    with chat_container:
        empty_state = ui.column().classes("w-full items-center justify-center gap-2 py-24")
        with empty_state:
            ui.label("📦").classes("text-5xl")
            ui.label("Welcome to SmartLogix").classes("text-2xl font-bold text-slate-700")
            ui.label(
                "Describe a delivery issue or ask a policy question to get started."
            ).classes("text-sm text-slate-400")
        empty_state.set_visibility(not bool(history))

        for turn in history:
            with ui.chat_message(
                name=username if turn["role"] == "user" else "SmartLogix",
                sent=turn["role"] == "user",
            ).props(
                "bg-color=primary text-color=white"
                if turn["role"] == "user"
                else "bg-color=grey-2 text-color=grey-9"
            ):
                ui.markdown(turn["text"])

    def _scroll_down():
        scroll_area.scroll_to(percent=1.0)

    async def send_message(text: str | None = None):
        text = (text if text is not None else input_box.value or "").strip()
        if not text:
            return
        empty_state.set_visibility(False)
        input_box.value = ""
        input_box.disable()
        send_button.disable()

        with chat_container:
            with ui.chat_message(name=username, sent=True).props(
                "bg-color=primary text-color=white"
            ):
                ui.markdown(text)
            typing = ui.chat_message(name="SmartLogix", sent=False).props(
                "bg-color=grey-2 text-color=grey-9"
            )
            with typing:
                with ui.row().classes("items-center gap-2"):
                    ui.spinner("dots", size="lg")
                    status_label = ui.label("Starting...").classes(
                        "text-xs text-slate-400 italic"
                    )
        _scroll_down()

        # Agent pipeline runs in a worker thread (run.io_bound); on_progress is
        # called from that thread, so it only writes a plain string into this
        # dict. The ui.timer below polls it from the UI's own event loop,
        # which is the safe place to touch NiceGUI elements.
        progress_state = {"stage": "Starting..."}

        def _on_progress(stage: str) -> None:
            progress_state["stage"] = stage

        def _poll_progress() -> None:
            status_label.text = progress_state["stage"]
            _scroll_down()

        progress_timer = ui.timer(0.3, _poll_progress)

        result = await run.io_bound(handle_request, text, session_id, auth_token, _on_progress)

        progress_timer.cancel()
        typing.clear()
        with typing:
            ui.markdown(result.get("final_answer", "(no response)"))
            trace = result.get("trace")
            if trace:
                with ui.expansion("🔍 Agent trace (evidence log)", icon="manage_search").classes(
                    "w-full text-xs mt-2"
                ):
                    ui.code(json.dumps(trace, indent=2, default=str), language="json").classes(
                        "w-full"
                    )
        _scroll_down()

        input_box.enable()
        send_button.enable()
        input_box.run_method("focus")

    with ui.footer().classes("bg-white border-t").style("border-color:#e2e8f0"):
        with ui.row().classes(
            "w-full max-w-3xl mx-auto items-center py-2 gap-2 my-2 px-2 bg-slate-50 "
            "rounded-full shadow-sm border border-slate-100"
        ):
            input_box = (
                ui.input(placeholder="Describe your delivery issue or ask a question...")
                .classes("flex-grow")
                .props("borderless dense")
                .on("keydown.enter", lambda: send_message())
            )
            send_button = ui.button(icon="send", on_click=lambda: send_message()).props(
                "round color=primary unelevated"
            )

    _scroll_down()


@ui.page("/knowledge")
def knowledge_page():
    """A dedicated page that talks to the Policy Agent (IR/RAG microservice)
    directly - separate from the 4-agent exception-resolution chat flow, so
    the retrieval agent can be demoed and tested entirely on its own."""
    ui.colors(primary=BRAND_PRIMARY)
    _inject_theme()

    if not app.storage.user.get("auth_token"):
        ui.navigate.to("/")
        return

    session_id = app.storage.user.get("session_id", "-")

    with ui.header().classes("items-center justify-between px-4 sl-header").style(
        f"background:{BRAND_DARK}"
    ):
        with ui.row().classes("items-center gap-2"):
            ui.button(icon="arrow_back", on_click=lambda: ui.navigate.to("/chat")).props(
                "flat color=white round dense"
            )
            with ui.row().classes("w-9 h-9 rounded-xl items-center justify-center bg-white/15"):
                ui.label("📖").classes("text-lg")
            ui.label("SmartLogix - Knowledge Base").classes("text-xl font-bold tracking-tight")
        ui.button("Back to chat", icon="chat", on_click=lambda: ui.navigate.to("/chat")).props(
            "flat color=white no-caps"
        )

    with ui.column().classes("w-full max-w-2xl mx-auto p-6 gap-1"):
        ui.label("Ask the Knowledge Base").classes("text-2xl font-bold text-slate-800")
        ui.label(
            "This goes straight to the Policy Agent (ChromaDB + RAG over the policy "
            "documents) - ask anything about refunds, delivery times, prohibited "
            "items, or data privacy."
        ).classes("text-sm text-slate-500 mb-4")

        with ui.row().classes("w-full items-center gap-2"):
            query_input = (
                ui.input(placeholder="e.g. What is your refund policy?")
                .classes("flex-grow")
                .props("outlined dense clearable")
            )
            ask_button = ui.button(icon="search", on_click=lambda: ask()).props(
                "round color=primary"
            )
        query_input.on("keydown.enter", lambda: ask())

        ui.label("Try:").classes("text-xs text-slate-400 mt-3")
        with ui.row().classes("gap-2 flex-wrap"):
            for question, _ in FAQ_ITEMS:
                ui.chip(question, on_click=lambda q=question: _ask_with(q)).props(
                    "outline color=primary clickable"
                ).classes("text-xs")

        result_area = ui.column().classes("w-full gap-2 mt-6")

        def _ask_with(question: str) -> None:
            query_input.set_value(question)
            ask()

        async def ask() -> None:
            query = (query_input.value or "").strip()
            if not query:
                return
            query_input.disable()
            ask_button.disable()
            result_area.clear()
            with result_area:
                with ui.row().classes("items-center gap-2"):
                    ui.spinner("dots", size="lg")
                    ui.label("Searching policy knowledge base...").classes(
                        "text-xs text-slate-400 italic"
                    )

            policy_result = await run.io_bound(call_policy_agent, query, session_id)

            result_area.clear()
            with result_area:
                with ui.card().classes("w-full p-4 rounded-xl shadow-sm"):
                    ui.markdown(policy_result.answer)
                    if policy_result.sources:
                        ui.label("Source: " + ", ".join(policy_result.sources)).classes(
                            "text-xs text-slate-400 mt-2"
                        )
                if policy_result.chunks:
                    with ui.expansion(
                        "🔍 Retrieved passages (RAG evidence)", icon="manage_search"
                    ).classes("w-full text-xs"):
                        for i, chunk in enumerate(policy_result.chunks, 1):
                            ui.markdown(f"**Passage {i}:**\n\n{chunk}").classes(
                                "text-xs text-slate-600 mb-2"
                            )

            query_input.enable()
            ask_button.enable()
            query_input.run_method("focus")


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(
        title="SmartLogix",
        favicon="📦",
        port=8080,
        storage_secret=UI_STORAGE_SECRET,
        reload=False,
    )
