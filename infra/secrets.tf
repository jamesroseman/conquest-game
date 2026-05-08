resource "google_secret_manager_secret" "google_oauth_client_id" {
  project   = var.project_id
  secret_id = "google-oauth-client-id"

  replication {
    auto {}
  }

  depends_on = [google_project_service.enabled]
}

resource "google_secret_manager_secret" "jwt_signing_key" {
  project   = var.project_id
  secret_id = "jwt-signing-key"

  replication {
    auto {}
  }

  depends_on = [google_project_service.enabled]
}

# Bind runtime SA read access on each secret.
resource "google_secret_manager_secret_iam_member" "runtime_oauth" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.google_oauth_client_id.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_secret_manager_secret_iam_member" "runtime_jwt" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.jwt_signing_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}
