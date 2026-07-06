##############################################################################
# Receipt — Core Infrastructure (LEAN sandbox stack, eu-central-1)
#
# Multi-tenant fiscal aggregator (BSP) for MoR EIMS. This stack hosts the
# dockerized fiscal-core service plus its backing Postgres, secrets, KMS key,
# signed-invoice/QR archive bucket and an ECR repo for the image.
#
# Deliberately SEPARATE from the Delta SPMU stack:
#   * own VPC (10.20.0.0/16, vs Delta's 10.0.0.0/16)
#   * 'receipt' name prefix on every resource
# so the two can coexist in one AWS account without collisions.
#
# Cost posture: t3.small EC2, db.t3.micro single-AZ RDS, 1 NAT-free public
# subnet design (EC2 in a public subnet with a public IP; RDS not publicly
# accessible). No NAT gateway, no load balancer, no CloudFront — sandbox only.
##############################################################################

# Random suffix for globally-unique names (S3 bucket, etc.)
resource "random_id" "suffix" {
  byte_length = 4
}

# Availability zones available in the region (use the first two).
data "aws_availability_zones" "available" {
  state = "available"
}

# Latest Canonical Ubuntu 22.04 LTS AMI (used when var.ami_id is empty).
data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

locals {
  name_prefix = "${var.project_name}-${var.environment}"
  ami_id      = var.ami_id != "" ? var.ami_id : data.aws_ami.ubuntu.id
  azs         = slice(data.aws_availability_zones.available.names, 0, 2)
}

##############################################################################
# VPC + networking (2 public subnets across 2 AZs; RDS needs >= 2 AZ subnets)
##############################################################################

resource "aws_vpc" "main" {
  cidr_block           = "10.20.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name = "${local.name_prefix}-vpc"
  }
}

resource "aws_subnet" "public_a" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.20.1.0/24"
  availability_zone       = local.azs[0]
  map_public_ip_on_launch = true

  tags = {
    Name = "${local.name_prefix}-public-a"
  }
}

resource "aws_subnet" "public_b" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.20.2.0/24"
  availability_zone       = local.azs[1]
  map_public_ip_on_launch = true

  tags = {
    Name = "${local.name_prefix}-public-b"
  }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "${local.name_prefix}-igw"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = {
    Name = "${local.name_prefix}-public-rt"
  }
}

resource "aws_route_table_association" "public_a" {
  subnet_id      = aws_subnet.public_a.id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "public_b" {
  subnet_id      = aws_subnet.public_b.id
  route_table_id = aws_route_table.public.id
}

##############################################################################
# Security groups
#   app: 80/443 from anywhere, 22 from allowed_ssh_cidr
#   db : Postgres (5432) only from the app SG
##############################################################################

resource "aws_security_group" "app" {
  name        = "${local.name_prefix}-app-sg"
  description = "fiscal-core host: HTTP/HTTPS from anywhere, SSH from allowed CIDR"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "SSH (restricted)"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.allowed_ssh_cidr]
  }

  egress {
    description = "All outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${local.name_prefix}-app-sg"
  }
}

resource "aws_security_group" "db" {
  name        = "${local.name_prefix}-db-sg"
  description = "RDS Postgres: 5432 only from the app SG"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "PostgreSQL from app SG"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.app.id]
  }

  egress {
    description = "All outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${local.name_prefix}-db-sg"
  }
}

##############################################################################
# KMS key (encrypts the Secrets Manager secret; also usable for SSE elsewhere)
##############################################################################

resource "aws_kms_key" "main" {
  description             = "${local.name_prefix} key for Secrets Manager + app encryption"
  deletion_window_in_days = 7
  enable_key_rotation     = true

  tags = {
    Name = "${local.name_prefix}-kms"
  }
}

resource "aws_kms_alias" "main" {
  name          = "alias/${local.name_prefix}"
  target_key_id = aws_kms_key.main.key_id
}

##############################################################################
# Secrets Manager — per-merchant secrets blob
# Placeholder value only; real client_secret/api_key/private_key/certificate
# are injected out-of-band (CLI / console), never committed to Terraform state.
# Secret id matches what fiscal-core's AwsSecretsManager backend resolves.
##############################################################################

resource "aws_secretsmanager_secret" "merchant_secrets" {
  name        = "${var.project_name}/merchant-secrets"
  description = "Per-merchant EIMS credentials (client_secret, api_key, private key, certificate). Real values added out-of-band."
  kms_key_id  = aws_kms_key.main.arn

  # Sandbox: allow quick teardown/recreate without the 7-30 day recovery wait.
  recovery_window_in_days = 0

  tags = {
    Name = "${local.name_prefix}-merchant-secrets"
  }
}

resource "aws_secretsmanager_secret_version" "merchant_secrets_placeholder" {
  secret_id = aws_secretsmanager_secret.merchant_secrets.id
  secret_string = jsonencode({
    _comment = "PLACEHOLDER. Replace out-of-band per merchant. Do not commit real values."
  })

  # The real value is managed out-of-band; don't let Terraform clobber it.
  lifecycle {
    ignore_changes = [secret_string]
  }
}

##############################################################################
# S3 — signed-invoice / QR archive (versioned + encrypted, private)
##############################################################################

resource "aws_s3_bucket" "archive" {
  bucket = "${var.project_name}-archive-${random_id.suffix.hex}"

  tags = {
    Name = "${local.name_prefix}-archive"
  }
}

resource "aws_s3_bucket_versioning" "archive" {
  bucket = aws_s3_bucket.archive.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "archive" {
  bucket = aws_s3_bucket.archive.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.main.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "archive" {
  bucket = aws_s3_bucket.archive.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

##############################################################################
# ECR — repository for the fiscal-core image
##############################################################################

resource "aws_ecr_repository" "fiscal_core" {
  name                 = "${var.project_name}/fiscal-core"
  image_tag_mutability = "MUTABLE"
  force_delete         = true # sandbox convenience

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.main.arn
  }

  tags = {
    Name = "${local.name_prefix}-ecr"
  }
}

# Keep only the most recent images to control storage cost.
resource "aws_ecr_lifecycle_policy" "fiscal_core" {
  repository = aws_ecr_repository.fiscal_core.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep last 10 images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 10
        }
        action = { type = "expire" }
      }
    ]
  })
}

##############################################################################
# IAM — instance role so the EC2 host can read secrets, use the KMS key,
# access the archive bucket and pull from ECR (least-privilege, scoped to this
# stack's resources). SSM core policy attached for keyless shell access.
##############################################################################

data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ec2" {
  name               = "${local.name_prefix}-ec2-role"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json

  tags = {
    Name = "${local.name_prefix}-ec2-role"
  }
}

data "aws_iam_policy_document" "ec2_inline" {
  # Read the merchant secrets
  statement {
    sid       = "SecretsRead"
    actions   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
    resources = [aws_secretsmanager_secret.merchant_secrets.arn]
  }

  # Use the KMS key (decrypt secrets, encrypt/decrypt archive objects)
  statement {
    sid = "KmsUse"
    actions = [
      "kms:Decrypt",
      "kms:Encrypt",
      "kms:GenerateDataKey",
      "kms:DescribeKey",
    ]
    resources = [aws_kms_key.main.arn]
  }

  # Read/write the signed-invoice/QR archive
  statement {
    sid       = "ArchiveBucket"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
    resources = [aws_s3_bucket.archive.arn, "${aws_s3_bucket.archive.arn}/*"]
  }

  # Pull the image from ECR
  statement {
    sid       = "EcrPull"
    actions   = ["ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage", "ecr:BatchCheckLayerAvailability"]
    resources = [aws_ecr_repository.fiscal_core.arn]
  }

  statement {
    sid       = "EcrAuth"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "ec2_inline" {
  name   = "${local.name_prefix}-ec2-policy"
  role   = aws_iam_role.ec2.id
  policy = data.aws_iam_policy_document.ec2_inline.json
}

# Keyless SSM Session Manager access (so SSH isn't strictly required).
resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "ec2" {
  name = "${local.name_prefix}-ec2-profile"
  role = aws_iam_role.ec2.name
}

##############################################################################
# SSH key pair (optional — only created when ssh_public_key is provided)
##############################################################################

resource "aws_key_pair" "main" {
  count      = var.ssh_public_key != "" ? 1 : 0
  key_name   = "${local.name_prefix}-key"
  public_key = var.ssh_public_key

  tags = {
    Name = "${local.name_prefix}-key"
  }
}

##############################################################################
# EC2 — dockerized fiscal-core host
# user_data installs Docker + the Compose plugin. If fiscal_core_image is set,
# it logs into ECR and runs the container wired to RDS + AWS Secrets Manager.
##############################################################################

locals {
  db_url = var.create_rds ? "postgresql+psycopg://${aws_db_instance.main[0].username}:${var.db_password}@${aws_db_instance.main[0].address}:${aws_db_instance.main[0].port}/${aws_db_instance.main[0].db_name}" : "postgresql+psycopg://receipt:${var.db_password}@db:5432/receipt"

  user_data = <<-EOF
#!/bin/bash
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y ca-certificates curl gnupg awscli

# --- Install Docker Engine + Compose plugin (official repo) ---
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

systemctl enable docker
systemctl start docker
usermod -aG docker ubuntu || true

# --- Service environment for the fiscal-core container ---
mkdir -p /etc/receipt
cat > /etc/receipt/fiscal-core.env <<'ENVEOF'
ENV=${var.environment}
SECRETS_BACKEND=aws
AWS_REGION=${var.aws_region}
LOG_LEVEL=INFO
DATABASE_URL=${local.db_url}
ENVEOF
chmod 600 /etc/receipt/fiscal-core.env

IMAGE="${var.fiscal_core_image}"
if [ -n "$IMAGE" ]; then
  # Authenticate to ECR.
  ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
  aws ecr get-login-password --region ${var.aws_region} \
    | docker login --username AWS --password-stdin "$ACCOUNT_ID.dkr.ecr.${var.aws_region}.amazonaws.com"
  docker pull "$IMAGE" || echo "WARN: pull failed (image may not exist yet)"

  mkdir -p /opt/receipt
  cat > /opt/receipt/docker-compose.yml <<COMPOSEEOF
services:
%{ if !var.create_rds ~}
  db:
    image: postgres:16
    restart: unless-stopped
    environment:
      POSTGRES_USER: receipt
      POSTGRES_PASSWORD: ${var.db_password}
      POSTGRES_DB: receipt
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U receipt"]
      interval: 5s
      timeout: 3s
      retries: 20
%{ endif ~}
  app:
    image: ${var.fiscal_core_image}
    restart: unless-stopped
    ports:
      - "${var.app_port}:${var.app_port}"
      - "80:${var.app_port}"
    env_file:
      - /etc/receipt/fiscal-core.env
    volumes:
      - /opt/receipt/secrets:/app/secrets
%{ if !var.create_rds ~}
    depends_on:
      db:
        condition: service_healthy
volumes:
  pgdata:
%{ endif ~}
COMPOSEEOF
  mkdir -p /opt/receipt/secrets
  docker compose -f /opt/receipt/docker-compose.yml up -d || echo "WARN: compose up failed - provisioning will retry"
fi

echo "receipt fiscal-core host bootstrap complete" > /home/ubuntu/setup-complete.txt
EOF
}

resource "aws_instance" "app" {
  ami                    = local.ami_id
  instance_type          = var.instance_type
  subnet_id              = aws_subnet.public_a.id
  vpc_security_group_ids = [aws_security_group.app.id]
  iam_instance_profile   = aws_iam_instance_profile.ec2.name
  key_name               = var.ssh_public_key != "" ? aws_key_pair.main[0].key_name : null
  user_data              = local.user_data

  root_block_device {
    volume_size = 30
    volume_type = "gp3"
    encrypted   = true
  }

  metadata_options {
    http_tokens   = "required" # IMDSv2 only
    http_endpoint = "enabled"
  }

  tags = {
    Name = "${local.name_prefix}-app"
  }
}

resource "aws_eip" "app" {
  instance = aws_instance.app.id
  domain   = "vpc"

  tags = {
    Name = "${local.name_prefix}-eip"
  }
}

##############################################################################
# RDS PostgreSQL 16 (db.t3.micro, single-AZ, encrypted, 7-day backups)
##############################################################################

resource "aws_db_subnet_group" "main" {
  name       = "${local.name_prefix}-db-subnet"
  subnet_ids = [aws_subnet.public_a.id, aws_subnet.public_b.id]

  tags = {
    Name = "${local.name_prefix}-db-subnet"
  }
}

resource "aws_db_instance" "main" {
  count          = var.create_rds ? 1 : 0
  identifier     = "${local.name_prefix}-db"
  engine         = "postgres"
  engine_version = var.db_engine_version
  instance_class = var.db_instance_class

  allocated_storage     = var.db_allocated_storage
  max_allocated_storage = 100
  storage_type          = "gp3"
  storage_encrypted     = true
  kms_key_id            = aws_kms_key.main.arn

  db_name  = var.project_name
  username = "receipt"
  password = var.db_password

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.db.id]
  publicly_accessible    = false
  multi_az               = false # sandbox

  backup_retention_period = var.db_backup_retention_period
  backup_window           = "23:00-23:30" # ~02:00 EAT, off-peak
  maintenance_window      = "sun:00:00-sun:01:00"
  copy_tags_to_snapshot   = true

  skip_final_snapshot       = false
  final_snapshot_identifier = "${local.name_prefix}-final-${random_id.suffix.hex}"
  deletion_protection       = false # sandbox; flip to true for prod

  tags = {
    Name = "${local.name_prefix}-db"
  }
}
