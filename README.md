# HRMS Agent — Autonomous AI HR System

> An autonomous AI system that executes multi-step HR workflows — hire, onboard, IT provisioning — from a single natural language prompt. Live in production on AWS ECS Fargate.

**Basel Atiyire** · basilatiyire@gmail.com · [hrms.basilatiyire.com](https://hrms.basilatiyire.com)

![Python](https://img.shields.io/badge/Python-3.12-blue) ![Claude](https://img.shields.io/badge/Anthropic-Claude_API-orange) ![AWS](https://img.shields.io/badge/AWS-ECS_Fargate-yellow) ![Terraform](https://img.shields.io/badge/Terraform-38_resources-purple) ![Streamlit](https://img.shields.io/badge/Frontend-Streamlit-red)

---

## 🎬 Video Walkthrough

**[Watch on Loom →](https://www.loom.com/share/37ae9b646ffe4f02b8ace85ed858e413)**

The walkthrough covers: why I chose this problem, a live demo of the agent executing a full hire-to-onboard workflow, architecture walkthrough, and what I'd build next.

---

## 01 · Problem Statement

When a company hires someone, a single event fans out into tasks across HR, IT, and management — create the employee record, generate onboarding tasks, open IT provisioning tickets, notify the manager, track completion. In most companies without enterprise integrations, this coordination happens manually: an HR manager opens the HRIS, then a ticketing system, then a spreadsheet, then follows up two days later to see what stalled.

The people most affected are **HR and operations staff at small-to-mid-sized companies** who carry coordination overhead that doesn't require their judgment — just their time. They track stale tickets, chase pending approvals, and re-enter the same information across systems.

| Metric | Value |
|---|---|
| Tools the agent can call | 12 |
| Infrastructure cost reduction | 56% ($62 → $27/month) |
| Prompts to hire → onboard → IT ticket | 1 |

Success looks like: an HR manager types `"Hire Sarah Connor as DevOps in IT"` and the agent creates the employee record, generates onboarding tasks, opens the IT provisioning ticket, and surfaces any stale items — without the manager touching a second screen. That's exactly what this system does, live, at [hrms.basilatiyire.com](https://hrms.basilatiyire.com).

AI is the right tool here because this isn't a form-fill or a rigid script problem. Onboarding is **conditional and stateful**: if IT provisioning fails, dependent tasks need to hold; if instructions are ambiguous, the system should ask rather than guess. That requires reasoning, not just routing — which is what the Claude agent provides.

---

## 02 · Solution Overview

HRMS Agent is a production-deployed autonomous AI system built on Streamlit + FastAPI, backed by Claude's tool-use API, and running live on AWS ECS Fargate. It accepts natural language instructions and executes complex, multi-step HR workflows — reasoning over tool outputs at each step, recovering from failures, and surfacing proactive alerts without being asked.

### Core agent capabilities

- **Multi-step planning** — `"Hire Sarah Connor as DevOps in IT"` triggers: create employee → generate onboarding tasks → open IT ticket, all from one prompt. The agent chains 12 registered tools against live SQLite data.
- **Persistent memory** — conversation history and agent facts are stored as `agent_memory.json` on AWS EFS, surviving Streamlit restarts and container replacements.
- **Proactive alerting** — on every load, the agent surfaces stale tickets open more than 7 days and leave requests pending more than 3 days without being prompted.
- **Self-correcting execution** — failed tool calls retry up to 3 times with graceful fallback messaging rather than silent failure.
- **Role-based access control** — leave approvals are restricted to Manager, HR Admin, and HR Staff roles; actions are enforced at the application layer and logged to a structured JSON audit trail.

### Dashboard features

- Real-time KPIs: employee count, open tickets, pending onboarding tasks, pending leave
- Leave approval flow with overlap validation and state guards
- Ticket and onboarding task management with actor tracking
- Structured JSON audit sidebar — filterable, exportable, covering every write action

AI is **core** to the solution, not bolted on. The dashboard surfaces data; the agent acts on it. Without the LLM's ability to reason over tool outputs, handle ambiguous instructions mid-workflow, and replan on failure, this would require a rigid hand-coded state machine that breaks on any edge case.

---

## 03 · AI Integration

### Why Claude's tool-use API

I chose **Claude Sonnet** for its tool-use reliability and structured output consistency. When an agent is executing real write operations against a live database — creating employees, opening tickets, updating statuses — a hallucinated tool call or malformed parameter isn't just unhelpful, it corrupts data. Claude's tool-use API gave me the most consistent, schema-adherent invocation behavior across all my testing.

The agent registers **12 tools** exposed via a **FastMCP server** (`hr_mcp_server.py`) — the Model Context Protocol gives me a structured, auditable interface between the agent and the underlying HR data layer. Every tool call, input, and output is captured in LangSmith for full observability.

### Agentic patterns used

- **Tool-use with chaining** — tools are called sequentially; each output informs the next call. The hire workflow chains 3 tools in a single agent execution.
- **Self-correcting execution** — 3-retry logic with graceful fallback. On failure, the agent retries before surfacing a specific error to the user.
- **Persistent cross-session memory** — `agent_memory.json` on EFS. The agent remembers context across sessions without a separate vector store.
- **Proactive alerting without prompting** — the agent runs a scan on load, surfaces time-sensitive items, and presents them before the user asks anything.
- **MCP-based tool registry** — tools are defined once in the FastMCP server and consumed cleanly by the agent, making it straightforward to add new capabilities without touching agent logic.

### Tradeoffs considered

| Dimension | Decision | Tradeoff |
|---|---|---|
| Cost vs. capability | Claude Sonnet over Opus | Sonnet hits the reliability bar for structured tool calls at significantly lower cost. Opus added latency with no meaningful quality gain for this task type. |
| Database simplicity vs. scalability | SQLite on EFS, single Fargate replica | Eliminated RDS (~$30+/month). Safe for internal HR tooling traffic. Trade-off: no horizontal scaling — acceptable for this use case. |
| Infrastructure cost vs. security | Public subnets, removed NAT Gateway | Cut monthly cost 56% ($62 → $27). Compensated with tight security groups, ALB + ACM SSL at the edge, non-root container user. No security regression. |
| Observability vs. complexity | LangSmith + CloudWatch | LangSmith gives per-tool-call trace visibility; CloudWatch handles container-level logs. Two systems, but each does something the other cannot. |
| Flexibility vs. auditability | Structured JSON audit log on EFS | Every write action logged with timestamp, actor, and details. Small write overhead per action but every state change is defensible. |

### Where AI exceeded expectations

The proactive alerting behavior. I defined the tool and gave the agent context about what "stale" meant — but the decision to surface alerts unprompted, prioritize them, and present them before the user asked anything emerged from the model's instruction-following. I didn't hardcode that behavior; the agent reasoned its way to it.

### Where it fell short

Latency under concurrent load. When multiple users trigger agent workflows simultaneously, tool call queuing compounds. The current single-replica, synchronous design was intentional (SQLite safety), but it limits throughput. This is the first thing I'd address in v2.

---

## 04 · Architecture & Design Decisions

```
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
```

### Key design decisions

- **SQLite on EFS over RDS** — RDS adds ~$30+/month for an internal tool with moderate traffic. SQLite on EFS with a single Fargate replica cuts database cost to ~$0.30/month.
- **FastMCP for tool registration** — defining tools once in the MCP server and consuming them in the agent layer keeps concerns separated. Adding a new HR capability means writing one tool definition, not modifying agent logic.
- **EFS for all persistent state** — agent memory, the SQLite database, and the audit log all live on EFS. Container restarts lose nothing. I tested this explicitly by killing the Fargate task mid-workflow.
- **Terraform for 38 AWS resources** — the entire stack is reproducible from a single `terraform apply`. I tore down and redeployed the full stack multiple times to iterate on infrastructure decisions.
- **Streamlit for the frontend** — the audience is HR managers, not developers. Streamlit delivered a usable, functional dashboard without a separate frontend build pipeline.

### How AI coding tools changed my process

I used **Claude** and **Cursor** throughout. The clearest acceleration: Terraform module generation, FastAPI route scaffolding, SQLAlchemy model creation, and Pydantic schema definitions. Tasks that would have taken 2–3 hours took 20–30 minutes.

Where the tools hit limits: **agent loop debugging**. When the planning loop entered unexpected states — the agent calling the wrong tool in a retry sequence, or memory state becoming inconsistent — AI coding tools couldn't diagnose it reliably. That required reading actual LangSmith execution traces and reasoning through the state machine manually. The AI is a force multiplier on velocity; debugging agentic behavior is still a human job.

One structural change: because implementation came fast, I spent more time on **interfaces and contracts first** — defining tool input/output schemas before writing implementations. That inversion made the codebase more modular and made adding new tools much cleaner.

---

## 05 · Getting Started

### Prerequisites

- Python 3.12
- Docker
- AWS CLI (for cloud deployment)

### Run locally

```bash
git clone https://github.com/BaselAtiyire/hrms-agent.git
cd hrms-agent

# Create virtual environment
python -m venv .venv
source .venv/bin/activate       # Mac/Linux
# .venv\Scripts\activate        # Windows

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Add your ANTHROPIC_API_KEY to .env

# Run
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
# All other config uses defaults for local development
# See .env.example for full variable list
```

### AWS deployment (Terraform)

```bash
cd infra/
cp prod.tfvars.example prod.tfvars
terraform init
terraform apply -var-file="prod.tfvars"

# Then push Docker image — CI/CD handles the rest on every git push
```

See `DEPLOYMENT.md` for the full step-by-step guide.

---

## 06 · Demo

**Live:** [hrms.basilatiyire.com](https://hrms.basilatiyire.com)

### Hire a new employee

```
Agent prompt: "Hire Sarah Connor as DevOps in IT"

Agent executes:
  1. create_employee(name="Sarah Connor", role="DevOps", dept="IT")
  2. generate_onboarding_tasks(employee_id=...)
  3. create_ticket(type="IT_PROVISIONING", assignee=...)

Returns: confirmation with employee ID, task count, ticket reference
```

### Proactive alert check (no prompt needed)

On load, the agent automatically surfaces stale tickets open more than 7 days and leave requests pending more than 3 days — before the user types anything.

### Leave approval

HR Admin or Manager selects a pending leave request and approves or rejects with one click. The action is validated against the user's role, written to the audit log, and the table updates in real time.

---

## 07 · Testing & Error Handling

### Failure modes addressed

- **Tool call failure mid-workflow** — 3-retry logic. On third failure, the agent halts the dependent step, logs the failure with the specific error, and surfaces a clear message rather than silently continuing.
- **Ambiguous instructions** — the agent asks a targeted clarifying question rather than hallucinating a decision. Tested with intentionally underspecified prompts.
- **Container restart during workflow** — all state lives on EFS. I killed the Fargate task mid-execution and confirmed the agent resumed from the last persisted state.
- **Invalid leave approval** — state guards prevent approving an already-approved request; role checks block unauthorized users before the write happens.
- **Audit completeness** — every write action is captured in a structured JSON line with timestamp, actor, and details. No write succeeds silently.

### What I didn't fully solve

Concurrent workflow conflicts. The single-replica, SQLite design is safe in the current deployment, but if two users trigger agent workflows simultaneously, execution is sequential and one user waits. I'd address this in v2 with an async task queue.

---

## 08 · Future Improvements

**01 — Async task queue for concurrent workflows**
Replace synchronous execution with Celery + Redis so multiple workflows run in parallel. This unlocks multi-user production deployments and removes the single-replica constraint.

**02 — Live integrations — Workday, Okta, ServiceNow**
The current tool registry operates on local SQLite. The next step is live API integrations so the agent acts on real enterprise systems. Same agent, same tool interface — just real data on the other side.

**03 — Multi-agent architecture with specialized subagents**
Break the monolithic agent into specialized subagents: IT provisioning, HRIS operations, communications. An orchestrator delegates to each. Simpler agents are more reliable and easier to test in isolation.

**04 — RAG over HR policy documents**
Embed the company's onboarding playbooks and HR policies so the agent can validate workflow steps against current policy and answer policy questions without hardcoded rules.

**05 — PostgreSQL on RDS for multi-replica support**
SQLite on EFS was the right call for v1 cost optimization. PostgreSQL unlocks horizontal Fargate scaling and removes the single-replica constraint entirely.

---

## 09 · Links

| | |
|---|---|
| Live demo | [https://hrms.basilatiyire.com](https://hrms.basilatiyire.com) |
| Repository | [github.com/BaselAtiyire/hrms-agent](https://github.com/BaselAtiyire/hrms-agent) |
| Video walkthrough | [loom.com/share/37ae9b646ffe4f02b8ace85ed858e413](https://www.loom.com/share/37ae9b646ffe4f02b8ace85ed858e413) |

---

## 10 · Third-Party Libraries & Acknowledgments

| Library | Purpose |
|---|---|
| Anthropic Python SDK | Claude API client |
| Streamlit | Frontend dashboard framework |
| FastAPI | Async Python web framework |
| FastMCP | Model Context Protocol server implementation |
| SQLAlchemy | ORM and database abstraction |
| Pydantic | Data validation and schema enforcement |
| LangSmith | LLM observability and tracing (Langchain, Inc.) |
| Terraform | Infrastructure as code (HashiCorp) |
| Docker | Containerization |

No proprietary code, trade secrets, or confidential information from any employer is included. All credentials use placeholder values in `.env.example`. No live API keys appear anywhere in the repository.

 · Basel Atiyire · April 2026*
