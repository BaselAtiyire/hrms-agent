from app.models import Employee, SessionLocal


class EmployeeService:
    VALID_SYSTEM_ROLES = {"HR Admin", "HR Staff", "Manager", "IT Support", "Employee"}

    def create_employee(self, data):
        db = SessionLocal()
        try:
            if data.system_role and data.system_role not in self.VALID_SYSTEM_ROLES:
                raise ValueError(
                    f"Invalid system role: {data.system_role}. "
                    f"Allowed roles: {', '.join(sorted(self.VALID_SYSTEM_ROLES))}"
                )

            if data.emp_id:
                existing_emp_id = db.query(Employee).filter(Employee.emp_id == data.emp_id).first()
                if existing_emp_id:
                    raise ValueError(f"Employee ID {data.emp_id} already exists.")

            if data.email:
                existing_email = db.query(Employee).filter(Employee.email == data.email).first()
                if existing_email:
                    raise ValueError(f"Employee email {data.email} already exists.")

            if data.emp_id and data.manager_emp_id and data.emp_id == data.manager_emp_id:
                raise ValueError("Employee cannot be their own manager.")

            if data.manager_emp_id:
                manager = db.query(Employee).filter(Employee.emp_id == data.manager_emp_id).first()
                if not manager:
                    raise ValueError(f"Manager ID {data.manager_emp_id} does not exist.")

            emp = Employee(
                emp_id=data.emp_id,
                name=data.name,
                email=data.email,
                department=data.department,
                role=data.role,
                system_role=data.system_role or "Employee",
                manager_emp_id=data.manager_emp_id,
            )

            db.add(emp)
            db.commit()
            db.refresh(emp)

            return {
                "message": f"Employee {emp.emp_id} created successfully.",
                "employee": {
                    "emp_id": emp.emp_id,
                    "name": emp.name,
                    "email": emp.email,
                    "department": emp.department,
                    "role": emp.role,
                    "system_role": emp.system_role,
                    "manager_emp_id": emp.manager_emp_id,
                    "status": emp.status,
                },
            }
        finally:
            db.close()

    def get_employee(self, emp_id: str):
        db = SessionLocal()
        try:
            emp = db.query(Employee).filter(Employee.emp_id == emp_id).first()
            if not emp:
                raise ValueError(f"Employee {emp_id} not found.")

            return {
                "emp_id": emp.emp_id,
                "name": emp.name,
                "email": emp.email,
                "department": emp.department,
                "role": emp.role,
                "system_role": emp.system_role,
                "manager_emp_id": emp.manager_emp_id,
                "status": emp.status,
            }
        finally:
            db.close()

    def list_employees(self):
        db = SessionLocal()
        try:
            rows = db.query(Employee).all()
            return [
                {
                    "emp_id": e.emp_id,
                    "name": e.name,
                    "email": e.email,
                    "department": e.department,
                    "role": e.role,
                    "system_role": e.system_role,
                    "manager_emp_id": e.manager_emp_id,
                    "status": e.status,
                }
                for e in rows
            ]
        finally:
            db.close()