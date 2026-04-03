"""
app/services/leave_service.py  — drop-in replacement
Adds approve_leave() and reject_leave() with full audit trail.
"""

from __future__ import annotations

from datetime import datetime, date
from typing import Optional

from sqlalchemy.orm import Session

from app.models import LeaveRequest, Employee, SessionLocal
from app.schemas import LeaveRequestCreate


def _db() -> Session:
    return SessionLocal()


def _to_dict(r: LeaveRequest) -> dict:
    return {
        "request_id": r.request_id,
        "emp_id": r.emp_id,
        "leave_type": r.leave_type,
        "start_date": r.start_date,
        "end_date": r.end_date,
        "reason": r.reason,
        "status": r.status,
        "approved_by": getattr(r, "approved_by", None),
        "approved_at": str(getattr(r, "approved_at", None) or ""),
        "rejection_reason": getattr(r, "rejection_reason", None),
        "created_at": str(r.created_at),
        "updated_at": str(r.updated_at),
    }


def _count_days(start: str, end: str) -> int:
    try:
        s = date.fromisoformat(start)
        e = date.fromisoformat(end)
        return max((e - s).days + 1, 1)
    except Exception:
        return 0


def _check_overlap(db: Session, emp_id: str, start_date: str, end_date: str,
                   exclude_id: Optional[str] = None) -> Optional[LeaveRequest]:
    """Return an existing approved/pending leave that overlaps the given range."""
    rows = (
        db.query(LeaveRequest)
        .filter(
            LeaveRequest.emp_id == emp_id,
            LeaveRequest.status.in_(["Approved", "Pending"]),
        )
        .all()
    )
    for row in rows:
        if exclude_id and row.request_id == exclude_id:
            continue
        try:
            existing_start = date.fromisoformat(row.start_date)
            existing_end = date.fromisoformat(row.end_date)
            new_start = date.fromisoformat(start_date)
            new_end = date.fromisoformat(end_date)
            if new_start <= existing_end and new_end >= existing_start:
                return row
        except Exception:
            continue
    return None


class LeaveService:
    # ------------------------------------------------------------------ #
    # Existing methods (kept intact)                                       #
    # ------------------------------------------------------------------ #

    def list_leave_requests(self, emp_id: Optional[str] = None) -> list[dict]:
        db = _db()
        try:
            q = db.query(LeaveRequest)
            if emp_id:
                q = q.filter(LeaveRequest.emp_id == emp_id)
            return [_to_dict(r) for r in q.order_by(LeaveRequest.created_at.desc()).all()]
        finally:
            db.close()

    def create_leave_request(self, payload: LeaveRequestCreate) -> dict:
        db = _db()
        try:
            # Auto-generate request_id
            last = (
                db.query(LeaveRequest)
                .order_by(LeaveRequest.id.desc())
                .first()
            )
            next_num = (last.id + 1) if last else 1
            request_id = f"L{next_num:04d}"

            # Validate employee exists
            emp = db.query(Employee).filter(Employee.emp_id == payload.emp_id).first()
            if not emp:
                return {"error": f"Employee {payload.emp_id} not found."}

            # Validate dates
            try:
                start = date.fromisoformat(payload.start_date)
                end = date.fromisoformat(payload.end_date)
                if end < start:
                    return {"error": "end_date must be on or after start_date."}
            except ValueError:
                return {"error": "Invalid date format. Use YYYY-MM-DD."}

            # Overlap check
            overlap = _check_overlap(db, payload.emp_id, payload.start_date, payload.end_date)
            if overlap:
                return {
                    "error": (
                        f"Leave overlap: {overlap.request_id} "
                        f"({overlap.start_date} → {overlap.end_date}, {overlap.status})."
                    )
                }

            row = LeaveRequest(
                request_id=request_id,
                emp_id=payload.emp_id,
                leave_type=payload.leave_type,
                start_date=payload.start_date,
                end_date=payload.end_date,
                reason=payload.reason,
                status="Pending",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return {
                "message": "Leave request created.",
                "request_id": request_id,
                "leave_request": _to_dict(row),
            }
        finally:
            db.close()

    # ------------------------------------------------------------------ #
    # NEW: approve / reject                                                #
    # ------------------------------------------------------------------ #

    def approve_leave(
        self,
        request_id: str,
        approved_by: str,
    ) -> dict:
        """
        Approve a pending leave request.

        Args:
            request_id:  The leave request ID (e.g. "L0001").
            approved_by: emp_id of the approver (must be a manager or HR).

        Returns a dict with keys: message, request_id, leave_request, audit.
        """
        db = _db()
        try:
            row = db.query(LeaveRequest).filter(LeaveRequest.request_id == request_id).first()
            if not row:
                return {"error": f"Leave request {request_id} not found."}

            if row.status != "Pending":
                return {
                    "error": (
                        f"Cannot approve: request is already '{row.status}'. "
                        "Only Pending requests can be approved."
                    )
                }

            # Role-based guard: approver must exist and be Manager/HR Admin/HR Staff
            approver = db.query(Employee).filter(Employee.emp_id == approved_by).first()
            if not approver:
                return {"error": f"Approver {approved_by} not found."}

            allowed_roles = {"Manager", "HR Admin", "HR Staff"}
            approver_system_role = getattr(approver, "system_role", None) or ""
            if approver_system_role not in allowed_roles:
                return {
                    "error": (
                        f"{approver.name} ({approved_by}) has system role "
                        f"'{approver_system_role}' and is not authorised to approve leave. "
                        f"Allowed roles: {', '.join(sorted(allowed_roles))}."
                    )
                }

            now = datetime.utcnow()
            row.status = "Approved"
            row.updated_at = now

            # Persist audit columns if they exist on the model
            if hasattr(row, "approved_by"):
                row.approved_by = approved_by
            if hasattr(row, "approved_at"):
                row.approved_at = now
            if hasattr(row, "rejection_reason"):
                row.rejection_reason = None

            db.commit()
            db.refresh(row)

            days = _count_days(row.start_date, row.end_date)
            return {
                "message": (
                    f"Leave request {request_id} approved by {approver.name} ({approved_by})."
                ),
                "request_id": request_id,
                "leave_request": _to_dict(row),
                "audit": {
                    "action": "approved",
                    "approved_by_emp_id": approved_by,
                    "approved_by_name": approver.name,
                    "approved_at": now.isoformat(),
                    "duration_days": days,
                },
            }
        finally:
            db.close()

    def reject_leave(
        self,
        request_id: str,
        rejected_by: str,
        rejection_reason: str = "",
    ) -> dict:
        """
        Reject a pending leave request.

        Args:
            request_id:       The leave request ID (e.g. "L0001").
            rejected_by:      emp_id of the person rejecting.
            rejection_reason: Optional reason shown to the employee.

        Returns a dict with keys: message, request_id, leave_request, audit.
        """
        db = _db()
        try:
            row = db.query(LeaveRequest).filter(LeaveRequest.request_id == request_id).first()
            if not row:
                return {"error": f"Leave request {request_id} not found."}

            if row.status != "Pending":
                return {
                    "error": (
                        f"Cannot reject: request is already '{row.status}'. "
                        "Only Pending requests can be rejected."
                    )
                }

            # Role-based guard
            rejector = db.query(Employee).filter(Employee.emp_id == rejected_by).first()
            if not rejector:
                return {"error": f"Rejector {rejected_by} not found."}

            allowed_roles = {"Manager", "HR Admin", "HR Staff"}
            rejector_system_role = getattr(rejector, "system_role", None) or ""
            if rejector_system_role not in allowed_roles:
                return {
                    "error": (
                        f"{rejector.name} ({rejected_by}) has system role "
                        f"'{rejector_system_role}' and is not authorised to reject leave."
                    )
                }

            now = datetime.utcnow()
            row.status = "Rejected"
            row.updated_at = now

            if hasattr(row, "approved_by"):
                row.approved_by = rejected_by
            if hasattr(row, "approved_at"):
                row.approved_at = now
            if hasattr(row, "rejection_reason"):
                row.rejection_reason = rejection_reason or None

            db.commit()
            db.refresh(row)

            return {
                "message": (
                    f"Leave request {request_id} rejected by {rejector.name} ({rejected_by})."
                    + (f" Reason: {rejection_reason}" if rejection_reason else "")
                ),
                "request_id": request_id,
                "leave_request": _to_dict(row),
                "audit": {
                    "action": "rejected",
                    "rejected_by_emp_id": rejected_by,
                    "rejected_by_name": rejector.name,
                    "rejected_at": now.isoformat(),
                    "rejection_reason": rejection_reason or None,
                },
            }
        finally:
            db.close()