# Receipt — Infrastructure (Terraform, AWS)

Lean **sandbox-stage** stack for the Receipt MoR EIMS fiscal aggregator (BSP),
in **eu-central-1**, using the AWS CLI/SDK credentials profile **`delta`**.

It is deliberately separate from the Delta SPMU stack: its own VPC
(`10.20.0.0/16`) and a `receipt-` name prefix on every resource, so both can
live in the same AWS account without collisions.

## What this provisions

| Resource | Notes |
|---|---|
| VPC + 2 public subnets (2 AZ) + IGW + route table | RDS needs ≥ 2 AZ subnets; EC2 lives in the public subnet (no NAT → cheaper). |
| Security groups | app SG: 80/443 from anywhere, 22 from `allowed_ssh_cidr`; db SG: 5432 **only** from the app SG. |
| EC2 `t3.small` (Ubuntu 22.04) + Elastic IP | `user_data` installs Docker + the Compose plugin; runs the dockerized fiscal-core when `fiscal_core_image` is set. IMDSv2 enforced. |
| RDS PostgreSQL 16 `db.t3.micro` | single-AZ (sandbox), `storage_encrypted=true` (KMS), `backup_retention_period=7`, `skip_final_snapshot=false`, not publicly accessible. |
| KMS key (+ alias) | encrypts Secrets Manager, RDS storage, S3 archive and ECR. Rotation enabled. |
| Secrets Manager `receipt/merchant-secrets` | **placeholder** value only; real per-merchant credentials are added out-of-band (`lifecycle.ignore_changes` keeps Terraform from clobbering them). |
| S3 archive bucket | versioned + KMS-encrypted + fully private. Holds signed invoices / QR PNGs. |
| ECR repo `receipt/fiscal-core` | scan-on-push, KMS-encrypted, keep-last-10 lifecycle policy. |
| IAM instance role | least-privilege: read the secret, use the KMS key, R/W the archive bucket, pull from ECR, plus SSM Session Manager (keyless shell). |

### Outputs
`ec2_public_ip`, `ec2_public_dns`, `rds_endpoint`, `rds_address`,
`ecr_repository_url`, `secret_arn`, `kms_key_id`, `archive_bucket`.

## App wiring

`user_data` writes `/etc/receipt/fiscal-core.env` with exactly what the
fiscal-core service reads (`app/config.py`):

```
ENV=sandbox
SECRETS_BACKEND=aws
AWS_REGION=eu-central-1
LOG_LEVEL=INFO
DATABASE_URL=postgresql+psycopg://receipt:<db_password>@<rds-address>:5432/receipt
```

With `SECRETS_BACKEND=aws`, the service resolves merchant credentials from
Secrets Manager via the attached instance role — no static AWS keys on the host.

## Usage

> Requires Terraform ≥ 1.5 and an AWS profile named `delta`
> (`aws configure --profile delta`). `init`/`validate` below need **no** AWS
> credentials.

### 1. Init (no backend, no creds)

```bash
cd infra
terraform init -backend=false
terraform validate
```

### 2. Plan (needs AWS creds — review carefully)

```bash
cp terraform.tfvars.example sandbox.tfvars   # then edit; sandbox.tfvars is git-ignored
terraform init                               # real init (local state backend)
terraform plan -var-file=sandbox.tfvars
```

### 3. Apply — **manual, gated step**

`terraform apply` is **not** run by any automation here. It creates billable AWS
resources. Run it yourself, only after reviewing the plan:

```bash
terraform apply -var-file=sandbox.tfvars
```

### 4. Deploy the image (after apply)

```bash
# Build + push fiscal-core to ECR, then either set fiscal_core_image and
# re-apply, or pull/run manually on the host.
aws ecr get-login-password --region eu-central-1 --profile delta \
  | docker login --username AWS --password-stdin "$(terraform output -raw ecr_repository_url | cut -d/ -f1)"
docker build -t "$(terraform output -raw ecr_repository_url):latest" ../fiscal-core
docker push "$(terraform output -raw ecr_repository_url):latest"
```

### 5. Populate the secret (out-of-band)

```bash
aws secretsmanager put-secret-value --profile delta --region eu-central-1 \
  --secret-id "$(terraform output -raw secret_arn)" \
  --secret-string file://merchant-secrets.json   # never commit this file
```

## Cost note

Sandbox-sized and intentionally cheap, but **not free** — it runs continuously:

- EC2 `t3.small` (~US$15/mo on-demand) + 30 GB gp3 EBS + 1 Elastic IP
  (free while attached to a running instance).
- RDS `db.t3.micro` single-AZ (~US$13/mo) + 20 GB gp3 + 7-day backups.
- KMS key (~US$1/mo) + Secrets Manager secret (~US$0.40/mo) + small S3/ECR
  storage + data transfer.

Rough idle baseline ~**US$30–35/month**. No NAT gateway, load balancer, or
CloudFront are provisioned (deliberately, to keep cost down). `terraform destroy`
tears everything down; RDS takes a final snapshot (`skip_final_snapshot=false`)
which incurs minor snapshot storage until you delete it.

## Security posture (sandbox)

- Default `allowed_ssh_cidr = 0.0.0.0/0` is for first-boot convenience — **lock
  it to your IP/32** in your tfvars. SSM Session Manager works without SSH.
- `deletion_protection` and `multi_az` are off for sandbox; flip both on for prod.
- The Secrets Manager secret ships with a placeholder; never put real
  credentials into Terraform variables or state.
