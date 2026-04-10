from __future__ import annotations
import json, os, time, uuid
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Any
from sqlalchemy import create_engine, text

MAX_ITERATIONS   = 20
MAX_TOOL_RETRIES = 3
MEMORY_FILE      = Path("/data/agent_memory.json")
AUDIT_LOG        = Path("/data/audit.log")
MODEL            = "claude-sonnet-4-20250514"
LANGSMITH_PROJECT = os.getenv("LANGCHAIN_PROJECT", "hrms-agent-prod")

def _setup_langsmith():
    key = os.getenv("LANGSMITH_API_KEY")
    if not key:
        return False
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_ENDPOINT"]   = "https://api.smith.langchain.com"
    os.environ["LANGCHAIN_API_KEY"]    = key
    os.environ["LANGCHAIN_PROJECT"]    = LANGSMITH_PROJECT
    return True

LANGSMITH_ENABLED = _setup_langsmith()

def _ls_client():
    if not LANGSMITH_ENABLED:
        return None
    try:
        from langsmith import Client
        return Client()
    except ImportError:
        return None

def _anthropic():
    try:
        import anthropic
        return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    except KeyError:
        raise RuntimeError("ANTHROPIC_API_KEY not set.")

def _audit(action, performed_by, details):
    entry = {"timestamp": datetime.utcnow().isoformat(timespec="seconds")+"Z", "action": action, "performed_by": performed_by, **details}
    with open(AUDIT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

class AgentMemory:
    MAX_HISTORY = 40
    def __init__(self, path=MEMORY_FILE):
        self.path  = path
        self._data = self._load()
    def _load(self):
        if self.path.exists():
            try: return json.loads(self.path.read_text(encoding="utf-8"))
            except: pass
        return {"conversation_history": [], "facts": {}, "last_digest_at": None}
    def save(self):
        self.path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
    @property
    def history(self): return self._data["conversation_history"]
    def add_turn(self, role, content):
        self._data["conversation_history"].append({"role": role, "content": content})
        if len(self._data["conversation_history"]) > self.MAX_HISTORY:
            self._data["conversation_history"] = self._data["conversation_history"][-self.MAX_HISTORY:]
        self.save()
    def clear_history(self):
        self._data["conversation_history"] = []
        self.save()
    def remember(self, key, value):
        self._data["facts"][key] = {"value": value, "at": datetime.utcnow().isoformat()}
        self.save()
    def all_facts(self):
        return {k: v["value"] for k, v in self._data["facts"].items()}
    @property
    def last_digest_at(self): return self._data.get("last_digest_at")
    def mark_digest_sent(self):
        self._data["last_digest_at"] = datetime.utcnow().isoformat()
        self.save()

class HRDB:
    def __init__(self, db_path):
        self.engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    def query(self, sql, params=None):
        with self.engine.connect() as conn:
            return [dict(r._mapping) for r in conn.execute(text(sql), params or {}).fetchall()]
    def execute(self, sql, params=None):
        with self.engine.begin() as conn: conn.execute(text(sql), params or {})
    def scalar(self, sql, params=None):
        with self.engine.connect() as conn: return conn.execute(text(sql), params or {}).scalar()
    def next_emp_id(self):
        rows = self.query("SELECT emp_id FROM employees")
        nums = [int(r["emp_id"][1:]) for r in rows if r["emp_id"].startswith("E") and r["emp_id"][1:].isdigit()]
        return f"E{(max(nums)+1):03d}" if nums else "E001"
    def next_ticket_id(self):
        return f"T{(self.scalar('SELECT COUNT(*) FROM tickets') or 0)+1:04d}"
    def get_stale_tickets(self, days=7):
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        return self.query("SELECT * FROM tickets WHERE status='Open' AND updated_at < :c", {"c": cutoff})
    def get_pending_leaves(self):
        return self.query("SELECT * FROM leave_requests WHERE status='Pending'")
    def get_long_pending_leaves(self, days=3):
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        return self.query("SELECT * FROM leave_requests WHERE status='Pending' AND created_at < :c", {"c": cutoff})
    def get_overdue_onboarding(self):
        today = date.today().isoformat()
        return self.query("SELECT * FROM onboarding_tasks WHERE status='Pending' AND due_date IS NOT NULL AND due_date < :t", {"t": today})

def generate_alerts(db):
    alerts = []
    for t in db.get_overdue_onboarding():
        alerts.append({"level":"warning","type":"overdue_onboarding","message":f"Onboarding task '{t['task_name']}' for {t['emp_id']} is overdue","data":t})
    for t in db.get_stale_tickets():
        alerts.append({"level":"warning","type":"stale_ticket","message":f"Ticket {t['ticket_id']} ({t['item']}) has been open for over 7 days","data":t})
    for r in db.get_long_pending_leaves():
        alerts.append({"level":"info","type":"pending_leave","message":f"Leave request {r['request_id']} for {r['emp_id']} has been pending for over 3 days","data":r})
    return alerts

TOOLS = [
    {"name":"get_employees","description":"Return all employees.","input_schema":{"type":"object","properties":{},"required":[]}},
    {"name":"get_tickets","description":"Return all support tickets.","input_schema":{"type":"object","properties":{},"required":[]}},
    {"name":"get_leave_requests","description":"Return all leave requests.","input_schema":{"type":"object","properties":{},"required":[]}},
    {"name":"get_onboarding_tasks","description":"Return onboarding tasks.","input_schema":{"type":"object","properties":{"emp_id":{"type":"string"}},"required":[]}},
    {"name":"get_alerts","description":"Return current proactive alerts.","input_schema":{"type":"object","properties":{},"required":[]}},
    {"name":"create_employee","description":"Create a new employee.","input_schema":{"type":"object","properties":{"name":{"type":"string"},"email":{"type":"string"},"department":{"type":"string"},"role":{"type":"string"},"system_role":{"type":"string"},"manager_emp_id":{"type":"string"},"emp_id":{"type":"string"}},"required":["name"]}},
    {"name":"create_ticket","description":"Create a support ticket.","input_schema":{"type":"object","properties":{"emp_id":{"type":"string"},"category":{"type":"string"},"item":{"type":"string"},"reason":{"type":"string"}},"required":["emp_id","category","item","reason"]}},
    {"name":"create_onboarding_tasks","description":"Generate onboarding tasks.","input_schema":{"type":"object","properties":{"emp_id":{"type":"string"}},"required":["emp_id"]}},
    {"name":"approve_leave","description":"Approve a pending leave request.","input_schema":{"type":"object","properties":{"request_id":{"type":"string"}},"required":["request_id"]}},
    {"name":"reject_leave","description":"Reject a pending leave request.","input_schema":{"type":"object","properties":{"request_id":{"type":"string"},"rejection_reason":{"type":"string"}},"required":["request_id"]}},
    {"name":"close_ticket","description":"Close an open ticket.","input_schema":{"type":"object","properties":{"ticket_id":{"type":"string"}},"required":["ticket_id"]}},
    {"name":"complete_onboarding_task","description":"Mark onboarding task complete.","input_schema":{"type":"object","properties":{"emp_id":{"type":"string"},"task_name":{"type":"string"}},"required":["emp_id","task_name"]}},
    {"name":"remember_fact","description":"Store a fact in memory.","input_schema":{"type":"object","properties":{"key":{"type":"string"},"value":{"type":"string"}},"required":["key","value"]}},
    {"name":"recall_facts","description":"Retrieve all facts from memory.","input_schema":{"type":"object","properties":{},"required":[]}},
]

DEFAULT_ONBOARDING_TASKS = [
    ("Create company email account","IT"),("Prepare laptop","IT"),
    ("Assign HR orientation","HR"),("Add to payroll","Finance"),
    ("Set up access cards","Facilities"),("Assign buddy / mentor","HR"),
]

class HRAgentV2:
    def __init__(self, db_path="/data/hrms.db", actor_id="system"):
        self.db       = HRDB(db_path)
        self.actor_id = actor_id
        self.memory   = AgentMemory()

    def _execute_tool(self, name, inputs):
        if name == "get_employees":
            return json.dumps(self.db.query("SELECT * FROM employees ORDER BY emp_id"))
        if name == "get_tickets":
            return json.dumps(self.db.query("SELECT * FROM tickets ORDER BY created_at DESC"))
        if name == "get_leave_requests":
            return json.dumps(self.db.query("SELECT * FROM leave_requests ORDER BY created_at DESC"))
        if name == "get_onboarding_tasks":
            emp_id = inputs.get("emp_id")
            rows = self.db.query("SELECT * FROM onboarding_tasks WHERE emp_id=:e",{"e":emp_id}) if emp_id else self.db.query("SELECT * FROM onboarding_tasks ORDER BY emp_id")
            return json.dumps(rows)
        if name == "get_alerts":
            return json.dumps(generate_alerts(self.db))
        if name == "create_employee":
            emp_id = inputs.get("emp_id") or self.db.next_emp_id()
            now = datetime.utcnow().isoformat()
            try:
                self.db.execute("INSERT INTO employees (emp_id,name,email,department,role,system_role,manager_emp_id,status,created_at) VALUES (:eid,:name,:email,:dept,:role,:srole,:mgr,'Active',:now)",
                    {"eid":emp_id,"name":inputs["name"],"email":inputs.get("email"),"dept":inputs.get("department"),"role":inputs.get("role"),"srole":inputs.get("system_role","Employee"),"mgr":inputs.get("manager_emp_id"),"now":now})
                _audit("EMPLOYEE_CREATED",self.actor_id,{"emp_id":emp_id,"name":inputs["name"]})
                return json.dumps({"success":True,"emp_id":emp_id,"name":inputs["name"]})
            except Exception as e: return json.dumps({"error":str(e)})
        if name == "create_ticket":
            tid = self.db.next_ticket_id(); now = datetime.utcnow().isoformat()
            try:
                self.db.execute("INSERT INTO tickets (ticket_id,emp_id,category,item,reason,status,created_at,updated_at) VALUES (:tid,:eid,:cat,:item,:reason,'Open',:now,:now)",
                    {"tid":tid,"eid":inputs["emp_id"],"cat":inputs["category"],"item":inputs["item"],"reason":inputs["reason"],"now":now})
                _audit("TICKET_CREATED",self.actor_id,{"ticket_id":tid,"emp_id":inputs["emp_id"]})
                return json.dumps({"success":True,"ticket_id":tid})
            except Exception as e: return json.dumps({"error":str(e)})
        if name == "create_onboarding_tasks":
            emp_id=inputs["emp_id"]; due=(date.today()+timedelta(days=7)).isoformat(); now=datetime.utcnow().isoformat(); created=[]
            for tname,owner in DEFAULT_ONBOARDING_TASKS:
                if not self.db.query("SELECT id FROM onboarding_tasks WHERE emp_id=:e AND task_name=:t",{"e":emp_id,"t":tname}):
                    self.db.execute("INSERT INTO onboarding_tasks (emp_id,task_name,status,owner,due_date,created_at,updated_at) VALUES (:e,:t,'Pending',:o,:d,:now,:now)",{"e":emp_id,"t":tname,"o":owner,"d":due,"now":now})
                    created.append(tname)
            _audit("ONBOARDING_TASKS_CREATED",self.actor_id,{"emp_id":emp_id,"tasks":created})
            return json.dumps({"success":True,"emp_id":emp_id,"tasks_created":created})
        if name == "approve_leave":
            row=self.db.query("SELECT * FROM leave_requests WHERE request_id=:r",{"r":inputs["request_id"]})
            if not row: return json.dumps({"error":f"{inputs['request_id']} not found."})
            row=row[0]
            if row["status"]!="Pending": return json.dumps({"error":f"Already '{row['status']}'."})
            self.db.execute("UPDATE leave_requests SET status='Approved',updated_at=:n WHERE request_id=:r",{"n":datetime.utcnow().isoformat(),"r":inputs["request_id"]})
            _audit("LEAVE_APPROVED",self.actor_id,{"request_id":inputs["request_id"],"emp_id":row["emp_id"]})
            return json.dumps({"success":True,"message":f"{inputs['request_id']} approved."})
        if name == "reject_leave":
            row=self.db.query("SELECT * FROM leave_requests WHERE request_id=:r",{"r":inputs["request_id"]})
            if not row: return json.dumps({"error":f"{inputs['request_id']} not found."})
            row=row[0]
            if row["status"]!="Pending": return json.dumps({"error":f"Already '{row['status']}'."})
            self.db.execute("UPDATE leave_requests SET status='Rejected',updated_at=:n WHERE request_id=:r",{"n":datetime.utcnow().isoformat(),"r":inputs["request_id"]})
            _audit("LEAVE_REJECTED",self.actor_id,{"request_id":inputs["request_id"],"emp_id":row["emp_id"],"reason":inputs.get("rejection_reason")})
            return json.dumps({"success":True,"message":f"{inputs['request_id']} rejected."})
        if name == "close_ticket":
            row=self.db.query("SELECT * FROM tickets WHERE ticket_id=:t",{"t":inputs["ticket_id"]})
            if not row: return json.dumps({"error":f"{inputs['ticket_id']} not found."})
            row=row[0]
            if row["status"]=="Closed": return json.dumps({"error":f"{inputs['ticket_id']} already closed."})
            self.db.execute("UPDATE tickets SET status='Closed',updated_at=:n WHERE ticket_id=:t",{"n":datetime.utcnow().isoformat(),"t":inputs["ticket_id"]})
            _audit("TICKET_CLOSED",self.actor_id,{"ticket_id":inputs["ticket_id"],"emp_id":row["emp_id"]})
            return json.dumps({"success":True,"message":f"{inputs['ticket_id']} closed."})
        if name == "complete_onboarding_task":
            now=datetime.utcnow().isoformat()
            self.db.execute("UPDATE onboarding_tasks SET status='Completed',completed_at=:n,updated_at=:n WHERE emp_id=:e AND task_name=:t",{"n":now,"e":inputs["emp_id"],"t":inputs["task_name"]})
            _audit("ONBOARDING_TASK_COMPLETED",self.actor_id,{"emp_id":inputs["emp_id"],"task_name":inputs["task_name"]})
            return json.dumps({"success":True,"message":f"'{inputs['task_name']}' completed."})
        if name == "remember_fact":
            self.memory.remember(inputs["key"],inputs["value"])
            return json.dumps({"success":True})
        if name == "recall_facts":
            return json.dumps(self.memory.all_facts())
        return json.dumps({"error":f"Unknown tool: {name}"})

    def _call_tool_with_retry(self, name, inputs):
        last_error = None
        for attempt in range(1, MAX_TOOL_RETRIES+1):
            try:
                result = self._execute_tool(name, inputs)
                parsed = json.loads(result)
                if "error" not in parsed: return result
                last_error = parsed["error"]
                if any(k in last_error.lower() for k in ["not found","already","cannot"]): return result
                time.sleep(0.5*attempt)
            except Exception as e:
                last_error = str(e); time.sleep(0.5*attempt)
        return json.dumps({"error":f"Tool '{name}' failed after {MAX_TOOL_RETRIES} attempts: {last_error}"})

    def chat(self, user_message):
        facts = self.memory.all_facts()
        facts_ctx = ("\n\nMemory:\n"+"\n".join(f"  - {k}: {v}" for k,v in facts.items())) if facts else ""
        system = f"You are a production HR operations agent. Use tools to fetch live data. Actor: {self.actor_id}{facts_ctx}"

        self.memory.add_turn("user", user_message)
        messages = list(self.memory.history[:-1])
        messages.append({"role":"user","content":user_message})

        final_text = ""
        tool_calls_log = []
        start_time = datetime.utcnow()
        ls = _ls_client()
        parent_run_id = str(uuid.uuid4())

        if ls:
            try:
                ls.create_run(id=parent_run_id, name="hrms-agent-chat", run_type="chain",
                    inputs={"user_message":user_message,"actor_id":self.actor_id},
                    project_name=LANGSMITH_PROJECT)
            except Exception: parent_run_id = None

        for iteration in range(MAX_ITERATIONS):
            client = _anthropic()
            llm_start = datetime.utcnow()
            response = client.messages.create(model=MODEL, max_tokens=2048, system=system, tools=TOOLS, messages=messages)
            text_parts = [b.text for b in response.content if b.type=="text"]
            tool_uses  = [b for b in response.content if b.type=="tool_use"]
            if text_parts: final_text = "\n".join(text_parts)

            if ls and parent_run_id:
                try:
                    llm_id = str(uuid.uuid4())
                    ls.create_run(id=llm_id, parent_run_id=parent_run_id, name="claude-messages", run_type="llm",
                        inputs={"messages":messages,"model":MODEL},
                        outputs={"text":final_text,"stop_reason":response.stop_reason,
                                 "input_tokens":response.usage.input_tokens,"output_tokens":response.usage.output_tokens,
                                 "latency_ms":int((datetime.utcnow()-llm_start).total_seconds()*1000)},
                        project_name=LANGSMITH_PROJECT)
                    ls.update_run(llm_id, end_time=datetime.utcnow())
                except Exception: pass

            if response.stop_reason=="end_turn" or not tool_uses: break

            messages.append({"role":"assistant","content":response.content})
            tool_results = []
            for tu in tool_uses:
                ts = datetime.utcnow()
                result_str = self._call_tool_with_retry(tu.name, tu.input)
                dur = int((datetime.utcnow()-ts).total_seconds()*1000)
                tool_calls_log.append({"tool":tu.name,"input":tu.input,"output":result_str,"duration_ms":dur})
                if ls and parent_run_id:
                    try:
                        tid = str(uuid.uuid4())
                        ls.create_run(id=tid, parent_run_id=parent_run_id, name=f"tool-{tu.name}", run_type="tool",
                            inputs=tu.input, outputs={"result":result_str,"duration_ms":dur},
                            project_name=LANGSMITH_PROJECT)
                        ls.update_run(tid, end_time=datetime.utcnow())
                    except Exception: pass
                tool_results.append({"type":"tool_result","tool_use_id":tu.id,"content":result_str})
            messages.append({"role":"user","content":tool_results})

        if ls and parent_run_id:
            try:
                ls.update_run(parent_run_id,
                    outputs={"response":final_text,"tool_calls":tool_calls_log,
                             "iterations":iteration+1,"duration_ms":int((datetime.utcnow()-start_time).total_seconds()*1000)},
                    end_time=datetime.utcnow())
            except Exception: pass

        if final_text: self.memory.add_turn("assistant", final_text)
        return final_text or "I completed the requested actions."

    def run_evaluation(self):
        ls = _ls_client()
        if not ls: return {"error":"LangSmith not configured."}
        eval_cases = [
            {"input":"How many employees do we have?","keywords":["employee","total","count"],"category":"data_query"},
            {"input":"Show me all open tickets","keywords":["ticket","open","status"],"category":"data_query"},
            {"input":"Are there any pending leave requests?","keywords":["leave","pending","request"],"category":"data_query"},
            {"input":"What alerts do we have right now?","keywords":["alert","stale","pending"],"category":"proactive"},
            {"input":"Which departments have the most employees?","keywords":["department","finance","it"],"category":"analytics"},
        ]
        results = []
        for case in eval_cases:
            try:
                response = self.chat(case["input"])
                rl = response.lower()
                hits = [k for k in case["keywords"] if k in rl]
                score = len(hits)/len(case["keywords"])
                results.append({"input":case["input"],"category":case["category"],"score":round(score,2),"hits":hits,"passed":score>=0.6,"response":response[:200]})
                try:
                    eid = str(uuid.uuid4())
                    ls.create_run(id=eid, name=f"eval-{case['category']}", run_type="chain",
                        inputs={"question":case["input"]},
                        outputs={"score":score,"passed":score>=0.6,"hits":hits},
                        project_name=f"{LANGSMITH_PROJECT}-evals")
                    ls.update_run(eid, end_time=datetime.utcnow())
                except Exception: pass
            except Exception as e:
                results.append({"input":case["input"],"error":str(e),"score":0,"passed":False})
        passed = sum(1 for r in results if r.get("passed"))
        return {"total":len(results),"passed":passed,"failed":len(results)-passed,
                "avg_score":round(sum(r.get("score",0) for r in results)/len(results),2),
                "pass_rate":f"{round(passed/len(results)*100)}%","results":results}

    def run_scheduled_digest(self):
        alerts = generate_alerts(self.db)
        digest = self.chat(
            f"Generate a concise daily HR digest.\nAlerts: {json.dumps(alerts)}\n"
            f"Pending leave: {json.dumps(self.db.get_pending_leaves())}\n"
            f"Stale tickets: {json.dumps(self.db.get_stale_tickets())}\n"
            f"Pending onboarding: {json.dumps(self.db.query('SELECT * FROM onboarding_tasks WHERE status=chr(80)+chr(101)+chr(110)+chr(100)+chr(105)+chr(110)+chr(103)'))}\n"
            f"Format: Alerts | Leave | Tickets | Onboarding. Be concise."
        )
        self.memory.mark_digest_sent()
        _audit("SCHEDULED_DIGEST","system",{"digest_length":len(digest)})
        return digest

if __name__ == "__main__":
    import sys
    agent = HRAgentV2(actor_id="system")
    print(agent.chat(" ".join(sys.argv[1:])) if len(sys.argv)>1 else agent.run_scheduled_digest())
