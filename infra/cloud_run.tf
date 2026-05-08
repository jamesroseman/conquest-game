resource "google_cloud_run_v2_service" "conquest" {
  name     = var.service_name
  location = var.region
  project  = var.project_id

  template {
    service_account = google_service_account.runtime.email

    containers {
      image = var.image
      ports {
        container_port = 8080
      }
      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
      env {
        name  = "CONQUEST_DEV_LOGIN"
        value = "0"
      }
      env {
        name = "CONQUEST_GOOGLE_CLIENT_ID"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.google_oauth_client_id.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "CONQUEST_JWT_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.jwt_signing_key.secret_id
            version = "latest"
          }
        }
      }
    }
  }

  depends_on = [
    google_project_service.enabled,
    google_secret_manager_secret_iam_member.runtime_oauth,
    google_secret_manager_secret_iam_member.runtime_jwt,
  ]
}

# Public access for the GraphQL endpoint. Tighten with IAP / per-route auth later if needed.
resource "google_cloud_run_v2_service_iam_member" "public" {
  location = google_cloud_run_v2_service.conquest.location
  project  = var.project_id
  name     = google_cloud_run_v2_service.conquest.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

output "service_url" {
  value = google_cloud_run_v2_service.conquest.uri
}
