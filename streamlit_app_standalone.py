"""
HRMS Analytics Dashboard — with Audit Logging
Reads directly from hrms.db. Writes audit trail to audit.log.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text

try:
    import anthropic as _anthropic
    CLAUDE_AVAILABLE = bool(os.getenv("ANTHROPIC_API_KEY"))
except ImportError:
    _anthropic = None
    CLAUDE_AVAILABLE = False

# ── Paths ─────────────────────────────────────────────────────────────
BASE_DIR = Path("/data")
DB_PATH  = Path("/data/hrms.db")
LOG_PATH = BASE_DIR / "audit.log"

# ── Audit logger ──────────────────────────────────────────────────────
audit_logger = logging.getLogger("hrms.audit")
audit_logger.setLevel(logging.INFO)
audit_logger.propagate = False

if not audit_logger.handlers:
    _handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
    _handler.setFormatter(logging.Formatter("%(message)s"))
    audit_logger.addHandler(_handler)


def audit(action: str, performed_by: str, details: dict):
    """Append a structured JSON line to audit.log."""
    entry = {
        "timestamp":    datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "action":       action,
        "performed_by": performed_by,
        **details,
    }
    audit_logger.info(json.dumps(entry))


def read_audit_log(n: int = 200) -> list[dict]:
    """Return last n audit entries, newest first."""
    if not LOG_PATH.exists():
        return []
    lines = LOG_PATH.read_text(encoding="utf-8").strip().splitlines()
    entries = []
    for line in reversed(lines):
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries[:n]


# ── DB ────────────────────────────────────────────────────────────────
engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
)


def query(sql: str) -> pd.DataFrame:
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn)


@st.cache_data(ttl=10)
def load_data():
    return (
        query("SELECT * FROM employees"),
        query("SELECT * FROM tickets"),
        query("SELECT * FROM onboarding_tasks"),
        query("SELECT * FROM leave_requests"),
    )


# ── Actions (each writes an audit entry) ─────────────────────────────

def approve_leave(request_id: str, approved_by: str) -> dict:
    with engine.begin() as conn:
        row = conn.execute(text("SELECT * FROM leave_requests WHERE request_id=:r"), {"r": request_id}).fetchone()
        if not row:
            return {"error": f"Request {request_id} not found."}
        if row.status != "Pending":
            return {"error": f"Already '{row.status}'."}
        conn.execute(
            text("UPDATE leave_requests SET status='Approved', updated_at=:n WHERE request_id=:r"),
            {"n": datetime.utcnow().isoformat(), "r": request_id},
        )
    audit("LEAVE_APPROVED", approved_by, {
        "request_id": request_id, "emp_id": row.emp_id,
        "leave_type": row.leave_type, "start_date": row.start_date, "end_date": row.end_date,
    })
    return {"message": f"✅ {request_id} approved by {approved_by}."}


def reject_leave(request_id: str, rejected_by: str, reason: str = "") -> dict:
    with engine.begin() as conn:
        row = conn.execute(text("SELECT * FROM leave_requests WHERE request_id=:r"), {"r": request_id}).fetchone()
        if not row:
            return {"error": f"Request {request_id} not found."}
        if row.status != "Pending":
            return {"error": f"Already '{row.status}'."}
        conn.execute(
            text("UPDATE leave_requests SET status='Rejected', updated_at=:n WHERE request_id=:r"),
            {"n": datetime.utcnow().isoformat(), "r": request_id},
        )
    audit("LEAVE_REJECTED", rejected_by, {
        "request_id": request_id, "emp_id": row.emp_id,
        "leave_type": row.leave_type, "rejection_reason": reason or None,
    })
    return {"message": f"❌ {request_id} rejected." + (f" Reason: {reason}" if reason else "")}


def close_ticket(ticket_id: str, closed_by: str) -> dict:
    with engine.begin() as conn:
        row = conn.execute(text("SELECT * FROM tickets WHERE ticket_id=:t"), {"t": ticket_id}).fetchone()
        if not row:
            return {"error": f"Ticket {ticket_id} not found."}
        if row.status == "Closed":
            return {"error": f"Ticket {ticket_id} already closed."}
        conn.execute(
            text("UPDATE tickets SET status='Closed', updated_at=:n WHERE ticket_id=:t"),
            {"n": datetime.utcnow().isoformat(), "t": ticket_id},
        )
    audit("TICKET_CLOSED", closed_by, {
        "ticket_id": ticket_id, "emp_id": row.emp_id,
        "category": row.category, "item": row.item,
    })
    return {"message": f"🎫 Ticket {ticket_id} closed by {closed_by}."}


def complete_task(emp_id: str, task_name: str, completed_by: str) -> dict:
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT * FROM onboarding_tasks WHERE emp_id=:e AND task_name=:t"),
            {"e": emp_id, "t": task_name},
        ).fetchone()
        if not row:
            return {"error": "Task not found."}
        if row.status == "Completed":
            return {"error": "Task already completed."}
        conn.execute(
            text("""UPDATE onboarding_tasks
                    SET status='Completed', completed_at=:n, updated_at=:n
                    WHERE emp_id=:e AND task_name=:t"""),
            {"n": datetime.utcnow().isoformat(), "e": emp_id, "t": task_name},
        )
    audit("ONBOARDING_TASK_COMPLETED", completed_by, {
        "emp_id": emp_id, "task_name": task_name, "owner": row.owner,
    })
    return {"message": f"📋 '{task_name}' marked complete."}


def update_employee_status(emp_id: str, new_status: str, updated_by: str) -> dict:
    with engine.begin() as conn:
        row = conn.execute(text("SELECT * FROM employees WHERE emp_id=:e"), {"e": emp_id}).fetchone()
        if not row:
            return {"error": f"Employee {emp_id} not found."}
        old_status = row.status
        conn.execute(
            text("UPDATE employees SET status=:s WHERE emp_id=:e"),
            {"s": new_status, "e": emp_id},
        )
    audit("EMPLOYEE_UPDATED", updated_by, {
        "emp_id": emp_id, "name": row.name,
        "field": "status", "old_value": old_status, "new_value": new_status,
    })
    return {"message": f"👤 {row.name} status → {new_status}."}


# ── Sidebar: Audit Log Panel ──────────────────────────────────────────

ACTION_ICONS = {
    "LEAVE_APPROVED":            "✅",
    "LEAVE_REJECTED":            "❌",
    "TICKET_CLOSED":             "🎫",
    "ONBOARDING_TASK_COMPLETED": "📋",
    "EMPLOYEE_UPDATED":          "👤",
}

DETAIL_KEYS = ["request_id", "ticket_id", "emp_id", "task_name", "field", "new_value"]


def render_audit_sidebar():
    st.sidebar.divider()
    st.sidebar.header("📋 Audit Log")

    entries = read_audit_log()

    if not entries:
        st.sidebar.caption("No audit entries yet. Actions you take will appear here.")
        return

    all_actions = sorted({e["action"] for e in entries})
    selected = st.sidebar.multiselect("Filter by action", all_actions, default=all_actions)
    filtered = [e for e in entries if e["action"] in selected]

    st.sidebar.caption(f"{len(filtered)} entries · newest first")

    for entry in filtered[:50]:
        icon   = ACTION_ICONS.get(entry["action"], "•")
        ts     = entry.get("timestamp", "")[:19].replace("T", " ")
        by     = entry.get("performed_by", "?")
        action = entry["action"].replace("_", " ").title()
        parts  = [f"{k}: {entry[k]}" for k in DETAIL_KEYS if k in entry]
        detail = " · ".join(parts[:3])

        st.sidebar.markdown(
            f"{icon} **{action}**  \n"
            f"<small>🕐 {ts} &nbsp;·&nbsp; 👤 {by}</small>  \n"
            f"<small style='color:gray'>{detail}</small>",
            unsafe_allow_html=True,
        )

    if len(filtered) > 50:
        st.sidebar.caption(f"… {len(filtered) - 50} more in audit.log")

    st.sidebar.divider()
    if st.sidebar.button("⬇️ Export audit.log"):
        data = LOG_PATH.read_text(encoding="utf-8") if LOG_PATH.exists() else ""
        st.sidebar.download_button("Download", data=data, file_name="audit.log", mime="text/plain")


# ── App ───────────────────────────────────────────────────────────────

st.set_page_config(page_title="HRMS Dashboard", page_icon="🏢", layout="wide")
st.title("🏢 HR Analytics Dashboard")
st.caption(f"Live data · Audit trail → {LOG_PATH}")

emp_df, ticket_df, task_df, leave_df = load_data()

# Sidebar: filters
st.sidebar.header("Filters")
dept = st.sidebar.selectbox(
    "Department",
    ["All"] + sorted(emp_df["department"].dropna().unique().tolist()),
)
if dept != "All":
    filtered_emp = emp_df[emp_df["department"] == dept]
    ids = filtered_emp["emp_id"].tolist()
    ticket_df = ticket_df[ticket_df["emp_id"].isin(ids)]
    task_df   = task_df[task_df["emp_id"].isin(ids)]
    leave_df  = leave_df[leave_df["emp_id"].isin(ids)]
else:
    filtered_emp = emp_df

# Sidebar: audit log panel
render_audit_sidebar()

# KPIs
k1, k2, k3, k4 = st.columns(4)
k1.metric("👥 Employees",          len(filtered_emp))
k2.metric("🎫 Open Tickets",       int((ticket_df["status"] == "Open").sum()))
k3.metric("📋 Pending Onboarding", int((task_df["status"] == "Pending").sum()))
k4.metric("🏖️ Pending Leave",     int((leave_df["status"] == "Pending").sum()))

# Charts
col1, col2 = st.columns(2)
with col1:
    st.subheader("Headcount by Department")
    if not filtered_emp.empty:
        st.bar_chart(filtered_emp.groupby("department")["emp_id"].count().sort_values(ascending=False))
with col2:
    st.subheader("Tickets by Category")
    if not ticket_df.empty:
        st.bar_chart(ticket_df.groupby("category")["ticket_id"].count().sort_values(ascending=False))

st.divider()

tab1, tab2, tab3, tab4, tab5 = st.tabs(["👥 Employees", "🎫 Tickets", "📋 Onboarding", "🏖️ Leave Requests", "🤖 Agent"])

# ── Employees ─────────────────────────────────────────────────────────
with tab1:
    cols = [c for c in ["emp_id","name","email","department","role","manager_emp_id","status","system_role"] if c in filtered_emp.columns]
    st.dataframe(filtered_emp[cols].sort_values("emp_id"), use_container_width=True, hide_index=True)

    st.markdown("#### ✏️ Update Employee Status")
    emp_opts = {f"{r['name']} ({r['emp_id']})": r["emp_id"] for _, r in filtered_emp.iterrows()}
    ca, cb, cc = st.columns([2, 1, 2])
    sel_emp    = ca.selectbox("Employee",   list(emp_opts.keys()), key="upd_emp")
    new_status = cb.selectbox("New status", ["Active","Inactive","On Leave","Terminated"], key="upd_status")
    by_emp     = cc.selectbox("Updated by", list(emp_opts.keys()), key="upd_by")
    if st.button("Update Status"):
        r = update_employee_status(emp_opts[sel_emp], new_status, emp_opts[by_emp])
        st.error(r["error"]) if "error" in r else (st.success(r["message"]), st.cache_data.clear(), st.rerun())

# ── Tickets ───────────────────────────────────────────────────────────
with tab2:
    cols = [c for c in ["ticket_id","emp_id","category","item","status","reason"] if c in ticket_df.columns]
    st.dataframe(ticket_df[cols].sort_values("ticket_id") if not ticket_df.empty else ticket_df,
                 use_container_width=True, hide_index=True)

    open_tix = ticket_df[ticket_df["status"] == "Open"]
    if not open_tix.empty:
        st.markdown("#### 🔒 Close a Ticket")
        emp_opts = {f"{r['name']} ({r['emp_id']})": r["emp_id"] for _, r in emp_df.iterrows()}
        ca, cb = st.columns([2, 2])
        sel_tkt  = ca.selectbox("Ticket",    open_tix["ticket_id"].tolist(), key="tkt_sel")
        by_tkt   = cb.selectbox("Closed by", list(emp_opts.keys()), key="tkt_by")
        if st.button("Close Ticket"):
            r = close_ticket(sel_tkt, emp_opts[by_tkt])
            st.error(r["error"]) if "error" in r else (st.success(r["message"]), st.cache_data.clear(), st.rerun())

# ── Onboarding ────────────────────────────────────────────────────────
with tab3:
    cols = [c for c in ["emp_id","task_name","owner","status","due_date"] if c in task_df.columns]
    st.dataframe(task_df[cols].sort_values(["emp_id","owner"]) if not task_df.empty else task_df,
                 use_container_width=True, hide_index=True)

    pending_tasks = task_df[task_df["status"] == "Pending"]
    if not pending_tasks.empty:
        st.markdown("#### ✅ Complete a Task")
        emp_opts  = {f"{r['name']} ({r['emp_id']})": r["emp_id"] for _, r in emp_df.iterrows()}
        task_opts = {f"{r['emp_id']} — {r['task_name']}": (r["emp_id"], r["task_name"])
                     for _, r in pending_tasks.iterrows()}
        ca, cb = st.columns([3, 2])
        sel_task = ca.selectbox("Task",         list(task_opts.keys()), key="task_sel")
        comp_by  = cb.selectbox("Completed by", list(emp_opts.keys()),  key="task_by")
        if st.button("Mark Complete"):
            eid, tname = task_opts[sel_task]
            r = complete_task(eid, tname, emp_opts[comp_by])
            st.error(r["error"]) if "error" in r else (st.success(r["message"]), st.cache_data.clear(), st.rerun())

# ── Leave Requests ────────────────────────────────────────────────────
with tab4:
    if leave_df.empty:
        st.info("No leave requests.")
    else:
        managers = emp_df[emp_df["system_role"].isin(["Manager","HR Admin","HR Staff"])] \
            if "system_role" in emp_df.columns else pd.DataFrame()
        if managers.empty:
            managers = emp_df
        mgr_opts  = {f"{r['name']} ({r['emp_id']})": r["emp_id"] for _, r in managers.iterrows()}
        acting_as = mgr_opts[st.selectbox("Acting as (approver)", list(mgr_opts.keys()))]

        sf      = st.radio("Filter", ["All","Pending","Approved","Rejected"], horizontal=True)
        display = leave_df if sf == "All" else leave_df[leave_df["status"] == sf]
        notif   = st.empty()

        done = display[display["status"] != "Pending"]
        if not done.empty:
            show = [c for c in ["request_id","emp_id","leave_type","start_date","end_date","status","reason"] if c in done.columns]
            st.dataframe(done[show], use_container_width=True, hide_index=True)

        pending = display[display["status"] == "Pending"]
        if not pending.empty:
            st.markdown("#### ⏳ Pending — action required")
            rej_reason = st.text_input("Rejection reason (optional)", placeholder="e.g. Insufficient staffing")
            for _, row in pending.iterrows():
                c1,c2,c3,c4,c5,c6,c7 = st.columns([1,1.2,1,1.2,1.5,0.6,0.6])
                c1.markdown(f"**{row['request_id']}**")
                c2.markdown(row["emp_id"])
                c3.markdown(str(row.get("leave_type", "")))
                c4.markdown(f"{row.get('start_date','')} → {row.get('end_date','')}")
                c5.markdown(f"_{row.get('reason','') or '—'}_")
                if c6.button("✅", key=f"a_{row['request_id']}", help="Approve"):
                    r = approve_leave(row["request_id"], acting_as)
                    if "error" in r:
                        notif.error(r["error"])
                    else:
                        notif.success(r["message"])
                        st.cache_data.clear()
                        st.rerun()
                if c7.button("❌", key=f"r_{row['request_id']}", help="Reject"):
                    r = reject_leave(row["request_id"], acting_as, rej_reason)
                    if "error" in r:
                        notif.error(r["error"])
                    else:
                        notif.warning(r["message"])
                        st.cache_data.clear()
                        st.rerun()

# ── Tab 5: HR Agent v2 ────────────────────────────────────────────────
with tab5:
    st.subheader("🤖 HR Agent")
    st.caption("Full agentic HR assistant — multi-step planning, persistent memory, proactive alerts, self-correction.")

    if not CLAUDE_AVAILABLE:
        st.warning(
            "**ANTHROPIC_API_KEY not set.**\n\n"
            "```powershell\n$env:ANTHROPIC_API_KEY='sk-ant-...'\nstreamlit run streamlit_app_standalone.py\n```"
        )
    else:
        # ── Import agent ──────────────────────────────────────────────
        import sys
        sys.path.insert(0, str(Path(r"C:\HRMS")))
        try:
            from agent.hr_agent_v2 import HRAgentV2, generate_alerts, HRDB
            AGENT_AVAILABLE = True
        except ImportError:
            AGENT_AVAILABLE = False
            st.error("Could not import HRAgentV2. Make sure hr_agent_v2.py is saved to C:\\HRMS\\agent\\")

        if AGENT_AVAILABLE:
            # ── Actor selector ────────────────────────────────────────
            all_emps = query("SELECT emp_id, name FROM employees ORDER BY emp_id")
            emp_opts = {f"{r['name']} ({r['emp_id']})": r["emp_id"] for _, r in all_emps.iterrows()}
            actor_label = st.selectbox("You are acting as", list(emp_opts.keys()), key="agent_actor_sel")
            actor_id = emp_opts[actor_label]

            # ── Instantiate agent (cached per actor) ──────────────────
            @st.cache_resource
            def get_agent(aid: str) -> "HRAgentV2":
                return HRAgentV2(db_path=str(DB_PATH), actor_id=aid)

            agent = get_agent(actor_id)
            agent.actor_id = actor_id  # update actor if selector changes

            # ── Proactive alerts banner ───────────────────────────────
            db_inst = HRDB(str(DB_PATH))
            alerts = generate_alerts(db_inst)
            if alerts:
                with st.expander(f"🚨 {len(alerts)} proactive alert(s) — click to review", expanded=True):
                    for a in alerts:
                        icon = "⚠️" if a["level"] == "warning" else "ℹ️"
                        st.markdown(f"{icon} {a['message']}")

            # ── Persistent memory facts ───────────────────────────────
            facts = agent.memory.all_facts()
            if facts:
                with st.expander(f"🧠 Agent memory ({len(facts)} facts stored)"):
                    for k, v in facts.items():
                        st.markdown(f"- **{k}**: {v}")
                    if st.button("🗑️ Clear memory"):
                        agent.memory._data["facts"] = {}
                        agent.memory.save()
                        st.rerun()

            # ── Example prompts ───────────────────────────────────────
            with st.expander("💡 Example prompts"):
                st.markdown("""
**Multi-step planning**
- Hire Sarah Connor as a DevOps Engineer in IT reporting to E002 with email sarah@company.com
- Onboard E004 — create all tasks and an IT setup ticket

**Proactive alerts**
- What alerts do we have right now?
- Show me any overdue onboarding tasks

**Data queries**
- How many employees are in each department?
- Which tickets have been open longest?
- Who has pending leave requests?

**Actions**
- Approve leave request L0001
- Close ticket T0001
- Mark the laptop setup task as done for E004

**Memory**
- Remember that our HR policy allows 20 days annual leave
- What do you remember about our company?

**Digest**
- Give me a daily HR digest
                """)

            # ── Chat history (from persistent memory) ─────────────────
            for msg in agent.memory.history:
                role = msg["role"]
                content = msg["content"]
                if isinstance(content, str):
                    with st.chat_message(role):
                        st.markdown(content)

            # ── Chat input ────────────────────────────────────────────
            prompt = st.chat_input("Ask the HR agent anything...")
            if prompt:
                with st.chat_message("user"):
                    st.markdown(prompt)
                with st.chat_message("assistant"):
                    with st.spinner("Agent thinking..."):
                        try:
                            reply = agent.chat(prompt)
                        except Exception as e:
                            reply = f"❌ Agent error: {e}"
                    st.markdown(reply)
                st.cache_data.clear()
                st.rerun()

            # ── Controls ──────────────────────────────────────────────
            col_a, col_b = st.columns(2)
            with col_a:
                if st.button("📋 Run daily digest"):
                    with st.spinner("Generating digest..."):
                        digest = agent.run_scheduled_digest()
                    st.markdown(digest)
            with col_b:
                if st.button("🗑️ Clear conversation"):
                    agent.memory.clear_history()
                    st.rerun()
