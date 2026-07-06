##############################################################################
# Receipt — outputs
##############################################################################

output "ec2_public_ip" {
  description = "Elastic IP of the fiscal-core EC2 host."
  value       = aws_eip.app.public_ip
}

output "ec2_public_dns" {
  description = "Public DNS name of the fiscal-core EC2 host."
  value       = aws_instance.app.public_dns
}

output "rds_endpoint" {
  description = "RDS PostgreSQL endpoint (host:port)."
  value       = try(aws_db_instance.main[0].endpoint, "postgres-in-container")
}

output "rds_address" {
  description = "RDS PostgreSQL hostname (without port)."
  value       = try(aws_db_instance.main[0].address, "postgres-in-container")
}

output "ecr_repository_url" {
  description = "ECR repository URL for the fiscal-core image (docker push target)."
  value       = aws_ecr_repository.fiscal_core.repository_url
}

output "secret_arn" {
  description = "ARN of the receipt/merchant-secrets Secrets Manager secret."
  value       = aws_secretsmanager_secret.merchant_secrets.arn
}

output "kms_key_id" {
  description = "KMS key id used for secrets + storage encryption."
  value       = aws_kms_key.main.key_id
}

output "archive_bucket" {
  description = "S3 bucket holding signed-invoice / QR archives."
  value       = aws_s3_bucket.archive.bucket
}
