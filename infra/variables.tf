variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "region" {
  description = "Default region for regional resources."
  type        = string
  default     = "us-central1"
}

variable "service_name" {
  description = "Cloud Run service name."
  type        = string
  default     = "conquest"
}

variable "github_owner" {
  description = "GitHub org/owner that hosts the repo (for Workload Identity Federation)."
  type        = string
  default     = "jamesroseman"
}

variable "github_repo" {
  description = "GitHub repository name (without owner) for WIF."
  type        = string
  default     = "conquest-game"
}

variable "image" {
  description = "Container image to deploy. Set by the deploy workflow per release."
  type        = string
  default     = "us-central1-docker.pkg.dev/REPLACE_ME/conquest/conquest:latest"
}
