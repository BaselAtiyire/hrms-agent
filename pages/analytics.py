import streamlit as st
import pandas as pd
import plotly.express as px

from app.services.employee_service import EmployeeService
from app.services.ticket_service import TicketService
from app.services.onboarding_service import OnboardingService
from app.services.leave_service import LeaveService

st.set_page_config(page_title="HR Analytics Dashboard", page_icon="📊", layout="wide")

employee_service = EmployeeService()
ticket_service = TicketService()
onboarding_service = OnboardingService()
leave_service = LeaveService()


def safe_df(records):
    if not records:
        return pd.DataFrame()
    return pd.DataFrame(records)


employees_df = safe_df(employee_service.list_employees())
tickets_df = safe_df(ticket_service.list_tickets())
onboarding_df = safe_df(onboarding_service.list_tasks())
leave_df = safe_df(leave_service.list_leave_requests())

st.title("📊 HR Analytics Dashboard")
st.caption("Operational overview of employees, onboarding, tickets, and leave requests.")

# Top metrics
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("Employees", len(employees_df))

with col2:
    open_tickets = 0
    if not tickets_df.empty and "status" in tickets_df.columns:
        open_tickets = int((tickets_df["status"] == "Open").sum())
    st.metric("Open Tickets", open_tickets)

with col3:
    pending_tasks = 0
    if not onboarding_df.empty and "status" in onboarding_df.columns:
        pending_tasks = int((onboarding_df["status"] == "Pending").sum())
    st.metric("Pending Onboarding Tasks", pending_tasks)

with col4:
    pending_leave = 0
    if not leave_df.empty and "status" in leave_df.columns:
        pending_leave = int((leave_df["status"] == "Pending").sum())
    st.metric("Pending Leave Requests", pending_leave)

st.divider()

# Employees section
st.subheader("Employees")

if employees_df.empty:
    st.info("No employee data available.")
else:
    c1, c2 = st.columns(2)

    with c1:
        if "department" in employees_df.columns:
            dept_counts = (
                employees_df["department"]
                .fillna("Unknown")
                .value_counts()
                .reset_index()
            )
            dept_counts.columns = ["department", "count"]
            fig = px.bar(
                dept_counts,
                x="department",
                y="count",
                title="Employees by Department",
            )
            st.plotly_chart(fig, use_container_width=True)

    with c2:
        if "system_role" in employees_df.columns:
            role_counts = (
                employees_df["system_role"]
                .fillna("Unknown")
                .value_counts()
                .reset_index()
            )
            role_counts.columns = ["system_role", "count"]
            fig = px.pie(
                role_counts,
                names="system_role",
                values="count",
                title="Employees by Access Role",
            )
            st.plotly_chart(fig, use_container_width=True)

    with st.expander("View employee table"):
        st.dataframe(employees_df, use_container_width=True)

st.divider()

# Tickets section
st.subheader("Tickets")

if tickets_df.empty:
    st.info("No ticket data available.")
else:
    c1, c2 = st.columns(2)

    with c1:
        if "status" in tickets_df.columns:
            ticket_status_counts = (
                tickets_df["status"]
                .fillna("Unknown")
                .value_counts()
                .reset_index()
            )
            ticket_status_counts.columns = ["status", "count"]
            fig = px.bar(
                ticket_status_counts,
                x="status",
                y="count",
                title="Tickets by Status",
            )
            st.plotly_chart(fig, use_container_width=True)

    with c2:
        if "category" in tickets_df.columns:
            ticket_category_counts = (
                tickets_df["category"]
                .fillna("Unknown")
                .value_counts()
                .reset_index()
            )
            ticket_category_counts.columns = ["category", "count"]
            fig = px.pie(
                ticket_category_counts,
                names="category",
                values="count",
                title="Tickets by Category",
            )
            st.plotly_chart(fig, use_container_width=True)

    with st.expander("View ticket table"):
        st.dataframe(tickets_df, use_container_width=True)

st.divider()

# Onboarding section
st.subheader("Onboarding")

if onboarding_df.empty:
    st.info("No onboarding task data available.")
else:
    c1, c2 = st.columns(2)

    with c1:
        if "status" in onboarding_df.columns:
            onboarding_status_counts = (
                onboarding_df["status"]
                .fillna("Unknown")
                .value_counts()
                .reset_index()
            )
            onboarding_status_counts.columns = ["status", "count"]
            fig = px.bar(
                onboarding_status_counts,
                x="status",
                y="count",
                title="Onboarding Tasks by Status",
            )
            st.plotly_chart(fig, use_container_width=True)

    with c2:
        if "owner" in onboarding_df.columns:
            onboarding_owner_counts = (
                onboarding_df["owner"]
                .fillna("Unknown")
                .value_counts()
                .reset_index()
            )
            onboarding_owner_counts.columns = ["owner", "count"]
            fig = px.pie(
                onboarding_owner_counts,
                names="owner",
                values="count",
                title="Onboarding Tasks by Owner",
            )
            st.plotly_chart(fig, use_container_width=True)

    with st.expander("View onboarding task table"):
        st.dataframe(onboarding_df, use_container_width=True)

st.divider()

# Leave requests section
st.subheader("Leave Requests")

if leave_df.empty:
    st.info("No leave request data available.")
else:
    c1, c2 = st.columns(2)

    with c1:
        if "status" in leave_df.columns:
            leave_status_counts = (
                leave_df["status"]
                .fillna("Unknown")
                .value_counts()
                .reset_index()
            )
            leave_status_counts.columns = ["status", "count"]
            fig = px.bar(
                leave_status_counts,
                x="status",
                y="count",
                title="Leave Requests by Status",
            )
            st.plotly_chart(fig, use_container_width=True)

    with c2:
        if "leave_type" in leave_df.columns:
            leave_type_counts = (
                leave_df["leave_type"]
                .fillna("Unknown")
                .value_counts()
                .reset_index()
            )
            leave_type_counts.columns = ["leave_type", "count"]
            fig = px.pie(
                leave_type_counts,
                names="leave_type",
                values="count",
                title="Leave Requests by Type",
            )
            st.plotly_chart(fig, use_container_width=True)

    with st.expander("View leave request table"):
        st.dataframe(leave_df, use_container_width=True)