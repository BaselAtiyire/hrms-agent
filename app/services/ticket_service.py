from datetime import datetime
from app.models import Ticket, Employee, SessionLocal


class TicketService:
    VALID_STATUSES = {"Open", "In Progress", "Resolved", "Closed"}

    def create_ticket(self, data):
        db = SessionLocal()
        try:
            employee = db.query(Employee).filter(Employee.emp_id == data.emp_id).first()
            if not employee:
                raise ValueError(f"Employee {data.emp_id} does not exist.")

            if getattr(data, "ticket_id", None):
                existing_ticket = db.query(Ticket).filter(Ticket.ticket_id == data.ticket_id).first()
                if existing_ticket:
                    raise ValueError(f"Ticket ID {data.ticket_id} already exists.")

            ticket = Ticket(
                ticket_id=getattr(data, "ticket_id", None),
                emp_id=data.emp_id,
                category=data.category,
                item=data.item,
                reason=data.reason,
                status="Open",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )

            db.add(ticket)
            db.commit()
            db.refresh(ticket)

            return {
                "message": f"Ticket {ticket.ticket_id} was created successfully for employee {data.emp_id}.",
                "ticket_id": ticket.ticket_id,
                "summary": {
                    "employee_id": data.emp_id,
                    "category": data.category,
                    "item": data.item,
                    "reason": data.reason,
                    "status": ticket.status,
                },
            }
        finally:
            db.close()

    def update_ticket_status(self, ticket_id: str, status: str, notes: str | None = None, assigned_to: str | None = None):
        db = SessionLocal()
        try:
            if status not in self.VALID_STATUSES:
                raise ValueError(f"Invalid ticket status: {status}")

            ticket = db.query(Ticket).filter(Ticket.ticket_id == ticket_id).first()
            if not ticket:
                raise ValueError(f"Ticket {ticket_id} not found.")

            ticket.status = status
            ticket.updated_at = datetime.utcnow()

            if notes:
                ticket.notes = notes
            if assigned_to:
                ticket.assigned_to = assigned_to

            if status == "Resolved":
                ticket.resolved_at = datetime.utcnow()
            if status == "Closed":
                ticket.closed_at = datetime.utcnow()

            db.commit()
            db.refresh(ticket)

            return {
                "message": f"Ticket {ticket.ticket_id} updated successfully.",
                "ticket": {
                    "ticket_id": ticket.ticket_id,
                    "status": ticket.status,
                    "assigned_to": ticket.assigned_to,
                    "notes": ticket.notes,
                    "resolved_at": str(ticket.resolved_at) if ticket.resolved_at else None,
                    "closed_at": str(ticket.closed_at) if ticket.closed_at else None,
                },
            }
        finally:
            db.close()

    def list_tickets(self, emp_id: str | None = None):
        db = SessionLocal()
        try:
            query = db.query(Ticket)
            if emp_id:
                query = query.filter(Ticket.emp_id == emp_id)

            rows = query.all()
            return [
                {
                    "ticket_id": t.ticket_id,
                    "emp_id": t.emp_id,
                    "category": t.category,
                    "item": t.item,
                    "reason": t.reason,
                    "status": t.status,
                    "notes": t.notes,
                    "assigned_to": t.assigned_to,
                    "resolved_at": str(t.resolved_at) if t.resolved_at else None,
                    "closed_at": str(t.closed_at) if t.closed_at else None,
                }
                for t in rows
            ]
        finally:
            db.close()