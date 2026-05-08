resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "github-pool"
  display_name              = "GitHub Actions"
  project                   = var.project_id

  depends_on = [google_project_service.enabled]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-provider"
  display_name                       = "GitHub OIDC"
  project                            = var.project_id

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
  }

  # Restrict to this exact repository.
  attribute_condition = "attribute.repository == \"${var.github_owner}/${var.github_repo}\""

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

# Allow the GitHub workflow to impersonate the deployer SA.
resource "google_service_account_iam_member" "deployer_wif_binding" {
  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_owner}/${var.github_repo}"
}

output "workload_identity_provider" {
  value       = google_iam_workload_identity_pool_provider.github.name
  description = "Pass to google-github-actions/auth as `workload_identity_provider`."
}

output "deployer_sa_email" {
  value       = google_service_account.deployer.email
  description = "Pass to google-github-actions/auth as `service_account`."
}
