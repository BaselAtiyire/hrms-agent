from typing import Optional
from pydantic import BaseModel, EmailStr


class EmployeeCreate(BaseModel):
    emp_id: Optional[str] = None
    name: str
    email: Optional[EmailStr] = None
    department: Optional[str] = None
    role: Optional[str] = None
    system_role: Optional[str] = "Employee"
    manager_emp_id: Optional[str] = None


class TicketCreate(BaseModel):
    ticket_id: Optional[str] = None
    emp_id: str
    category: str
    item: str
    reason: str


class TicketStatusUpdate(BaseModel):
    status: str
    notes: Optional[str] = None
    assigned_to: Optional[str] = None


class OnboardingTaskStatusUpdate(BaseModel):
    status: str
    notes: Optional[str] = None


class LeaveRequestCreate(BaseModel):
    request_id: Optional[str] = None
    emp_id: str
    leave_type: str
    start_date: str
    end_date: str
    reason: Optional[str] = None


class LeaveRequestStatusUpdate(BaseModel):
    status: str
    notes: Optional[str] = None
    approved_by: Optional[str] = None