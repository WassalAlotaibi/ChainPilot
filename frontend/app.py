"""ChainPilot — operator-friendly Streamlit interface.

Run from the project root:
    python -m streamlit run frontend/app.py

This frontend calls existing ChainPilot FastAPI endpoints only.
"""

import json
import os
import uuid
from pathlib import Path

import requests
import streamlit as st
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
API = os.getenv("CHAINPILOT_API", "http://127.0.0.1:8000").rstrip("/")
AUTO = os.getenv("AUTO_AGENT_ON_INVENTORY", "false").strip().lower() == "true"

st.set_page_config(page_title="ChainPilot | Operations", page_icon="🏭", layout="wide")
st.markdown(
    """
    <style>
    .block-container {max-width: 1170px; padding-top: 1.8rem; padding-bottom: 3rem;}
    [data-testid="stSidebar"] {border-right: 1px solid rgba(130,145,165,.18);}
    [data-testid="stMetric"] {padding: 17px 20px; border-radius: 12px;
        border: 1px solid rgba(145,155,170,.24); background: rgba(125,140,160,.045);}
    [data-testid="stMetricLabel"] {font-size: .89rem;}
    h1,h2,h3 {letter-spacing: -.025em;}
    div[data-testid="stAlert"] {border-radius: 10px;}
    .cp-kicker {font-size: .75rem; letter-spacing: .14em; font-weight: 700;
        color: #58b9b2; text-transform: uppercase; margin-bottom: .35rem;}
    .cp-title {font-size: 2.05rem; font-weight: 750; letter-spacing: -.04em;
        margin: 0 0 6px; line-height: 1.2;}
    .cp-sub {font-size: 1rem; opacity: .72; margin-bottom: 20px;}
    .cp-surface {border: 1px solid rgba(135,150,170,.22); border-radius: 12px;
        padding: 13px 17px; margin-bottom: 13px;}
    .cp-step {border-left: 3px solid #4bb8ac; padding: 7px 0 7px 16px;
        margin: 10px 0;}
    .cp-step-title {font-size: .98rem; font-weight: 700;}
    .cp-step-sub {font-size: .87rem; opacity: .75; margin-top: 3px;}
    </style>
    """,
    unsafe_allow_html=True,
)


# ---- Reliable backend calls ------------------------------------------
def api(method, endpoint, *, timeout=25, **kwargs):
    try:
        response = requests.request(method, API + endpoint, timeout=timeout, **kwargs)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        message = str(exc)
        if getattr(exc, "response", None) is not None:
            try:
                result = exc.response.json()
                message = str(result.get("detail", result))
            except (ValueError, AttributeError):
                message = exc.response.text[:350]
        st.error(f"Cannot complete this action: {message}")
        st.stop()


def money(value):
    return f"{float(value):,.0f} SAR"


def label(value):
    return str(value or "unknown").replace("_", " ").capitalize()


def finish(message):
    st.session_state["notice"] = message
    st.rerun()


def safe_json(value):
    try:
        return json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}


def outstanding_spend(orders):
    statuses = {
        "pending_approval", "placed", "delayed", "shipped",
        "awaiting_receipt", "partially_received",
    }
    return sum(
        int(order.get("outstanding_quantity") or 0)
        * float(order.get("unit_price") or 0)
        for order in orders
        if order["status"] in statuses
    )


def explain_gap(item, suppliers, policy, available_budget):
    """Explain known constraints, not an invented AI opinion."""
    need = int(item.get("uncovered_shortage") or 0)
    offers = [s for s in suppliers if s["component"] == item["component"]]
    stocked = [s for s in offers if int(s["available"]) > 0]
    approved = [s for s in stocked if s["approved"] and float(s["unit_price"]) > 0]
    eligible = [
        s for s in approved
        if int(s["delivery_days"]) <= int(policy["max_delivery_days"])
    ]
    eligible_units = sum(int(s["available"]) for s in eligible)

    if not stocked:
        reason = "No supplier stock"
        detail = "All listed suppliers are out of stock"
    elif not approved:
        reason = "Supplier approval"
        detail = "Suppliers have stock, but no stocked supplier is approved"
    elif not eligible:
        reason = "Delivery limit"
        detail = "Approved suppliers exceed the allowed delivery time"
    elif available_budget <= 0:
        reason = "Budget exhausted"
        detail = "Existing orders already use the outstanding budget"
    elif available_budget < min(float(s["unit_price"]) for s in eligible):
        reason = "Budget too low"
        detail = "Remaining budget cannot buy one unit"
    elif eligible_units < need:
        reason = "Limited supplier stock"
        detail = f"Only {eligible_units} eligible units available for {need} needed"
    else:
        left = need
        lowest_possible_cost = 0.0
        for supplier in sorted(eligible, key=lambda s: float(s["unit_price"])):
            qty = min(left, int(supplier["available"]))
            lowest_possible_cost += qty * float(supplier["unit_price"])
            left -= qty
            if left == 0:
                break
        if lowest_possible_cost > available_budget:
            reason = "Budget limited"
            detail = "Available budget cannot cover the full shortage"
        else:
            reason = "Ready to evaluate"
            detail = "Supplier stock and budget are available"

    if eligible_units < need and reason not in ("No supplier stock", "Limited supplier stock"):
        detail += f"; eligible supplier capacity is {eligible_units} units"
    if available_budget <= 0 and reason != "Budget exhausted":
        detail += "; budget is also fully committed"
    return reason, detail


def recent_business_events(events):
    entries = []
    for event in events:
        action = event.get("action")
        data = safe_json(event.get("details"))
        description = None
        if action == "procurement_order":
            description = (
                f"Created order: {data.get('quantity', '?')} {data.get('component', 'units')} "
                f"from {data.get('supplier', 'supplier')} for "
                f"{money(data.get('total_cost', 0))} ({label(data.get('action'))})"
            )
        elif action == "procurement_escalation":
            description = (
                f"{data.get('uncovered_quantity', '?')} {data.get('component', 'units')} "
                f"still unfulfilled: {data.get('reason', 'review constraints')}"
            )
        elif action == "order_approved":
            description = f"Manager approved order #{data.get('order_id', '?')}"
        elif action == "warehouse_receipt":
            description = (
                f"Warehouse received {data.get('quantity_added', '?')} units "
                f"for order #{data.get('order_id', '?')}"
            )
        elif action == "supplier_event":
            description = (
                f"Supplier reported {label(data.get('event_type'))} "
                f"for order #{data.get('order_id', '?')}"
            )
        elif action == "demo_stock_adjusted":
            description = (
                f"Factory {data.get('action', 'adjusted')} {data.get('quantity', '?')} "
                f"{data.get('component', 'units')}"
            )
        elif action == "demo_target_changed":
            description = f"Production target changed to {data.get('target', '?')} laptops"
        elif action == "demo_scenario_loaded":
            description = "Loaded a demonstration scenario"
        elif action == "demo_reset":
            description = "Demo factory reset"
        elif action == "agent_completed":
            description = "Gemini completed an evaluation"
        elif action == "agent_failed":
            description = "Gemini evaluation failed; check server logs"
        if description:
            entries.append({
                "Time (UTC)": str(event.get("timestamp", ""))[:19].replace("T", " "),
                "Event": description,
            })
    return entries


def tool_steps(trace):
    """Extract only actual Gemini calls; never fabricate agent actions."""
    open_needs = []
    rankings = []
    actions = []
    called = set()
    for call in trace:
        name = call.get("tool")
        called.add(name)
        result = call.get("result")
        if name == "get_open_needs" and isinstance(result, list):
            open_needs = result
        elif name == "rank_suppliers":
            rankings.append((call.get("arguments") or {}, result))
        elif name == "execute_procurement" and isinstance(result, dict):
            actions.extend(result.get("actions") or [])
    return open_needs, rankings, actions, called


def render_agent_steps(trace, summary=None):
    needs, rankings, actions, called = tool_steps(trace)
    st.markdown("#### AI decision steps")
    if not trace:
        st.caption("No tool-call trace is available for this run yet.")
        if summary:
            with st.expander("Gemini's summary"):
                st.markdown(summary)
        return

    with st.container(border=True):
        st.markdown("**01  Inspect factory demand**")
        if needs:
            shortages = [x for x in needs if int(x.get("uncovered_shortage") or 0) > 0]
            if shortages:
                st.dataframe([
                    {
                        "Component": x["component"],
                        "In stock": x["stock"],
                        "Demand": x["demand"],
                        "Already ordered": x["ordered_or_pending"],
                        "Uncovered": x["uncovered_shortage"],
                    }
                    for x in shortages
                ], hide_index=True, use_container_width=True)
            else:
                st.write("Gemini found no uncovered purchasing need in the inventory snapshot.")
        else:
            st.caption("An inventory inspection result was not recorded for this run.")

    with st.container(border=True):
        st.markdown("**02  Review supplier candidates**")
        if rankings:
            for args, result in rankings:
                st.caption(f"{args.get('component', 'Component')} — {args.get('quantity', '?')} units")
                if isinstance(result, list) and result:
                    st.dataframe([
                        {
                            "Supplier": s.get("name", ""),
                            "Available": s.get("available", 0),
                            "Unit price (SAR)": s.get("unit_price", 0),
                            "Delivery days": s.get("delivery_days", 0),
                            "Policy score": s.get("score", ""),
                        }
                        for s in result
                    ], hide_index=True, use_container_width=True)
                elif isinstance(result, dict) and result.get("error"):
                    st.caption(f"Ranking failed: {result['error']}")
                else:
                    st.caption("No eligible supplier was returned by this tool call.")
        else:
            st.caption("No supplier-ranking tool call was recorded (it may not have been necessary).")

    with st.container(border=True):
        st.markdown("**03  Execute procurement or escalate**")
        purchases = [a for a in actions if a.get("order_id") is not None]
        escalations = [a for a in actions if a.get("action") == "escalated"]
        if purchases:
            st.dataframe([
                {
                    "Order": a["order_id"],
                    "Component": a.get("component", ""),
                    "Supplier": a.get("supplier", ""),
                    "Units": a.get("quantity", 0),
                    "Cost (SAR)": a.get("total_cost", 0),
                    "Status": label(a.get("action")),
                }
                for a in purchases
            ], hide_index=True, use_container_width=True)
        if escalations:
            st.dataframe([
                {
                    "Component": a.get("component", ""),
                    "Still unfulfilled": a.get("uncovered_quantity", 0),
                    "Reason": a.get("reason", "Check policy or supplier availability"),
                }
                for a in escalations
            ], hide_index=True, use_container_width=True)
        if not actions:
            if "execute_procurement" in called:
                st.write("The procurement service created no new orders.")
            else:
                st.caption("Gemini did not request procurement execution in this run.")

    if summary:
        with st.expander("Gemini's complete explanation"):
            st.markdown(summary)
    with st.expander("Technical tool calls"):
        st.json(trace)


def run_gemini():
    with st.spinner("Gemini is checking needs, policies, suppliers and existing orders..."):
        output = api("POST", "/agent/run", timeout=180)
    st.session_state["manual_agent_result"] = output
    finish("Agent evaluation finished. See the recorded decision steps below.")


# ---- Sidebar and navigation ------------------------------------------
PAGES = ["Dashboard", "Factory Inventory", "Suppliers", "Settings"]
if "page" not in st.session_state:
    st.session_state["page"] = "Dashboard"


def go_to(page):
    st.session_state["page"] = page


st.sidebar.markdown("## ChainPilot")
st.sidebar.caption("Supply chain operations")
page = st.sidebar.radio("Workspace", PAGES, key="page")
st.sidebar.divider()
st.sidebar.caption("Inventory automation: " + ("Enabled" if AUTO else "Manual testing"))
if st.sidebar.button("Refresh", use_container_width=True):
    st.rerun()

if st.session_state.get("notice"):
    st.success(st.session_state.pop("notice"))


# ---- DASHBOARD -------------------------------------------------------
if page == "Dashboard":
    st.markdown('<div class="cp-kicker">Operations / Overview</div>', unsafe_allow_html=True)
    st.markdown('<div class="cp-title">Factory Dashboard</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="cp-sub">Current demand, procurement decisions, and outstanding orders — all in one place.</div>',
        unsafe_allow_html=True,
    )

    inventory = api("GET", "/inventory/")
    orders = api("GET", "/procurement/orders")
    suppliers = api("GET", "/suppliers/")
    policy = api("GET", "/policies/")
    events = api("GET", "/activity")

    committed = outstanding_spend(orders)
    budget_left = max(0, float(policy["max_budget"]) - committed)
    remaining = sum(int(x["uncovered_shortage"]) for x in inventory)
    pending = [o for o in orders if o["status"] == "pending_approval"]
    m1, m2, m3 = st.columns(3)
    m1.metric("Units still to source", remaining, help="Units not in stock and not already covered by open orders")
    m2.metric("Orders awaiting approval", len(pending), help="Purchases the manager must approve")
    m3.metric("Budget available", money(budget_left), help="Outstanding commitment limit minus active unreceived orders")

    st.subheader("Needs attention")
    st.caption("What is still missing and the actual constraint preventing it from being ordered.")
    attention = []
    for item in inventory:
        if int(item["uncovered_shortage"]) <= 0:
            continue
        cause, explanation = explain_gap(item, suppliers, policy, budget_left)
        attention.append({
            "Component": item["component"],
            "Still needed": int(item["uncovered_shortage"]),
            "Already on order": int(item["ordered_or_pending"]),
            "Reason / status": cause,
            "Explanation": explanation,
        })
    if attention:
        st.dataframe(attention, hide_index=True, use_container_width=True)
    else:
        st.info("No new purchasing shortage. Some orders may still need approval or physical delivery.")

    policy_col, agent_col = st.columns([2, 1], gap="medium")
    with policy_col:
        st.markdown(
            f"**Current buying policy:** speed {policy['speed_weight']} / "
            f"cost {policy['cost_weight']} / reliability {policy['reliability_weight']}  "
            f"\nDelivery limit: {policy['max_delivery_days']} days · "
            f"Outstanding budget: {money(policy['max_budget'])}"
        )
    with agent_col:
        st.button("Manage policies", on_click=go_to, args=("Settings",), use_container_width=True)

    st.divider()
    st.subheader("Agent investigation")
    st.caption("Follow what Gemini actually inspected, which suppliers it compared, and what actions were executed.")
    left, right = st.columns([1, 1], gap="large")
    with left:
        if st.button("Run AI evaluation", type="primary", use_container_width=True):
            run_gemini()
    with right:
        st.caption(
            "Inventory monitoring is ON — changes can trigger background evaluations."
            if AUTO else "Automatic inventory monitoring is OFF. Use Run AI evaluation for this test."
        )

    manual = st.session_state.get("manual_agent_result")
    if manual:
        st.caption(f"Last manual run: {label(manual.get('status'))} · {manual.get('elapsed_seconds', '?')} seconds")
        render_agent_steps(manual.get("trace", []), manual.get("summary"))
    else:
        st.caption("Run Gemini to see a complete decision trace here. Automatic tool activity appears below.")

    def latest_agent_activity():
        current_events = api("GET", "/activity")
        if not current_events:
            st.caption("No agent activity recorded yet.")
            return
        # This is a recent-activity view, NOT a guaranteed run identifier.
        first_terminal = next(
            (i for i, e in enumerate(current_events)
             if e["action"] in ("agent_completed", "agent_failed")),
            None,
        )
        if first_terminal is None or first_terminal > 0:
            newest = current_events[0]["action"]
            if newest in ("agent_tool_call", "agent_triggered_automatically"):
                st.write("**Recent automatic activity:** evaluation started or tool execution recorded")
            elif newest == "agent_failed":
                st.write("**Recent automatic activity:** evaluation failed")
        if first_terminal is not None:
            event = current_events[first_terminal]
            name = "Completed" if event["action"] == "agent_completed" else "Failed"
            st.caption(f"Latest recorded agent result: {name} · {event.get('timestamp', '')[:19].replace('T',' ')} UTC")
        tool_events = [e for e in current_events[:18] if e["action"] == "agent_tool_call"]
        if tool_events:
            tool_names = [safe_json(e.get("details")).get("tool", "unknown") for e in tool_events[:5]]
            st.caption("Recent actual tools: " + " · ".join(tool_names))
        st.caption("Activity refreshes every 5 seconds. This is log-based progress, not a real-time token stream.")

    # Auto-refresh is available in Streamlit 1.39+.
    if hasattr(st, "fragment"):
        latest_agent_activity = st.fragment(run_every="5s")(latest_agent_activity)
    with st.container(border=True):
        latest_agent_activity()

    with st.expander("Potential suppliers for current shortages"):
        possible = []
        for x in inventory:
            if int(x["uncovered_shortage"]) <= 0:
                continue
            for supplier in suppliers:
                if supplier["component"] != x["component"]:
                    continue
                is_eligible = bool(supplier["approved"]) and int(supplier["available"]) > 0 and int(supplier["delivery_days"]) <= int(policy["max_delivery_days"])
                possible.append({
                    "Needed component": x["component"],
                    "Supplier": supplier["name"],
                    "Available": supplier["available"],
                    "Price / unit (SAR)": supplier["unit_price"],
                    "Delivery days": supplier["delivery_days"],
                    "Eligible by stock/time": "Yes" if is_eligible else "No",
                })
        if possible:
            st.dataframe(possible, hide_index=True, use_container_width=True)
            st.caption("These are current offers from the supplier database, not necessarily suppliers selected by Gemini.")
        else:
            st.write("No currently uncovered shortage or no supplier offers.")

    st.divider()
    st.subheader("Purchase history and costs")
    st.caption("Confirmed purchase orders and approval requests. ChainPilot does not transfer money.")
    if orders:
        st.dataframe([
            {
                "Order": o["id"], "Component": o["component"],
                "Supplier": o["supplier"], "Units": o["quantity"],
                "Received": o["received_quantity"], "Total (SAR)": o["total_cost"],
                "Status": label(o["status"]),
            }
            for o in orders
        ], hide_index=True, use_container_width=True)
    else:
        st.info("No purchase orders yet. Create a shortage on Factory Inventory, then run Gemini.")

    # Pending approvals: visible, not hidden in menus.
    if pending:
        st.markdown("#### Orders requiring approval")
        by_id = {o["id"]: o for o in pending}
        chosen = st.selectbox(
            "Select order", list(by_id),
            format_func=lambda oid: f"Order #{oid} — {by_id[oid]['component']} — {money(by_id[oid]['total_cost'])}",
        )
        if st.button("Approve selected order"):
            api("POST", f"/procurement/orders/{chosen}/approve")
            finish(f"Order #{chosen} approved. Warehouse receipt is still required.")

    with st.expander("Warehouse receiving — confirm physical delivery"):
        eligible = [
            o for o in orders if o["status"] in (
                "placed", "delayed", "shipped", "awaiting_receipt", "partially_received"
            ) and int(o["outstanding_quantity"]) > 0
        ]
        if not eligible:
            st.caption("No approved orders awaiting receipt.")
        else:
            by_id = {o["id"]: o for o in eligible}
            with st.form("receipt_form"):
                selected = st.selectbox("Order", list(by_id), format_func=lambda oid: f"#{oid} · {by_id[oid]['supplier']} · {by_id[oid]['component']}")
                number = st.number_input("Units actually received", min_value=1, max_value=int(by_id[selected]["outstanding_quantity"]), value=int(by_id[selected]["outstanding_quantity"]))
                submit = st.form_submit_button("Confirm receipt")
            if submit:
                result = api("POST", f"/procurement/orders/{selected}/receive", json={"receipt_id": str(uuid.uuid4()), "quantity": int(number)})
                finish(f"Warehouse inventory increased by {result['quantity_added']} units.")

    st.divider()
    st.subheader("Recent activity")
    log_rows = recent_business_events(events)[:12]
    if log_rows:
        st.dataframe(log_rows, hide_index=True, use_container_width=True)
    else:
        st.caption("No business activity recorded yet.")


# ---- FACTORY INVENTORY ------------------------------------------------
elif page == "Factory Inventory":
    st.markdown('<div class="cp-kicker">Operations / Factory</div>', unsafe_allow_html=True)
    st.title("Factory Inventory")
    st.caption("Adjust physical stock, change production demand, or replay a controlled scenario.")
    inventory = api("GET", "/inventory/")
    st.dataframe([
        {"Component": x["component"], "In warehouse": x["stock"], "Production demand": x["demand"],
         "Already ordered": x["ordered_or_pending"], "Still needed": x["uncovered_shortage"]}
        for x in inventory
    ], hide_index=True, use_container_width=True)
    st.caption("Already ordered includes pending approval. It is not physically available until receipt confirmation.")

    c1, c2 = st.columns(2, gap="large")
    with c1:
        st.subheader("Change physical stock")
        with st.form("stock_adjustment"):
            component = st.selectbox("Component", [x["component"] for x in inventory])
            action = st.radio("Change type", ["consume", "add"], horizontal=True, format_func=lambda x: "Use in production" if x == "consume" else "Manual adjustment (+)")
            quantity = st.number_input("Units", min_value=1, value=20, step=1)
            save = st.form_submit_button("Apply adjustment", type="primary")
        if save:
            result = api("POST", f"/demo/inventory/{component}/adjust", json={"action": action, "quantity": int(quantity)})
            st.session_state.pop("manual_agent_result", None)
            finish(f"{component} stock: {result['previous_stock']} → {result['new_stock']} units.")
    with c2:
        st.subheader("Change production demand")
        st.caption("In this demo, one of each component is required per laptop.")
        with st.form("production_target"):
            target = st.number_input("Laptops planned", min_value=0, value=int(inventory[0]["demand"]) if inventory else 500, step=50)
            change = st.form_submit_button("Save demand")
        if change:
            api("POST", "/demo/production-target", json={"target": int(target)})
            st.session_state.pop("manual_agent_result", None)
            finish(f"Production target set to {target} laptops.")

    st.divider()
    st.subheader("Demo scenarios")
    st.caption("Recreate the split-supplier example or return to the original data.")
    with st.expander("Load scenario or reset factory"):
        st.warning("These actions clear fictional orders, receipts and activity. Do not use them during an agent evaluation.")
        confirm = st.checkbox("I understand the existing demo records will be replaced")
        a, b = st.columns(2)
        if a.button("Load 300-battery shortage", disabled=not confirm, use_container_width=True):
            api("POST", "/demo/scenario", json={"name": "battery_split"})
            st.session_state.pop("manual_agent_result", None)
            finish("Split-supplier scenario loaded. Open Dashboard to evaluate.")
        if b.button("Reset to starting factory", disabled=not confirm, use_container_width=True):
            api("POST", "/demo/reset")
            st.session_state.pop("manual_agent_result", None)
            finish("Factory demo reset.")
    st.info("Automatic inventory evaluation is ENABLED." if AUTO else "Automatic inventory evaluation is OFF. Run Gemini manually on Dashboard.")


# ---- SUPPLIERS --------------------------------------------------------
elif page == "Suppliers":
    st.markdown('<div class="cp-kicker">Operations / Procurement network</div>', unsafe_allow_html=True)
    st.title("Suppliers")
    st.caption("Remaining supplier stock, existing reservations, costs, and delivery expectations.")
    suppliers = api("GET", "/suppliers/")
    orders = api("GET", "/procurement/orders")
    filter_options = ["All"] + sorted({s["component"] for s in suppliers})
    component_filter = st.selectbox("Component", filter_options)
    active = {"pending_approval", "placed", "delayed", "shipped", "awaiting_receipt", "partially_received"}
    displayed = []
    for s in suppliers:
        if component_filter != "All" and s["component"] != component_filter:
            continue
        reserved = sum(
            int(o.get("outstanding_quantity") or 0)
            for o in orders if o["supplier_id"] == s["id"] and o["status"] in active
        )
        displayed.append({
            "Supplier": s["name"], "Component": s["component"], "Available": s["available"],
            "Reserved": reserved, "Price / unit (SAR)": s["unit_price"],
            "Delivery (days)": s["delivery_days"], "Reliability (%)": s["reliability"],
            "Status": "Eligible" if s["approved"] else "Paused",
        })
    st.dataframe(displayed, hide_index=True, use_container_width=True)
    st.caption("Available quantity decreases as purchase orders are reserved. Reserved units are not yet factory stock.")

    st.divider()
    st.subheader("Supplier updates")
    st.caption("Simulate a delivery delay, cancellation, quantity reduction, or shipment update for an approved order.")
    secret = os.getenv("SUPPLIER_WEBHOOK_SECRET")
    active_orders = [o for o in orders if o["status"] not in ("pending_approval", "cancelled", "received", "rejected")]
    if not secret:
        st.info("Configure SUPPLIER_WEBHOOK_SECRET in your project's .env file to use simulated supplier notifications.")
    elif not active_orders:
        st.info("No active approved purchase orders. Approve an order on Dashboard first.")
    else:
        by_id = {o["id"]: o for o in active_orders}
        oid = st.selectbox("Order", list(by_id), format_func=lambda x: f"#{x} · {by_id[x]['supplier']} · {by_id[x]['component']}")
        event_kind = st.selectbox("Supplier update", ["delayed", "cancelled", "partial_fulfillment", "shipped", "delivered"], format_func=label)
        with st.form("supplier_event"):
            days = None
            fulfillable = None
            if event_kind == "delayed":
                days = st.number_input("Updated delivery estimate (days)", min_value=1, value=5)
            if event_kind == "partial_fulfillment":
                order = by_id[oid]
                fulfillable = st.number_input("Total quantity supplier can fulfill", min_value=int(order["received_quantity"]), max_value=int(order["fulfillable_quantity"]), value=int(order["fulfillable_quantity"]))
            note = st.text_input("Supplier note", "Demonstration update")
            submit = st.form_submit_button("Send supplier update", type="primary")
        if submit:
            payload = {"event_id": str(uuid.uuid4()), "order_id": int(oid), "event_type": event_kind, "note": note}
            if days is not None:
                payload["expected_delivery_days"] = int(days)
            if fulfillable is not None:
                payload["fulfillable_quantity"] = int(fulfillable)
            result = api("POST", "/supplier-events/", json=payload, headers={"X-Supplier-Secret": secret})
            finish(result.get("message", "Supplier update recorded") + (" · Agent scheduled" if result.get("agent_triggered") else ""))
    st.caption("A supplier saying 'delivered' never adds stock. Warehouse receiving is confirmed on Dashboard.")


# ---- SETTINGS / POLICIES ---------------------------------------------
else:
    st.markdown('<div class="cp-kicker">Administration / Settings</div>', unsafe_allow_html=True)
    st.title("Procurement Policies")
    st.caption("Set supplier priorities and hard limits. Changes apply to new decisions, not existing orders.")
    policy = api("GET", "/policies/")
    presets = {
        "Current / Custom": None,
        "Production First": (70, 10, 20),
        "Budget First": (15, 75, 10),
        "Balanced": (35, 35, 30),
    }
    choice = st.selectbox("Purchasing strategy", list(presets), key="strategy")
    weights = presets[choice] or (
        int(policy["speed_weight"]), int(policy["cost_weight"]), int(policy["reliability_weight"])
    )
    st.subheader("Supplier priorities")
    with st.form("policy_form"):
        a, b, c = st.columns(3)
        speed = a.slider("Delivery speed", 0, 100, int(weights[0]), key="speed_" + choice)
        cost = b.slider("Lower cost", 0, 100, int(weights[1]), key="cost_" + choice)
        reliability = c.slider("Reliability", 0, 100, int(weights[2]), key="reliability_" + choice)
        st.subheader("Purchasing limits")
        d, e, f = st.columns(3)
        budget = d.number_input("Max outstanding budget (SAR)", min_value=1.0, value=float(policy["max_budget"]), step=500.0)
        days = e.number_input("Max delivery (days)", min_value=1, value=int(policy["max_delivery_days"]))
        threshold = f.number_input("Manager approval above (SAR)", min_value=0.0, value=float(policy["approval_threshold"]), step=500.0)
        save = st.form_submit_button("Save policy", type="primary")
    if save:
        if speed + cost + reliability <= 0:
            st.error("At least one supplier priority must be positive.")
        else:
            api("PUT", "/policies/", json={
                "speed_weight": speed, "cost_weight": cost, "reliability_weight": reliability,
                "max_budget": budget, "max_delivery_days": days, "approval_threshold": threshold,
            })
            finish("Company purchasing policy saved.")
    st.caption("An outstanding budget is the maximum value of active, unreceived commitments—not money paid.")
    st.button("Back to Dashboard", on_click=go_to, args=("Dashboard",))
