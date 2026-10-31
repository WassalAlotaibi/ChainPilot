
"""
ChainPilot — Procurement Operations Frontend

Run from the project root:
    python -m streamlit run frontend/app.py

Pages:
    Dashboard
    Factory Inventory
    Suppliers
    Settings

Backend endpoints remain unchanged.
"""

import json
import os
import uuid
from pathlib import Path

import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv


# ============================================================
# CONFIGURATION
# ============================================================

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

API_URL = os.getenv(
    "CHAINPILOT_API",
    "http://127.0.0.1:8000"
).rstrip("/")

SUPPLIER_SECRET = os.getenv(
    "SUPPLIER_WEBHOOK_SECRET", ""
)

AUTO_INVENTORY = os.getenv(
    "AUTO_AGENT_ON_INVENTORY", "false"
).lower() == "true"

AUTO_CANCEL = os.getenv(
    "DEMO_AUTO_CONFIRM_CANCELLATION", "false"
).lower() == "true"

ACTIVE_STATUSES = {
    "pending_approval",
    "placed",
    "delayed",
    "cancellation_requested",
    "shipped",
    "awaiting_receipt",
    "partially_received",
}

RECEIVABLE_STATUSES = {
    "placed",
    "delayed",
    "shipped",
    "awaiting_receipt",
    "partially_received",
}

PAGES = [
    "Dashboard",
    "Factory Inventory",
    "Suppliers",
    "Settings",
]


# ============================================================
# PAGE AND THEME
# ============================================================

st.set_page_config(
    page_title="ChainPilot | Procurement",
    page_icon=":material/hub:",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Do not override Streamlit's background.
# These colors work with both native light and dark modes.

st.markdown(
    """
<style>

/* Main layout */

.block-container {
    max-width: 1240px;
    padding-top: 1.5rem;
    padding-bottom: 3rem;
}

/* Typography */

h1 {
    font-size: 2.05rem !important;
    font-weight: 760 !important;
    letter-spacing: -.035em;
}

h2 {
    font-size: 1.35rem !important;
    font-weight: 700 !important;
    letter-spacing: -.02em;
    margin-top: 1rem;
}

h3 {
    font-size: 1.03rem !important;
    font-weight: 660 !important;
}

.cp-eyebrow {
    font-size: .73rem;
    font-weight: 750;
    letter-spacing: .11em;
    color: #168d89;
    margin-bottom: 5px;
}

.cp-description {
    font-size: .9rem;
    opacity: .75;
    line-height: 1.55;
    margin-top: -7px;
    margin-bottom: 20px;
}

.cp-small {
    font-size: .78rem;
    opacity: .72;
    line-height: 1.5;
}

.cp-heading {
    font-size: .98rem;
    font-weight: 700;
    margin-top: 12px;
    margin-bottom: 8px;
}

/* Sidebar */

[data-testid="stSidebar"] {
    border-right: 1px solid
        color-mix(in srgb, currentColor 12%, transparent);
}

.cp-brand {
    padding: 10px 1px 20px;
}

.cp-brand-name {
    font-size: 1.27rem;
    font-weight: 800;
    letter-spacing: -.025em;
}

.cp-brand-desc {
    font-size: .78rem;
    opacity: .68;
    margin-top: 3px;
}

.cp-nav-heading {
    font-size: .69rem;
    letter-spacing: .11em;
    font-weight: 750;
    opacity: .6;
    margin: 12px 0 12px;
}

[data-testid="stSidebar"] .stButton button {
    width: 100%;
    justify-content: flex-start !important;
    text-align: left !important;
    min-height: 43px !important;
    padding: 9px 15px !important;
    border-radius: 9px !important;
    background: transparent !important;
    border: 1px solid transparent !important;
    box-shadow: none !important;
    color: inherit !important;
    font-weight: 550 !important;
}

/* No inline icons in navigation:
   prevents the icon/label misalignment. */

[data-testid="stSidebar"] .stButton button p {
    margin: 0 !important;
    line-height: 1.35 !important;
}

[data-testid="stSidebar"] .stButton button:hover {
    background:
        color-mix(in srgb, currentColor 7%, transparent)
        !important;
}

.cp-sidebar-divider {
    border-top: 1px solid
        color-mix(in srgb, currentColor 12%, transparent);
    margin-top: 24px;
    padding-top: 17px;
}

.cp-monitor-heading {
    font-size: .69rem;
    font-weight: 750;
    opacity: .65;
    letter-spacing: .09em;
}

.cp-monitor-value {
    font-size: .88rem;
    margin-top: 9px;
    font-weight: 650;
}

.cp-monitor-hint {
    font-size: .76rem;
    opacity: .65;
    margin-top: 6px;
    line-height: 1.6;
}

/* Metrics */

[data-testid="stMetric"] {
    border: 1px solid
        color-mix(in srgb, currentColor 13%, transparent);
    border-radius: 13px;
    padding: 17px 18px;
    background:
        color-mix(in srgb, currentColor 2%, transparent);
}

[data-testid="stMetricLabel"] {
    font-size: .81rem;
    font-weight: 600;
    opacity: .78;
}

[data-testid="stMetricValue"] {
    font-size: 1.45rem;
    font-variant-numeric: tabular-nums;
    letter-spacing: -.02em;
}

/* Buttons */

button[kind="primary"] {
    background: #087f80 !important;
    border-color: #087f80 !important;
    color: white !important;
}

button[kind="primary"]:hover {
    background: #096d70 !important;
    border-color: #096d70 !important;
}

/* Inputs */

[data-testid="stTextInput"] input {
    direction: ltr !important;
    text-align: left !important;
    font-variant-numeric: tabular-nums;
}

/* Tables */

[data-testid="stDataFrame"] {
    border-radius: 11px;
    overflow: hidden;
}

/* Messages */

[data-testid="stAlert"] {
    border-radius: 10px;
}

/* Smaller explanatory boxes */

.cp-summary {
    border-left: 3px solid #0e9292;
    padding: 8px 14px;
    margin: 12px 0;
    font-size: .89rem;
}

</style>
""",
    unsafe_allow_html=True,
)


# ============================================================
# API HELPER
# ============================================================

def api(method, endpoint, timeout=40, **kwargs):
    try:
        response = requests.request(
            method,
            API_URL + endpoint,
            timeout=timeout,
            **kwargs,
        )

        response.raise_for_status()
        return response.json()

    except requests.RequestException as error:
        message = str(error)

        if error.response is not None:
            try:
                body = error.response.json()
                message = str(body.get("detail", body))
            except (ValueError, TypeError):
                message = error.response.text[:300]

        st.error(f"Request failed: {message}")
        st.stop()


def money(value):
    return f"{float(value or 0):,.0f} SAR"


def decimal_money(value):
    return f"{float(value or 0):,.2f}"


def pretty(value):
    return str(
        value or "Unknown"
    ).replace("_", " ").capitalize()


def log_details(event):
    raw = event.get("details") or {}

    if isinstance(raw, dict):
        return raw

    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def notify(message, icon="✅"):
    st.session_state["cp_notification"] = (
        message,
        icon,
    )
    st.rerun()


def show_notification():
    result = st.session_state.pop(
        "cp_notification", None
    )

    if result:
        message, icon = result
        st.toast(message, icon=icon)


# ============================================================
# DISPLAY HELPERS
# ============================================================

def status_color(value):
    text = str(value).lower()

    if any(word in text for word in [
        "cancelled",
        "failed",
        "rejected",
        "blocked",
        "exhausted",
    ]):
        return "rgba(215,73,76,.16)"

    if any(word in text for word in [
        "delayed",
        "pending",
        "requested",
        "waiting",
        "limited",
        "risk",
    ]):
        return "rgba(220,151,45,.19)"

    if any(word in text for word in [
        "received",
        "approved",
        "eligible",
        "completed",
        "ready",
    ]):
        return "rgba(29,155,113,.16)"

    return "rgba(41,122,165,.12)"


def display_table(rows, status_column=None):
    if not rows:
        st.caption("No records to show.")
        return

    frame = pd.DataFrame(rows)

    if status_column and status_column in frame.columns:

        def highlight(row):
            color = status_color(row[status_column])

            return [
                f"background-color: {color}"
                if column == status_column
                else ""
                for column in row.index
            ]

        st.dataframe(
            frame.style.apply(
                highlight,
                axis=1,
            ),
            hide_index=True,
            use_container_width=True,
        )

    else:
        st.dataframe(
            frame,
            hide_index=True,
            use_container_width=True,
        )


def order_rows(orders):
    return [
        {
            "Order": f"#{order['id']}",
            "Component": order["component"],
            "Supplier": order["supplier"],
            "Ordered": int(order["quantity"]),
            "Received": int(order["received_quantity"]),
            "Cost (SAR)": decimal_money(
                order["total_cost"]
            ),
            "Status": pretty(order["status"]),
        }
        for order in orders
    ]


def outstanding_commitment(orders):
    return sum(
        float(order.get("unit_price") or 0)
        * int(order.get("outstanding_quantity") or 0)
        for order in orders
        if order.get("status") in ACTIVE_STATUSES
    )


def shortage_reason(
    component,
    suppliers,
    policy,
    budget_left,
):
    available = [
        supplier
        for supplier in suppliers
        if (
            supplier["component"] == component["component"]
            and int(supplier["available"]) > 0
        )
    ]

    if not available:
        return (
            "Supplier stock unavailable",
            "No supplier currently has available units.",
        )

    approved = [
        supplier
        for supplier in available
        if supplier["approved"]
    ]

    if not approved:
        return (
            "Suppliers paused",
            "Stock exists, but stocked suppliers "
            "are unavailable for new orders.",
        )

    eligible = [
        supplier
        for supplier in approved
        if (
            int(supplier["delivery_days"])
            <= int(policy["max_delivery_days"])
        )
    ]

    if not eligible:
        return (
            "Delivery limit",
            "Available suppliers do not meet "
            "the maximum delivery time.",
        )

    if budget_left <= 0:
        return (
            "Budget exhausted",
            "Existing commitments use the purchasing budget.",
        )

    cheapest = min(
        float(s["unit_price"])
        for s in eligible
    )

    if budget_left < cheapest:
        return (
            "Budget limited",
            "Remaining budget cannot cover one unit.",
        )

    needed = int(component["uncovered_shortage"])

    quantity = sum(
        int(s["available"])
        for s in eligible
    )

    if quantity < needed:
        return (
            "Supplier stock limited",
            f"Only {quantity} eligible units "
            f"are available for {needed} needed.",
        )

    return (
        "Ready to evaluate",
        "Suppliers have eligible stock. "
        "ChainPilot can evaluate procurement.",
    )


# ============================================================
# RECOVERY DECISION HELPERS
# ============================================================

def latest_recovery_decisions(records):
    latest = {}

    for record in records:
        latest.setdefault(
            record.get("order_id"),
            record,
        )

    return latest


def recovery_summary(record, orders_by_id):
    order_id = record.get("order_id")

    order = orders_by_id.get(
        order_id, {}
    )

    decision = record.get("decision")
    current_status = order.get("status")

    if decision == "request_cancellation":
        if current_status == "cancelled":
            title = "Cancellation confirmed"
        elif current_status == "cancellation_requested":
            title = "Waiting for supplier confirmation"
        else:
            title = "Cancellation requested"

    elif decision == "keep_order":
        title = "Keep current order"

    elif decision == "cancellation_confirmed":
        title = "Cancellation confirmed"

    else:
        title = pretty(decision)

    explanation = record.get(
        "reason",
        "No explanation was saved.",
    )

    return title, explanation


def show_recent_recovery(
    records,
    orders,
    limit=2,
):
    if not records:
        st.caption(
            "No supplier recovery decisions recorded."
        )
        return

    lookup = {
        order["id"]: order
        for order in orders
    }

    for record in records[:limit]:
        order_id = record.get("order_id")
        title, explanation = recovery_summary(
            record,
            lookup,
        )

        with st.container(border=True):
            st.markdown(
                f"**Order #{order_id} — {title}**"
            )
            st.write(explanation)

            st.caption(
                f"Policy: {record.get('policy', 'Not recorded')} "
                f"· Trigger: {pretty(record.get('trigger'))}"
            )


# ============================================================
# AGENT RESULTS
# ============================================================

def show_agent_result(result):
    trace = result.get("trace") or []

    purchases = []
    issues = []
    comparisons = []

    for tool in trace:
        name = tool.get("tool")

        if name == "rank_suppliers":
            comparisons.append(tool)

        if (
            name == "execute_procurement"
            and isinstance(tool.get("result"), dict)
        ):
            actions = tool["result"].get("actions") or []

            for action in actions:
                if action.get("order_id") is not None:
                    purchases.append(action)
                else:
                    issues.append(action)

    status = result.get("status", "unknown")

    if status == "completed":
        st.success(
            "ChainPilot completed its evaluation."
        )
    elif status == "failed":
        st.error(
            "ChainPilot evaluation failed. "
            "Check the details below."
        )
    else:
        st.warning(
            f"Evaluation status: {pretty(status)}"
        )

    if purchases:
        total = sum(
            float(item.get("total_cost") or 0)
            for item in purchases
        )

        quantity = sum(
            int(item.get("quantity") or 0)
            for item in purchases
        )

        st.markdown(
            f"**Purchased {quantity} units — "
            f"{money(total)} committed**"
        )

        display_table([
            {
                "Order": f"#{item['order_id']}",
                "Component": item.get("component"),
                "Supplier": item.get("supplier"),
                "Units": item.get("quantity"),
                "Cost (SAR)": decimal_money(
                    item.get("total_cost")
                ),
                "Decision": pretty(
                    item.get("action")
                ),
            }
            for item in purchases
        ], "Decision")

    if issues:
        for issue in issues:
            st.warning(
                f"{issue.get('component')}: "
                f"{issue.get('uncovered_quantity')} "
                f"units remain unfulfilled. "
                f"{issue.get('reason', '')}"
            )

    if not purchases and not issues:
        st.info(
            "No new orders created during this evaluation. "
            "Existing stock and orders may already "
            "cover current demand."
        )

    with st.expander(
        "View full procurement evaluation",
        expanded=False,
    ):
        st.markdown(
            result.get("summary")
            or "No AI explanation returned."
        )

    with st.expander(
        "Supplier comparisons and technical details",
        expanded=False,
    ):
        for comparison in comparisons:
            args = comparison.get("arguments") or {}

            st.markdown(
                f"**{args.get('component', 'Component')}**"
            )

            if isinstance(comparison.get("result"), list):
                display_table(
                    comparison["result"]
                )

        st.json(trace)


def show_automatic_activity(logs):
    starts = [
        event
        for event in logs
        if (
            event.get("action") == "agent_started"
            and log_details(event).get("source")
            == "automatic"
        )
    ]

    if not starts:
        st.caption(
            "No automatic evaluations recorded."
        )
        return

    for event in starts[:3]:
        metadata = log_details(event)
        run_id = metadata.get("run_id")

        if not run_id:
            continue

        related = sorted(
            [
                item
                for item in logs
                if log_details(item).get("run_id")
                == run_id
            ],
            key=lambda item: item.get("id", 0),
        )

        final = next(
            (
                item
                for item in reversed(related)
                if item.get("action") in {
                    "agent_completed",
                    "agent_failed",
                    "agent_incomplete",
                }
            ),
            None,
        )

        state = (
            pretty(final["action"].replace("agent_", ""))
            if final
            else "Running"
        )

        title = metadata.get(
            "trigger",
            "Automatic evaluation",
        )

        with st.expander(
            f"{title} — {state}"
        ):
            for step in related:
                if step.get("action") == "agent_tool_call":
                    data = log_details(step)

                    st.write(
                        f"**{pretty(data.get('tool'))}:** "
                        f"{data.get('explanation', 'Tool completed.')}"
                    )

            if final:
                final_data = log_details(final)

                if final["action"] == "agent_failed":
                    st.error(
                        final_data.get("summary")
                        or "Automatic evaluation failed."
                    )
                else:
                    st.markdown(
                        final_data.get("summary")
                        or "Evaluation completed."
                    )


# ============================================================
# ACTIVITY FEED
# ============================================================

def activity_description(event, order_lookup):
    action = event.get("action")
    data = log_details(event)
    order_id = data.get("order_id")

    if action == "procurement_order":
        return (
            f"Ordered {data.get('quantity')} "
            f"{data.get('component')} from "
            f"{data.get('supplier')} — "
            f"{money(data.get('total_cost'))}"
        )

    if action == "order_approved":
        return f"Manager approved order #{order_id}"

    if action == "warehouse_receipt":
        return (
            f"Received {data.get('quantity_added')} "
            f"units for order #{order_id}"
        )

    if action == "supplier_event":
        supplier = order_lookup.get(
            order_id, {}
        ).get("supplier", "Supplier")

        return (
            f"{supplier} reported "
            f"{pretty(data.get('event_type'))} "
            f"for order #{order_id}"
        )

    if action == "recovery_decision":
        return (
            f"Order #{order_id}: "
            f"{pretty(data.get('decision'))} — "
            f"{data.get('reason', '')}"
        )

    if action == "recovery_cancellation_confirmed":
        return (
            f"Cancellation confirmed for order #{order_id}"
        )

    if action == "procurement_escalation":
        return (
            f"{data.get('component')} still unfulfilled: "
            f"{data.get('reason', '')}"
        )

    if action == "supplier_simulated_restock":
        return (
            f"Demo supplier replenished "
            f"{data.get('units_added')} units"
        )

    if action == "agent_completed":
        return "ChainPilot completed an evaluation"

    if action == "agent_failed":
        return "ChainPilot evaluation failed"

    return None


# ============================================================
# NAVIGATION — TEXT ONLY FOR RELIABLE ALIGNMENT
# ============================================================

if "cp_page" not in st.session_state:
    st.session_state.cp_page = "Dashboard"

if st.session_state.get("cp_next_page"):
    st.session_state.cp_page = (
        st.session_state.pop("cp_next_page")
    )


def navigate(destination):
    st.session_state.cp_next_page = destination
    st.rerun()


with st.sidebar:
    logo = (
        ROOT
        / "frontend"
        / "assets"
        / "logo.png"
    )

    if logo.exists():
        st.image(str(logo), width=54)

    st.markdown(
        '<div class="cp-brand">'
        '<div class="cp-brand-name">ChainPilot</div>'
        '<div class="cp-brand-desc">'
        'Autonomous procurement'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="cp-nav-heading">WORKSPACE</div>',
        unsafe_allow_html=True,
    )

    navigation = [
        ("Dashboard", "dashboard"),
        ("Factory Inventory", "inventory"),
        ("Suppliers", "suppliers"),
        ("Settings", "settings"),
    ]

    for title, key in navigation:
        if st.button(
            title,
            key=f"cp_nav_{key}",
            use_container_width=True,
        ):
            navigate(title)

        if title == st.session_state.cp_page:
            st.markdown(
                f"""
<style>
.st-key-cp_nav_{key} button {{
    background: rgba(8,127,128,.14) !important;
    border-left: 3px solid #087f80 !important;
    font-weight: 720 !important;
    padding-left: 12px !important;
}}
</style>
""",
                unsafe_allow_html=True,
            )

    status = (
        "Automatic"
        if AUTO_INVENTORY
        else "Manual"
    )

    hint = (
        "Stock changes can trigger ChainPilot."
        if AUTO_INVENTORY
        else "Run ChainPilot from the Dashboard."
    )

    st.markdown(
        '<div class="cp-sidebar-divider">'
        '<div class="cp-monitor-heading">'
        'INVENTORY MONITORING'
        '</div>'
        f'<div class="cp-monitor-value">{status}</div>'
        f'<div class="cp-monitor-hint">{hint}</div>'
        '</div>',
        unsafe_allow_html=True,
    )

show_notification()

page = st.session_state.cp_page


# ============================================================
# PAGE 1 — DASHBOARD
# ============================================================

if page == "Dashboard":

    st.markdown(
        '<div class="cp-eyebrow">OPERATIONS</div>',
        unsafe_allow_html=True,
    )

    st.title("Factory Dashboard")

    st.markdown(
        '<div class="cp-description">'
        'Monitor factory demand, supplier disruptions, '
        'and ChainPilot purchasing decisions.'
        '</div>',
        unsafe_allow_html=True,
    )

    inventory = api("GET", "/inventory/")
    orders = api("GET", "/procurement/orders")
    suppliers = api("GET", "/suppliers/")
    policy = api("GET", "/policies/")
    recovery = api("GET", "/recovery/decisions")
    logs = api("GET", "/activity")

    order_lookup = {
        order["id"]: order
        for order in orders
    }

    budget_left = max(
        0,
        float(policy["max_budget"])
        - outstanding_commitment(orders),
    )

    shortages = [
        item
        for item in inventory
        if item["uncovered_shortage"] > 0
    ]

    risks = [
        order
        for order in orders
        if order["status"] in {
            "delayed",
            "cancellation_requested",
        }
    ]

    pending_approvals = [
        order
        for order in orders
        if order["status"] == "pending_approval"
    ]

    # --------------------------------------------------------
    # OVERVIEW
    # --------------------------------------------------------

    metrics = st.columns(4)

    metrics[0].metric(
        "Unfulfilled units",
        sum(
            item["uncovered_shortage"]
            for item in shortages
        ),
    )

    metrics[1].metric(
        "Supplier risks",
        len(risks),
    )

    metrics[2].metric(
        "Approvals needed",
        len(pending_approvals),
    )

    metrics[3].metric(
        "Budget available",
        money(budget_left),
    )

    if shortages:
        st.error(
            "Some factory demand is not covered. "
            "Review the shortages below."
        )

    elif risks:
        st.warning(
            "Some supplier orders have delivery "
            "or cancellation risks."
        )

    elif pending_approvals:
        st.warning(
            "Purchase orders are awaiting manager approval."
        )

    else:
        st.success(
            "Factory demand is covered. "
            "No active supplier risks or pending approvals."
        )

    # --------------------------------------------------------
    # SHORTAGES
    # --------------------------------------------------------

    st.subheader("Needs attention")

    shortage_rows = []

    for item in shortages:
        status, reason = shortage_reason(
            item,
            suppliers,
            policy,
            budget_left,
        )

        shortage_rows.append({
            "Component": item["component"],
            "Missing": item["uncovered_shortage"],
            "Already ordered": item["ordered_or_pending"],
            "Status": status,
            "Explanation": reason,
        })

    display_table(shortage_rows, "Status")

    # --------------------------------------------------------
    # SUPPLIER RECOVERY
    # --------------------------------------------------------

    st.subheader("Supplier disruptions")

    latest = latest_recovery_decisions(
        recovery
    )

    risk_rows = []

    for order in risks:
        record = latest.get(order["id"], {})

        if record:
            outcome, explanation = recovery_summary(
                record,
                order_lookup,
            )
        else:
            outcome = "Awaiting review"
            explanation = (
                "No recovery decision recorded yet."
            )

        risk_rows.append({
            "Order": f"#{order['id']}",
            "Supplier": order["supplier"],
            "Component": order["component"],
            "Delivery (days)": order.get(
                "expected_delivery_days"
            ),
            "Decision": outcome,
            "Why": explanation,
        })

    display_table(risk_rows, "Decision")

    cancelled = [
        order
        for order in orders
        if order["status"] == "cancelled"
    ]

    if cancelled:
        st.markdown(
            '<div class="cp-heading">'
            'Cancelled orders'
            '</div>',
            unsafe_allow_html=True,
        )

        # Preserve the original request reason,
        # not only a later confirmation log.
        cancel_reasons = {}

        for record in recovery:
            if record.get("decision") == "request_cancellation":
                cancel_reasons.setdefault(
                    record.get("order_id"),
                    record.get("reason"),
                )

        display_table([
            {
                "Order": f"#{order['id']}",
                "Supplier": order["supplier"],
                "Component": order["component"],
                "Status": "Cancelled",
                "Reason": (
                    cancel_reasons.get(order["id"])
                    or latest.get(order["id"], {}).get(
                        "reason",
                        "See recovery history."
                    )
                ),
            }
            for order in cancelled
        ], "Status")

    with st.expander(
        "View complete recovery history"
    ):
        display_table([
            {
                "Order": f"#{record.get('order_id')}",
                "Policy": record.get("policy", "—"),
                "Decision": pretty(
                    record.get("decision")
                ),
                "Reason": record.get("reason", ""),
            }
            for record in recovery[:40]
        ], "Decision")

    # --------------------------------------------------------
    # CONFIRM CANCELLATION
    # --------------------------------------------------------

    pending_cancel = [
        order
        for order in orders
        if order["status"] == "cancellation_requested"
    ]

    if pending_cancel:
        st.warning(
            "Cancellation requested. Supplier stock "
            "and purchasing budget remain reserved "
            "until the supplier confirms."
        )

        options = {
            order["id"]: order
            for order in pending_cancel
        }

        selected = st.selectbox(
            "Cancellation awaiting supplier confirmation",
            list(options),
            format_func=lambda number: (
                f"#{number} · "
                f"{options[number]['supplier']}"
            ),
        )

        if st.button(
            "Simulate supplier confirming cancellation"
        ):
            if not SUPPLIER_SECRET:
                st.error(
                    "SUPPLIER_WEBHOOK_SECRET "
                    "is missing from .env."
                )
            else:
                api(
                    "POST",
                    (
                        f"/recovery/orders/{selected}"
                        "/confirm-cancellation"
                    ),
                    timeout=100,
                    headers={
                        "X-Supplier-Secret": SUPPLIER_SECRET
                    },
                )

                notify(
                    f"Order #{selected} cancellation confirmed. "
                    "Replacement procurement evaluated."
                )

    # --------------------------------------------------------
    # CHAINPILOT AGENT
    # --------------------------------------------------------

    st.divider()

    st.subheader("ChainPilot investigation")

    st.caption(
        f"Policy: Speed {policy['speed_weight']} · "
        f"Cost {policy['cost_weight']} · "
        f"Reliability {policy['reliability_weight']} · "
        f"Approval above {money(policy['approval_threshold'])}"
    )

    if st.button(
        "Run ChainPilot",
        type="primary",
    ):
        with st.spinner(
            "ChainPilot is evaluating inventory "
            "and purchasing policy..."
        ):
            result = api(
                "POST",
                "/agent/run",
                timeout=180,
            )

        st.session_state["cp_manual_result"] = result

        notify(
            "ChainPilot evaluation completed."
        )

    manual = st.session_state.get(
        "cp_manual_result"
    )

    if manual:
        show_agent_result(manual)
    else:
        st.caption(
            "Run ChainPilot to see its latest "
            "procurement decision."
        )

    # --------------------------------------------------------
    # PREVIOUS RECOVERY EXPLANATIONS
    # --------------------------------------------------------

    if recovery:
        st.markdown(
            '<div class="cp-heading">'
            'Recent recovery decisions'
            '</div>',
            unsafe_allow_html=True,
        )

        st.caption(
            "These decisions were recorded after "
            "supplier events or policy changes. "
            "They may predate the manual evaluation."
        )

        show_recent_recovery(
            recovery,
            orders,
            limit=2,
        )

    with st.expander(
        "Automatic ChainPilot activity"
    ):
        show_automatic_activity(logs)

    # --------------------------------------------------------
    # PURCHASE HISTORY
    # --------------------------------------------------------

    st.divider()

    st.subheader("Purchases and delivery")

    display_table(
        order_rows(orders),
        "Status",
    )

    # --------------------------------------------------------
    # APPROVALS
    # --------------------------------------------------------

    if pending_approvals:
        st.markdown(
            '<div class="cp-heading">'
            'Manager approvals'
            '</div>',
            unsafe_allow_html=True,
        )

        for order in pending_approvals:

            with st.container(border=True):
                left, right = st.columns(
                    [4, 1],
                    vertical_alignment="center",
                )

                left.markdown(
                    f"**Order #{order['id']} — "
                    f"{order['component']}**"
                )

                left.caption(
                    f"{order['supplier']} · "
                    f"{order['quantity']} units · "
                    f"{money(order['total_cost'])}"
                )

                left.caption(
                    "Approval follows the company's "
                    "purchasing threshold, including "
                    "combined split-order plans."
                )

                if right.button(
                    "Approve",
                    key=f"approve_{order['id']}",
                    use_container_width=True,
                ):
                    api(
                        "POST",
                        (
                            f"/procurement/orders/"
                            f"{order['id']}/approve"
                        ),
                    )

                    notify(
                        f"Order #{order['id']} approved."
                    )

    # --------------------------------------------------------
    # WAREHOUSE RECEIPT
    # --------------------------------------------------------

    with st.expander(
        "Warehouse receiving — confirm delivery"
    ):
        receivable = [
            order
            for order in orders
            if (
                order["status"] in RECEIVABLE_STATUSES
                and int(
                    order.get("outstanding_quantity") or 0
                ) > 0
            )
        ]

        if not receivable:
            st.caption(
                "No approved orders are waiting for receipt."
            )

        else:
            options = {
                order["id"]: order
                for order in receivable
            }

            with st.form("warehouse_receipt"):
                chosen = st.selectbox(
                    "Purchase order",
                    list(options),
                    format_func=lambda number: (
                        f"#{number} · "
                        f"{options[number]['supplier']} · "
                        f"{options[number]['component']}"
                    ),
                )

                maximum = int(
                    options[chosen]["outstanding_quantity"]
                )

                quantity = st.number_input(
                    "Units received",
                    min_value=1,
                    max_value=maximum,
                    value=maximum,
                )

                save = st.form_submit_button(
                    "Confirm warehouse receipt"
                )

            if save:
                response = api(
                    "POST",
                    (
                        f"/procurement/orders/"
                        f"{chosen}/receive"
                    ),
                    json={
                        "receipt_id": str(uuid.uuid4()),
                        "quantity": int(quantity),
                    },
                )

                notify(
                    "Factory warehouse stock increased by "
                    f"{response.get('quantity_added', 0)} units."
                )

    # --------------------------------------------------------
    # ACTIVITY
    # --------------------------------------------------------

    with st.expander(
        "Recent business activity"
    ):
        activities = []

        for event in logs:
            explanation = activity_description(
                event,
                order_lookup,
            )

            if explanation:
                activities.append({
                    "Time (UTC)": str(
                        event.get("timestamp", "")
                    )[:19],
                    "Event": explanation,
                })

            if len(activities) >= 20:
                break

        display_table(activities)


# ============================================================
# PAGE 2 — FACTORY INVENTORY
# ============================================================

elif page == "Factory Inventory":

    st.markdown(
        '<div class="cp-eyebrow">WAREHOUSE</div>',
        unsafe_allow_html=True,
    )

    st.title("Factory Inventory")

    st.markdown(
        '<div class="cp-description">'
        'Manage physical component stock and '
        'the production target.'
        '</div>',
        unsafe_allow_html=True,
    )

    inventory = api(
        "GET",
        "/inventory/",
    )

    display_table([
        {
            "Component": item["component"],
            "Warehouse stock": item["stock"],
            "Demand": item["demand"],
            "Already ordered": item["ordered_or_pending"],
            "Unfulfilled": item["uncovered_shortage"],
        }
        for item in inventory
    ])

    shortage = sum(
        int(item["uncovered_shortage"])
        for item in inventory
    )

    if shortage:
        st.warning(
            f"{shortage} units remain unfulfilled."
        )
    else:
        st.success(
            "All demand is covered by warehouse stock "
            "or existing orders."
        )

    st.caption(
        "Already ordered means incoming or pending "
        "components. It does not mean those units "
        "are physically in the factory."
    )

    left, right = st.columns(
        2,
        gap="large",
    )

    # --------------------------------------------------------
    # STOCK ADJUSTMENT
    # --------------------------------------------------------

    with left:
        st.subheader("Adjust warehouse stock")

        with st.form("stock_adjustment"):
            component = st.selectbox(
                "Component",
                [
                    item["component"]
                    for item in inventory
                ],
            )

            operation = st.radio(
                "Adjustment",
                ["consume", "add"],
                horizontal=True,
                format_func=lambda value: (
                    "Used in production"
                    if value == "consume"
                    else "Add stock"
                ),
            )

            quantity = st.number_input(
                "Number of units",
                min_value=1,
                value=20,
            )

            save = st.form_submit_button(
                "Save stock change",
                type="primary",
            )

        if save:
            result = api(
                "POST",
                (
                    f"/demo/inventory/"
                    f"{component}/adjust"
                ),
                json={
                    "action": operation,
                    "quantity": int(quantity),
                },
            )

            st.session_state.pop(
                "cp_manual_result",
                None,
            )

            notify(
                f"{component}: "
                f"{result['previous_stock']} → "
                f"{result['new_stock']} units."
            )

    # --------------------------------------------------------
    # PRODUCTION TARGET
    # --------------------------------------------------------

    with right:
        st.subheader("Production target")

        with st.form("production_target"):
            target = st.number_input(
                "Laptops to manufacture",
                min_value=0,
                value=(
                    int(inventory[0]["demand"])
                    if inventory
                    else 500
                ),
                step=50,
            )

            save = st.form_submit_button(
                "Save target"
            )

        if save:
            api(
                "POST",
                "/demo/production-target",
                json={
                    "target": int(target)
                },
            )

            st.session_state.pop(
                "cp_manual_result",
                None,
            )

            notify(
                f"Production target updated "
                f"to {target} laptops."
            )

    # --------------------------------------------------------
    # DEMO SCENARIOS
    # --------------------------------------------------------

    with st.expander(
        "Demo scenarios and factory reset"
    ):
        st.warning(
            "These actions clear fictional purchase orders "
            "and activity history. Do not reset while "
            "an evaluation is running."
        )

        confirm = st.checkbox(
            "I understand the demo data will be reset."
        )

        first, second = st.columns(2)

        if first.button(
            "Load 300-battery scenario",
            disabled=not confirm,
            use_container_width=True,
        ):
            api(
                "POST",
                "/demo/scenario",
                json={
                    "name": "battery_split"
                },
            )

            st.session_state.pop(
                "cp_manual_result",
                None,
            )

            notify(
                "300-battery scenario loaded."
            )

        if second.button(
            "Reset factory",
            disabled=not confirm,
            use_container_width=True,
        ):
            api(
                "POST",
                "/demo/reset",
            )

            st.session_state.pop(
                "cp_manual_result",
                None,
            )

            notify(
                "Demo factory restored."
            )


# ============================================================
# PAGE 3 — SUPPLIERS
# ============================================================

elif page == "Suppliers":

    st.markdown(
        '<div class="cp-eyebrow">SUPPLIER NETWORK</div>',
        unsafe_allow_html=True,
    )

    st.title("Suppliers")

    st.markdown(
        '<div class="cp-description">'
        'Monitor supplier capacity, incoming orders '
        'and delivery notifications.'
        '</div>',
        unsafe_allow_html=True,
    )

    suppliers = api(
        "GET",
        "/suppliers/",
    )

    orders = api(
        "GET",
        "/procurement/orders",
    )

    component_filter = st.selectbox(
        "Filter by component",
        ["All"] + sorted({
            supplier["component"]
            for supplier in suppliers
        }),
    )

    supplier_rows = []

    for supplier in suppliers:

        if (
            component_filter != "All"
            and supplier["component"] != component_filter
        ):
            continue

        reserved = sum(
            int(order.get("outstanding_quantity") or 0)
            for order in orders
            if (
                order["supplier_id"] == supplier["id"]
                and order["status"] in ACTIVE_STATUSES
            )
        )

        supplier_rows.append({
            "Supplier": supplier["name"],
            "Component": supplier["component"],
            "Available": int(supplier["available"]),
            "Reserved": reserved,
            "Price (SAR/unit)": decimal_money(
                supplier["unit_price"]
            ),
            "Delivery (days)": int(
                supplier["delivery_days"]
            ),
            "Reliability": (
                f"{float(supplier['reliability']):.0f}%"
            ),
            "Status": (
                "Eligible"
                if supplier["approved"]
                else "Paused"
            ),
        })

    display_table(
        supplier_rows,
        "Status",
    )

    st.caption(
        "Eligible: ChainPilot may select the supplier. "
        "Paused: ChainPilot excludes it from new purchases, "
        "even if stock is available. Existing orders "
        "can remain active."
    )

    # --------------------------------------------------------
    # EXISTING ORDERS
    # --------------------------------------------------------

    st.subheader("Orders with suppliers")

    display_table(
        order_rows(orders),
        "Status",
    )

    # --------------------------------------------------------
    # EVENT SIMULATOR
    # --------------------------------------------------------

    st.divider()

    st.subheader("Simulate a supplier update")

    st.caption(
        "Choose an actual outstanding order. "
        "This simulates a message from its supplier."
    )

    eligible_orders = [
        order
        for order in orders
        if (
            order["status"] in RECEIVABLE_STATUSES
            and int(
                order.get("outstanding_quantity") or 0
            ) > 0
        )
    ]

    if not SUPPLIER_SECRET:
        st.warning(
            "SUPPLIER_WEBHOOK_SECRET is missing "
            "from .env."
        )

    elif not eligible_orders:
        st.info(
            "No approved active orders are available "
            "for a supplier notification."
        )

    else:
        companies = {
            order["supplier_id"]: order["supplier"]
            for order in eligible_orders
        }

        supplier_id = st.selectbox(
            "Supplier reporting",
            list(companies),
            format_func=lambda identifier: (
                companies[identifier]
            ),
        )

        relevant_orders = {
            order["id"]: order
            for order in eligible_orders
            if order["supplier_id"] == supplier_id
        }

        order_id = st.selectbox(
            "Affected order",
            list(relevant_orders),
            format_func=lambda number: (
                f"#{number} · "
                f"{relevant_orders[number]['component']} · "
                f"{relevant_orders[number]['outstanding_quantity']} "
                "remaining"
            ),
        )

        order = relevant_orders[order_id]

        event_type = st.selectbox(
            "Supplier notification",
            [
                "delayed",
                "cancelled",
                "partial_fulfillment",
                "shipped",
                "delivered",
            ],
            format_func=lambda value: {
                "delayed": "Delivery delayed",
                "cancelled": "Supplier cancelled the order",
                "partial_fulfillment": "Can deliver fewer units",
                "shipped": "Order shipped",
                "delivered": "Order delivered",
            }[value],
        )

        with st.form("supplier_event"):
            days = None
            fulfillable = None

            if event_type == "delayed":
                days = st.number_input(
                    "Revised delivery (days)",
                    min_value=1,
                    value=max(
                        5,
                        int(
                            order.get(
                                "expected_delivery_days"
                            ) or 1
                        ),
                    ),
                )

            if event_type == "partial_fulfillment":
                fulfillable = st.number_input(
                    "Total deliverable units",
                    min_value=int(
                        order["received_quantity"]
                    ),
                    max_value=int(
                        order["fulfillable_quantity"]
                    ),
                    value=int(
                        order["fulfillable_quantity"]
                    ),
                )

            note = st.text_input(
                "Supplier note",
                value="Demo supplier notification",
            )

            send = st.form_submit_button(
                "Send supplier update",
                type="primary",
            )

        if send:
            if (
                event_type == "partial_fulfillment"
                and int(fulfillable) == 0
            ):
                st.error(
                    "Use the cancellation event if "
                    "the supplier cannot deliver any units."
                )

            else:
                payload = {
                    "event_id": str(uuid.uuid4()),
                    "order_id": int(order_id),
                    "event_type": event_type,
                    "note": note,
                }

                if days is not None:
                    payload[
                        "expected_delivery_days"
                    ] = int(days)

                if fulfillable is not None:
                    payload[
                        "fulfillable_quantity"
                    ] = int(fulfillable)

                result = api(
                    "POST",
                    "/supplier-events/",
                    json=payload,
                    headers={
                        "X-Supplier-Secret": SUPPLIER_SECRET
                    },
                    timeout=100,
                )

                recovery_decisions = (
                    result.get("recovery_decisions") or []
                )

                receipt = (
                    result.get("warehouse_receipt") or {}
                )

                if recovery_decisions:
                    message = (
                        recovery_decisions[0].get("reason")
                        or "Delay reviewed by ChainPilot."
                    )

                elif receipt:
                    message = (
                        f"Warehouse received "
                        f"{receipt.get('quantity_added', 0)} "
                        "units."
                    )

                else:
                    message = (
                        result.get("message")
                        or "Supplier update recorded."
                    )

                notify(
                    message,
                    "⚠️"
                    if event_type == "delayed"
                    else "✅",
                )

    st.caption(
        "Shipped means in transit and does not "
        "increase factory stock. In the demo delivery "
        "workflow, Delivered can automatically confirm "
        "warehouse receipt if that backend feature "
        "is installed."
    )


# ============================================================
# PAGE 4 — SETTINGS
# ============================================================

else:

    st.markdown(
        '<div class="cp-eyebrow">ADMINISTRATION</div>',
        unsafe_allow_html=True,
    )

    st.title("Purchasing policies")

    st.markdown(
        '<div class="cp-description">'
        'Choose which factors ChainPilot prioritizes '
        'when purchasing or responding to delays.'
        '</div>',
        unsafe_allow_html=True,
    )

    policy = api(
        "GET",
        "/policies/",
    )

    presets = {
        "Current / Custom": None,
        "Production First": (70, 10, 20),
        "Budget First": (15, 75, 10),
        "Balanced": (35, 35, 30),
    }

    selected_preset = st.selectbox(
        "Strategy",
        list(presets),
    )

    weights = (
        presets[selected_preset]
        or (
            int(policy["speed_weight"]),
            int(policy["cost_weight"]),
            int(policy["reliability_weight"]),
        )
    )

    st.caption(
        "Enter priority values from 0 to 100. "
        "ChainPilot normalizes the weights "
        "when evaluating suppliers."
    )

    # Explicit English-number entry.
    # No sliders with offset labels.

    def parse_number(text, field, integer=False):
        translation = str.maketrans(
            "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹",
            "01234567890123456789",
        )

        cleaned = (
            str(text)
            .translate(translation)
            .replace(",", "")
            .replace("٬", "")
            .strip()
        )

        try:
            value = (
                int(cleaned)
                if integer
                else float(cleaned)
            )

        except ValueError:
            raise ValueError(
                f"{field}: enter a valid number."
            )

        if value < 0:
            raise ValueError(
                f"{field}: the value cannot be negative."
            )

        return value

    with st.form("policy_form"):

        first, second, third = st.columns(3)

        with first:
            speed_raw = st.text_input(
                "Delivery speed priority",
                value=str(weights[0]),
            )

        with second:
            cost_raw = st.text_input(
                "Low cost priority",
                value=str(weights[1]),
            )

        with third:
            reliability_raw = st.text_input(
                "Reliability priority",
                value=str(weights[2]),
            )

        st.markdown(
            '<div class="cp-heading">'
            'Purchasing limits'
            '</div>',
            unsafe_allow_html=True,
        )

        first, second, third = st.columns(3)

        with first:
            budget_raw = st.text_input(
                "Maximum outstanding budget (SAR)",
                value=str(
                    int(float(policy["max_budget"]))
                ),
            )

        with second:
            days_raw = st.text_input(
                "Maximum delivery days",
                value=str(
                    int(policy["max_delivery_days"])
                ),
            )

        with third:
            threshold_raw = st.text_input(
                "Manager approval threshold (SAR)",
                value=str(
                    int(float(policy["approval_threshold"]))
                ),
            )

        save = st.form_submit_button(
            "Save purchasing policy",
            type="primary",
        )

    if save:
        try:
            speed = parse_number(
                speed_raw,
                "Delivery speed",
                integer=True,
            )

            cost = parse_number(
                cost_raw,
                "Low cost",
                integer=True,
            )

            reliability = parse_number(
                reliability_raw,
                "Reliability",
                integer=True,
            )

            budget = parse_number(
                budget_raw,
                "Budget",
            )

            days = parse_number(
                days_raw,
                "Delivery days",
                integer=True,
            )

            approval = parse_number(
                threshold_raw,
                "Approval threshold",
            )

            if any(
                value > 100
                for value in (
                    speed,
                    cost,
                    reliability,
                )
            ):
                raise ValueError(
                    "Priorities must be between 0 and 100."
                )

            if speed + cost + reliability == 0:
                raise ValueError(
                    "At least one priority must be above zero."
                )

            if budget <= 0:
                raise ValueError(
                    "Budget must be greater than zero."
                )

            if days < 1:
                raise ValueError(
                    "Delivery days must be at least one."
                )

        except ValueError as error:
            st.error(str(error))

        else:
            api(
                "PUT",
                "/policies/",
                json={
                    "speed_weight": speed,
                    "cost_weight": cost,
                    "reliability_weight": reliability,
                    "max_budget": budget,
                    "max_delivery_days": days,
                    "approval_threshold": approval,
                },
                timeout=100,
            )

            notify(
                "Purchasing policy saved. "
                "Eligible outstanding orders reviewed."
            )

    with st.expander(
        "How purchasing priorities work"
    ):
        st.markdown(
            """
**Production First:** Prefer faster eligible suppliers.

**Budget First:** Give more importance to lower cost.

**Balanced:** Consider speed, cost and supplier reliability
with similar priority.

**Maximum budget:** Limits outstanding purchasing commitments.

**Approval threshold:** Determines when a manager must approve
a purchase. Combined sourcing plans may also require approval.
"""
        )

    st.info(
        "Automatic simulated supplier cancellation: "
        + (
            "Enabled. The fictional supplier "
            "confirms cancellation immediately."
            if AUTO_CANCEL
            else
            "Disabled. Cancellation waits for "
            "a simulated supplier confirmation."
        )
    )

    if st.button(
        "Return to Dashboard"
    ):
        navigate("Dashboard")
