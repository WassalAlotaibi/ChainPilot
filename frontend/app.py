"""ChainPilot Streamlit UI. Start: python -m streamlit run frontend/app.py"""
import json
import os
import uuid
from pathlib import Path

import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')
API = os.getenv('CHAINPILOT_API', 'http://127.0.0.1:8000').rstrip('/')
SECRET = os.getenv('SUPPLIER_WEBHOOK_SECRET', '')
AUTO = os.getenv('AUTO_AGENT_ON_INVENTORY', 'false').lower() == 'true'
AUTOCANCEL = os.getenv('DEMO_AUTO_CONFIRM_CANCELLATION', 'false').lower() == 'true'
ACTIVE = {'pending_approval', 'placed', 'delayed', 'cancellation_requested', 'shipped', 'awaiting_receipt', 'partially_received'}
RECEIVABLE = {'placed', 'delayed', 'shipped', 'awaiting_receipt', 'partially_received'}
PAGES = ['Dashboard', 'Factory Inventory', 'Suppliers', 'Settings']

st.set_page_config(page_title='ChainPilot | Procurement', page_icon=':material/hub:', layout='wide')
st.markdown('''<style>
:root {--cp-teal:#148b83;--cp-blue:#367ca7;--cp-line:color-mix(in srgb,currentColor 13%,transparent)}
.block-container {max-width:1240px;padding-top:1.7rem;padding-bottom:3rem}
h1 {font-size:2.1rem!important;letter-spacing:-.035em}
h2 {font-size:1.42rem!important;letter-spacing:-.02em;padding-top:.35rem}
h3 {font-size:1.07rem!important}
[data-testid="stSidebar"] {border-right:1px solid var(--cp-line)}
[data-testid="stMetric"] {padding:16px 18px;border-radius:13px;border:1px solid var(--cp-line);background:color-mix(in srgb,currentColor 2%,transparent)}
[data-testid="stMetricLabel"] {font-weight:550;opacity:.76}
[data-testid="stMetricValue"] {font-variant-numeric:tabular-nums;font-size:1.55rem}
[data-testid="stDataFrame"] {border-radius:10px;overflow:hidden}
[data-testid="stAlert"] {border-radius:11px}
[data-testid="stSidebar"] .stButton button {min-height:42px;justify-content:flex-start!important;gap:12px!important;text-align:left!important;border:1px solid transparent!important;background:transparent!important;color:inherit!important;border-radius:9px!important;box-shadow:none!important;font-weight:520!important}
[data-testid="stSidebar"] .stButton button:hover {background:color-mix(in srgb,currentColor 7%,transparent)!important}
[data-testid="stSidebar"] .stButton button [data-testid="stIconMaterial"],
[data-testid="stSidebar"] .stButton button span[data-testid="stIconMaterial"] {flex:0 0 20px;min-width:20px;display:inline-flex;align-items:center;justify-content:center}
[data-testid="stSidebar"] .stButton button p {margin:0;line-height:1.2}
.cp-kicker {font-size:.69rem;letter-spacing:.13em;font-weight:750;color:#198c86;margin-bottom:8px}
.cp-description {font-size:.89rem;opacity:.7;margin-top:-6px;margin-bottom:18px}
.cp-brand {display:flex;gap:11px;align-items:center;padding:12px 0 20px}
.cp-symbol {width:39px;height:39px;display:grid;place-items:center;background:#134541;color:#eafff8;border-radius:11px;font-weight:800;letter-spacing:-.03em;flex-shrink:0}
.cp-name {font-size:1.08rem;font-weight:800;line-height:1.2}
.cp-caption {font-size:.73rem;opacity:.68;line-height:1.4;margin-top:3px}
.cp-side-label {font-size:.68rem;letter-spacing:.12em;font-weight:750;opacity:.55;padding:6px 3px 9px}
.cp-side-footer {margin-top:25px;border-top:1px solid var(--cp-line);padding-top:17px;font-size:.8rem;line-height:1.6;opacity:.75}
.cp-dot {width:8px;height:8px;border-radius:50%;background:#89949e;display:inline-block;margin-right:8px}
.cp-dot.on {background:#159d87}
.cp-note {font-size:.82rem;opacity:.72;line-height:1.5}
.cp-label {font-size:.78rem;font-weight:650;opacity:.85}
.cp-chip {display:inline-block;font-size:.72rem;font-weight:700;padding:3px 9px;border-radius:7px;background:rgba(20,139,131,.12);color:#1a9d92}
.cp-stat {border-left:3px solid var(--cp-teal);padding:8px 13px;margin:10px 0}
.cp-section {margin:13px 0 7px;font-weight:680}
/* Fields remain left-to-right regardless of browser/OS locale. */
[data-testid="stTextInput"] input {direction:ltr!important;text-align:left!important;font-variant-numeric:tabular-nums}
</style>''', unsafe_allow_html=True)


def api(method, route, timeout=40, **kw):
    try:
        res = requests.request(method, API + route, timeout=timeout, **kw)
        res.raise_for_status()
        return res.json()
    except requests.RequestException as exc:
        reason = str(exc)
        if exc.response is not None:
            try:
                body = exc.response.json()
                reason = str(body.get('detail', body))
            except (ValueError, TypeError):
                reason = exc.response.text[:250]
        st.error('Request failed: ' + reason)
        st.stop()


def money(x):
    return f'{float(x or 0):,.0f} SAR'


def label(s):
    return str(s or '').replace('_', ' ').capitalize()


def log_data(row):
    d = row.get('details') or {}
    if isinstance(d, dict):
        return d
    try:
        p = json.loads(d)
        return p if isinstance(p, dict) else {}
    except (TypeError, ValueError):
        return {}


def notify(msg, icon=':material/check_circle:'):
    st.session_state['cp_notice'] = (msg, icon)
    st.rerun()


def table(rows, status=None):
    if not rows:
        st.caption('Nothing to display yet.')
        return
    df = pd.DataFrame(rows)
    if status and status in df:
        def style(r):
            s = str(r[status]).lower()
            if any(v in s for v in ('cancel', 'failed', 'blocked', 'exhausted')):
                color = 'rgba(215,75,74,.16)'
            elif any(v in s for v in ('delay', 'pending', 'waiting', 'requested', 'limited', 'risk')):
                color = 'rgba(218,153,55,.17)'
            elif any(v in s for v in ('received', 'eligible', 'approved', 'ready', 'completed')):
                color = 'rgba(38,153,112,.15)'
            else:
                color = 'rgba(50,124,166,.12)'
            return [f'background-color:{color}' if k == status else '' for k in r.index]
        st.dataframe(df.style.apply(style, axis=1), hide_index=True, use_container_width=True)
    else:
        st.dataframe(df, hide_index=True, use_container_width=True)


def outstanding_budget(orders):
    return sum(float(o.get('unit_price') or 0) * int(o.get('outstanding_quantity') or 0)
               for o in orders if o.get('status') in ACTIVE)


def reason_for_gap(item, suppliers, policy, left_budget):
    eligible = [s for s in suppliers if s['component'] == item['component'] and s['available'] > 0]
    if not eligible:
        return 'Supplier stock unavailable', 'No supplier currently has available stock.'
    eligible = [s for s in eligible if s['approved']]
    if not eligible:
        return 'Supplier blocked', 'Suppliers with stock are paused.'
    eligible = [s for s in eligible if s['delivery_days'] <= policy['max_delivery_days']]
    if not eligible:
        return 'Delivery limited', 'Available suppliers exceed the delivery limit.'
    if left_budget < min(float(s['unit_price']) for s in eligible):
        return 'Budget exhausted', 'Outstanding commitments leave insufficient budget.'
    if sum(s['available'] for s in eligible) < item['uncovered_shortage']:
        return 'Supplier stock limited', 'Not enough eligible supplier units to cover the entire shortage.'
    return 'Ready to evaluate', 'Eligible suppliers exist; ChainPilot can assess an order.'


def order_rows(orders):
    return [{'Order': f"#{o['id']}", 'Component': o['component'], 'Supplier': o['supplier'],
             'Ordered': o['quantity'], 'Received': o['received_quantity'],
             'Cost (SAR)': o['total_cost'], 'Status': label(o['status'])} for o in orders]


def event_message(e, lookup):
    a, d = e.get('action'), log_data(e)
    oid = d.get('order_id')
    if a == 'procurement_order':
        return f"Order created: {d.get('quantity')} {d.get('component')} from {d.get('supplier')} — {money(d.get('total_cost'))}"
    if a == 'warehouse_receipt':
        return f"Warehouse received {d.get('quantity_added')} units for order #{oid}"
    if a == 'supplier_event':
        return f"{lookup.get(oid, {}).get('supplier', 'Supplier')} reported {label(d.get('event_type'))} on order #{oid}"
    if a == 'recovery_decision':
        return f"Order #{oid}: {label(d.get('decision'))} — {d.get('reason', '')}"
    if a == 'recovery_cancellation_confirmed':
        return f"Cancellation confirmed for order #{oid}; {d.get('units_released')} units released"
    if a == 'order_approved':
        return f'Manager approved order #{oid}'
    if a == 'agent_completed':
        return 'ChainPilot completed an evaluation'
    if a == 'procurement_escalation':
        return f"Unfulfilled {d.get('component')}: {d.get('reason')}"
    if a == 'supplier_simulated_restock':
        return f"Supplier replenished {d.get('units_added')} units (demo simulation)"
    return None


def run_result(result):
    trace = result.get('trace') or []
    buys, issues, rankings = [], [], []
    for t in trace:
        if t.get('tool') == 'rank_suppliers':
            rankings.append(t)
        if t.get('tool') == 'execute_procurement' and isinstance(t.get('result'), dict):
            for a in t['result'].get('actions') or []:
                (buys if a.get('order_id') is not None else issues).append(a)
    if result.get('status') == 'completed':
        st.success('ChainPilot completed its evaluation.')
    else:
        st.warning('Evaluation status: ' + label(result.get('status')))
    if buys:
        table([{'Order': f"#{a['order_id']}", 'Component': a.get('component'),
                'Supplier': a.get('supplier'), 'Units': a.get('quantity'),
                'Cost (SAR)': a.get('total_cost'), 'Decision': label(a.get('action'))} for a in buys], 'Decision')
    elif not issues:
        st.info('No new purchase orders were created in this run.')
    for a in issues:
        st.warning(f"{a.get('component')}: {a.get('uncovered_quantity')} units still unfulfilled. {a.get('reason', '')}")
    with st.expander('View full evaluation explanation', expanded=False):
        st.markdown(result.get('summary') or 'No AI summary returned.')
    with st.expander('See supplier comparisons and tool records', expanded=False):
        for t in rankings:
            st.markdown('**' + str((t.get('arguments') or {}).get('component', 'Supplier comparison')) + '**')
            if isinstance(t.get('result'), list):
                table(t['result'])
        st.json(trace)


def automatic_history(logs):
    starts = [x for x in logs if x.get('action') == 'agent_started' and log_data(x).get('source') == 'automatic']
    if not starts:
        st.caption('No automatic agent evaluations recorded.')
        return
    for start in starts[:2]:
        rid = log_data(start).get('run_id')
        if not rid:
            continue
        related = sorted((e for e in logs if log_data(e).get('run_id') == rid), key=lambda x: x.get('id', 0))
        final = next((e for e in reversed(related) if e.get('action') in ('agent_completed', 'agent_failed', 'agent_incomplete')), None)
        state = label(final['action'].replace('agent_', '')) if final else 'Running'
        with st.expander(f"{log_data(start).get('trigger', 'Automatic inventory change')} · {state}"):
            for e in related:
                if e.get('action') == 'agent_tool_call':
                    d = log_data(e)
                    st.write(f"**{label(d.get('tool'))}:** {d.get('explanation', 'Tool result saved.')}")
            if final:
                st.markdown(log_data(final).get('summary') or 'Evaluation finished.')


# NAVIGATION: Material icons belong to their buttons, not separate floating HTML.
if 'cp_page' not in st.session_state:
    st.session_state.cp_page = 'Dashboard'
if 'cp_next' in st.session_state:
    st.session_state.cp_page = st.session_state.pop('cp_next')

def go(where):
    st.session_state.cp_next = where
    st.rerun()

with st.sidebar:
    logo = ROOT / 'frontend' / 'assets' / 'logo.png'
    if logo.exists():
        a, b = st.columns([1, 3], vertical_alignment='center')
        a.image(str(logo), width=42)
        b.markdown('**ChainPilot**')
    else:
        st.markdown('<div class="cp-brand"><div class="cp-symbol">CP</div><div><div class="cp-name">ChainPilot</div><div class="cp-caption">Procurement intelligence</div></div></div>', unsafe_allow_html=True)
    st.markdown('<div class="cp-side-label">WORKSPACE</div>', unsafe_allow_html=True)
    for title, ico, key in [
        ('Dashboard', 'space_dashboard', 'dashboard'),
        ('Factory Inventory', 'inventory_2', 'inventory'),
        ('Suppliers', 'local_shipping', 'suppliers'),
        ('Settings', 'tune', 'settings'),
    ]:
        if st.button(title, icon=f':material/{ico}:', key=f'cp_nav_{key}', use_container_width=True):
            go(title)
        if title == st.session_state.cp_page:
            st.markdown(f'<style>.st-key-cp_nav_{key} button {{background:rgba(20,139,131,.13)!important;border-left:3px solid #148b83!important;font-weight:700!important;padding-left:10px!important}}</style>', unsafe_allow_html=True)
    st.markdown('<div class="cp-side-footer">INVENTORY MONITORING<br><span class="cp-dot '+('on' if AUTO else '')+'"></span><strong>'+('Automatic' if AUTO else 'Manual')+'</strong><div class="cp-note">'+('New inventory changes can trigger ChainPilot.' if AUTO else 'Run ChainPilot from the Dashboard.')+'</div></div>', unsafe_allow_html=True)

if st.session_state.get('cp_notice'):
    message, icon = st.session_state.pop('cp_notice')
    st.toast(message, icon=icon)

page = st.session_state.cp_page

if page == 'Dashboard':
    st.markdown('<div class="cp-kicker">OPERATIONS OVERVIEW</div>', unsafe_allow_html=True)
    st.title('Factory Dashboard')
    st.markdown('<div class="cp-description">Inventory needs, supplier risks, and every purchasing decision in one place.</div>', unsafe_allow_html=True)
    inv = api('GET', '/inventory/')
    orders = api('GET', '/procurement/orders')
    suppliers = api('GET', '/suppliers/')
    policy = api('GET', '/policies/')
    recovery = api('GET', '/recovery/decisions')
    logs = api('GET', '/activity')
    lookup = {o['id']: o for o in orders}
    budget = max(0, float(policy['max_budget']) - outstanding_budget(orders))
    missing = [i for i in inv if i.get('uncovered_shortage', 0) > 0]
    delays = [o for o in orders if o['status'] in ('delayed', 'cancellation_requested')]
    approvals = [o for o in orders if o['status'] == 'pending_approval']
    m = st.columns(4)
    m[0].metric('Unfulfilled units', sum(i['uncovered_shortage'] for i in missing))
    m[1].metric('Supplier risks', len(delays))
    m[2].metric('Approvals needed', len(approvals))
    m[3].metric('Budget available', money(budget))
    if missing:
        st.error('Factory demand is not fully covered. Review the shortages below.')
    elif delays:
        st.warning('All demand is covered, but some deliveries are at risk.')
    elif approvals:
        st.warning('Orders are awaiting manager approval.')
    else:
        st.success('No uncovered shortages, active delays, or pending approvals.')
    st.subheader('Needs attention')
    table([{'Component': i['component'], 'Missing': i['uncovered_shortage'],
            'Already on order': i['ordered_or_pending'], 'Status': reason_for_gap(i, suppliers, policy, budget)[0],
            'Explanation': reason_for_gap(i, suppliers, policy, budget)[1]} for i in missing], 'Status')
    st.subheader('Supplier disruptions')
    recent = {}
    for r in recovery:
        recent.setdefault(r.get('order_id'), r)
    rows = []
    for o in delays:
        r = recent.get(o['id'], {})
        decision = ('Awaiting cancellation confirmation' if o['status'] == 'cancellation_requested'
                    else 'Keep order' if r.get('decision') == 'keep_order' else 'Delay under review')
        rows.append({'Order': f"#{o['id']}", 'Supplier': o['supplier'], 'Component': o['component'],
                     'Delivery (days)': o['expected_delivery_days'], 'Decision': decision,
                     'Why': r.get('reason', 'No recovery decision recorded yet.')})
    table(rows, 'Decision')
    cancelled = [o for o in orders if o['status'] == 'cancelled']
    if cancelled:
        st.markdown('**Cancelled orders — explanation**')
        table([{'Order': f"#{o['id']}", 'Supplier': o['supplier'], 'Component': o['component'],
                'Status': 'Cancelled', 'Reason': recent.get(o['id'], {}).get('reason', 'See recovery history.')} for o in cancelled], 'Status')
    with st.expander('View full recovery decision history'):
        table([{'Order': f"#{r.get('order_id')}", 'Policy': r.get('policy'), 'Decision': label(r.get('decision')),
                'Reason': r.get('reason')} for r in recovery[:30]], 'Decision')
    pending_cancel = [o for o in orders if o['status'] == 'cancellation_requested']
    if pending_cancel:
        st.warning('Cancellation was requested. Supplier stock and budget remain reserved until confirmation.')
        choices = {o['id']: o for o in pending_cancel}
        oid = st.selectbox('Order waiting for supplier cancellation confirmation', list(choices), format_func=lambda n: f"#{n} · {choices[n]['supplier']}")
        if st.button('Simulate supplier confirming cancellation', icon=':material/check_circle:'):
            if not SECRET:
                st.error('SUPPLIER_WEBHOOK_SECRET is not configured.')
            else:
                api('POST', f'/recovery/orders/{oid}/confirm-cancellation', timeout=100,
                    headers={'X-Supplier-Secret': SECRET})
                notify(f'Cancellation confirmed for order #{oid}. Replacement sourcing evaluated.')
    st.divider()
    st.subheader('ChainPilot investigation')
    st.caption(f"Current policy — Speed {policy['speed_weight']} · Cost {policy['cost_weight']} · Reliability {policy['reliability_weight']} · Manager approval above {money(policy['approval_threshold'])}")
    if st.button('Run ChainPilot', type='primary', icon=':material/play_arrow:'):
        with st.spinner('Evaluating actual inventory, suppliers and policy...'):
            st.session_state['cp_manual'] = api('POST', '/agent/run', timeout=180)
        notify('ChainPilot finished its evaluation.')
    manual = st.session_state.get('cp_manual')
    if manual:
        run_result(manual)
    else:
        st.caption('Run ChainPilot to see the purchasing outcome and optional detailed explanation.')
    if recovery:
        st.markdown('**Recent recovery decisions**')
        st.caption('These decisions were recorded when supplier events or policy changes occurred, not necessarily during the manual run.')
        for r in recovery[:3]:
            with st.container(border=True):
                st.markdown(f"**Order #{r.get('order_id')} · {label(r.get('decision'))}**")
                st.write(r.get('reason') or 'No reason recorded.')
    with st.expander('Automatic ChainPilot activity'):
        automatic_history(logs)
    st.divider()
    st.subheader('Purchases and delivery')
    table(order_rows(orders), 'Status')
    if approvals:
        st.markdown('**Manager approvals**')
        for o in approvals:
            with st.container(border=True):
                a, b = st.columns([4, 1], vertical_alignment='center')
                a.markdown(f"**Order #{o['id']} · {o['supplier']} · {o['quantity']} {o['component']}**")
                a.caption(f"{money(o['total_cost'])} · Approval policy applies to this purchase (or its combined sourcing plan).")
                if b.button('Approve', key=f"approve_{o['id']}", icon=':material/check:', use_container_width=True):
                    api('POST', f"/procurement/orders/{o['id']}/approve")
                    notify(f"Order #{o['id']} approved.")
    with st.expander('Warehouse receiving — confirm physical delivery'):
        candidates = [o for o in orders if o['status'] in RECEIVABLE and o.get('outstanding_quantity', 0) > 0]
        if not candidates:
            st.caption('No approved orders are waiting for receipt.')
        else:
            opts = {o['id']: o for o in candidates}
            with st.form('receive'):
                oid = st.selectbox('Purchase order', list(opts), format_func=lambda n: f"#{n} · {opts[n]['supplier']} · {opts[n]['component']}")
                qty = st.number_input('Units physically received', min_value=1, max_value=int(opts[oid]['outstanding_quantity']), value=int(opts[oid]['outstanding_quantity']))
                submit = st.form_submit_button('Confirm warehouse receipt')
            if submit:
                rec = api('POST', f'/procurement/orders/{oid}/receive', json={'receipt_id': str(uuid.uuid4()), 'quantity': int(qty)})
                notify(f"Factory stock increased by {rec.get('quantity_added', 0)} units.")
    with st.expander('Recent business activity'):
        records = []
        for e in logs:
            msg = event_message(e, lookup)
            if msg:
                records.append({'UTC time': str(e.get('timestamp', ''))[:19], 'Event': msg})
            if len(records) == 20:
                break
        table(records)

elif page == 'Factory Inventory':
    st.markdown('<div class="cp-kicker">WAREHOUSE</div>', unsafe_allow_html=True)
    st.title('Factory Inventory')
    st.markdown('<div class="cp-description">Track the difference between physical stock, incoming orders and unmet demand.</div>', unsafe_allow_html=True)
    inv = api('GET', '/inventory/')
    table([{'Component': i['component'], 'Warehouse stock': i['stock'], 'Demand': i['demand'],
            'Already ordered': i['ordered_or_pending'], 'Unfulfilled': i['uncovered_shortage']} for i in inv])
    total = sum(int(i['uncovered_shortage']) for i in inv)
    if total:
        st.warning(f'{total} units are still uncovered.')
    else:
        st.success('All demand is covered by warehouse stock and existing orders.')
    a, b = st.columns(2, gap='large')
    with a:
        st.subheader('Adjust warehouse stock')
        with st.form('stock'):
            comp = st.selectbox('Component', [i['component'] for i in inv])
            action = st.radio('Action', ['consume', 'add'], horizontal=True, format_func=lambda x: 'Consume in production' if x == 'consume' else 'Add stock')
            qty = st.number_input('Number of units', min_value=1, value=20)
            submit = st.form_submit_button('Save stock change', type='primary')
        if submit:
            res = api('POST', f'/demo/inventory/{comp}/adjust', json={'action': action, 'quantity': int(qty)})
            st.session_state.pop('cp_manual', None)
            notify(f"{comp} warehouse stock: {res['previous_stock']} → {res['new_stock']}.")
    with b:
        st.subheader('Production target')
        with st.form('target'):
            qty = st.number_input('Laptops to manufacture', min_value=0, value=int(inv[0]['demand']) if inv else 500, step=50)
            submit = st.form_submit_button('Save target')
        if submit:
            api('POST', '/demo/production-target', json={'target': int(qty)})
            st.session_state.pop('cp_manual', None)
            notify(f'Production target updated to {qty}.')
    with st.expander('Demo scenarios and reset'):
        st.warning('These actions clear demo order and activity history. Do not reset while the agent is running.')
        confirm = st.checkbox('I understand this resets demo records.')
        a, b = st.columns(2)
        if a.button('Load 300-battery scenario', disabled=not confirm, use_container_width=True):
            api('POST', '/demo/scenario', json={'name': 'battery_split'})
            st.session_state.pop('cp_manual', None)
            notify('Battery scenario loaded.')
        if b.button('Reset factory', disabled=not confirm, use_container_width=True):
            api('POST', '/demo/reset')
            st.session_state.pop('cp_manual', None)
            notify('Demo restored to seed data.')

elif page == 'Suppliers':
    st.markdown('<div class="cp-kicker">SUPPLIER NETWORK</div>', unsafe_allow_html=True)
    st.title('Suppliers')
    st.markdown('<div class="cp-description">Review supplier availability and simulate messages on real purchase orders.</div>', unsafe_allow_html=True)
    suppliers = api('GET', '/suppliers/')
    orders = api('GET', '/procurement/orders')
    category = st.selectbox('Component filter', ['All'] + sorted({s['component'] for s in suppliers}))
    view = []
    for s in suppliers:
        if category != 'All' and s['component'] != category:
            continue
        reserved = sum(int(o.get('outstanding_quantity') or 0) for o in orders if o['supplier_id'] == s['id'] and o['status'] in ACTIVE)
        view.append({'Supplier': s['name'], 'Component': s['component'], 'Available': s['available'],
                     'Reserved': reserved, 'Unit price (SAR)': s['unit_price'], 'Delivery (days)': s['delivery_days'],
                     'Reliability (%)': s['reliability'], 'Status': 'Eligible' if s['approved'] else 'Paused'})
    table(view, 'Status')
    st.subheader('Existing supplier orders')
    table(order_rows(orders), 'Status')
    st.divider()
    st.subheader('Simulate a supplier update')
    eligible = [o for o in orders if o['status'] in RECEIVABLE and int(o.get('outstanding_quantity') or 0) > 0]
    if not SECRET:
        st.warning('Configure SUPPLIER_WEBHOOK_SECRET in .env for supplier notifications.')
    elif not eligible:
        st.info('There are no approved active purchase orders to update.')
    else:
        companies = {o['supplier_id']: o['supplier'] for o in eligible}
        sid = st.selectbox('Supplier', list(companies), format_func=lambda v: companies[v])
        relevant = {o['id']: o for o in eligible if o['supplier_id'] == sid}
        oid = st.selectbox('Order', list(relevant), format_func=lambda v: f"#{v} · {relevant[v]['component']} · {relevant[v]['outstanding_quantity']} remaining")
        order = relevant[oid]
        kind = st.selectbox('What did the supplier report?', ['delayed', 'cancelled', 'partial_fulfillment', 'shipped', 'delivered'],
                            format_func=lambda v: {'delayed': 'Delivery delayed', 'cancelled': 'Supplier cancelled the order',
                                                   'partial_fulfillment': 'Can deliver fewer units', 'shipped': 'Shipped (in transit)',
                                                   'delivered': 'Delivered to factory'}[v])
        with st.form('supplier_event'):
            days, fulfilled = None, None
            if kind == 'delayed':
                days = st.number_input('New delivery estimate (days)', min_value=1, value=max(5, int(order.get('expected_delivery_days') or 1)))
            if kind == 'partial_fulfillment':
                fulfilled = st.number_input('Total units supplier can fulfill', min_value=int(order['received_quantity']),
                                            max_value=int(order['fulfillable_quantity']), value=int(order['fulfillable_quantity']))
            note = st.text_input('Supplier note', value='Demo supplier notification')
            send = st.form_submit_button('Send supplier update', type='primary')
        if send:
            if kind == 'partial_fulfillment' and fulfilled == 0:
                st.error('Choose Supplier cancelled if zero units can be fulfilled.')
            else:
                payload = {'event_id': str(uuid.uuid4()), 'order_id': int(oid), 'event_type': kind, 'note': note}
                if days is not None:
                    payload['expected_delivery_days'] = int(days)
                if fulfilled is not None:
                    payload['fulfillable_quantity'] = int(fulfilled)
                result = api('POST', '/supplier-events/', json=payload, headers={'X-Supplier-Secret': SECRET}, timeout=100)
                decisions = result.get('recovery_decisions') or []
                receipt = result.get('warehouse_receipt') or {}
                msg = (decisions[0].get('reason') if decisions else
                       f"Warehouse received {receipt.get('quantity_added')} units" if receipt else
                       result.get('message') or f'Supplier update recorded for order #{oid}.')
                notify(msg, ':material/info:' if kind == 'delayed' else ':material/check_circle:')
    st.caption('Shipped means in transit. In demo mode, Delivered updates factory stock if the supplier delivery backend update is installed.')

else:  # Settings
    st.markdown('<div class="cp-kicker">ADMINISTRATION</div>', unsafe_allow_html=True)
    st.title('Purchasing policies')
    st.markdown('<div class="cp-description">Choose how ChainPilot balances speed, cost and reliability. These settings also guide recovery decisions.</div>', unsafe_allow_html=True)
    policy = api('GET', '/policies/')
    presets = {'Current / Custom': None, 'Production First': (70, 10, 20), 'Budget First': (15, 75, 10), 'Balanced': (35, 35, 30)}
    choice = st.selectbox('Purchasing strategy', list(presets))
    weights = presets[choice] or (int(policy['speed_weight']), int(policy['cost_weight']), int(policy['reliability_weight']))
    st.caption('Percentage fields replace the misaligned sliders. The bars underneath always correspond to the values shown.')
    def ascii_number(text, name, integer=False):
        trans = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')
        clean = str(text).translate(trans).replace(',', '').replace('٬', '').strip()
        try:
            number = int(clean) if integer else float(clean)
        except ValueError:
            raise ValueError(f'{name}: enter a valid English-digit number.')
        if number < 0:
            raise ValueError(f'{name}: cannot be negative.')
        return number
    with st.form('policies'):
        cols = st.columns(3)
        labels = ['Delivery speed (%)', 'Low purchase cost (%)', 'Supplier reliability (%)']
        fields = []
        for i, col in enumerate(cols):
            with col:
                value = st.text_input(labels[i], value=str(weights[i]), key=f'weight_{choice}_{i}')
                fields.append(value)
                st.progress(int(weights[i]) / 100)
        st.markdown('<div class="cp-section">Purchasing limits</div>', unsafe_allow_html=True)
        cols = st.columns(3)
        with cols[0]:
            budget_raw = st.text_input('Maximum outstanding budget (SAR)', value=str(int(float(policy['max_budget']))))
        with cols[1]:
            days_raw = st.text_input('Maximum delivery days', value=str(int(policy['max_delivery_days'])))
        with cols[2]:
            threshold_raw = st.text_input('Approval threshold (SAR)', value=str(int(float(policy['approval_threshold']))))
        save = st.form_submit_button('Save purchasing policy', type='primary', icon=':material/save:')
    if save:
        try:
            speed, cost, reliability = [ascii_number(x, labels[i], True) for i, x in enumerate(fields)]
            budget = ascii_number(budget_raw, 'Budget')
            days = ascii_number(days_raw, 'Delivery days', True)
            approval = ascii_number(threshold_raw, 'Approval threshold')
            if any(x > 100 for x in (speed, cost, reliability)) or not (speed + cost + reliability):
                raise ValueError('Priorities must be between 0 and 100, with at least one above zero.')
            if budget <= 0 or days < 1:
                raise ValueError('Budget must be positive and delivery days must be at least 1.')
        except ValueError as exc:
            st.error(str(exc))
        else:
            api('PUT', '/policies/', json={'speed_weight': speed, 'cost_weight': cost,
                'reliability_weight': reliability, 'max_budget': budget, 'max_delivery_days': days,
                'approval_threshold': approval}, timeout=100)
            notify('Purchasing policy saved. Open orders were reviewed.')
    st.info('Automatic supplier cancellation confirmation is ' + ('enabled' if AUTOCANCEL else 'disabled') + '. This affects only the fictional supplier simulation.')
    if st.button('Back to Dashboard', icon=':material/arrow_back:'):
        go('Dashboard')
