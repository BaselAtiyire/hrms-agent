import json
import os
from openai import OpenAI
from dotenv import load_dotenv

from agent.hr_agent import HRAgent

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
agent = HRAgent()

SYSTEM_PROMPT = """
You are an HR operations agent.

Your task is to choose the best tool for the user's request and extract arguments.

Available tools:
- list_employees
- create_employee
- create_ticket
- onboard_employee
- send_welcome_email
- hire_employee

Return valid JSON only.
Do not use markdown.
Do not explain.

Output schema:
{
  "tool": "list_employees",
  "arguments": {
    "emp_id": null,
    "name": null,
    "email": null,
    "department": null,
    "role": null,
    "system_role": null,
    "manager_emp_id": null,
    "category": null,
    "item": null,
    "reason": null
  }
}

Tool rules:
- Use "hire_employee" when the user wants a full hiring workflow:
  employee creation + onboarding + IT setup + welcome email.
- Use "create_employee" when the user wants employee creation only.
- Use "create_ticket" when the user wants ticket creation only.
- Use "onboard_employee" when the user wants onboarding only.
- Use "send_welcome_email" only when the user explicitly wants to send a welcome email.
- Use "list_employees" for requests to show, list, or view employees.
- If the request is unclear, return:
  {"tool": "unknown", "arguments": {}}

Extraction rules:
- Preserve IDs exactly if the user gives them.
- Extract manager_emp_id when the user says things like:
  "reporting to E001", "under E001", "manager E001".
- Extract system_role only if the user clearly gives an access role like:
  "HR Admin", "HR Staff", "Manager", "IT Support", "Employee".
- If system_role is not provided, leave it null.
- For create_ticket, extract:
  emp_id, category, item, reason.
- For onboard_employee, extract emp_id.
- For create_employee or hire_employee, extract:
  emp_id, name, email, department, role, system_role, manager_emp_id.

Important validation hints:
- If the user asks to onboard but no employee ID is given, still choose onboard_employee with emp_id = null.
- If the user asks to create a ticket but some fields are missing, still choose create_ticket and leave missing fields null.
- If the user asks to hire or create an employee but name is missing, still choose the best matching tool and leave name null.

Examples:

User: Show all employees
Output:
{"tool":"list_employees","arguments":{"emp_id":null,"name":null,"email":null,"department":null,"role":null,"system_role":null,"manager_emp_id":null,"category":null,"item":null,"reason":null}}

User: Onboard E004
Output:
{"tool":"onboard_employee","arguments":{"emp_id":"E004","name":null,"email":null,"department":null,"role":null,"system_role":null,"manager_emp_id":null,"category":null,"item":null,"reason":null}}

User: Create an IT ticket for E003 for a new mouse because the current one is faulty
Output:
{"tool":"create_ticket","arguments":{"emp_id":"E003","name":null,"email":null,"department":null,"role":null,"system_role":null,"manager_emp_id":null,"category":"IT","item":"new mouse","reason":"the current one is faulty"}}

User: Hire Emma White as a Data Analyst in Finance with system role Employee reporting to E001 and email emma@example.com
Output:
{"tool":"hire_employee","arguments":{"emp_id":null,"name":"Emma White","email":"emma@example.com","department":"Finance","role":"Data Analyst","system_role":"Employee","manager_emp_id":"E001","category":null,"item":null,"reason":null}}

User: Send a welcome email to emma@example.com for Emma White with employee ID E005
Output:
{"tool":"send_welcome_email","arguments":{"emp_id":"E005","name":"Emma White","email":"emma@example.com","department":null,"role":null,"system_role":null,"manager_emp_id":null,"category":null,"item":null,"reason":null}}
"""


def parse_prompt(prompt: str) -> dict:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    )
    content = response.choices[0].message.content
    return json.loads(content)


def normalize_id(value):
    if not value:
        return value
    return str(value).strip()


def normalize_text(value):
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def validate_tool_arguments(tool: str, arguments: dict) -> dict:
    arguments = arguments or {}

    normalized = {
        "emp_id": normalize_id(arguments.get("emp_id")),
        "name": normalize_text(arguments.get("name")),
        "email": normalize_text(arguments.get("email")),
        "department": normalize_text(arguments.get("department")),
        "role": normalize_text(arguments.get("role")),
        "system_role": normalize_text(arguments.get("system_role")),
        "manager_emp_id": normalize_id(arguments.get("manager_emp_id")),
        "category": normalize_text(arguments.get("category")),
        "item": normalize_text(arguments.get("item")),
        "reason": normalize_text(arguments.get("reason")),
    }

    if tool in {"create_employee", "hire_employee"}:
        if (
            normalized["emp_id"]
            and normalized["manager_emp_id"]
            and normalized["emp_id"] == normalized["manager_emp_id"]
        ):
            return {
                "error": "Employee cannot be their own manager.",
                "tip": "Use a different manager_emp_id.",
            }

    return {"arguments": normalized}


def run_chat_agent(prompt: str):
    try:
        parsed = parse_prompt(prompt)
    except Exception as e:
        return {"message": f"Agent parse error: {str(e)}"}

    tool = parsed.get("tool")
    arguments = parsed.get("arguments", {}) or {}

    tools = agent.available_tools()

    if tool == "unknown" or tool not in tools:
        return {"message": "Sorry, I could not understand that request."}

    validation = validate_tool_arguments(tool, arguments)
    if "error" in validation:
        return {
            "message": f"❌ {validation['error']}",
            "tip": validation.get("tip"),
        }

    arguments = validation["arguments"]

    try:
        if tool == "list_employees":
            return tools[tool]()

        if tool == "onboard_employee":
            emp_id = arguments.get("emp_id")
            if not emp_id:
                return {
                    "message": "Which employee should I onboard?",
                    "tip": "Example: Onboard E004",
                }
            return tools[tool](emp_id)

        if tool == "create_ticket":
            required = ["emp_id", "category", "item", "reason"]
            missing = [field for field in required if not arguments.get(field)]
            if missing:
                return {
                    "message": f"Missing required ticket fields: {', '.join(missing)}",
                    "tip": "Example: Create an IT ticket for E004 for a new mouse because the current one is faulty",
                }

            return tools[tool](
                emp_id=arguments.get("emp_id"),
                category=arguments.get("category"),
                item=arguments.get("item"),
                reason=arguments.get("reason"),
            )

        if tool == "create_employee":
            if not arguments.get("name"):
                return {
                    "message": "Employee name is required.",
                    "tip": "Example: Create employee Emma White in Finance as a Data Analyst reporting to E001",
                }

            return tools[tool](
                emp_id=arguments.get("emp_id"),
                name=arguments.get("name"),
                email=arguments.get("email"),
                department=arguments.get("department"),
                role=arguments.get("role"),
                system_role=arguments.get("system_role") or "Employee",
                manager_emp_id=arguments.get("manager_emp_id"),
            )

        if tool == "hire_employee":
            if not arguments.get("name"):
                return {
                    "message": "Employee name is required for hiring.",
                    "tip": "Example: Hire Emma White as a Data Analyst in Finance with system role Employee reporting to E001 and email emma@example.com",
                }

            return tools[tool](
                emp_id=arguments.get("emp_id"),
                name=arguments.get("name"),
                email=arguments.get("email"),
                department=arguments.get("department"),
                role=arguments.get("role"),
                system_role=arguments.get("system_role") or "Employee",
                manager_emp_id=arguments.get("manager_emp_id"),
            )

        if tool == "send_welcome_email":
            if not arguments.get("email") or not arguments.get("name"):
                return {
                    "message": "Email and employee name are required.",
                    "tip": "Example: Send a welcome email to emma@example.com for Emma White with employee ID E005",
                }

            return tools[tool](
                to_email=arguments.get("email"),
                employee_name=arguments.get("name"),
                emp_id=arguments.get("emp_id"),
            )

        return {"message": "Tool selected but no handler was matched."}

    except Exception as e:
        return {"message": f"Agent error: {str(e)}"}