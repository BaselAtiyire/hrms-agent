from datetime import datetime
import uuid

from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text
from sqlalchemy.orm import declarative_base, sessionmaker
from app.config import DATABASE_URL


def generate_emp_id():
    return f"E-{uuid.uuid4().hex[:8].upper()}"


def generate_ticket_id():
    return f"T-{uuid.uuid4().hex[:8].upper()}"


def generate_leave_request_id():
    return f"L-{uuid.uuid4().hex[:8].upper()}"


engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


class Employee(Base):
    __tablename__ = "employees"

    id             = Column(Integer, primary_key=True, index=True)
    emp_id         = Column(String, unique=True, nullable=False, index=True, default=generate_emp_id)
    name           = Column(String, nullable=False)
    email          = Column(String, nullable=True)
    department     = Column(String, nullable=True)
    role           = Column(String, nullable=True)       # job title
    system_role    = Column(String, default="Employee")  # access role
    manager_emp_id = Column(String, nullable=True)
    status         = Column(String, default="Active")
    created_at     = Column(DateTime, default=datetime.utcnow)


class Ticket(Base):
    __tablename__ = "tickets"

    id          = Column(Integer, primary_key=True, index=True)
    ticket_id   = Column(String, unique=True, nullable=False, index=True, default=generate_ticket_id)
    emp_id      = Column(String, nullable=False)
    category    = Column(String, nullable=False)
    item        = Column(String, nullable=False)
    reason      = Column(Text, nullable=False)
    status      = Column(String, default="Open")
    # ── added by migrate.py ──────────────────────────────────────────
    notes       = Column(Text, nullable=True)
    assigned_to = Column(String, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    closed_at   = Column(DateTime, nullable=True)
    # ────────────────────────────────────────────────────────────────
    created_at  = Column(DateTime, default=datetime.utcnow)
    updated_at  = Column(DateTime, default=datetime.utcnow)


class OnboardingTask(Base):
    __tablename__ = "onboarding_tasks"

    id           = Column(Integer, primary_key=True, index=True)
    emp_id       = Column(String, nullable=False)
    task_name    = Column(String, nullable=False)
    status       = Column(String, default="Pending")
    owner        = Column(String, nullable=True)
    due_date     = Column(String, nullable=True)
    notes        = Column(Text, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at   = Column(DateTime, default=datetime.utcnow)
    updated_at   = Column(DateTime, default=datetime.utcnow)


class LeaveRequest(Base):
    __tablename__ = "leave_requests"

    id          = Column(Integer, primary_key=True, index=True)
    request_id  = Column(String, unique=True, nullable=False, index=True, default=generate_leave_request_id)
    emp_id      = Column(String, nullable=False, index=True)
    leave_type  = Column(String, nullable=False)
    start_date  = Column(String, nullable=False)
    end_date    = Column(String, nullable=False)
    reason      = Column(Text, nullable=True)
    status      = Column(String, default="Pending")
    # ── added by migrate.py ──────────────────────────────────────────
    notes       = Column(Text, nullable=True)
    approved_by = Column(String, nullable=True)
    approved_at = Column(DateTime, nullable=True)
    rejected_at = Column(DateTime, nullable=True)
    # ────────────────────────────────────────────────────────────────
    created_at  = Column(DateTime, default=datetime.utcnow)
    updated_at  = Column(DateTime, default=datetime.utcnow)
