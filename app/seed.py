from app.models import Base, engine, SessionLocal, Employee, Ticket


def seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    if db.query(Employee).count() == 0:
        employees = [
            Employee(
                emp_id="E001",
                name="Alice Johnson",
                email="alice@example.com",
                department="HR",
                role="HR Manager",
                system_role="HR Admin",
            ),
            Employee(
                emp_id="E002",
                name="Brian Smith",
                email="brian@example.com",
                department="IT",
                role="IT Support",
                system_role="IT Support",
                manager_emp_id="E001",
            ),
            Employee(
                emp_id="E003",
                name="Cathy Brown",
                email="cathy@example.com",
                department="Finance",
                role="Financial Analyst",
                system_role="Employee",
                manager_emp_id="E001",
            ),
            Employee(
                emp_id="E004",
                name="David Lee",
                email="david@example.com",
                department="Engineering",
                role="Software Engineer",
                system_role="Manager",
                manager_emp_id="E001",
            ),
        ]
        db.add_all(employees)

    if db.query(Ticket).count() == 0:
        tickets = [
            Ticket(
                ticket_id="T0001",
                emp_id="E004",
                category="IT",
                item="Laptop Charger",
                reason="Current charger is faulty",
                status="Open",
            ),
            Ticket(
                ticket_id="T0002",
                emp_id="E003",
                category="HR",
                item="Leave Clarification",
                reason="Need HR clarification on policy",
                status="In Progress",
            ),
        ]
        db.add_all(tickets)

    db.commit()
    db.close()
    print("Seed data inserted successfully.")


if __name__ == "__main__":
    seed()