"""
streamlit_app.py  — drop-in replacement
Adds inline Approve / Reject buttons in the Leave Requests tab.
Managers/HR can action directly from the dashboard.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from app.models import Base, Employee, LeaveRequest, OnboardingTask, SessionLocal, Ticket, engine
from app.services.leave_service import LeaveService

leave_service = LeaveService()


def _init_db() -> None:
    Base.metadata.create_all(bind=engine)


def _safe_dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


@st.cache_data(ttl=10)
def load_data():
    db = SessionLocal()
    try:
        employees = db.query(Employee).all()
        tickets = db.query(Ticket).all()
        tasks = db.query(OnboardingTask).all()
        leaves = db.query(LeaveRequest).all()

        emp_df = pd.DataFrame(
            [
                {
                    "emp_id": e.emp_id,
                    "name": e.name,
                    "email": e.email,
                    "department": e.department,
                    "role": e.role,
                    "manager_emp_id": e.manager_emp_id,
                    "status": e.status,
                    "system_role": getattr(e, "system_role", None),
                    "created_at": _safe_dt(getattr(e, "created_at", None)),
                }
                for e in employees
            ]
        )

        ticket_df = pd.DataFrame(
            [
                {
                    "ticket_id": t.ticket_id,
                    "emp_id": t.emp_id,
                    "category": t.category,
                    "item": t.item,
                    "reason": t.reason,
                    "status": t.status,
                    "created_at": _safe_dt(getattr(t, "created_at", None)),
                    "updated_at": _safe_dt(getattr(t, "updated_at", None)),
                }
                for t in tickets
            ]
        )

        task_df = pd.DataFrame(
            [
                {
                    "emp_id": t.emp_id,
                    "task_name": t.task_name,
                    "owner": t.owner,
                    "status": t.status,
                    "due_date": t.due_date,
                    "created_at": _safe_dt(getattr(t, "created_at", None)),
                }
                for t in tasks
            ]
        )

        leave_df = pd.DataFrame(
            [
                {
                    "request_id": r.request_id,
                    "emp_id": r.emp_id,
                    "leave_type": r.leave_type,
                    "start_date": r.start_date,
                    "end_date": r.end_date,
                    "reason": r.reason,
                    "status": r.status,
                    "approved_by": getattr(r, "approved_by", None),
                    "rejection_reason": getattr(r, "rejection_reason", None),
                    "created_at": _safe_dt(getattr(r, "created_at", None)),
                    "updated_at": _safe_dt(getattr(r, "updated_at", None)),
                }
                for r in leaves
            ]
        )

        return emp_df, ticket_df, task_df, leave_df
    finally:
        db.close()


def _load_managers(emp_df: pd.DataFrame) -> list[tuple[str, str]]:
    """Return [(emp_id, label)] for employees with Manager/HR roles."""
    if emp_df.empty:
        return []
    mask = emp_df["system_role"].isin(["Manager", "HR Admin", "HR Staff"])
    managers = emp_df[mask][["emp_id", "name", "system_role"]].drop_duplicates()
    return [(row["emp_id"], f"{row['name']} ({row['emp_id']}) — {row['system_role']}")
            for _, row in managers.iterrows()]


def _render_leave_tab(leave_df: pd.DataFrame, emp_df: pd.DataFrame):
    """Render the Leave Requests tab with inline approve/reject actions."""
    st.subheader("Leave Requests")

    if leave_df.empty:
        st.info("No leave requests found.")
        return

    # ── Approver selector ────────────────────────────────────────────
    managers = _load_managers(emp_df)
    if managers:
        manager_labels = [label for _, label in managers]
        manager_ids = [emp_id for emp_id, _ in managers]
        selected_idx = st.selectbox(
            "Acting as (approver/rejector)",
            range(len(manager_labels)),
            format_func=lambda i: manager_labels[i],
            key="leave_approver",
        )
        acting_as = manager_ids[selected_idx]
    else:
        st.warning(
            "No employees with Manager / HR Admin / HR Staff roles found. "
            "Update an employee's system_role to enable approvals."
        )
        acting_as = None

    # ── Status filter ────────────────────────────────────────────────
    status_filter = st.radio(
        "Filter by status",
        ["All", "Pending", "Approved", "Rejected"],
        horizontal=True,
        key="leave_status_filter",
    )
    display_df = leave_df if status_filter == "All" else leave_df[leave_df["status"] == status_filter]

    if display_df.empty:
        st.info(f"No {status_filter.lower()} leave requests.")
        return

    # ── Notification area ────────────────────────────────────────────
    notif = st.empty()

    # ── Per-row action table ─────────────────────────────────────────
    pending_rows = display_df[display_df["status"] == "Pending"]
    non_pending = display_df[display_df["status"] != "Pending"]

    # Show non-pending rows as plain dataframe
    if not non_pending.empty:
        show_cols = ["request_id", "emp_id", "leave_type", "start_date", "end_date", "status",
                     "approved_by", "rejection_reason", "reason"]
        present = [c for c in show_cols if c in non_pending.columns]
        st.dataframe(non_pending[present].sort_values("request_id"),
                     use_container_width=True, hide_index=True)

    # Show pending rows with action buttons
    if not pending_rows.empty:
        st.markdown("#### ⏳ Pending Requests")

        # Rejection reason input (shared for all pending rows for simplicity)
        rejection_reason = st.text_input(
            "Rejection reason (optional, applies to the Reject button you click)",
            key="rejection_reason_input",
            placeholder="e.g. Insufficient staffing during that period",
        )

        for _, row in pending_rows.iterrows():
            with st.container():
                c1, c2, c3, c4, c5, c6 = st.columns([1.2, 1, 1, 1.5, 1.5, 0.8])
                c1.markdown(f"**{row['request_id']}**")
                c2.markdown(row["emp_id"])
                c3.markdown(row["leave_type"])
                c4.markdown(f"{row['start_date']} → {row['end_date']}")
                c5.markdown(f"_{row.get('reason', '') or '—'}_")

                btn_col_a, btn_col_r = c6.columns(2)
                approve_key = f"approve_{row['request_id']}"
                reject_key = f"reject_{row['request_id']}"

                if btn_col_a.button("✅", key=approve_key, help="Approve this leave request",
                                    disabled=acting_as is None):
                    result = leave_service.approve_leave(
                        request_id=row["request_id"],
                        approved_by=acting_as,
                    )
                    if "error" in result:
                        notif.error(result["error"])
                    else:
                        notif.success(result["message"])
                        st.cache_data.clear()
                        st.rerun()

                if btn_col_r.button("❌", key=reject_key, help="Reject this leave request",
                                    disabled=acting_as is None):
                    result = leave_service.reject_leave(
                        request_id=row["request_id"],
                        rejected_by=acting_as,
                        rejection_reason=rejection_reason,
                    )
                    if "error" in result:
                        notif.error(result["error"])
                    else:
                        notif.warning(result["message"])
                        st.cache_data.clear()
                        st.rerun()


def main():
    _init_db()

    st.set_page_config(page_title="HR Analytics", layout="wide")
    st.title("HR Analytics Dashboard")
    st.caption("Powered by your HRMS SQLite database.")

    emp_df, ticket_df, task_df, leave_df = load_data()

    # ── Sidebar filters ───────────────────────────────────────────────
    st.sidebar.header("Filters")
    departments = sorted([d for d in emp_df.get("department", pd.Series()).dropna().unique().tolist() if d])
    dept = st.sidebar.selectbox("Department", options=["All"] + departments, index=0)

    if dept != "All" and not emp_df.empty:
        emp_df = emp_df[emp_df["department"] == dept]
        if not ticket_df.empty:
            ticket_df = ticket_df[ticket_df["emp_id"].isin(emp_df["emp_id"].tolist())]
        if not task_df.empty:
            task_df = task_df[task_df["emp_id"].isin(emp_df["emp_id"].tolist())]
        if not leave_df.empty:
            leave_df = leave_df[leave_df["emp_id"].isin(emp_df["emp_id"].tolist())]

    # ── KPI row ───────────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Employees", int(len(emp_df.index)) if not emp_df.empty else 0)
    c2.metric("Open tickets", int((ticket_df["status"] == "Open").sum()) if not ticket_df.empty else 0)
    c3.metric("Pending onboarding tasks", int((task_df["status"] == "Pending").sum()) if not task_df.empty else 0)
    c4.metric("Pending leave requests", int((leave_df["status"] == "Pending").sum()) if not leave_df.empty else 0)

    left, right = st.columns([1, 1])
    with left:
        st.subheader("Headcount by department")
        if emp_df.empty:
            st.info("No employees found for the selected filter.")
        else:
            dept_counts = (
                emp_df.assign(department=emp_df["department"].fillna("Unassigned"))
                .groupby("department")["emp_id"]
                .count()
                .sort_values(ascending=False)
            )
            st.bar_chart(dept_counts)

    with right:
        st.subheader("Tickets by category")
        if ticket_df.empty:
            st.info("No tickets found for the selected filter.")
        else:
            cat_counts = ticket_df.groupby("category")["ticket_id"].count().sort_values(ascending=False)
            st.bar_chart(cat_counts)

    st.divider()

    tab1, tab2, tab3, tab4 = st.tabs(["Employees", "Tickets", "Onboarding tasks", "Leave requests"])

    with tab1:
        st.subheader("Employees")
        if emp_df.empty:
            st.write([])
        else:
            show_cols = ["emp_id", "name", "email", "department", "role", "manager_emp_id", "status", "system_role"]
            present = [c for c in show_cols if c in emp_df.columns]
            st.dataframe(emp_df[present].sort_values(["emp_id"]), use_container_width=True, hide_index=True)

    with tab2:
        st.subheader("Tickets")
        if ticket_df.empty:
            st.write([])
        else:
            show_cols = ["ticket_id", "emp_id", "category", "item", "status", "reason"]
            st.dataframe(ticket_df[show_cols].sort_values(["ticket_id"]), use_container_width=True, hide_index=True)

    with tab3:
        st.subheader("Onboarding tasks")
        if task_df.empty:
            st.write([])
        else:
            show_cols = ["emp_id", "task_name", "owner", "status", "due_date"]
            st.dataframe(task_df[show_cols].sort_values(["emp_id", "owner"]), use_container_width=True, hide_index=True)

    with tab4:
        _render_leave_tab(leave_df, emp_df)


if __name__ == "__main__":
    main()
