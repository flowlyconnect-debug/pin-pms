terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

resource "aws_instance" "app" {
  ami                    = var.app_ami_id
  instance_type          = var.app_instance_type
  subnet_id              = var.public_subnet_id
  vpc_security_group_ids = [var.app_security_group_id]
  key_name               = var.ssh_key_name
  tags = {
    Name    = "pindora-pms-app"
    Service = "pindora-pms"
  }
}

resource "aws_db_instance" "postgres" {
  identifier             = "pindora-pms-db"
  allocated_storage      = 20
  engine                 = "postgres"
  engine_version         = "16.3"
  instance_class         = var.db_instance_class
  db_subnet_group_name   = var.db_subnet_group_name
  vpc_security_group_ids = [var.db_security_group_id]
  username               = var.db_username
  password               = var.db_password
  db_name                = var.db_name
  skip_final_snapshot    = true
}

resource "aws_s3_bucket" "backups" {
  bucket = var.backup_bucket_name
  tags = {
    Name    = "pindora-pms-backups"
    Service = "pindora-pms"
  }
}

resource "aws_route53_record" "app" {
  zone_id = var.route53_zone_id
  name    = var.app_fqdn
  type    = "A"
  ttl     = 300
  records = [aws_instance.app.public_ip]
}

variable "aws_region" { type = string }
variable "app_ami_id" { type = string }
variable "app_instance_type" { type = string, default = "t3.small" }
variable "public_subnet_id" { type = string }
variable "app_security_group_id" { type = string }
variable "ssh_key_name" { type = string }
variable "db_instance_class" { type = string, default = "db.t4g.micro" }
variable "db_subnet_group_name" { type = string }
variable "db_security_group_id" { type = string }
variable "db_username" { type = string }
variable "db_password" {
  type      = string
  sensitive = true
}
variable "db_name" { type = string, default = "pindora" }
variable "backup_bucket_name" { type = string }
variable "route53_zone_id" { type = string }
variable "app_fqdn" { type = string }
