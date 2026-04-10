terraform {
  required_version = ">= 1.7"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
  backend "s3" {
    bucket         = "hrms-tfstate-prod"
    key            = "hrms/prod/terraform.tfstate"
    region         = "us-east-1"
    encrypt        = true
    dynamodb_table = "hrms-tfstate-lock"
  }
}

provider "aws" { region = var.aws_region }

variable "aws_region"        { default = "us-east-1" }
variable "app_name"          { default = "hrms" }
variable "environment"       { default = "prod" }
variable "container_port"    { default = 8501 }
variable "cpu"               { default = 512 }
variable "memory"            { default = 1024 }
variable "desired_count"     { default = 1 }
variable "image_tag"         { default = "latest" }
variable "openai_api_key"    { sensitive = true }
variable "anthropic_api_key" { sensitive = true }
variable "langsmith_api_key" { sensitive = true }
variable "vpc_cidr"          { default = "10.0.0.0/16" }

locals {
  name_prefix = "${var.app_name}-${var.environment}"
  common_tags = {
    Project     = var.app_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_ecr_repository" "hrms" {
  name                 = local.name_prefix
  image_tag_mutability = "MUTABLE"
  image_scanning_configuration {
    scan_on_push = true
  }
  tags = local.common_tags
}

resource "aws_ecr_lifecycle_policy" "hrms" {
  repository = aws_ecr_repository.hrms.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last 10 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = { type = "expire" }
    }]
  })
}

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true
  tags = merge(local.common_tags, { Name = "${local.name_prefix}-vpc" })
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = merge(local.common_tags, { Name = "${local.name_prefix}-igw" })
}

data "aws_availability_zones" "available" { state = "available" }

resource "aws_subnet" "public" {
  count                   = 2
  vpc_id                  = aws_vpc.main.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, count.index)
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = true
  tags = merge(local.common_tags, { Name = "${local.name_prefix}-public-${count.index}" })
}

resource "aws_subnet" "private" {
  count             = 2
  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, count.index + 10)
  availability_zone = data.aws_availability_zones.available.names[count.index]
  tags = merge(local.common_tags, { Name = "${local.name_prefix}-private-${count.index}" })
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }
  tags = merge(local.common_tags, { Name = "${local.name_prefix}-public-rt" })
}

resource "aws_route_table_association" "public" {
  count          = 2
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_security_group" "alb" {
  name   = "${local.name_prefix}-alb-sg"
  vpc_id = aws_vpc.main.id
  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = local.common_tags
}

resource "aws_security_group" "ecs_task" {
  name   = "${local.name_prefix}-ecs-sg"
  vpc_id = aws_vpc.main.id
  ingress {
    from_port       = var.container_port
    to_port         = var.container_port
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = local.common_tags
}

resource "aws_security_group" "efs" {
  name   = "${local.name_prefix}-efs-sg"
  vpc_id = aws_vpc.main.id
  ingress {
    from_port       = 2049
    to_port         = 2049
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs_task.id]
  }
  tags = local.common_tags
}

resource "aws_efs_file_system" "hrms_data" {
  creation_token   = "${local.name_prefix}-sqlite"
  performance_mode = "generalPurpose"
  throughput_mode  = "bursting"
  encrypted        = true
  lifecycle_policy {
    transition_to_ia = "AFTER_30_DAYS"
  }
  tags = merge(local.common_tags, { Name = "${local.name_prefix}-efs" })
}

resource "aws_efs_mount_target" "hrms_data" {
  count           = 2
  file_system_id  = aws_efs_file_system.hrms_data.id
  subnet_id       = aws_subnet.private[count.index].id
  security_groups = [aws_security_group.efs.id]
}

resource "aws_efs_access_point" "hrms_data" {
  file_system_id = aws_efs_file_system.hrms_data.id
  posix_user {
    uid = 1001
    gid = 1001
  }
  root_directory {
    path = "/data"
    creation_info {
      owner_uid   = 1001
      owner_gid   = 1001
      permissions = "755"
    }
  }
  tags = local.common_tags
}

resource "aws_secretsmanager_secret" "openai_key" {
  name                    = "${local.name_prefix}/openai-api-key"
  recovery_window_in_days = 7
  tags                    = local.common_tags
}

resource "aws_secretsmanager_secret_version" "openai_key" {
  secret_id     = aws_secretsmanager_secret.openai_key.id
  secret_string = var.openai_api_key
}

resource "aws_iam_role" "ecs_task_execution" {
  name = "${local.name_prefix}-task-execution-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
    }]
  })
  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution" {
  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "ecs_secrets" {
  name = "${local.name_prefix}-secrets-policy"
  role = aws_iam_role.ecs_task_execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = [aws_secretsmanager_secret.openai_key.arn]
    }]
  })
}

resource "aws_iam_role" "ecs_task" {
  name = "${local.name_prefix}-task-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
    }]
  })
  tags = local.common_tags
}

resource "aws_iam_role_policy" "ecs_task_logs" {
  name = "${local.name_prefix}-task-logs-policy"
  role = aws_iam_role.ecs_task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
      Resource = ["${aws_cloudwatch_log_group.hrms.arn}:*"]
    }]
  })
}

resource "aws_cloudwatch_log_group" "hrms" {
  name              = "/ecs/${local.name_prefix}"
  retention_in_days = 30
  tags              = local.common_tags
}

resource "aws_lb" "hrms" {
  name               = "${local.name_prefix}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id
  tags               = local.common_tags
}

resource "aws_lb_target_group" "hrms" {
  name        = "${local.name_prefix}-tg"
  port        = var.container_port
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip"
  health_check {
    enabled             = true
    path                = "/_stcore/health"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 10
    interval            = 30
    matcher             = "200"
  }
  tags = local.common_tags
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.hrms.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.hrms.arn
  }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.hrms.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = "arn:aws:acm:us-east-1:768504743291:certificate/31d07d71-5dd5-447c-b7f9-a215ae3799ac"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.hrms.arn
  }
}

resource "aws_lb_listener_rule" "http_redirect" {
  listener_arn = aws_lb_listener.http.arn
  priority     = 1
  action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
  condition {
    path_pattern {
      values = ["/*"]
    }
  }
}

resource "aws_ecs_cluster" "hrms" {
  name = "${local.name_prefix}-cluster"
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
  tags = local.common_tags
}

resource "aws_ecs_cluster_capacity_providers" "hrms" {
  cluster_name       = aws_ecs_cluster.hrms.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]
  default_capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
  }
}

resource "aws_ecs_task_definition" "hrms" {
  family                   = local.name_prefix
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.cpu
  memory                   = var.memory
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([{
    name      = local.name_prefix
    image     = "${aws_ecr_repository.hrms.repository_url}:${var.image_tag}"
    essential = true
    portMappings = [{ containerPort = var.container_port, protocol = "tcp" }]
    environment = [
      { name = "APP_ENV",            value = var.environment },
      { name = "DATABASE_URL",       value = "sqlite:////data/hrms.db" },
      { name = "LOG_LEVEL",          value = "info" },
      { name = "ANTHROPIC_API_KEY",  value = var.anthropic_api_key },
      { name = "LANGSMITH_API_KEY",  value = var.langsmith_api_key },
      { name = "LANGCHAIN_PROJECT",  value = "hrms-agent-prod" }
    ]
    secrets = [{ name = "OPENAI_API_KEY", valueFrom = aws_secretsmanager_secret.openai_key.arn }]
    mountPoints = [{ sourceVolume = "hrms-data", containerPath = "/data", readOnly = false }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.hrms.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "ecs"
      }
    }
  }])

  volume {
    name = "hrms-data"
    efs_volume_configuration {
      file_system_id     = aws_efs_file_system.hrms_data.id
      transit_encryption = "ENABLED"
      authorization_config {
        access_point_id = aws_efs_access_point.hrms_data.id
        iam             = "ENABLED"
      }
    }
  }
  tags = local.common_tags
}

resource "aws_ecs_service" "hrms" {
  name                              = "${local.name_prefix}-service"
  cluster                           = aws_ecs_cluster.hrms.id
  task_definition                   = aws_ecs_task_definition.hrms.arn
  desired_count                     = var.desired_count
  launch_type                       = "FARGATE"
  platform_version                  = "LATEST"
  health_check_grace_period_seconds = 120
  force_new_deployment              = true
  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.ecs_task.id]
    assign_public_ip = true
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.hrms.arn
    container_name   = local.name_prefix
    container_port   = var.container_port
  }
  depends_on = [aws_lb_listener.http, aws_efs_mount_target.hrms_data]
  tags = local.common_tags
}

output "alb_dns_name"         { value = aws_lb.hrms.dns_name }
output "ecr_repository_url"   { value = aws_ecr_repository.hrms.repository_url }
output "ecs_cluster_name"     { value = aws_ecs_cluster.hrms.name }
output "ecs_service_name"     { value = aws_ecs_service.hrms.name }
output "cloudwatch_log_group" { value = aws_cloudwatch_log_group.hrms.name }
