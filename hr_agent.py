"""
agent/hr_agent.py  — drop-in replacement
Adds approve_leave() and reject_leave() tools.
"""

from __future__ import annotations

from app.schemas import EmployeeCreate, TicketCreate
from app.services.employee_service import EmployeeService
from app.services.ticket_service import TicketService
from app.services.onboarding_service import OnboardingService
from app.services.email_service import EmailService
from app.services.leave_service import LeaveService


class HRAgent:
    def __init__(self):
        self.employee_service = EmployeeService()
        self.ticket_service = TicketService()
        self.onboarding_service = OnboardingService()
        self.email_service = EmailService()
        self.leave_service = LeaveService()

    def available_tools(self):
        return {
            "list_employees": self.list_employees,
            "create_employee": self.create_employee,
            "create_ticket": self.create_ticket,
            "onboard_employee": self.onboard_employee,
            "send_welcome_email": self.send_welcome_email,
            "hire_employee": self.hire_employee,
            # ── NEW ──────────────────────────────────────────
            "list_leave_requests": self.list_leave_requests,
            "approve_leave": self.approve_leave,
            "reject_leave": self.reject_leave,
        }

    # ------------------------------------------------------------------ #
    # Existing tools (unchanged)                                           #
    # ------------------------------------------------------------------ #

    def list_employees(self):
        return self.employee_service.list_employees()

    def create_employee(
        self,
        name: str,
        email: str | None = None,
        department: str | None = None,
        role: str | None = None,
        system_role: str | None = "Employee",
        manager_emp_id: str | None = None,
        emp_id: str | None = None,
    ):
        payload = EmployeeCreate(
            emp_id=emp_id,
            name=name,
            email=email,
            department=department,
            role=role,
            system_role=system_role,
            manager_emp_id=manager_emp_id,
        )
        return self.employee_service.create_employee(payload)

    def create_ticket(
        self,
        emp_id: str,
        category: str,
        item: str,
        reason: str,
        ticket_id: str | None = None,
    ):
        payload = TicketCreate(
            ticket_id=ticket_id,
            emp_id=emp_id,
            category=category,
            item=item,
            reason=reason,
        )
        return self.ticket_service.create_ticket(payload)

    def onboard_employee(self, emp_id: str):
        return self.onboarding_service.generate_default_tasks(emp_id)

    def send_welcome_email(self, to_email: str, employee_name: str, emp_id: str | None = None):
        return self.email_service.send_welcome_email(
            to_email=to_email,
            employee_name=employee_name,
            emp_id=emp_id,
        )

    def hire_employee(
        self,
        name: str,
        email: str | None = None,
        department: str | None = None,
        role: str | None = None,
        system_role: str | None = "Employee",
        manager_emp_id: str | None = None,
        emp_id: str | None = None,
    ):
        employee_result = self.create_employee(
            name=name,
            email=email,
            department=department,
            role=role,
            system_role=system_role,
            manager_emp_id=manager_emp_id,
            emp_id=emp_id,
        )
        employee = employee_result["employee"]
        final_emp_id = employee["emp_id"]

        onboarding_result = self.onboard_employee(final_emp_id)
        ticket_result = self.create_ticket(
            emp_id=final_emp_id,
            category="IT",
            item="Laptop and account setup",
            reason=f"Prepare laptop, email access, and starter tools for {role or 'new employee'} onboarding.",
        )
        email_result = self.send_welcome_email(
            to_email=employee.get("email"),
            employee_name=employee.get("name"),
            emp_id=final_emp_id,
        )
        return {
            "message": f"Agent completed hiring workflow for {employee.get('name')}.",
            "employee": employee,
            "onboarding": onboarding_result,
            "ticket": ticket_result,
            "email": email_result,
        }

    # ------------------------------------------------------------------ #
    # NEW: leave management                                                #
    # ------------------------------------------------------------------ #

    def list_leave_requests(self, emp_id: str | None = None):
        return self.leave_service.list_leave_requests(emp_id)

    def approve_leave(self, request_id: str, approved_by: str) -> dict:
        """
        Approve a pending leave request.
        approved_by must be the emp_id of a Manager or HR staff member.
        """
        return self.leave_service.approve_leave(
            request_id=request_id,
            approved_by=approved_by,
        )

    def reject_leave(
        self,
        request_id: str,
        rejected_by: str,
        rejection_reason: str = "",
    ) -> dict:
        """
        Reject a pending leave request with an optional reason.
        rejected_by must be the emp_id of a Manager or HR staff member.
        """
        return self.leave_service.reject_leave(
            request_id=request_id,
            rejected_by=rejected_by,
            rejection_reason=rejection_reason,
        )
