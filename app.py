"""
SmartLogix - NiceGUI web UI.

Pure Python UI (no HTML/CSS/JS files to hand-write) on top of the same
coordinator/agents backend used by the group system. Run with:

    python app.py

Login: demo / Demo@123 (seeded automatically on first run).
"""

import json
import re
import urllib.parse
import uuid
from datetime import datetime
from pathlib import Path

from nicegui import ui, app, run

from src.config import UI_STORAGE_SECRET
from src.security.auth import seed_demo_user, verify_credentials, create_access_token
from src.coordinator import handle_request, get_session_history, call_policy_agent
from src.utils.tracking import get_order_status

seed_demo_user()

BRAND_PRIMARY = "#2563eb"
BRAND_DARK = "#1e3a8a"

EXAMPLE_PROMPTS = [
    "My order ORD10017 arrived damaged, the plates were broken",
    "Order ORD10256 came damaged, what happened?",
    "My delivery ORD10008 is very late, when will it arrive?",
    "I can't find my parcel, order ORD10007, it's been days",
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


def _svg_avatar(bg: str, glyph: str) -> str:
    """Builds a tiny inline SVG avatar as a data URI - hand-drawn flat vector
    glyphs (not emoji) so the icon renders identically on every OS/browser
    and matches the Material-icon look used everywhere else in the app."""
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">' \
          f'<rect width="64" height="64" rx="32" fill="{bg}"/>{glyph}</svg>'
    return "data:image/svg+xml," + urllib.parse.quote(svg)


_BOX_GLYPH = (
    '<path d="M20 27 L32 21 L44 27 L44 45 L32 51 L20 45 Z" '
    'fill="none" stroke="white" stroke-width="3" stroke-linejoin="round"/>'
    '<path d="M20 27 L32 33 L44 27 M32 33 L32 51" '
    'fill="none" stroke="white" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>'
)
_PERSON_GLYPH = (
    '<circle cx="32" cy="25" r="10" fill="white"/>'
    '<path d="M14 54 C14 38, 50 38, 50 54 Z" fill="white"/>'
)

BOT_AVATAR = _svg_avatar(BRAND_PRIMARY, _BOX_GLYPH)
USER_AVATAR = _svg_avatar("#64748b", _PERSON_GLYPH)
FAVICON_SVG = (
    f'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">'
    f'<rect width="64" height="64" rx="14" fill="{BRAND_PRIMARY}"/>{_BOX_GLYPH}</svg>'
)

# (material_icon, label, badge_classes)
OUTCOME_STYLES = {
    "full_refund": ("check_circle", "Full Refund Approved", "bg-green-50 text-green-700 border-green-200"),
    "partial_refund": ("hourglass_top", "Partial Refund Approved", "bg-amber-50 text-amber-700 border-amber-200"),
    "no_refund": ("cancel", "No Refund", "bg-red-50 text-red-700 border-red-200"),
    "escalated_to_human": ("support_agent", "Escalated to Human Review", "bg-blue-50 text-blue-700 border-blue-200"),
}

STATUS_STYLES = {
    "Delivered": ("check_circle", "Delivered", "bg-green-50 text-green-700 border-green-200"),
    "In Transit": ("local_shipping", "In Transit", "bg-blue-50 text-blue-700 border-blue-200"),
    "Delayed": ("schedule", "Delayed", "bg-amber-50 text-amber-700 border-amber-200"),
    "Damaged": ("warning", "Damaged", "bg-red-50 text-red-700 border-red-200"),
    "Lost": ("help", "Lost", "bg-red-50 text-red-700 border-red-200"),
}

NAV_ITEMS = [
    ("chat", "/chat", "Chat", "forum"),
    ("knowledge", "/knowledge", "Help Center", "menu_book"),
    ("track", "/track", "Track Order", "local_shipping"),
]

PRICING_TIERS = [
    {
        "name": "Free",
        "price": "$0",
        "period": "/month",
        "tagline": "For very small sellers",
        "features": ["10 resolutions / month", "Email support", "Basic order tracking"],
        "cta": "Get Started",
        "featured": False,
    },
    {
        "name": "Basic",
        "price": "$29",
        "period": "/month",
        "tagline": "For small delivery companies",
        "features": [
            "200 resolutions / month",
            "Priority email support",
            "Full tracking + Help Center",
        ],
        "cta": "Get Started",
        "featured": False,
    },
    {
        "name": "Pro",
        "price": "$99",
        "period": "/month",
        "tagline": "For medium businesses",
        "features": [
            "Unlimited resolutions",
            "24/7 priority support",
            "Advanced analytics",
            "API access (limited)",
        ],
        "cta": "Get Started",
        "featured": True,
    },
    {
        "name": "Enterprise",
        "price": "Custom",
        "period": "",
        "tagline": "For large logistics companies",
        "features": [
            "Everything in Pro",
            "Dedicated account manager",
            "Custom integration & SLA",
            "On-premise deployment option",
        ],
        "cta": "Contact Us",
        "featured": False,
    },
]

# Design tokens (CSS custom properties) that flip under body.body--dark, so
# every surface/text/border color in the app comes from one place instead of
# being hardcoded per element - this is what makes dark mode actually
# consistent rather than a per-element patch job.
_THEME_HEAD_HTML = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
  :root {
    --sl-grad-start: #f8fafc; --sl-grad-end: #eef2ff;
    --sl-surface: #ffffff; --sl-surface-2: #f8fafc;
    --sl-border: #e2e8f0;
    --sl-text: #1e293b; --sl-text-muted: #64748b; --sl-text-faint: #94a3b8;
    --sl-shadow: 0 1px 3px rgba(15, 23, 42, 0.08);
  }
  body.body--dark {
    --sl-grad-start: #0b1220; --sl-grad-end: #1a2332;
    --sl-surface: #1e293b; --sl-surface-2: #16202f;
    --sl-border: #334155;
    --sl-text: #f1f5f9; --sl-text-muted: #cbd5e1; --sl-text-faint: #94a3b8;
    --sl-shadow: 0 1px 3px rgba(0, 0, 0, 0.5);
  }

  body, .q-field, .q-btn, .q-item, .q-chat-message, .q-chip {
    font-family: 'Inter', -apple-system, sans-serif !important;
  }
  body {
    background: linear-gradient(180deg, var(--sl-grad-start) 0%, var(--sl-grad-end) 100%) !important;
    transition: background 0.25s ease;
  }
  ::-webkit-scrollbar { width: 8px; height: 8px; }
  ::-webkit-scrollbar-thumb { background: var(--sl-border); border-radius: 8px; }
  ::-webkit-scrollbar-track { background: transparent; }

  .sl-header { box-shadow: 0 2px 16px rgba(30, 58, 138, 0.25); }
  .sl-nav-active { background: rgba(255, 255, 255, 0.18) !important; }

  .sl-surface { background-color: var(--sl-surface) !important; }
  .sl-surface-2 { background-color: var(--sl-surface-2) !important; }
  .sl-border { border-color: var(--sl-border) !important; }
  .sl-text { color: var(--sl-text) !important; }
  .sl-text-muted { color: var(--sl-text-muted) !important; }
  .sl-text-faint { color: var(--sl-text-faint) !important; }

  .sl-card { transition: all 0.15s ease; }
  .sl-card:hover {
    background: rgba(37, 99, 235, 0.08) !important;
    border-color: #93c5fd !important;
    transform: translateX(3px);
  }

  .sl-result-card { transition: box-shadow 0.2s ease, transform 0.2s ease; }
  .sl-result-card:hover { box-shadow: 0 10px 28px rgba(15, 23, 42, 0.14) !important; }

  .q-message-text { border-radius: 16px !important; max-width: 75%; box-shadow: var(--sl-shadow); }
  .q-message-name { font-weight: 600 !important; }
  .sl-bot-bubble .q-message-text { background: var(--sl-surface) !important; color: var(--sl-text) !important; }
  .sl-bot-bubble .q-message-name, .sl-bot-bubble .q-message-stamp { color: var(--sl-text-muted) !important; }
  /* ui.markdown() renders its own <div class="nicegui-markdown">, and some
     nested tags (links, bold, etc.) carry their own explicit color that
     plain `inherit` didn't beat. Force every text node inside it to solid
     white in dark mode - no exceptions - so replies stay fully readable. */
  body.body--dark .nicegui-markdown,
  body.body--dark .nicegui-markdown * { color: #f8fafc !important; }

  /* ui.code() renders a <pre><code> block that doesn't wrap by default, so
     long JSON lines (e.g. long "reasoning"/"answer" strings in the agent
     trace) were overflowing past the chat bubble and off the visible
     screen. Force it to wrap and stay within its container instead. */
  .nicegui-code, .nicegui-code pre, .nicegui-code code {
    white-space: pre-wrap !important;
    word-break: break-word !important;
    overflow-wrap: anywhere !important;
    max-width: 100% !important;
  }

  @keyframes sl-fade-in {
    from { opacity: 0; transform: translateY(6px); }
    to { opacity: 1; transform: translateY(0); }
  }
  .q-message { animation: sl-fade-in 0.25s ease; }

  .sl-chip { transition: all 0.15s ease; }
  .sl-chip:hover { transform: translateY(-1px); }

  .sl-blob {
    position: fixed; border-radius: 9999px; filter: blur(80px);
    opacity: 0.35; z-index: 0; pointer-events: none;
  }
  .sl-pricing-card { transition: all 0.2s ease; }
  .sl-pricing-card:hover { transform: translateY(-4px); box-shadow: 0 16px 40px rgba(15,23,42,0.16) !important; }
  .sl-pricing-featured {
    border: 2px solid var(--q-primary) !important;
    box-shadow: 0 12px 32px rgba(37, 99, 235, 0.25) !important;
  }
</style>
"""


def _inject_theme() -> None:
    ui.add_head_html(_THEME_HEAD_HTML)


def _logout():
    app.storage.user.clear()
    ui.navigate.to("/")


def _toggle_dark(dark: ui.dark_mode) -> None:
    dark.toggle()
    app.storage.user["dark_mode"] = dark.value


def _set_debug_mode(value: bool) -> None:
    app.storage.user["debug_mode"] = value


def _page_header(active: str, username: str, dark: ui.dark_mode) -> None:
    """Shared top nav for every logged-in page (Chat / Help Center / Track
    Order), plus the dark-mode toggle and logout - keeps navigation and
    branding consistent across pages."""
    with ui.header().classes("items-center justify-between px-4 sl-header").style(
        f"background:{BRAND_DARK}"
    ):
        with ui.row().classes("items-center gap-3"):
            with ui.row().classes("w-9 h-9 rounded-xl items-center justify-center bg-white/15"):
                ui.icon("inventory_2", color="white").classes("text-lg")
            ui.label("SmartLogix").classes("text-xl font-bold tracking-tight mr-2")
            with ui.row().classes("items-center gap-1"):
                for key, path, label, icon in NAV_ITEMS:
                    classes = "text-xs rounded-lg" + (" sl-nav-active" if key == active else "")
                    ui.button(label, icon=icon, on_click=lambda p=path: ui.navigate.to(p)).props(
                        "flat dense no-caps color=white"
                    ).classes(classes)
        with ui.row().classes("items-center gap-3"):
            with ui.row().classes("items-center gap-1"):
                ui.icon("bug_report", color="white").classes("text-base opacity-80")
                ui.switch(
                    value=app.storage.user.get("debug_mode", False),
                    on_change=lambda e: _set_debug_mode(e.value),
                ).props("color=white dense size=sm").tooltip(
                    "Debug mode - show the agent trace under each reply"
                )
            ui.button(
                icon="dark_mode", on_click=lambda: _toggle_dark(dark)
            ).props("flat color=white round dense").tooltip("Toggle dark mode")
            ui.label(f"Signed in as {username}").classes("text-sm text-blue-100")
            ui.button("Log out", icon="logout", on_click=_logout).props(
                "flat color=white dense no-caps"
            )


def _render_outcome_banner(action: str | None) -> None:
    if not action or action not in OUTCOME_STYLES:
        return
    icon, label, classes = OUTCOME_STYLES[action]
    with ui.row().classes(
        f"items-center gap-1.5 text-xs font-bold px-3 py-1.5 rounded-full border w-fit mb-2 {classes}"
    ):
        ui.icon(icon).classes("text-sm")
        ui.label(label)


@ui.page("/")
def login_page():
    ui.colors(primary=BRAND_PRIMARY)

    if app.storage.user.get("auth_token"):
        ui.navigate.to("/chat")
        return

    _inject_theme()

    with ui.row().classes("w-72 h-72 sl-blob").style(
        f"top:-6rem; left:-6rem; background:{BRAND_PRIMARY}"
    ):
        pass
    with ui.row().classes("w-72 h-72 sl-blob").style(
        f"bottom:-6rem; right:-6rem; background:{BRAND_DARK}"
    ):
        pass

    with ui.column().classes("absolute-center items-center gap-1").style("z-index: 1"):
        with ui.card().classes("w-96 p-8 rounded-3xl shadow-2xl"):
            with ui.column().classes("items-center w-full mb-2"):
                with ui.row().classes(
                    "w-16 h-16 rounded-2xl items-center justify-center mb-3"
                ).style(f"background: linear-gradient(135deg, {BRAND_PRIMARY}, {BRAND_DARK})"):
                    ui.icon("inventory_2", color="white").classes("text-3xl")
                ui.label("SmartLogix").classes("text-3xl font-extrabold text-center w-full").style(
                    f"color:{BRAND_DARK}"
                )
                ui.label("Sri Lanka Delivery Exception Assistant").classes(
                    "text-sm sl-text-faint text-center w-full"
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
                "text-xs sl-text-faint text-center w-full mt-4"
            )

        ui.button(
            "View Pricing Plans",
            icon="payments",
            on_click=lambda: ui.navigate.to("/pricing"),
        ).props("flat no-caps color=primary").classes("mt-3")


@ui.page("/pricing")
def pricing_page():
    """Public pricing page - no login required, same as a real SaaS site.
    Mirrors the commercialization plan's tiers (report + this UI stay
    consistent)."""
    ui.colors(primary=BRAND_PRIMARY)
    _inject_theme()

    with ui.header().classes("items-center justify-between px-4 sl-header").style(
        f"background:{BRAND_DARK}"
    ):
        with ui.row().classes("items-center gap-3").on(
            "click", lambda: ui.navigate.to("/")
        ).style("cursor:pointer"):
            with ui.row().classes("w-9 h-9 rounded-xl items-center justify-center bg-white/15"):
                ui.icon("inventory_2", color="white").classes("text-lg")
            ui.label("SmartLogix").classes("text-xl font-bold tracking-tight")
        ui.button("Log in", icon="login", on_click=lambda: ui.navigate.to("/")).props(
            "flat color=white no-caps"
        )

    with ui.column().classes("w-full items-center p-8 gap-2"):
        ui.label("Simple, transparent pricing").classes(
            "text-3xl font-extrabold sl-text text-center"
        )
        ui.label(
            "Pick the plan that fits your delivery volume. Upgrade or downgrade anytime."
        ).classes("text-sm sl-text-muted text-center mb-8")

        with ui.row().classes("w-full max-w-6xl gap-4 justify-center items-stretch flex-wrap"):
            for tier in PRICING_TIERS:
                card_classes = (
                    "w-64 p-6 rounded-2xl shadow-md sl-pricing-card flex flex-col"
                )
                if tier["featured"]:
                    card_classes += " sl-pricing-featured"
                with ui.card().classes(card_classes):
                    if tier["featured"]:
                        ui.label("MOST POPULAR").classes(
                            "text-[10px] font-bold text-white bg-primary px-2 py-1 "
                            "rounded-full self-start mb-2 tracking-wider"
                        )
                    ui.label(tier["name"]).classes("text-lg font-bold sl-text")
                    ui.label(tier["tagline"]).classes("text-xs sl-text-faint mb-3")
                    with ui.row().classes("items-baseline gap-1 mb-4"):
                        ui.label(tier["price"]).classes("text-3xl font-extrabold sl-text")
                        if tier["period"]:
                            ui.label(tier["period"]).classes("text-sm sl-text-faint")
                    with ui.column().classes("gap-2 mb-6 flex-grow"):
                        for feature in tier["features"]:
                            with ui.row().classes("items-start gap-2"):
                                ui.icon("check_circle", color="primary").classes("text-base mt-0.5")
                                ui.label(feature).classes("text-xs sl-text-muted")
                    ui.button(
                        tier["cta"], on_click=lambda: ui.navigate.to("/")
                    ).classes("w-full rounded-xl").props(
                        f"{'unelevated color=primary' if tier['featured'] else 'outline color=primary'}"
                    )

        with ui.card().classes("w-full max-w-3xl p-5 rounded-2xl mt-8 sl-surface-2"):
            with ui.row().classes("items-center gap-3"):
                ui.icon("api", color="primary").classes("text-2xl")
                with ui.column().classes("gap-0"):
                    ui.label("API Licensing").classes("text-sm font-bold sl-text")
                    ui.label(
                        "$0.10 - $0.20 per request - for platforms that want to "
                        "embed SmartLogix's exception-resolution as a service."
                    ).classes("text-xs sl-text-muted")


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

    dark = ui.dark_mode(app.storage.user.get("dark_mode", False))
    _page_header("chat", username, dark)

    with ui.left_drawer().classes("sl-surface-2 p-4").style("border-right: 1px solid var(--sl-border)"):
        ui.label("TRY AN EXAMPLE").classes(
            "font-bold text-[11px] tracking-wider sl-text-faint mb-2"
        )
        for example in EXAMPLE_PROMPTS:
            with ui.row().classes(
                "sl-card sl-surface sl-border w-full items-start gap-2 p-3 rounded-xl "
                "cursor-pointer mb-2 border shadow-sm"
            ).on("click", lambda e=example: send_message(e)):
                ui.icon("chat_bubble_outline", color="primary").classes("text-sm mt-0.5")
                ui.label(example).classes("text-xs sl-text-muted leading-snug")

        ui.separator().classes("my-4")
        ui.label("Every reply includes an expandable agent trace — useful for the "
                  "security audit assignment too.").classes("text-xs sl-text-faint")

    scroll_area = ui.scroll_area().classes("w-full h-[calc(100vh-160px)]")
    with scroll_area:
        chat_container = ui.column().classes("w-full max-w-3xl mx-auto gap-1 p-4")

    with chat_container:
        empty_state = ui.column().classes("w-full items-center justify-center gap-2 py-24")
        with empty_state:
            ui.icon("inventory_2").classes("text-6xl text-primary")
            ui.label("Welcome to SmartLogix").classes("text-2xl font-bold sl-text")
            ui.label(
                "Describe a delivery issue or ask a policy question to get started."
            ).classes("text-sm sl-text-faint")
        empty_state.set_visibility(not bool(history))

        for turn in history:
            is_user = turn["role"] == "user"
            msg = ui.chat_message(
                name=username if is_user else "SmartLogix",
                sent=is_user,
                stamp=turn.get("timestamp"),
                avatar=USER_AVATAR if is_user else BOT_AVATAR,
            )
            if is_user:
                msg.props("bg-color=primary text-color=white")
            else:
                msg.classes("sl-bot-bubble")
            with msg:
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
        now_stamp = datetime.now().strftime("%H:%M")

        with chat_container:
            with ui.chat_message(
                name=username, sent=True, stamp=now_stamp, avatar=USER_AVATAR
            ).props("bg-color=primary text-color=white"):
                ui.markdown(text)
            typing = ui.chat_message(
                name="SmartLogix", sent=False, stamp=now_stamp, avatar=BOT_AVATAR
            ).classes("sl-bot-bubble")
            with typing:
                with ui.row().classes("items-center gap-2"):
                    ui.spinner("dots", size="lg")
                    status_label = ui.label("Starting...").classes(
                        "text-xs sl-text-faint italic"
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
            _render_outcome_banner(result.get("action"))
            ui.markdown(result.get("final_answer", "(no response)"))
            if result.get("redirect_to_knowledge"):
                ui.button(
                    "Open Help Center",
                    icon="menu_book",
                    on_click=lambda: ui.navigate.to("/knowledge"),
                ).props("unelevated color=primary dense no-caps").classes("mt-2")
            trace = result.get("trace")
            if trace and app.storage.user.get("debug_mode", False):
                with ui.expansion("Agent trace (evidence log)", icon="manage_search").classes(
                    "w-full text-xs mt-2"
                ):
                    ui.code(json.dumps(trace, indent=2, default=str), language="json").classes(
                        "w-full"
                    )
        _scroll_down()

        input_box.enable()
        send_button.enable()
        input_box.run_method("focus")

    with ui.footer().classes("sl-surface border-t").style("border-color:var(--sl-border)"):
        with ui.row().classes(
            "w-full max-w-3xl mx-auto items-center py-2 gap-2 my-2 px-2 sl-surface-2 sl-border "
            "rounded-full shadow-sm border"
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

    username = app.storage.user["username"]
    session_id = app.storage.user.get("session_id", "-")

    dark = ui.dark_mode(app.storage.user.get("dark_mode", False))
    _page_header("knowledge", username, dark)

    with ui.column().classes("w-full max-w-2xl mx-auto p-6 gap-1"):
        ui.label("Search the Help Center").classes("text-2xl font-bold sl-text")
        ui.label(
            "This goes straight to the Policy Agent (ChromaDB + RAG over the policy "
            "documents) - ask anything about refunds, delivery times, prohibited "
            "items, or data privacy."
        ).classes("text-sm sl-text-muted mb-4")

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

        ui.label("Try:").classes("text-xs sl-text-faint mt-3")
        with ui.row().classes("gap-2 flex-wrap"):
            for question, _ in FAQ_ITEMS:
                ui.chip(question, on_click=lambda q=question: _ask_with(q)).props(
                    "outline color=primary clickable"
                ).classes("text-xs sl-chip")

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
                    ui.label("Searching the Help Center...").classes(
                        "text-xs sl-text-faint italic"
                    )

            policy_result = await run.io_bound(call_policy_agent, query, session_id)

            result_area.clear()
            with result_area:
                with ui.card().classes("w-full p-4 rounded-xl shadow-sm sl-result-card"):
                    ui.markdown(policy_result.answer)
                    if policy_result.sources:
                        ui.label("Source: " + ", ".join(policy_result.sources)).classes(
                            "text-xs sl-text-faint mt-2"
                        )
                if policy_result.chunks:
                    with ui.expansion(
                        "Retrieved passages (RAG evidence)", icon="manage_search"
                    ).classes("w-full text-xs"):
                        for i, chunk in enumerate(policy_result.chunks, 1):
                            ui.markdown(f"**Passage {i}:**\n\n{chunk}").classes(
                                "text-xs sl-text-muted mb-2"
                            )

            query_input.enable()
            ask_button.enable()
            query_input.run_method("focus")


@ui.page("/track")
def track_page():
    """Plain order-status lookup - a direct data read (src/utils/tracking.py),
    no agent/LLM call involved, so it's instant."""
    ui.colors(primary=BRAND_PRIMARY)
    _inject_theme()

    if not app.storage.user.get("auth_token"):
        ui.navigate.to("/")
        return

    username = app.storage.user["username"]
    dark = ui.dark_mode(app.storage.user.get("dark_mode", False))
    _page_header("track", username, dark)

    with ui.column().classes("w-full max-w-xl mx-auto p-6 gap-1"):
        ui.label("Track Your Order").classes("text-2xl font-bold sl-text")
        ui.label(
            "Instant status lookup - a plain data read, no LLM call needed for this."
        ).classes("text-sm sl-text-muted mb-4")

        with ui.row().classes("w-full items-center gap-2"):
            order_input = (
                ui.input(placeholder="e.g. ORD10017")
                .classes("flex-grow")
                .props("outlined dense clearable")
            )
            ui.button(icon="search", on_click=lambda: track()).props("round color=primary")
        order_input.on("keydown.enter", lambda: track())

        result_area = ui.column().classes("w-full gap-2 mt-6")

        def _empty_hint() -> None:
            with ui.column().classes("w-full items-center gap-2 py-16"):
                ui.icon("local_shipping", size="2.5rem").classes("sl-text-faint")
                ui.label("Enter an order ID above to see its status.").classes(
                    "text-sm sl-text-faint"
                )

        with result_area:
            _empty_hint()

        def _detail_row(label: str, value: str) -> None:
            with ui.row().classes("w-full justify-between text-sm"):
                ui.label(label).classes("sl-text-faint")
                ui.label(str(value)).classes("sl-text font-medium")

        def track() -> None:
            order_id = (order_input.value or "").strip()
            result_area.clear()
            if not order_id:
                with result_area:
                    _empty_hint()
                return
            info = get_order_status(order_id)
            with result_area:
                if not info:
                    ui.label(f"No order found for '{order_id}'.").classes(
                        "text-sm text-red-500"
                    )
                    return
                status_icon, status_label, classes = STATUS_STYLES.get(
                    info["status"],
                    ("help", info["status"], "bg-slate-100 text-slate-700 border-slate-200"),
                )
                with ui.card().classes("w-full p-5 rounded-xl shadow-sm sl-result-card gap-3"):
                    with ui.row().classes("items-center justify-between w-full"):
                        ui.label(info["order_id"]).classes("text-lg font-bold sl-text")
                        with ui.row().classes(
                            f"items-center gap-1 text-xs font-bold px-3 py-1 rounded-full border {classes}"
                        ):
                            ui.icon(status_icon).classes("text-sm")
                            ui.label(status_label)
                    ui.separator()
                    with ui.column().classes("gap-1 w-full"):
                        _detail_row("Item", info["item_name"])
                        _detail_row(
                            "Route", f"{info['origin_city']} → {info['destination_city']}"
                        )
                        _detail_row("Courier", info["courier_name"])
                        _detail_row("Order date", info["order_date"])
                        _detail_row("Packaging", info["packaging_label"])


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(
        title="SmartLogix",
        favicon=FAVICON_SVG,
        port=8080,
        storage_secret=UI_STORAGE_SECRET,
        reload=False,
    )
