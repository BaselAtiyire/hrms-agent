from app.schemas import EmployeeCreate, TicketCreate
from app.services.employee_service import EmployeeService
from app.services.ticket_service import TicketService
from app.services.onboarding_service import OnboardingService

employee_service = EmployeeService()
ticket_service = TicketService()
onboarding_service = OnboardingService()


def auto_generate_emp_id() -> str:
    employees = employee_service.list_employees()
    if not employees:
        return "E001"

    max_num = 0
    for emp in employees:
        emp_id = emp.get("emp_id", "")
        if emp_id.startswith("E") and emp_id[1:].isdigit():
            max_num = max(max_num, int(emp_id[1:]))

    return f"E{max_num + 1:03d}"


def hire_employee_workflow(
    name: str,
    email: str | None = None,
    department: str | None = None,
    role: str | None = None,
    manager_emp_id: str | None = None,
):
    emp_id = auto_generate_emp_id()

    employee = EmployeeCreate(
        emp_id=emp_id,
        name=name,
        email=email,
        department=department,
        role=role,
        manager_emp_id=manager_emp_id,
    )

    employee_result = employee_service.create_employee(employee)

    onboarding_result = onboarding_service.generate_default_tasks(emp_id)

    ticket = TicketCreate(
        emp_id=emp_id,
        category="IT",
        item="Laptop and account setup",
        reason=f"Prepare laptop, email access, and starter tools for {role or 'new employee'} onboarding.",
    )
    ticket_result = ticket_service.create_ticket(ticket)

    return {
        "message": f"Hiring workflow completed for {name}.",
        "employee": employee_result,
        "onboarding": onboarding_result,
        "it_ticket": ticket_result,
    }