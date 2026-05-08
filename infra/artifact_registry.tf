resource "google_artifact_registry_repository" "conquest" {
  project       = var.project_id
  location      = var.region
  repository_id = "conquest"
  description   = "Conquest container images"
  format        = "DOCKER"

  depends_on = [google_project_service.enabled]
}
