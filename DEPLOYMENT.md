# HRMS — Production Deployment Guide

## Architecture

```
Internet
   │
   ▼
Application Load Balancer  (public subnets, us-east-1a/b)
   │  HTTP :80
   ▼
ECS Fargate Task  (private subnet, 1 replica)
   │  FastAPI + Uvicorn :8000
   │
   ├──► EFS Volume /data/hrms.db   (SQLite, encrypted, persistent)
   ├──► ECR Image  hrms-prod:sha
   ├──► Secrets Manager  OPENAI_API_KEY
   └──► CloudWatch Logs  /ecs/hrms-prod
```

> **Why single replica?** SQLite supports one writer at a time.
> One Fargate task + EFS is safe, simple, and sufficient for internal HR tooling.
> Migrate to RDS PostgreSQL if you ever need horizontal scaling.

---

## Prerequisites

| Tool | Version |
|---|---|
| AWS CLI | ≥ 2.x |
| Terraform | ≥ 1.7 |
| Docker | ≥ 24 |
| Python | 3.12 |

---

## First-time Setup

### 1. Bootstrap Terraform remote state

Create the S3 bucket and DynamoDB lock table **before** running `terraform init`:

```bash
aws s3 mb s3://hrms-tfstate-prod --region us-east-1
aws s3api put-bucket-versioning \
  --bucket hrms-tfstate-prod \
  --versioning-configuration Status=Enabled

aws dynamodb create-table \
  --table-name hrms-tfstate-lock \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --region us-east-1
```

### 2. Provision infrastructure

```bash
cd infra/

# Copy and fill in real values (never commit prod.tfvars)
cp prod.tfvars.example prod.tfvars
vi prod.tfvars

terraform init
terraform plan -var-file=prod.tfvars
terraform apply -var-file=prod.tfvars
```

Terraform will output:
- `alb_dns_name` — point your domain's CNAME here
- `ecr_repository_url` — used by CI/CD
- `ecs_cluster_name` / `ecs_service_name`

### 3. Configure GitHub Secrets

In your repo → Settings → Secrets and variables → Actions:

| Secret | Value |
|---|---|
| `AWS_ACCESS_KEY_ID` | IAM user with ECS/ECR/Secrets permissions |
| `AWS_SECRET_ACCESS_KEY` | ↑ |
| `AWS_REGION` | `us-east-1` |
| `ECR_REPOSITORY` | `hrms-prod` |
| `ECS_CLUSTER` | `hrms-prod-cluster` |
| `ECS_SERVICE` | `hrms-prod-service` |
| `ECS_TASK_FAMILY` | `hrms-prod` |

### 4. Create a GitHub Environment

Go to Settings → Environments → New environment → name it `production`.
Enable **Required reviewers** so every deploy to main needs manual approval.

---

## CI/CD Flow

```
git push main
      │
      ▼
[test]  ruff lint + pytest
      │
      ▼
[build-and-push]  docker build → ECR  (tagged with Git SHA + timestamp)
      │           trivy vulnerability scan (blocks on CRITICAL/HIGH)
      ▼
[deploy]  ← requires manual approval in GitHub Environments
      │   aws ecs render-task-definition (swap image tag)
      │   aws ecs deploy (wait for stability)
      ▼
ECS Fargate rolling update (old task stays until new task is healthy)
```

---

## Local Development

```bash
cp .env.example .env
# fill in OPENAI_API_KEY

docker compose up --build
# API available at http://localhost:8000
# Docs at http://localhost:8000/docs
```

---

## Health Check

```bash
curl http://<alb_dns_name>/health
# → {"status":"ok","env":"prod"}
```

---

## Viewing Logs

```bash
aws logs tail /ecs/hrms-prod --follow --region us-east-1
```

---

## Rollback

```bash
# List recent task definition revisions
aws ecs list-task-definitions --family-prefix hrms-prod --sort DESC

# Force the service back to a previous revision
aws ecs update-service \
  --cluster hrms-prod-cluster \
  --service hrms-prod-service \
  --task-definition hrms-prod:<PREVIOUS_REVISION>
```

---

## Cost Estimate (us-east-1, single replica)

| Service | Est. monthly |
|---|---|
| ECS Fargate (0.25 vCPU / 0.5 GB) | ~$9 |
| ALB | ~$17 |
| EFS (< 1 GB) | ~$0.30 |
| NAT Gateway | ~$35 |
| ECR storage | ~$0.10 |
| Secrets Manager | ~$0.40 |
| **Total** | **~$62/month** |

> NAT Gateway dominates cost. For dev/staging, you can use public subnets
> with `assign_public_ip = true` and remove the NAT to save ~$35/month.

---

## Security Notes

- Container runs as non-root user (UID 1001)
- EFS volume is encrypted at rest
- ECS tasks run in private subnets — no public IP
- `OPENAI_API_KEY` stored in Secrets Manager, never in env files or image
- ECR image scanning enabled on every push
- Trivy blocks deploys with CRITICAL/HIGH CVEs
