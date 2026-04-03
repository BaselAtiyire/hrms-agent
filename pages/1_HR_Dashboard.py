import streamlit as st
import pandas as pd
import plotly.express as px

from app.services.employee_service import EmployeeService
from app.services.ticket_service import TicketService
from app.services.onboarding_service import OnboardingService
from app.services.leave_service import LeaveService

st.set_page_config(page_title="HR Dashboard", page_icon="📊", layout="wide")

# Services
employee_service = EmployeeService()
ticket_service = TicketService()
onboarding_service = OnboardingService()
leave_service = LeaveService()


def to_df(data):
    if not data:
        return pd.DataFrame()
    return pd.DataFrame(data)


# Load data
employees = to_df(employee_service.list_employees())
tickets = to_df(ticket_service.list_tickets())
onboarding = to_df(onboarding_service.list_tasks())
leaves = to_df(leave_service.list_leave_requests())

# Header
st.title("📊 HR Analytics Dashboard")
st.caption("Real-time overview of HR operations")

# =========================
# TOP METRICS
# =========================
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("Total Employees", len(employees))

with col2:
    open_tickets = 0
    if not tickets.empty and "status" in tickets.columns:
        open_tickets = int((tickets["status"] == "Open").sum())
    st.metric("Open Tickets", open_tickets)

with col3:
    pending_tasks = 0
    if not onboarding.empty and "status" in onboarding.columns:
        pending_tasks = int((onboarding["status"] == "Pending").sum())
    st.metric("Pending Onboarding", pending_tasks)

with col4:
    pending_leaves = 0
    if not leaves.empty and "status" in leaves.columns:
        pending_leaves = int((leaves["status"] == "Pending").sum())
    st.metric("Pending Leave", pending_leaves)

st.divider()

# =========================
# EMPLOYEES SECTION
# =========================
st.subheader("👥 Employees Overview")

if employees.empty:
    st.info("No employee data available.")
else:
    c1, c2 = st.columns(2)

    with c1:
        if "department" in employees.columns:
            dept = (
                employees["department"]
                .fillna("Unknown")
                .value_counts()
                .reset_index()
            )
            dept.columns = ["department", "count"]

            fig = px.bar(
                dept,
                x="department",
                y="count",
                title="Employees by Department",
            )
            st.plotly_chart(fig, use_container_width=True)

    with c2:
        if "system_role" in employees.columns:
            role = (
                employees["system_role"]
                .fillna("Unknown")
                .value_counts()
                .reset_index()
            )
            role.columns = ["system_role", "count"]

            fig = px.pie(
                role,
                names="system_role",
                values="count",
                title="Employees by Access Role",
            )
            st.plotly_chart(fig, use_container_width=True)

    with st.expander("View Employees Table"):
        st.dataframe(employees, use_container_width=True)

st.divider()

# =========================
# TICKETS SECTION
# =========================
st.subheader("🎫 Tickets Overview")

if tickets.empty:
    st.info("No ticket data available.")
else:
    c1, c2 = st.columns(2)

    with c1:
        if "status" in tickets.columns:
            status = (
                tickets["status"]
                .fillna("Unknown")
                .value_counts()
                .reset_index()
            )
            status.columns = ["status", "count"]

            fig = px.bar(
                status,
                x="status",
                y="count",
                title="Tickets by Status",
            )
            st.plotly_chart(fig, use_container_width=True)

    with c2:
        if "category" in tickets.columns:
            cat = (
                tickets["category"]
                .fillna("Unknown")
                .value_counts()
                .reset_index()
            )
            cat.columns = ["category", "count"]

            fig = px.pie(
                cat,
                names="category",
                values="count",
                title="Tickets by Category",
            )
            st.plotly_chart(fig, use_container_width=True)

    with st.expander("View Tickets Table"):
        st.dataframe(tickets, use_container_width=True)

st.divider()

# =========================
# ONBOARDING SECTION
# =========================
st.subheader("📋 Onboarding Tasks")

if onboarding.empty:
    st.info("No onboarding data available.")
else:
    c1, c2 = st.columns(2)

    with c1:
        if "status" in onboarding.columns:
            status = (
                onboarding["status"]
                .fillna("Unknown")
                .value_counts()
                .reset_index()
            )
            status.columns = ["status", "count"]

            fig = px.bar(
                status,
                x="status",
                y="count",
                title="Onboarding Status",
            )
            st.plotly_chart(fig, use_container_width=True)

    with c2:
        if "owner" in onboarding.columns:
            owner = (
                onboarding["owner"]
                .fillna("Unknown")
                .value_counts()
                .reset_index()
            )
            owner.columns = ["owner", "count"]

            fig = px.pie(
                owner,
                names="owner",
                values="count",
                title="Tasks by Owner",
            )
            st.plotly_chart(fig, use_container_width=True)

    with st.expander("View Onboarding Tasks"):
        st.dataframe(onboarding, use_container_width=True)

st.divider()

# =========================
# LEAVE SECTION
# =========================
st.subheader("🏖 Leave Requests")

if leaves.empty:
    st.info("No leave data available.")
else:
    c1, c2 = st.columns(2)

    with c1:
        if "status" in leaves.columns:
            status = (
                leaves["status"]
                .fillna("Unknown")
                .value_counts()
                .reset_index()
            )
            status.columns = ["status", "count"]

            fig = px.bar(
                status,
                x="status",
                y="count",
                title="Leave Status",
            )
            st.plotly_chart(fig, use_container_width=True)

    with c2:
        if "leave_type" in leaves.columns:
            typ = (
                leaves["leave_type"]
                .fillna("Unknown")
                .value_counts()
                .reset_index()
            )
            typ.columns = ["leave_type", "count"]

            fig = px.pie(
                typ,
                names="leave_type",
                values="count",
                title="Leave Types",
            )
            st.plotly_chart(fig, use_container_width=True)

    with st.expander("View Leave Requests"):
        st.dataframe(leaves, use_container_width=True)