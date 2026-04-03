"""
agent/chat_ai.py  — drop-in replacement
Adds approve_leave and reject_leave NLP parsing + dispatch.
"""

from __future__ import annotations

import json
import os

from dotenv import load_dotenv
from openai import OpenAI

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
- list_leave_requests
- approve_leave
- reject_leave

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
    "reason": null,
    "request_id": null,
    "approved_by": null,
    "rejected_by": null,
    "rejection_reason": null
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
- Use "list_leave_requests" when the user wants to view, show, or list leave requests.
- Use "approve_leave" when the user wants to approve a leave request.
  Extract request_id (e.g. "L0001") and approved_by (the approver's emp_id, e.g. "E001").
- Use "reject_leave" when the user wants to reject or deny a leave request.
  Extract request_id, rejected_by (emp_id), and optionally rejection_reason.
- If the request is unclear, return:
  {"tool": "unknown", "arguments": {}}

Extraction rules:
- Preserve IDs exactly if the user gives them.
- Extract manager_emp_id when the user says things like:
  "reporting to E001", "under E001", "manager E001".
- Extract system_role only if the user clearly gives an access role like:
  "HR Admin", "HR Staff", "Manager", "IT Support", "Employee".
- If system_role is not provided, leave it null.
- For approve_leave / reject_leave:
  - request_id is the leave request ID (e.g. "L0001").
  - approved_by / rejected_by is the emp_id of the person taking the action.
  - rejection_reason is any reason phrase after "because", "reason:", "due to", etc.
- For create_ticket, extract: emp_id, category, item, reason.
- For onboard_employee, extract emp_id.
- For create_employee or hire_employee, extract:
  emp_id, name, email, department, role, system_role, manager_emp_id.

Important validation hints:
- If the user asks to approve/reject but no request_id is given, still choose the tool with request_id = null.
- If the user asks to approve/reject but no approver emp_id is given, still choose the tool with approved_by/rejected_by = null.

Examples:

User: Approve leave request L0001 as E001
Output:
{"tool":"approve_leave","arguments":{"emp_id":null,"name":null,"email":null,"department":null,"role":null,"system_role":null,"manager_emp_id":null,"category":null,"item":null,"reason":null,"request_id":"L0001","approved_by":"E001","rejected_by":null,"rejection_reason":null}}

User: Reject L0002 as E001 because insufficient staffing
Output:
{"tool":"reject_leave","arguments":{"emp_id":null,"name":null,"email":null,"department":null,"role":null,"system_role":null,"manager_emp_id":null,"category":null,"item":null,"reason":null,"request_id":"L0002","approved_by":null,"rejected_by":"E001","rejection_reason":"insufficient staffing"}}

User: Show all leave requests
Output:
{"tool":"list_leave_requests","arguments":{"emp_id":null,"name":null,"email":null,"department":null,"role":null,"system_role":null,"manager_emp_id":null,"category":null,"item":null,"reason":null,"request_id":null,"approved_by":null,"rejected_by":null,"rejection_reason":null}}

User: Show leave requests for E002
Output:
{"tool":"list_leave_requests","arguments":{"emp_id":"E002","name":null,"email":null,"department":null,"role":null,"system_role":null,"manager_emp_id":null,"category":null,"item":null,"reason":null,"request_id":null,"approved_by":null,"rejected_by":null,"rejection_reason":null}}

User: Show all employees
Output:
{"tool":"list_employees","arguments":{"emp_id":null,"name":null,"email":null,"department":null,"role":null,"system_role":null,"manager_emp_id":null,"category":null,"item":null,"reason":null,"request_id":null,"approved_by":null,"rejected_by":null,"rejection_reason":null}}
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
    return json.loads(response.choices[0].message.content)


def normalize_id(value) -> str | None:
    if not value:
        return None
    return str(value).strip() or None


def normalize_text(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def validate_tool_arguments(tool: str, arguments: dict) -> dict:
    arguments = arguments or {}
    normalized = {
        "emp_id":           normalize_id(arguments.get("emp_id")),
        "name":             normalize_text(arguments.get("name")),
        "email":            normalize_text(arguments.get("email")),
        "department":       normalize_text(arguments.get("department")),
        "role":             normalize_text(arguments.get("role")),
        "system_role":      normalize_text(arguments.get("system_role")),
        "manager_emp_id":   normalize_id(arguments.get("manager_emp_id")),
        "category":         normalize_text(arguments.get("category")),
        "item":             normalize_text(arguments.get("item")),
        "reason":           normalize_text(arguments.get("reason")),
        # leave-specific
        "request_id":       normalize_id(arguments.get("request_id")),
        "approved_by":      normalize_id(arguments.get("approved_by")),
        "rejected_by":      normalize_id(arguments.get("rejected_by")),
        "rejection_reason": normalize_text(arguments.get("rejection_reason")),
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


def run_chat_agent(prompt: str):  # noqa: C901  (complexity ok for dispatcher)
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
        return {"message": f"❌ {validation['error']}", "tip": validation.get("tip")}

    arguments = validation["arguments"]

    try:
        # ── existing tools ─────────────────────────────────────────────
        if tool == "list_employees":
            return tools[tool]()

        if tool == "list_leave_requests":
            return tools[tool](emp_id=arguments.get("emp_id"))

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
            missing = [f for f in required if not arguments.get(f)]
            if missing:
                return {
                    "message": f"Missing required ticket fields: {', '.join(missing)}",
                    "tip": "Example: Create an IT ticket for E004 for a new mouse because the current one is faulty",
                }
            return tools[tool](
                emp_id=arguments["emp_id"],
                category=arguments["category"],
                item=arguments["item"],
                reason=arguments["reason"],
            )

        if tool == "create_employee":
            if not arguments.get("name"):
                return {
                    "message": "Employee name is required.",
                    "tip": "Example: Create employee Emma White in Finance as a Data Analyst reporting to E001",
                }
            return tools[tool](
                emp_id=arguments.get("emp_id"),
                name=arguments["name"],
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
                    "tip": "Example: Hire Emma White as a Data Analyst in Finance with system role Employee reporting to E001",
                }
            return tools[tool](
                emp_id=arguments.get("emp_id"),
                name=arguments["name"],
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
                to_email=arguments["email"],
                employee_name=arguments["name"],
                emp_id=arguments.get("emp_id"),
            )

        # ── NEW: leave approval / rejection ────────────────────────────
        if tool == "approve_leave":
            request_id = arguments.get("request_id")
            approved_by = arguments.get("approved_by")
            if not request_id:
                return {
                    "message": "Which leave request should I approve? Provide the request ID (e.g. L0001).",
                    "tip": "Example: Approve leave request L0001 as E001",
                }
            if not approved_by:
                return {
                    "message": "Who is approving this leave? Provide the approver's employee ID.",
                    "tip": "Example: Approve leave request L0001 as E001",
                }
            return tools[tool](request_id=request_id, approved_by=approved_by)

        if tool == "reject_leave":
            request_id = arguments.get("request_id")
            rejected_by = arguments.get("rejected_by")
            if not request_id:
                return {
                    "message": "Which leave request should I reject? Provide the request ID (e.g. L0001).",
                    "tip": "Example: Reject leave request L0001 as E001 because insufficient staffing",
                }
            if not rejected_by:
                return {
                    "message": "Who is rejecting this leave? Provide the employee ID of the person rejecting.",
                    "tip": "Example: Reject leave request L0001 as E001 because insufficient staffing",
                }
            return tools[tool](
                request_id=request_id,
                rejected_by=rejected_by,
                rejection_reason=arguments.get("rejection_reason") or "",
            )

        return {"message": "Tool selected but no handler was matched."}

    except Exception as e:
        return {"message": f"Agent error: {str(e)}"}
