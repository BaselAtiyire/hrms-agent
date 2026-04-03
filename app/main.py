from fastapi import FastAPI, HTTPException, BackgroundTasks
from app.models import Base, engine
from app.schemas import (
    EmployeeCreate,
    TicketCreate,
    TicketStatusUpdate,
    OnboardingTaskStatusUpdate,
    LeaveRequestCreate,
    LeaveRequestStatusUpdate,
)
from app.services.employee_service import EmployeeService
from app.services.ticket_service import TicketService
from app.services.onboarding_service import OnboardingService
from app.services.leave_service import LeaveService
from app.workflows.hiring_workflow import create_employee_record, run_post_hire_automation

app = FastAPI(title="HRMS Backend")

Base.metadata.create_all(bind=engine)

employee_service = EmployeeService()
ticket_service = TicketService()
onboarding_service = OnboardingService()
leave_service = LeaveService()

ALLOWED_SYSTEM_ROLES = {"HR Admin", "HR Staff", "Manager", "IT Support", "Employee"}

PERMISSIONS = {
    "HR Admin": {
        "create_employee",
        "view_employees",
        "create_ticket",
        "view_tickets",
        "update_ticket_status",
        "onboard_employee",
        "update_onboarding_task",
        "view_onboarding_tasks",
        "create_leave_request",
        "update_leave_status",
        "view_leave_requests",
        "hire_employee",
    },
    "HR Staff": {
        "create_employee",
        "view_employees",
        "onboard_employee",
        "update_onboarding_task",
        "view_onboarding_tasks",
        "create_leave_request",
        "view_leave_requests",
        "hire_employee",
    },
    "Manager": {
        "view_employees",
        "view_onboarding_tasks",
        "create_leave_request",
        "update_leave_status",
        "view_leave_requests",
    },
    "IT Support": {
        "create_ticket",
        "view_tickets",
        "update_ticket_status",
        "view_onboarding_tasks",
        "update_onboarding_task",
    },
    "Employee": {
        "create_leave_request",
    },
}


def check_permission(actor_role: str, action: str):
    if actor_role not in ALLOWED_SYSTEM_ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid system role: {actor_role}")

    if action not in PERMISSIONS[actor_role]:
        raise HTTPException(
            status_code=403,
            detail=f"{actor_role} is not allowed to perform {action}",
        )


@app.get("/")
def root():
    return {"message": "HRMS backend is running"}


@app.get("/health")
def health():
    """Container / load-balancer liveness probe (no auth)."""
    return {"status": "ok"}


@app.get("/employees")
def list_employees(actor_role: str):
    check_permission(actor_role, "view_employees")
    return employee_service.list_employees()


@app.get("/employees/{emp_id}")
def get_employee(emp_id: str, actor_role: str):
    check_permission(actor_role, "view_employees")
    try:
        return employee_service.get_employee(emp_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/employees")
def create_employee(payload: EmployeeCreate, actor_role: str):
    check_permission(actor_role, "create_employee")
    try:
        return employee_service.create_employee(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/hire")
def hire_employee(payload: EmployeeCreate, actor_role: str, background_tasks: BackgroundTasks):
    check_permission(actor_role, "hire_employee")
    try:
        employee_result = create_employee_record(payload)
        employee = employee_result["employee"]

        background_tasks.add_task(run_post_hire_automation, employee)

        return {
            "message": f"Hiring started successfully for {employee['name']}.",
            "employee": employee,
            "background_jobs": [
                "onboarding_tasks",
                "it_setup_ticket",
                "welcome_email",
            ],
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/tickets")
def list_tickets(actor_role: str, emp_id: str | None = None):
    check_permission(actor_role, "view_tickets")
    return ticket_service.list_tickets(emp_id)


@app.post("/tickets")
def create_ticket(payload: TicketCreate, actor_role: str):
    check_permission(actor_role, "create_ticket")
    try:
        return ticket_service.create_ticket(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.patch("/tickets/{ticket_id}/status")
def update_ticket_status(ticket_id: str, payload: TicketStatusUpdate, actor_role: str):
    check_permission(actor_role, "update_ticket_status")
    try:
        return ticket_service.update_ticket_status(
            ticket_id=ticket_id,
            status=payload.status,
            notes=payload.notes,
            assigned_to=payload.assigned_to,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/onboard/{emp_id}")
def onboard_employee(emp_id: str, actor_role: str):
    check_permission(actor_role, "onboard_employee")
    try:
        return onboarding_service.generate_default_tasks(emp_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/onboarding/tasks")
def list_onboarding_tasks(actor_role: str, emp_id: str | None = None):
    check_permission(actor_role, "view_onboarding_tasks")
    return onboarding_service.list_tasks(emp_id)


@app.patch("/onboarding/tasks/{emp_id}")
def update_onboarding_task(emp_id: str, task_name: str, payload: OnboardingTaskStatusUpdate, actor_role: str):
    check_permission(actor_role, "update_onboarding_task")
    try:
        return onboarding_service.update_task_status(
            emp_id=emp_id,
            task_name=task_name,
            status=payload.status,
            notes=payload.notes,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/leave-requests")
def list_leave_requests(actor_role: str, emp_id: str | None = None):
    check_permission(actor_role, "view_leave_requests")
    return leave_service.list_leave_requests(emp_id)


@app.post("/leave-requests")
def create_leave_request(payload: LeaveRequestCreate, actor_role: str):
    check_permission(actor_role, "create_leave_request")
    try:
        return leave_service.create_leave_request(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.patch("/leave-requests/{request_id}/status")
def update_leave_status(request_id: str, payload: LeaveRequestStatusUpdate, actor_role: str):
    check_permission(actor_role, "update_leave_status")
    try:
        return leave_service.update_leave_status(
            request_id=request_id,
            status=payload.status,
            notes=payload.notes,
            approved_by=payload.approved_by,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))