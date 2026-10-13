variable "region" {
  type    = string
  default = "eu-north-1"
}

variable "account_id" {
  description = "The only account this configuration may touch (provider allowed_account_ids)."
  type        = string
  default     = "150911080650"
}

variable "image_tag" {
  description = <<-EOT
    Image tag the functions are CREATED from (the bootstrap push). After that,
    CI moves the image on every merge and Terraform ignores it.
  EOT
  type        = string
}

variable "schedules_enabled" {
  description = <<-EOT
    The cutover switch. Turns the two schedules on, and with them the silence
    alarms' notifications, so the time before cutover sends no alarm emails.
  EOT
  type        = bool
  default     = false
}

variable "alarm_email" {
  description = "Where alarms are emailed. The subscription must be confirmed from the email AWS sends."
  type        = string
  default     = ""
}

variable "reserve_orchestrator_concurrency" {
  description = <<-EOT
    Reserve one concurrent execution for the orchestrator. Off by default: a
    new account's quota (10, all of which must stay unreserved) refuses it.
    Overlapping runs are safe anyway (separate sandboxes).
  EOT
  type        = bool
  default     = false
}

# Pre-existing resources, referenced only (import is a separate backlog task).
variable "instance_role_name" {
  type    = string
  default = "elevator-ssm-role"
}

variable "deploy_role_name" {
  type    = string
  default = "github-actions-deploy"
}

variable "bedrock_policy_name" {
  type    = string
  default = "ElevatorBedrockInvokeNova"
}
