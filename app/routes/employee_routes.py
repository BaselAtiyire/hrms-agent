from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.schemas import EmployeeCreate
from app.database import get_db
from app.services.employee_service import create_employee as create_employee_service
from app.utils.email_service import send_welcome_email
import traceback

router = APIRouter()


@router.post("/employees")
def create_employee(employee: EmployeeCreate, db: Session = Depends(get_db)):
    try:
        print("✅ Route hit")

        # ✅ Create employee via service
        new_employee = create_employee_service(employee, db)

        # 🔥 Send email safely
        try:
            send_welcome_email(new_employee.email, new_employee.name)
            print("✅ Email sent successfully")
        except Exception as e:
            print("❌ Email error:", str(e))

        return new_employee

    except Exception as e:
        print("❌ CREATE EMPLOYEE ERROR:", str(e))
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))