# State in the hand-made bucket (Terraform cannot keep its state in a bucket it
# creates). Private, versioned, SSE-S3, TLS-only; see docs/deployment.md.
# use_lockfile: S3-native locking (Terraform >= 1.10), no DynamoDB table.
terraform {
  backend "s3" {
    bucket       = "elevator-tfstate-150911080650"
    key          = "serverless-tier/terraform.tfstate"
    region       = "eu-north-1"
    encrypt      = true
    use_lockfile = true
  }
}
