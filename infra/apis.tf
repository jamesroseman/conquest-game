locals {
  required_apis = [
    "run.googleapis.com",
    "firestore.googleapis.com",
    "secretmanager.googleapis.com",
    "artifactregistry.googleapis.com",
    "iamcredentials.googleapis.com",
    "iam.googleapis.com",
    "sts.googleapis.com",
  ]
}

resource "google_project_service" "enabled" {
  for_each           = toset(local.required_apis)
  project            = var.project_id
  service            = each.key
  disable_on_destroy = false
}
