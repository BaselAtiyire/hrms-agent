markdown# HRMS Agent — Autonomous AI HR System

> An autonomous AI system that executes multi-step HR workflows — hire, onboard, IT provisioning — from a single natural language prompt. Live in production on AWS ECS Fargate.

**Basel Atiyire** · basilatiyire@gmail.com · [hrms.basilatiyire.com](https://hrms.basilatiyire.com)

![Python](https://img.shields.io/badge/Python-3.12-blue) ![Claude](https://img.shields.io/badge/Anthropic-Claude_API-orange) ![AWS](https://img.shields.io/badge/AWS-ECS_Fargate-yellow) ![Terraform](https://img.shields.io/badge/Terraform-38_resources-purple) ![Streamlit](https://img.shields.io/badge/Frontend-Streamlit-red)

---

## 🎬 Video Walkthrough

**[Watch on Loom →](https://www.loom.com/share/37ae9b646ffe4f02b8ace85ed858e413)**

The walkthrough covers: why I chose this problem, a live demo of the agent executing a full hire-to-onboard workflow, architecture walkthrough, and what I'd build next.

---

## 📸 Screenshots

### 🏢 HR Analytics Dashboard
![HR Analytics Dashboard](docs/screenshots/hrms_basilatiyire_com_HR_Dashboard.png)
*Real-time KPIs — 14 employees, 4 open tickets, 48 onboarding tasks, 1 pending leave request.*

### 🎫 Tickets Overview
![Tickets Overview](docs/screenshots/Ticket_Overview.png)
*4 open and 1 in-progress tickets. 80% are IT category. Charts update in real time from the live database.*

### 📋 Onboarding Tasks
![Onboarding Tasks](docs/screenshots/Onboarding_Task.png)
*48 pending onboarding tasks auto-generated on employee hire via the agent workflow.*

### 🏖️ Leave Request Approval
![Leave Requests](docs/screenshots/LEAVEREQUEST_TAB.png)
*Role-based approval flow. One-click approve/reject with full audit trail written on every action.*

### 🤖 Claude AI Agent — Proactive Alerts
![Agent Tab](docs/screenshots/AGENT_TAB.png)
*The agent proactively surfaces 4 stale tickets and 1 pending leave request on load — without being asked.*

### 📋 Audit Log Sidebar
![Audit Sidebar](docs/screenshots/AUDITSIDE_BAR.png)
*Structured JSON audit trail. Every action logged to `/data/audit.log` on EFS with timestamp, actor, and details.*

---

## 01 · Problem Statement

When a company hires someone, a single event fans out into tasks across HR, IT, and management — create the employee record, generate onboarding tasks, open IT provisioning tickets, notify the manager, track completion. In most companies without enterprise integrations, this coordination happens manually: an HR manager opens the HRIS, then a ticketing system, then a spreadsheet, then follows up two days later to see what stalled.

The people most affected are **HR and operations staff at small-to-mid-sized companies** who carry coordination overhead that doesn't require their judgment — just their time.

| Metric | Value |
|---|---|
| Tools the agent can call | 12 |
| Infrastructure cost reduction | 56% ($62 → $27/month) |
| Prompts to hire → onboard → IT ticket | 1 |

AI is the right tool here because this isn't a form-fill or a rigid script problem. Onboarding is **conditional and stateful**: if IT provisioning fails, dependent tasks need to hold; if instructions are ambiguous, the system should ask rather than guess. That requires reasoning, not just routing.

---

## 02 · Solution Overview

HRMS Agent is a production-deployed autonomous AI system built on Streamlit + FastAPI, backed by Claude's tool-use API, and running live on AWS ECS Fargate. It accepts natural language instructions and executes complex, multi-step HR workflows — reasoning over tool outputs at each step, recovering from failures, and surfacing proactive alerts without being asked.

### Core agent capabilities

- **Multi-step planning** — `"Hire Sarah Connor as DevOps in IT"` triggers: create employee → generate onboarding tasks → open IT ticket, all from one prompt
- **Persistent memory** — `agent_memory.json` on AWS EFS, surviving Streamlit restarts and container replacements
- **Proactive alerting** — surfaces stale tickets (>7 days) and pending leave requests (>3 days) on every load without being prompted
- **Self-correcting execution** — failed tool calls retry up to 3 times with graceful fallback messaging
- **Role-based access control** — leave approvals restricted to Manager, HR Admin, HR Staff; every action logged to structured JSON audit trail

### Dashboard features

- Real-time KPIs: employee count, open tickets, pending onboarding, pending leave
- Leave approval flow with overlap validation and state guards
- Ticket and onboarding task management with actor tracking
- Structured JSON audit sidebar — filterable, exportable

---

## 03 · AI Integration

### Why Claude's tool-use API

I chose **Claude Sonnet** for its tool-use reliability and structured output consistency. When an agent is executing real write operations against a live database — creating employees, opening tickets, updating statuses — a hallucinated tool call or malformed parameter isn't just unhelpful, it corrupts data. Claude's tool-use API gave me the most consistent, schema-adherent invocation behavior across all my testing.

The agent registers **12 tools** exposed via a **FastMCP server** (`hr_mcp_server.py`) — the Model Context Protocol gives me a structured, auditable interface between the agent and the underlying HR data layer. Every tool call, input, and output is captured in LangSmith for full observability.

### Agentic patterns used

- **Tool-use with chaining** — tools called sequentially; each output informs the next call. The hire workflow chains 3 tools in a single execution.
- **Self-correcting execution** — 3-retry logic with graceful fallback before surfacing errors to the user
- **Persistent cross-session memory** — `agent_memory.json` on EFS without a separate vector store
- **Proactive alerting without prompting** — agent scans on load and surfaces time-sensitive items before the user asks
- **MCP-based tool registry** — tools defined once in FastMCP server, consumed cleanly by the agent

### Tradeoffs considered

| Dimension | Decision | Tradeoff |
|---|---|---|
| Cost vs. capability | Claude Sonnet over Opus | Sonnet hits the reliability bar at lower cost. Opus added latency with no quality gain. |
| Database vs. scalability | SQLite on EFS, single Fargate replica | Eliminated RDS (~$30+/month). Trade-off: no horizontal scaling. |
| Infrastructure cost vs. security | Public subnets, removed NAT Gateway | Cut cost 56% ($62 → $27). Tight security groups + ALB + ACM SSL. No security regression. |
| Observability vs. complexity | LangSmith + CloudWatch | LangSmith for per-tool-call traces; CloudWatch for container logs. |
| Flexibility vs. auditability | Structured JSON audit log | Every write logged with timestamp, actor, details. Fully defensible. |

### Where AI exceeded expectations

The proactive alerting behavior. I defined the tool and gave the agent context about what "stale" meant — but the decision to surface alerts unprompted emerged from the model's instruction-following. I didn't hardcode that; the agent reasoned its way to it.

### Where it fell short

Latency under concurrent load. The single-replica synchronous design was intentional (SQLite safety) but limits throughput. First thing I'd address in v2.

---

## 04 · Architecture & Design Decisions
Internet
│
▼ HTTPS (443)
Application Load Balancer  ← basilatiyire.com (ACM SSL cert)
│
▼ HTTP (8501)
ECS Fargate Task           ← Streamlit + Claude Agent
│                         Single replica (SQLite-safe)
├──► EFS /data/hrms.db       SQLite — encrypted, persistent
├──► EFS /data/audit.log     Structured JSON audit trail
├──► EFS agent_memory.json   Cross-session agent memory
├──► ECR Image               Docker image (multi-stage build)
├──► Secrets Manager         ANTHROPIC_API_KEY
└──► CloudWatch Logs         /ecs/hrms-prod (30-day retention)
FastMCP Server (hr_mcp_server.py)
└── 12 HR tools exposed via Model Context Protocol
Agent calls tools → SQLite reads/writes → audit log
GitHub Actions CI/CD
git push → docker build → ECR push → ECS update
Every push to main deploys automatically. No manual steps.

### Key design decisions

- **SQLite on EFS over RDS** — cuts database cost from ~$30+/month to ~$0.30/month. Safe for this workload and traffic level.
- **FastMCP for tool registration** — tools defined once, consumed by the agent cleanly. New capabilities = one tool definition, no agent logic changes.
- **EFS for all persistent state** — agent memory, database, and audit log survive container restarts. Tested explicitly by killing the Fargate task mid-workflow.
- **Terraform for 38 AWS resources** — entire stack reproducible from `terraform apply`. Tore it down and rebuilt multiple times during development.
- **Streamlit for the frontend** — audience is HR managers, not developers. Right tool for internal tooling at this stage.

### How AI coding tools changed my process

I used **Claude** and **Cursor** throughout. Biggest accelerations: Terraform module generation, FastAPI scaffolding, SQLAlchemy models, Pydantic schemas — tasks that would have taken 2–3 hours took 20–30 minutes.

Where tools hit limits: **agent loop debugging**. When the planning loop entered unexpected states, AI tools couldn't diagnose it. That required reading LangSmith execution traces and reasoning through the state machine manually. AI is a force multiplier on velocity; debugging agentic behavior is still a human job.

One structural change: because implementation came fast, I spent more time defining **interfaces and contracts first** — tool input/output schemas before implementations. That inversion made the codebase more modular.

---

## 05 · Getting Started

### Run locally

```bash
git clone https://github.com/BaselAtiyire/hrms-agent.git
cd hrms-agent

python -m venv .venv
source .venv/bin/activate       # Mac/Linux
# .venv\Scripts\activate        # Windows

pip install -r requirements.txt

cp .env.example .env
# Add your ANTHROPIC_API_KEY to .env

streamlit run streamlit_app_standalone.py
# App at http://localhost:8501
```

### With Docker (recommended)

```bash
docker compose up --build
# App at http://localhost:8501
```

### Environment variables

```bash
ANTHROPIC_API_KEY=your_key_here
# See .env.example for full variable list
```

### AWS deployment

```bash
cd infra/
cp prod.tfvars.example prod.tfvars
terraform init
terraform apply -var-file="prod.tfvars"
```

See `DEPLOYMENT.md` for the full step-by-step guide.

---

## 06 · Demo

**Live:** [hrms.basilatiyire.com](https://hrms.basilatiyire.com)

### Hire a new employee
Agent prompt: "Hire Sarah Connor as DevOps in IT"
Agent executes:

create_employee(name="Sarah Connor", role="DevOps", dept="IT")
generate_onboarding_tasks(employee_id=...)
create_ticket(type="IT_PROVISIONING", assignee=...)

Returns: confirmation with employee ID, task count, ticket reference

### Proactive alert check (no prompt needed)

On load, the agent surfaces stale tickets (>7 days) and pending leave requests (>3 days) before the user types anything.

### Leave approval

HR Admin or Manager approves or rejects with one click. Validated against user role, written to audit log, table updates in real time.

---

## 07 · Testing & Error Handling

### Failure modes addressed

- **Tool call failure mid-workflow** — 3-retry logic. On third failure, agent halts the dependent step and surfaces a specific error rather than silently continuing.
- **Ambiguous instructions** — agent asks a clarifying question rather than hallucinating a decision. Tested with intentionally underspecified prompts.
- **Container restart during workflow** — all state on EFS. Killed the Fargate task mid-execution; agent resumed from last persisted state.
- **Invalid leave approval** — state guards block already-approved requests; role checks fire before the write happens.
- **Audit completeness** — every write action captured with timestamp, actor, and details. No write succeeds silently.

### What I didn't fully solve

Concurrent workflow conflicts. Single-replica SQLite is safe now, but two simultaneous agent workflows queue sequentially. V2 fix: async task queue with Celery + Redis.

---

## 08 · Future Improvements

**01 — Async task queue**
Celery + Redis for parallel workflow execution. Unlocks multi-user deployments without the single-replica constraint.

**02 — Live integrations — Workday, Okta, ServiceNow**
Same agent, same tool interface — just real enterprise systems on the other side instead of local SQLite.

**03 — Multi-agent architecture**
Specialized subagents for IT provisioning, HRIS, and communications. Orchestrator delegates to each. Simpler agents are more reliable and easier to extend.

**04 — RAG over HR policy documents**
Embed onboarding playbooks and HR policies so the agent validates workflow steps against current policy without hardcoded rules.

**05 — PostgreSQL on RDS**
Unlocks horizontal Fargate scaling. SQLite on EFS was the right v1 call; PostgreSQL is the right v2 call.

---

## 09 · Links

| | |
|---|---|
| Live demo | [https://hrms.basilatiyire.com](https://hrms.basilatiyire.com) |
| Repository | [github.com/BaselAtiyire/hrms-agent](https://github.com/BaselAtiyire/hrms-agent) |
| Video walkthrough | [loom.com/share/37ae9b646ffe4f02b8ace85ed858e413](https://www.loom.com/share/37ae9b646ffe4f02b8ace85ed858e413) |

---

## 10 · Third-Party Libraries

| Library | Purpose |
|---|---|
| Anthropic Python SDK | Claude API client |
| Streamlit | Frontend dashboard |
| FastAPI | Async Python web framework |
| FastMCP | Model Context Protocol server |
| SQLAlchemy | ORM and database abstraction |
| Pydantic | Data validation |
| LangSmith | LLM observability and tracing |
| Terraform | Infrastructure as code |
| Docker | Containerization |

No proprietary code or confidential information from any employer is included. All credentials use placeholder values in `.env.example`. No live API keys appear anywhere in the repository.

---

*Klaviyo AI Builder Residency Application · Basel Atiyire · April 2026*
