terraform {
  backend "gcs" {
    bucket = "conquest-tfstate"
    prefix = "conquest/state"
  }
}
