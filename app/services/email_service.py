import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from dotenv import load_dotenv

load_dotenv()

EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")


def send_welcome_email(to_email, name):
    subject = "Welcome to the Company 🎉"

    body = f"""
Hello {name},

Welcome to the company!

Your employee account has been successfully created in our HRMS system.

We are excited to have you onboard 🎉

Best regards,  
HR Team
"""

    try:
        msg = MIMEMultipart()
        msg["From"] = EMAIL_USER
        msg["To"] = to_email
        msg["Subject"] = subject

        msg.attach(MIMEText(body, "plain"))

        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASS)

        server.send_message(msg)
        server.quit()

        print("✅ Welcome email sent!")
    except Exception as e:
        print("❌ Email error:", str(e))
