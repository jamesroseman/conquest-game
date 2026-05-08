resource "google_firestore_database" "default" {
  project     = var.project_id
  name        = "(default)"
  location_id = var.region
  type        = "FIRESTORE_NATIVE"

  depends_on = [google_project_service.enabled]
}

# Composite indexes called out in CLAUDE.md § Indexes.
resource "google_firestore_index" "events_by_sequence" {
  project    = var.project_id
  database   = google_firestore_database.default.name
  collection = "events"

  fields {
    field_path = "sequence"
    order      = "ASCENDING"
  }
}

resource "google_firestore_index" "country_states_by_owner" {
  project    = var.project_id
  database   = google_firestore_database.default.name
  collection = "countryStates"

  fields {
    field_path = "ownerPlayerId"
    order      = "ASCENDING"
  }
}

resource "google_firestore_index" "games_by_status_updated" {
  project    = var.project_id
  database   = google_firestore_database.default.name
  collection = "games"

  fields {
    field_path = "status"
    order      = "ASCENDING"
  }
  fields {
    field_path = "updatedAt"
    order      = "DESCENDING"
  }
}
