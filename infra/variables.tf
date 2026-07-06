##############################################################################
# Receipt — input variables
#
# Lean sandbox-stage defaults. Anything sensitive (db_password) must be supplied
# at plan/apply time via -var or a (git-ignored) *.tfvars file — never committed.
##############################################################################

variable "project_name" {
  description = "Project name used for resource naming and tagging (also the 'receipt' name prefix)."
  type        = string
  default     = "receipt"
}

variable "environment" {
  description = "Deployment environment (sandbox, staging, prod). Sandbox by default."
  type        = string
  default     = "sandbox"
}

variable "aws_region" {
  description = "AWS region for all resources."
  type        = string
  default     = "eu-central-1"
}

variable "aws_profile" {
  description = "Named AWS CLI/SDK credentials profile used by the provider."
  type        = string
  default     = "delta"
}

variable "db_password" {
  description = "RDS PostgreSQL master password. Supply via -var or a git-ignored tfvars file; never commit it."
  type        = string
  sensitive   = true
}

variable "instance_type" {
  description = "EC2 instance type for the fiscal-core host."
  type        = string
  default     = "t3.small"
}

variable "db_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t3.micro"
}

variable "allowed_ssh_cidr" {
  description = "CIDR allowed to reach the EC2 host on port 22 (SSH). Lock this to your own IP/32 — do NOT leave it as 0.0.0.0/0 in any real deployment."
  type        = string
  default     = "0.0.0.0/0"
}

variable "domain" {
  description = "Primary domain for the deployment (used in tags / future TLS + DNS wiring)."
  type        = string
  default     = "receipt.com.et"
}

variable "ssh_public_key" {
  description = "SSH public key material for EC2 access. Leave empty to skip creating a key pair (instance is still reachable via SSM if a role is attached out-of-band)."
  type        = string
  default     = ""
}

variable "ami_id" {
  description = "Ubuntu 22.04 LTS (jammy) AMI id for the target region. Empty = auto-resolve the latest Canonical Ubuntu 22.04 AMI via a data source."
  type        = string
  default     = ""
}

variable "db_engine_version" {
  description = "PostgreSQL major.minor engine version for RDS."
  type        = string
  default     = "16"
}

variable "db_allocated_storage" {
  description = "Initial RDS storage in GB (kept small for sandbox cost)."
  type        = number
  default     = 20
}

variable "db_backup_retention_period" {
  description = "RDS automated backup retention in days. Spec: 7. Set 0 only for a throwaway DB."
  type        = number
  default     = 7
}

variable "fiscal_core_image" {
  description = "Container image the EC2 host runs (e.g. <ecr-url>:tag). Empty = user_data sets up Docker only and leaves the image to be deployed out-of-band."
  type        = string
  default     = ""
}

variable "app_port" {
  description = "Port the dockerized fiscal-core (uvicorn) listens on inside the host."
  type        = number
  default     = 8000
}

variable "create_rds" {
  description = "Create RDS PostgreSQL. false = run Postgres as a container next to the app (free-plan accounts that block RDS)."
  type        = bool
  default     = true
}
