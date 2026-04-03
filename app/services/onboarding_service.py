from datetime import datetime
from app.models import Employee, OnboardingTask, SessionLocal


class OnboardingService:
    VALID_STATUSES = {"Pending", "In Progress", "Completed", "Blocked"}

    def generate_default_tasks(self, emp_id: str):
        db = SessionLocal()
        try:
            employee = db.query(Employee).filter(Employee.emp_id == emp_id).first()
            if not employee:
                raise ValueError(f"Employee {emp_id} does not exist.")

            existing_tasks = db.query(OnboardingTask).filter(OnboardingTask.emp_id == emp_id).first()
            if existing_tasks:
                raise ValueError(f"Onboarding tasks already exist for employee {emp_id}.")

            tasks = [
                ("Create company email account", "IT"),
                ("Prepare laptop", "IT"),
                ("Assign HR orientation", "HR"),
                ("Share employee handbook", "HR"),
                ("Assign onboarding buddy", "Manager"),
                ("Schedule first-week check-in", "Manager"),
            ]

            created_tasks = []

            for task_name, owner in tasks:
                task = OnboardingTask(
                    emp_id=emp_id,
                    task_name=task_name,
                    owner=owner,
                    status="Pending",
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
                db.add(task)
                created_tasks.append(
                    {
                        "task_name": task_name,
                        "owner": owner,
                        "status": "Pending",
                    }
                )

            db.commit()

            return {
                "message": f"Onboarding started successfully for employee {emp_id}.",
                "employee_id": emp_id,
                "tasks_created": len(created_tasks),
                "tasks": created_tasks,
            }
        finally:
            db.close()

    def update_task_status(self, emp_id: str, task_name: str, status: str, notes: str | None = None):
        db = SessionLocal()
        try:
            if status not in self.VALID_STATUSES:
                raise ValueError(f"Invalid onboarding task status: {status}")

            task = (
                db.query(OnboardingTask)
                .filter(OnboardingTask.emp_id == emp_id, OnboardingTask.task_name == task_name)
                .first()
            )

            if not task:
                raise ValueError(f"Task '{task_name}' for employee {emp_id} not found.")

            task.status = status
            task.updated_at = datetime.utcnow()

            if notes:
                task.notes = notes

            if status == "Completed":
                task.completed_at = datetime.utcnow()

            db.commit()
            db.refresh(task)

            return {
                "message": f"Onboarding task '{task.task_name}' updated successfully.",
                "task": {
                    "emp_id": task.emp_id,
                    "task_name": task.task_name,
                    "status": task.status,
                    "owner": task.owner,
                    "notes": task.notes,
                    "completed_at": str(task.completed_at) if task.completed_at else None,
                },
            }
        finally:
            db.close()

    def list_tasks(self, emp_id: str | None = None):
        db = SessionLocal()
        try:
            query = db.query(OnboardingTask)
            if emp_id:
                query = query.filter(OnboardingTask.emp_id == emp_id)

            rows = query.all()
            return [
                {
                    "emp_id": t.emp_id,
                    "task_name": t.task_name,
                    "status": t.status,
                    "owner": t.owner,
                    "due_date": t.due_date,
                    "notes": t.notes,
                    "completed_at": str(t.completed_at) if t.completed_at else None,
                }
                for t in rows
            ]
        finally:
            db.close()