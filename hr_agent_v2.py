"""
C:/HRMS/agent/hr_agent_v2.py

Full production HR Agent with:
  1. Multi-step planning      — complex workflows from one prompt
  2. Proactive alerts         — flags overdue onboarding, stale tickets, pending leave
  3. Scheduled tasks          — daily digest via run_scheduled_digest()
  4. Persistent memory        — conversation + facts stored in agent_memory.json
  5. Self-correction          — retries failed tools, falls back gracefully

Usage (from Streamlit agent tab):
    from agent.hr_agent_v2 import HRAgentV2
    agent = HRAgentV2(db_path=r"C:/HRMS/hrms.db", actor_id="E001")
    reply = agent.chat("Hire John Doe as a DevOps Engineer in IT reporting to E002")

Usage (scheduler — run from cron / Task Scheduler):
    python -m agent.hr_agent_v2
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

# ── Config ────────────────────────────────────────────────────────────
MAX_ITERATIONS   = 20      # agentic loop limit
MAX_TOOL_RETRIES = 3       # self-correction retries per tool call
MEMORY_FILE      = Path(r"C:/HRMS/agent_memory.json")
AUDIT_LOG        = Path(r"C:/HRMS/audit.log")
MODEL            = "claude-sonnet-4-20250514"

# ── Lazy Anthropic import ─────────────────────────────────────────────
def _anthropic():
    try:
        import anthropic
        return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    except KeyError:
        raise RuntimeError("ANTHROPIC_API_KEY environment variable not set.")
    except ImportError:
        raise RuntimeError("anthropic package not installed. Run: pip install anthropic")


# ── Audit ─────────────────────────────────────────────────────────────
def _audit(action: str, performed_by: str, details: dict):
    entry = {
        "timestamp":    datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "action":       action,
        "performed_by": performed_by,
        **details,
    }
    with open(AUDIT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


# ── Persistent Memory ─────────────────────────────────────────────────
class AgentMemory:
    """
    Persists across Streamlit sessions via agent_memory.json.
    Stores:
      - conversation_history  : last N message turns
      - facts                 : key/value facts the agent has learned
      - last_digest_at        : ISO timestamp of last scheduled digest
    """

    MAX_HISTORY = 40  # keep last 40 turns (20 exchanges)

    def __init__(self, path: Path = MEMORY_FILE):
        self.path = path
        self._data = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"conversation_history": [], "facts": {}, "last_digest_at": None}

    def save(self):
        self.path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")

    # Conversation
    @property
    def history(self) -> list[dict]:
        return self._data["conversation_history"]

    def add_turn(self, role: str, content):
        self._data["conversation_history"].append({"role": role, "content": content})
        # Trim to MAX_HISTORY
        if len(self._data["conversation_history"]) > self.MAX_HISTORY:
            self._data["conversation_history"] = self._data["conversation_history"][-self.MAX_HISTORY:]
        self.save()

    def clear_history(self):
        self._data["conversation_history"] = []
        self.save()

    # Facts
    def remember(self, key: str, value: Any):
        self._data["facts"][key] = {"value": value, "at": datetime.utcnow().isoformat()}
        self.save()

    def recall(self, key: str) -> Any:
        entry = self._data["facts"].get(key)
        return entry["value"] if entry else None

    def all_facts(self) -> dict:
        return {k: v["value"] for k, v in self._data["facts"].items()}

    # Digest tracking
    @property
    def last_digest_at(self) -> str | None:
        return self._data.get("last_digest_at")

    def mark_digest_sent(self):
        self._data["last_digest_at"] = datetime.utcnow().isoformat()
        self.save()


# ── DB helpers ────────────────────────────────────────────────────────
class HRDB:
    def __init__(self, db_path: str):
        self.engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False},
        )

    def query(self, sql: str, params: dict | None = None) -> list[dict]:
        with self.engine.connect() as conn:
            rows = conn.execute(text(sql), params or {}).fetchall()
            return [dict(r._mapping) for r in rows]

    def execute(self, sql: str, params: dict | None = None):
        with self.engine.begin() as conn:
            conn.execute(text(sql), params or {})

    def scalar(self, sql: str, params: dict | None = None) -> Any:
        with self.engine.connect() as conn:
            return conn.execute(text(sql), params or {}).scalar()

    # ── Convenience queries ───────────────────────────────────────────

    def get_employees(self) -> list[dict]:
        return self.query("SELECT * FROM employees ORDER BY emp_id")

    def get_employee(self, emp_id: str) -> dict | None:
        rows = self.query("SELECT * FROM employees WHERE emp_id=:e", {"e": emp_id})
        return rows[0] if rows else None

    def next_emp_id(self) -> str:
        rows = self.query("SELECT emp_id FROM employees")
        nums = []
        for r in rows:
            eid = r["emp_id"]
            if eid.startswith("E") and eid[1:].isdigit():
                nums.append(int(eid[1:]))
        return f"E{(max(nums) + 1):03d}" if nums else "E001"

    def next_ticket_id(self) -> str:
        n = self.scalar("SELECT COUNT(*) FROM tickets") or 0
        return f"T{n + 1:04d}"

    def next_leave_id(self) -> str:
        n = self.scalar("SELECT COUNT(*) FROM leave_requests") or 0
        return f"L{n + 1:04d}"

    def get_overdue_onboarding(self) -> list[dict]:
        """Tasks that are Pending and have a due_date in the past."""
        today = date.today().isoformat()
        return self.query(
            "SELECT * FROM onboarding_tasks WHERE status='Pending' AND due_date IS NOT NULL AND due_date < :t",
            {"t": today},
        )

    def get_pending_tasks_no_due_date(self) -> list[dict]:
        """Pending tasks with no due date set — may be forgotten."""
        return self.query(
            "SELECT * FROM onboarding_tasks WHERE status='Pending' AND (due_date IS NULL OR due_date='')"
        )

    def get_stale_tickets(self, days: int = 7) -> list[dict]:
        """Open tickets not updated in `days` days."""
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        return self.query(
            "SELECT * FROM tickets WHERE status='Open' AND updated_at < :c",
            {"c": cutoff},
        )

    def get_pending_leaves(self) -> list[dict]:
        return self.query("SELECT * FROM leave_requests WHERE status='Pending'")

    def get_long_pending_leaves(self, days: int = 3) -> list[dict]:
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        return self.query(
            "SELECT * FROM leave_requests WHERE status='Pending' AND created_at < :c",
            {"c": cutoff},
        )


# ── Proactive Alerts ──────────────────────────────────────────────────
def generate_alerts(db: HRDB) -> list[dict]:
    """
    Scan DB and return a list of alert dicts.
    Called on agent startup and during digest.
    """
    alerts = []

    overdue = db.get_overdue_onboarding()
    for t in overdue:
        alerts.append({
            "level":   "warning",
            "type":    "overdue_onboarding",
            "message": f"Onboarding task '{t['task_name']}' for {t['emp_id']} is overdue (due: {t['due_date']})",
            "data":    t,
        })

    stale = db.get_stale_tickets()
    for t in stale:
        alerts.append({
            "level":   "warning",
            "type":    "stale_ticket",
            "message": f"Ticket {t['ticket_id']} ({t['item']}) has been open for over 7 days",
            "data":    t,
        })

    long_pending = db.get_long_pending_leaves()
    for r in long_pending:
        alerts.append({
            "level":   "info",
            "type":    "pending_leave",
            "message": f"Leave request {r['request_id']} for {r['emp_id']} has been pending for over 3 days",
            "data":    r,
        })

    return alerts


# ── Tool definitions ──────────────────────────────────────────────────
TOOLS = [
    # ── Read ──────────────────────────────────────────────────────────
    {
        "name": "get_employees",
        "description": "Return all employees.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_tickets",
        "description": "Return all support tickets.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_leave_requests",
        "description": "Return all leave requests.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_onboarding_tasks",
        "description": "Return onboarding tasks, optionally filtered by emp_id.",
        "input_schema": {
            "type": "object",
            "properties": {
                "emp_id": {"type": "string", "description": "Filter by employee ID (optional)"}
            },
            "required": [],
        },
    },
    {
        "name": "get_alerts",
        "description": "Return current proactive alerts: overdue onboarding, stale tickets, long-pending leave.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    # ── Write ─────────────────────────────────────────────────────────
    {
        "name": "create_employee",
        "description": "Create a new employee record.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name":           {"type": "string"},
                "email":          {"type": "string"},
                "department":     {"type": "string"},
                "role":           {"type": "string"},
                "system_role":    {"type": "string", "description": "Employee, Manager, HR Admin, HR Staff, IT Support"},
                "manager_emp_id": {"type": "string"},
                "emp_id":         {"type": "string", "description": "Leave blank to auto-generate"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "create_ticket",
        "description": "Create a support ticket for an employee.",
        "input_schema": {
            "type": "object",
            "properties": {
                "emp_id":   {"type": "string"},
                "category": {"type": "string"},
                "item":     {"type": "string"},
                "reason":   {"type": "string"},
            },
            "required": ["emp_id", "category", "item", "reason"],
        },
    },
    {
        "name": "create_onboarding_tasks",
        "description": "Generate default onboarding tasks for an employee.",
        "input_schema": {
            "type": "object",
            "properties": {
                "emp_id": {"type": "string"},
            },
            "required": ["emp_id"],
        },
    },
    {
        "name": "approve_leave",
        "description": "Approve a pending leave request.",
        "input_schema": {
            "type": "object",
            "properties": {
                "request_id": {"type": "string"},
            },
            "required": ["request_id"],
        },
    },
    {
        "name": "reject_leave",
        "description": "Reject a pending leave request.",
        "input_schema": {
            "type": "object",
            "properties": {
                "request_id":       {"type": "string"},
                "rejection_reason": {"type": "string"},
            },
            "required": ["request_id"],
        },
    },
    {
        "name": "close_ticket",
        "description": "Close an open support ticket.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticket_id": {"type": "string"},
            },
            "required": ["ticket_id"],
        },
    },
    {
        "name": "complete_onboarding_task",
        "description": "Mark a specific onboarding task as completed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "emp_id":    {"type": "string"},
                "task_name": {"type": "string"},
            },
            "required": ["emp_id", "task_name"],
        },
    },
    # ── Memory ────────────────────────────────────────────────────────
    {
        "name": "remember_fact",
        "description": "Store a fact in persistent memory for future sessions. E.g. remember the user's preferred name or a recurring policy.",
        "input_schema": {
            "type": "object",
            "properties": {
                "key":   {"type": "string"},
                "value": {"type": "string"},
            },
            "required": ["key", "value"],
        },
    },
    {
        "name": "recall_facts",
        "description": "Retrieve all facts stored in persistent memory.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]

DEFAULT_ONBOARDING_TASKS = [
    ("Create company email account", "IT"),
    ("Prepare laptop",               "IT"),
    ("Assign HR orientation",        "HR"),
    ("Add to payroll",               "Finance"),
    ("Set up access cards",          "Facilities"),
    ("Assign buddy / mentor",        "HR"),
]


# ── Main Agent Class ──────────────────────────────────────────────────
class HRAgentV2:
    def __init__(self, db_path: str = r"C:\HRMS\hrms.db", actor_id: str = "system"):
        self.db       = HRDB(db_path)
        self.actor_id = actor_id
        self.memory   = AgentMemory()

    # ── Tool executor ─────────────────────────────────────────────────

    def _execute_tool(self, name: str, inputs: dict) -> str:
        """Execute one tool call. Returns JSON string result."""

        if name == "get_employees":
            return json.dumps(self.db.get_employees())

        if name == "get_tickets":
            return json.dumps(self.db.query("SELECT * FROM tickets ORDER BY created_at DESC"))

        if name == "get_leave_requests":
            return json.dumps(self.db.query("SELECT * FROM leave_requests ORDER BY created_at DESC"))

        if name == "get_onboarding_tasks":
            emp_id = inputs.get("emp_id")
            if emp_id:
                rows = self.db.query(
                    "SELECT * FROM onboarding_tasks WHERE emp_id=:e", {"e": emp_id}
                )
            else:
                rows = self.db.query("SELECT * FROM onboarding_tasks ORDER BY emp_id")
            return json.dumps(rows)

        if name == "get_alerts":
            return json.dumps(generate_alerts(self.db))

        if name == "create_employee":
            emp_id = inputs.get("emp_id") or self.db.next_emp_id()
            due_date = (date.today() + timedelta(days=7)).isoformat()
            now = datetime.utcnow().isoformat()
            try:
                self.db.execute(
                    """INSERT INTO employees
                       (emp_id, name, email, department, role, system_role, manager_emp_id, status, created_at)
                       VALUES (:eid,:name,:email,:dept,:role,:srole,:mgr,'Active',:now)""",
                    {
                        "eid":   emp_id,
                        "name":  inputs["name"],
                        "email": inputs.get("email"),
                        "dept":  inputs.get("department"),
                        "role":  inputs.get("role"),
                        "srole": inputs.get("system_role", "Employee"),
                        "mgr":   inputs.get("manager_emp_id"),
                        "now":   now,
                    },
                )
                _audit("EMPLOYEE_CREATED", self.actor_id, {
                    "emp_id": emp_id, "name": inputs["name"],
                    "department": inputs.get("department"), "role": inputs.get("role"),
                })
                return json.dumps({"success": True, "emp_id": emp_id, "name": inputs["name"]})
            except Exception as e:
                return json.dumps({"error": str(e)})

        if name == "create_ticket":
            ticket_id = self.db.next_ticket_id()
            now = datetime.utcnow().isoformat()
            try:
                self.db.execute(
                    """INSERT INTO tickets (ticket_id, emp_id, category, item, reason, status, created_at, updated_at)
                       VALUES (:tid,:eid,:cat,:item,:reason,'Open',:now,:now)""",
                    {
                        "tid":    ticket_id,
                        "eid":    inputs["emp_id"],
                        "cat":    inputs["category"],
                        "item":   inputs["item"],
                        "reason": inputs["reason"],
                        "now":    now,
                    },
                )
                _audit("TICKET_CREATED", self.actor_id, {
                    "ticket_id": ticket_id, "emp_id": inputs["emp_id"],
                    "category": inputs["category"], "item": inputs["item"],
                })
                return json.dumps({"success": True, "ticket_id": ticket_id})
            except Exception as e:
                return json.dumps({"error": str(e)})

        if name == "create_onboarding_tasks":
            emp_id = inputs["emp_id"]
            due_date = (date.today() + timedelta(days=7)).isoformat()
            now = datetime.utcnow().isoformat()
            created = []
            for task_name, owner in DEFAULT_ONBOARDING_TASKS:
                existing = self.db.query(
                    "SELECT id FROM onboarding_tasks WHERE emp_id=:e AND task_name=:t",
                    {"e": emp_id, "t": task_name},
                )
                if not existing:
                    self.db.execute(
                        """INSERT INTO onboarding_tasks
                           (emp_id, task_name, status, owner, due_date, created_at, updated_at)
                           VALUES (:e,:t,'Pending',:o,:d,:now,:now)""",
                        {"e": emp_id, "t": task_name, "o": owner, "d": due_date, "now": now},
                    )
                    created.append(task_name)
            _audit("ONBOARDING_TASKS_CREATED", self.actor_id, {"emp_id": emp_id, "tasks": created})
            return json.dumps({"success": True, "emp_id": emp_id, "tasks_created": created})

        if name == "approve_leave":
            request_id = inputs["request_id"]
            row = self.db.query(
                "SELECT * FROM leave_requests WHERE request_id=:r", {"r": request_id}
            )
            if not row:
                return json.dumps({"error": f"{request_id} not found."})
            row = row[0]
            if row["status"] != "Pending":
                return json.dumps({"error": f"Already '{row['status']}'."})
            self.db.execute(
                "UPDATE leave_requests SET status='Approved', updated_at=:n WHERE request_id=:r",
                {"n": datetime.utcnow().isoformat(), "r": request_id},
            )
            _audit("LEAVE_APPROVED", self.actor_id, {
                "request_id": request_id, "emp_id": row["emp_id"],
            })
            return json.dumps({"success": True, "message": f"{request_id} approved."})

        if name == "reject_leave":
            request_id = inputs["request_id"]
            row = self.db.query(
                "SELECT * FROM leave_requests WHERE request_id=:r", {"r": request_id}
            )
            if not row:
                return json.dumps({"error": f"{request_id} not found."})
            row = row[0]
            if row["status"] != "Pending":
                return json.dumps({"error": f"Already '{row['status']}'."})
            self.db.execute(
                "UPDATE leave_requests SET status='Rejected', updated_at=:n WHERE request_id=:r",
                {"n": datetime.utcnow().isoformat(), "r": request_id},
            )
            _audit("LEAVE_REJECTED", self.actor_id, {
                "request_id": request_id, "emp_id": row["emp_id"],
                "reason": inputs.get("rejection_reason"),
            })
            return json.dumps({"success": True, "message": f"{request_id} rejected."})

        if name == "close_ticket":
            ticket_id = inputs["ticket_id"]
            row = self.db.query("SELECT * FROM tickets WHERE ticket_id=:t", {"t": ticket_id})
            if not row:
                return json.dumps({"error": f"{ticket_id} not found."})
            row = row[0]
            if row["status"] == "Closed":
                return json.dumps({"error": f"{ticket_id} already closed."})
            self.db.execute(
                "UPDATE tickets SET status='Closed', updated_at=:n WHERE ticket_id=:t",
                {"n": datetime.utcnow().isoformat(), "t": ticket_id},
            )
            _audit("TICKET_CLOSED", self.actor_id, {
                "ticket_id": ticket_id, "emp_id": row["emp_id"],
            })
            return json.dumps({"success": True, "message": f"{ticket_id} closed."})

        if name == "complete_onboarding_task":
            emp_id, task_name = inputs["emp_id"], inputs["task_name"]
            now = datetime.utcnow().isoformat()
            self.db.execute(
                """UPDATE onboarding_tasks SET status='Completed', completed_at=:n, updated_at=:n
                   WHERE emp_id=:e AND task_name=:t""",
                {"n": now, "e": emp_id, "t": task_name},
            )
            _audit("ONBOARDING_TASK_COMPLETED", self.actor_id, {
                "emp_id": emp_id, "task_name": task_name,
            })
            return json.dumps({"success": True, "message": f"'{task_name}' completed for {emp_id}."})

        if name == "remember_fact":
            self.memory.remember(inputs["key"], inputs["value"])
            return json.dumps({"success": True, "stored": {inputs["key"]: inputs["value"]}})

        if name == "recall_facts":
            return json.dumps(self.memory.all_facts())

        return json.dumps({"error": f"Unknown tool: {name}"})

    # ── Self-correcting tool caller ───────────────────────────────────

    def _call_tool_with_retry(self, name: str, inputs: dict) -> str:
        """Call tool with up to MAX_TOOL_RETRIES retries on error."""
        last_error = None
        for attempt in range(1, MAX_TOOL_RETRIES + 1):
            try:
                result = self._execute_tool(name, inputs)
                parsed = json.loads(result)
                if "error" not in parsed:
                    return result
                last_error = parsed["error"]
                # Don't retry logic errors (wrong ID, wrong status)
                if any(k in last_error.lower() for k in ["not found", "already", "cannot"]):
                    return result
                # Retry transient errors
                time.sleep(0.5 * attempt)
            except Exception as e:
                last_error = str(e)
                time.sleep(0.5 * attempt)

        return json.dumps({
            "error": f"Tool '{name}' failed after {MAX_TOOL_RETRIES} attempts. Last error: {last_error}",
            "fallback": "Skipping this step — please retry manually if needed.",
        })

    # ── Core agentic loop ─────────────────────────────────────────────

    def chat(self, user_message: str) -> str:
        """
        Send a message to the agent. Maintains persistent memory.
        Returns the agent's final text response.
        """
        client = _anthropic()

        # Build facts context for system prompt
        facts = self.memory.all_facts()
        facts_context = ""
        if facts:
            facts_str = "\n".join(f"  - {k}: {v}" for k, v in facts.items())
            facts_context = f"\n\nPersistent memory (facts from previous sessions):\n{facts_str}"

        system = f"""You are a production HR operations agent for a real company.
You have access to live HR data and can take actions via tools.

Your capabilities:
- Answer questions about employees, tickets, leave requests, onboarding
- Execute multi-step workflows (e.g. full hiring: create employee → onboarding tasks → IT ticket)
- Approve/reject leave, close tickets, complete onboarding tasks
- Check proactive alerts for overdue or stale items
- Remember facts across sessions using remember_fact / recall_facts

Rules:
- Always use tools to fetch live data before answering data questions
- For complex requests (e.g. "hire someone"), plan all steps and execute them in sequence
- If a tool returns an error, explain what went wrong and what you did instead
- Be concise and professional
- Always confirm what actions you took at the end of a workflow
- The person acting is: {self.actor_id}{facts_context}
"""

        # Add user message to persistent memory
        self.memory.add_turn("user", user_message)

        # Build message list from persistent history
        messages = list(self.memory.history[:-1])  # all but the last (just added)
        messages.append({"role": "user", "content": user_message})

        final_text = ""

        for iteration in range(MAX_ITERATIONS):
            response = client.messages.create(
                model=MODEL,
                max_tokens=2048,
                system=system,
                tools=TOOLS,
                messages=messages,
            )

            text_parts = [b.text for b in response.content if b.type == "text"]
            tool_uses  = [b for b in response.content if b.type == "tool_use"]

            if text_parts:
                final_text = "\n".join(text_parts)

            # Done — no more tool calls
            if response.stop_reason == "end_turn" or not tool_uses:
                break

            # Execute tools (with self-correction)
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for tu in tool_uses:
                result_str = self._call_tool_with_retry(tu.name, tu.input)
                tool_results.append({
                    "type":        "tool_result",
                    "tool_use_id": tu.id,
                    "content":     result_str,
                })
            messages.append({"role": "user", "content": tool_results})

        # Persist assistant reply
        if final_text:
            self.memory.add_turn("assistant", final_text)

        return final_text or "I completed the requested actions."

    # ── Scheduled digest ──────────────────────────────────────────────

    def run_scheduled_digest(self) -> str:
        """
        Generate a daily HR digest.
        Call this from Windows Task Scheduler or a cron job.

        Example Task Scheduler command:
            python -c "from agent.hr_agent_v2 import HRAgentV2; print(HRAgentV2().run_scheduled_digest())"
        """
        alerts = generate_alerts(self.db)
        pending_leaves = self.db.get_pending_leaves()
        stale_tickets  = self.db.get_stale_tickets()
        pending_tasks  = self.db.query("SELECT * FROM onboarding_tasks WHERE status='Pending'")

        digest_prompt = f"""Generate a concise daily HR digest report.

Current data:
- Proactive alerts: {json.dumps(alerts)}
- Pending leave requests: {json.dumps(pending_leaves)}
- Stale open tickets (>7 days): {json.dumps(stale_tickets)}
- Pending onboarding tasks: {json.dumps(pending_tasks)}

Format as a clear daily summary with sections:
1. 🚨 Alerts requiring action
2. 🏖️ Pending leave requests
3. 🎫 Stale tickets
4. 📋 Onboarding progress

Be concise. Flag anything urgent."""

        digest = self.chat(digest_prompt)
        self.memory.mark_digest_sent()

        # Append digest to audit log
        _audit("SCHEDULED_DIGEST", "system", {"digest_length": len(digest)})

        return digest


# ── CLI entry point (for Task Scheduler) ─────────────────────────────
if __name__ == "__main__":
    import sys
    agent = HRAgentV2(actor_id="system")
    if len(sys.argv) > 1:
        # Direct query: python -m agent.hr_agent_v2 "show all pending leave"
        print(agent.chat(" ".join(sys.argv[1:])))
    else:
        # Default: run digest
        print(agent.run_scheduled_digest())
