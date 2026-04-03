"""
ui.py  — drop-in replacement
Adds formatter blocks for approve_leave / reject_leave / list_leave_requests.
New prompts and Quick Actions added at the bottom.
"""

import streamlit as st
from agent.chat_ai import run_chat_agent

st.set_page_config(page_title="HRMS Chat AI", page_icon="🤖", layout="wide")


# ── Formatters ────────────────────────────────────────────────────────


def _fmt_leave_list(records: list) -> str:
    if not records:
        return "No leave requests found."
    lines = ["### Leave Requests"]
    for r in records:
        status_icon = {"Approved": "✅", "Rejected": "❌", "Pending": "⏳"}.get(r.get("status", ""), "•")
        lines.append(
            f"- {status_icon} **{r.get('request_id', 'N/A')}** — "
            f"Employee: {r.get('emp_id', 'N/A')}  \n"
            f"  **Type:** {r.get('leave_type', 'N/A')} | "
            f"**Dates:** {r.get('start_date', 'N/A')} → {r.get('end_date', 'N/A')} | "
            f"**Status:** {r.get('status', 'N/A')}  \n"
            f"  **Reason:** {r.get('reason', 'N/A')}"
        )
    return "\n".join(lines)


def _fmt_leave_action(result: dict, action: str) -> str:
    icon = "✅" if action == "approved" else "❌"
    audit = result.get("audit", {})
    lr = result.get("leave_request", {})
    lines = [
        f"{icon} {result.get('message', '')}",
        "",
        "### Leave Request Details",
        f"**Request ID:** {lr.get('request_id', 'N/A')}  ",
        f"**Employee:** {lr.get('emp_id', 'N/A')}  ",
        f"**Type:** {lr.get('leave_type', 'N/A')}  ",
        f"**Dates:** {lr.get('start_date', 'N/A')} → {lr.get('end_date', 'N/A')}  ",
        f"**Status:** {lr.get('status', 'N/A')}  ",
    ]
    if action == "approved":
        lines += [
            "",
            "### Audit",
            f"**Approved by:** {audit.get('approved_by_name', 'N/A')} ({audit.get('approved_by_emp_id', 'N/A')})  ",
            f"**Approved at:** {audit.get('approved_at', 'N/A')}  ",
            f"**Duration:** {audit.get('duration_days', 'N/A')} day(s)  ",
        ]
    else:
        lines += [
            "",
            "### Audit",
            f"**Rejected by:** {audit.get('rejected_by_name', 'N/A')} ({audit.get('rejected_by_emp_id', 'N/A')})  ",
            f"**Rejected at:** {audit.get('rejected_at', 'N/A')}  ",
        ]
        if audit.get("rejection_reason"):
            lines.append(f"**Reason:** {audit['rejection_reason']}  ")
    return "\n".join(lines)


def format_result(result):
    if isinstance(result, str):
        return result

    if isinstance(result, list):
        if not result:
            return "No records found."

        first = result[0]

        if isinstance(first, dict) and "emp_id" in first and "leave_type" in first:
            return _fmt_leave_list(result)

        if isinstance(first, dict) and "emp_id" in first:
            lines = ["### Employees"]
            for emp in result:
                lines.append(
                    f"- **{emp.get('emp_id', 'N/A')}** — {emp.get('name', 'N/A')}  \n"
                    f"  **Department:** {emp.get('department', 'N/A')} | "
                    f"**Job Title:** {emp.get('role', 'N/A')} | "
                    f"**Access Role:** {emp.get('system_role', 'Employee')} | "
                    f"**Manager:** {emp.get('manager_emp_id', 'None')} | "
                    f"**Status:** {emp.get('status', 'N/A')}  \n"
                    f"  **Email:** {emp.get('email', 'N/A')}"
                )
            return "\n".join(lines)

        if isinstance(first, dict) and "ticket_id" in first:
            lines = ["### Tickets"]
            for ticket in result:
                lines.append(
                    f"- **{ticket.get('ticket_id', 'N/A')}** — Employee: {ticket.get('emp_id', 'N/A')}  \n"
                    f"  **Category:** {ticket.get('category', 'N/A')} | "
                    f"**Item:** {ticket.get('item', 'N/A')} | "
                    f"**Status:** {ticket.get('status', 'N/A')}  \n"
                    f"  **Reason:** {ticket.get('reason', 'N/A')}"
                )
            return "\n".join(lines)

        return str(result)

    if isinstance(result, dict):
        # ── leave approval ──────────────────────────────────────────
        if "audit" in result and result.get("audit", {}).get("action") == "approved":
            return _fmt_leave_action(result, "approved")

        if "audit" in result and result.get("audit", {}).get("action") == "rejected":
            return _fmt_leave_action(result, "rejected")

        # ── existing dict formatters (unchanged) ────────────────────
        if "message" in result and "employee" in result and "onboarding" in result and "it_ticket" in result:
            emp = result["employee"] or {}
            onboard = result["onboarding"] or {}
            ticket = result["it_ticket"] or {}
            lines = [
                f"✅ {result['message']}",
                "",
                "### Employee Created",
                f"**Employee ID:** {emp.get('emp_id', 'N/A')}  ",
                f"**Name:** {emp.get('name', 'N/A')}  ",
                f"**Email:** {emp.get('email', 'N/A')}  ",
                f"**Department:** {emp.get('department', 'N/A')}  ",
                f"**Job Title:** {emp.get('role', 'N/A')}  ",
                f"**Access Role:** {emp.get('system_role', 'Employee')}  ",
                f"**Manager ID:** {emp.get('manager_emp_id', 'None')}  ",
                "",
                "### Onboarding",
                f"**Status:** {onboard.get('message', 'Created')}  ",
                f"**Tasks Created:** {onboard.get('tasks_created', 'N/A')}",
                "",
                "### IT Ticket",
                f"**Ticket ID:** {ticket.get('ticket_id', 'N/A')}  ",
                f"**Status:** {ticket.get('message', 'Created')}",
            ]
            return "\n".join(lines)

        if "message" in result and "tasks" in result:
            lines = [
                f"✅ {result['message']}",
                "",
                f"**Employee ID:** {result.get('employee_id', 'N/A')}",
                f"**Tasks Created:** {result.get('tasks_created', 0)}",
                "",
                "### Onboarding Tasks",
            ]
            for task in result["tasks"]:
                lines.append(
                    f"- **{task.get('task_name', 'N/A')}** "
                    f"(Owner: {task.get('owner', 'N/A')}, Status: {task.get('status', 'N/A')})"
                )
            return "\n".join(lines)

        if "message" in result and "summary" in result:
            summary = result["summary"]
            return (
                f"✅ {result['message']}\n\n"
                f"**Ticket ID:** {result.get('ticket_id', 'N/A')}  \n"
                f"**Employee ID:** {summary.get('employee_id', 'N/A')}  \n"
                f"**Category:** {summary.get('category', 'N/A')}  \n"
                f"**Item:** {summary.get('item', 'N/A')}  \n"
                f"**Reason:** {summary.get('reason', 'N/A')}  \n"
                f"**Status:** {summary.get('status', 'N/A')}"
            )

        if "message" in result and "employee" in result:
            emp = result["employee"]
            return (
                f"✅ {result['message']}\n\n"
                f"**Employee ID:** {emp.get('emp_id', 'N/A')}  \n"
                f"**Name:** {emp.get('name', 'N/A')}  \n"
                f"**Email:** {emp.get('email', 'N/A')}  \n"
                f"**Department:** {emp.get('department', 'N/A')}  \n"
                f"**Job Title:** {emp.get('role', 'N/A')}  \n"
                f"**Access Role:** {emp.get('system_role', 'Employee')}  \n"
                f"**Manager ID:** {emp.get('manager_emp_id', 'None')}  \n"
                f"**Status:** {emp.get('status', 'N/A')}"
            )

        if "message" in result and "tip" in result:
            return f"**{result['message']}**\n\n**Tip:** {result['tip']}"

        if "message" in result:
            return f"✅ {result['message']}"

        if "error" in result:
            return f"❌ {result['error']}"

        return str(result)

    return str(result)


def handle_prompt(prompt: str):
    try:
        result = run_chat_agent(prompt)
        return format_result(result)
    except Exception as e:
        return f"❌ Error: {e}"


# ── Page ──────────────────────────────────────────────────────────────

st.title("🤖 HRMS Chat AI")
st.write("Ask HR questions in natural language.")

with st.expander("Example prompts"):
    st.markdown(
        """
**Employees**
- Show all employees
- Hire Emma White as a Data Analyst in Finance with system role Manager reporting to E001 with email emma@example.com

**Tickets**
- Show all tickets
- Create an IT ticket for E004 for a new mouse because the current one is faulty

**Onboarding**
- Onboard E004

**Leave requests**
- Show all leave requests
- Show leave requests for E002
- Approve leave request L0001 as E001
- Reject leave request L0001 as E001 because insufficient staffing
"""
    )

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

prompt = st.chat_input("Try: Approve leave request L0001 as E001")

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    reply = handle_prompt(prompt)
    st.session_state.messages.append({"role": "assistant", "content": reply})
    with st.chat_message("assistant"):
        st.markdown(reply)

st.divider()
st.subheader("Quick Actions")

col1, col2, col3, col4, col5, col6 = st.columns(6)

with col1:
    if st.button("Show Employees"):
        p = "Show all employees"
        r = handle_prompt(p)
        st.session_state.messages += [{"role": "user", "content": p}, {"role": "assistant", "content": r}]
        st.rerun()

with col2:
    if st.button("Show Tickets"):
        p = "Show all tickets"
        r = handle_prompt(p)
        st.session_state.messages += [{"role": "user", "content": p}, {"role": "assistant", "content": r}]
        st.rerun()

with col3:
    if st.button("Show Leave Requests"):
        p = "Show all leave requests"
        r = handle_prompt(p)
        st.session_state.messages += [{"role": "user", "content": p}, {"role": "assistant", "content": r}]
        st.rerun()

with col4:
    if st.button("Onboard E004"):
        p = "Onboard E004"
        r = handle_prompt(p)
        st.session_state.messages += [{"role": "user", "content": p}, {"role": "assistant", "content": r}]
        st.rerun()

with col5:
    if st.button("Approve L0001"):
        p = "Approve leave request L0001 as E001"
        r = handle_prompt(p)
        st.session_state.messages += [{"role": "user", "content": p}, {"role": "assistant", "content": r}]
        st.rerun()

with col6:
    if st.button("Clear Chat"):
        st.session_state.messages = []
        st.rerun()
