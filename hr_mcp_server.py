"""
hr_mcp_server.py  — drop-in replacement
Adds approve_leave() and reject_leave() MCP tools.
"""

from __future__ import annotations

from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from app.models import Base, engine
from app.schemas import EmployeeCreate, EmployeeUpdate, LeaveRequestCreate, TicketCreate
from app.services.employee_service import EmployeeService
from app.services.onboarding_service import OnboardingService
from app.services.ticket_service import TicketService
from app.services.leave_service import LeaveService

APP_NAME = "HRMS Agent"


def _init_db() -> None:
    Base.metadata.create_all(bind=engine)


def _blank_to_none(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    return value if value else None


_init_db()

mcp = FastMCP(APP_NAME)

employee_service = EmployeeService()
ticket_service = TicketService()
onboarding_service = OnboardingService()
leave_service = LeaveService()


# ── existing tools (unchanged) ─────────────────────────────────────────


@mcp.tool()
def list_employees() -> list[dict[str, Any]]:
    """Return all employees."""
    return employee_service.list_employees()


@mcp.tool()
def create_employee(
    emp_id: str,
    name: str,
    email: str = "",
    department: str = "",
    role: str = "",
    manager_emp_id: str = "",
):
    """Create a new employee."""
    employee = EmployeeCreate(
        emp_id=emp_id,
        name=name,
        email=_blank_to_none(email),
        department=_blank_to_none(department),
        role=_blank_to_none(role),
        manager_emp_id=_blank_to_none(manager_emp_id),
    )
    return employee_service.create_employee(employee)


@mcp.tool()
def update_employee(
    emp_id: str,
    name: str = "",
    email: str = "",
    department: str = "",
    role: str = "",
    manager_emp_id: str = "",
):
    """Update an existing employee (patch semantics)."""
    payload = EmployeeUpdate(
        name=_blank_to_none(name),
        email=_blank_to_none(email),
        department=_blank_to_none(department),
        role=_blank_to_none(role),
        manager_emp_id=_blank_to_none(manager_emp_id),
    )
    return employee_service.update_employee(emp_id, payload)


@mcp.tool()
def list_tickets(emp_id: str = ""):
    """Return all tickets (optionally filtered by employee)."""
    return ticket_service.list_tickets(_blank_to_none(emp_id))


@mcp.tool()
def create_ticket(
    emp_id: str,
    category: str,
    item: str,
    reason: str,
):
    """Create a support ticket."""
    ticket = TicketCreate(
        emp_id=emp_id,
        category=category,
        item=item,
        reason=reason,
    )
    return ticket_service.create_ticket(ticket)


@mcp.tool()
def create_leave_request(
    emp_id: str,
    leave_type: str,
    start_date: str,
    end_date: str,
    reason: str = "",
):
    """Create an employee leave request."""
    payload = LeaveRequestCreate(
        emp_id=emp_id,
        leave_type=leave_type,
        start_date=start_date,
        end_date=end_date,
        reason=_blank_to_none(reason),
    )
    return leave_service.create_leave_request(payload)


@mcp.tool()
def list_leave_requests(emp_id: str = ""):
    """Return leave requests (optionally filtered by employee)."""
    return leave_service.list_leave_requests(_blank_to_none(emp_id))


@mcp.tool()
def onboard_employee(emp_id: str):
    """Generate onboarding tasks for an employee."""
    return onboarding_service.generate_default_tasks(emp_id)


@mcp.tool()
def send_onboarding_email(emp_id: str):
    """Send onboarding email to the employee's email address."""
    return onboarding_service.send_onboarding_email(emp_id)


# ── NEW: leave approval / rejection ───────────────────────────────────


@mcp.tool()
def approve_leave(request_id: str, approved_by: str) -> dict:
    """
    Approve a pending leave request.

    Args:
        request_id:  Leave request ID, e.g. "L0001".
        approved_by: emp_id of the approver. Must have system_role of
                     Manager, HR Admin, or HR Staff.

    Returns a confirmation dict with audit details.
    """
    return leave_service.approve_leave(
        request_id=request_id,
        approved_by=approved_by,
    )


@mcp.tool()
def reject_leave(
    request_id: str,
    rejected_by: str,
    rejection_reason: str = "",
) -> dict:
    """
    Reject a pending leave request.

    Args:
        request_id:       Leave request ID, e.g. "L0001".
        rejected_by:      emp_id of the person rejecting. Must have system_role
                          of Manager, HR Admin, or HR Staff.
        rejection_reason: Optional reason communicated to the employee.

    Returns a confirmation dict with audit details.
    """
    return leave_service.reject_leave(
        request_id=request_id,
        rejected_by=rejected_by,
        rejection_reason=rejection_reason,
    )


if __name__ == "__main__":
    mcp.run()
