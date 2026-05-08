# Infrastructure

Every GCP resource for Conquest is declared here. Apply from a clean checkout:

```bash
cd infra
terraform init
terraform apply -var="project_id=conquest-prod" -var="region=us-central1"
```

State lives in a versioned GCS bucket (`conquest-tfstate`); see `backend.tf`. Bootstrap that
bucket once by hand, then move state under it with `terraform init -migrate-state`.

## What's owned by Terraform

| Resource                                       | Purpose                                    |
|------------------------------------------------|--------------------------------------------|
| `google_project_service`                       | Enable required APIs                       |
| `google_firestore_database`                    | Native-mode Firestore (single region)      |
| `google_artifact_registry_repository`          | Conquest container images                  |
| `google_cloud_run_v2_service.conquest`         | Conquest API on Cloud Run                  |
| `google_service_account.runtime`               | Runtime SA with least-privilege roles      |
| `google_service_account.deployer`              | Deploy SA used by GitHub Actions WIF       |
| `google_iam_workload_identity_pool*`           | WIF pool + GitHub provider                 |
| `google_secret_manager_secret*`                | `google-oauth-client-id`, `jwt-signing-key`|
| `google_project_iam_member`                    | All bindings                               |

No resources are clicked in the console.
