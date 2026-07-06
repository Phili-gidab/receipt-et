##############################################################################
# Receipt — Terraform / AWS provider configuration
#
# Mirrors the Delta SPMU conventions (hashicorp/aws ~> 5.0, eu-central-1,
# default_tags) but targets a SEPARATE, lean sandbox-stage stack. All resources
# carry a 'receipt' name prefix and live in their own VPC so they never collide
# with Delta's infrastructure even inside the same AWS account.
#
# Uses the named AWS CLI profile "delta" by default (the credentials profile the
# operator already has configured locally / in CI).
##############################################################################

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "aws" {
  region  = var.aws_region
  profile = var.aws_profile

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}
