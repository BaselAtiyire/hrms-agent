from app.schemas import EmployeeCreate, TicketCreate
from app.services.employee_service import EmployeeService
from app.services.ticket_service import TicketService
from app.services.onboarding_service import OnboardingService
from app.services.email_service import EmailService

employee_service = EmployeeService()
ticket_service = TicketService()
onboarding_service = OnboardingService()
email_service = EmailService()


def create_employee_record(data: EmployeeCreate):
    return employee_service.create_employee(data)


def run_post_hire_automation(employee: dict):
    emp_id = employee["emp_id"]
    role = employee.get("role") or "new employee"
    email = employee.get("email")
    name = employee.get("name")

    onboarding_result = onboarding_service.generate_default_tasks(emp_id)

    ticket = TicketCreate(
        emp_id=emp_id,
        category="IT",
        item="Laptop and account setup",
        reason=f"Prepare laptop, email access, and starter tools for {role} onboarding.",
    )
    ticket_result = ticket_service.create_ticket(ticket)

    email_result = email_service.send_welcome_email(
        to_email=email,
        employee_name=name,
        emp_id=emp_id,
    )

    return {
        "onboarding": onboarding_result,
        "ticket": ticket_result,
        "email": email_result,
    }