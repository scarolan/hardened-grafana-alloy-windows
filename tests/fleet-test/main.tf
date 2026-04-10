###############################################################################
# Fleet Management smoke test — one Linux VM + one Windows VM, each running
# the bare-minimum fleet-config.alloy to verify Fleet Management check-in.
#
# Usage:
#   source ../../.env && terraform init && terraform apply
#
# Teardown:
#   terraform destroy
###############################################################################

terraform {
  required_version = ">= 1.5"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
  zone    = var.zone
}

# ---------------------------------------------------------------------------
# Variables
# ---------------------------------------------------------------------------
variable "project_id" {
  description = "GCP project ID"
  type        = string
  default     = "solutions-engineering-248511"
}

variable "region" {
  type    = string
  default = "us-central1"
}

variable "zone" {
  type    = string
  default = "us-central1-a"
}

variable "gcloud_rw_api_key" {
  description = "Grafana Cloud API key with metrics:write, logs:write, fleet:write"
  type        = string
  sensitive   = true
}

variable "fleet_url" {
  description = "Fleet Management URL"
  type        = string
  default     = "https://fleet-management-prod-008.grafana.net"
}

variable "fleet_username" {
  description = "Fleet Management instance ID (basic_auth username)"
  type        = string
  default     = "860585"
}

variable "prometheus_url" {
  description = "Prometheus remote write URL"
  type        = string
  default     = "https://prometheus-prod-13-prod-us-east-0.grafana.net/api/prom/push"
}

variable "prometheus_username" {
  description = "Prometheus remote write username"
  type        = string
  default     = "1432853"
}

variable "loki_url" {
  description = "Loki push URL"
  type        = string
  default     = "https://logs-prod-006.grafana.net/loki/api/v1/push"
}

variable "loki_username" {
  description = "Loki push username"
  type        = string
  default     = "815417"
}

# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------
resource "google_compute_network" "fleet_test" {
  name                    = "fleet-test"
  auto_create_subnetworks = true
}

resource "google_compute_firewall" "allow_ssh" {
  name    = "fleet-test-allow-ssh"
  network = google_compute_network.fleet_test.name

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["fleet-test"]
}

resource "google_compute_firewall" "allow_rdp" {
  name    = "fleet-test-allow-rdp"
  network = google_compute_network.fleet_test.name

  allow {
    protocol = "tcp"
    ports    = ["3389"]
  }

  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["fleet-test"]
}

# Alloy UI — useful for debugging
resource "google_compute_firewall" "allow_alloy_ui" {
  name    = "fleet-test-allow-alloy-ui"
  network = google_compute_network.fleet_test.name

  allow {
    protocol = "tcp"
    ports    = ["12345"]
  }

  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["fleet-test"]
}

# ---------------------------------------------------------------------------
# Linux VM (Ubuntu 22.04)
# ---------------------------------------------------------------------------
resource "google_compute_instance" "linux" {
  name         = "fleet-test-linux"
  machine_type = "e2-small"
  tags         = ["fleet-test"]

  boot_disk {
    initialize_params {
      image = "ubuntu-os-cloud/ubuntu-2204-lts"
      size  = 20
    }
  }

  network_interface {
    network = google_compute_network.fleet_test.name
    access_config {}
  }

  metadata = {
    ssh-keys = "testrunner:${file(pathexpand("~/.ssh/id_rsa.pub"))}"
  }

  metadata_startup_script = templatefile("${path.module}/startup-linux.sh.tftpl", {
    gcloud_rw_api_key   = var.gcloud_rw_api_key
    fleet_url           = var.fleet_url
    fleet_username      = var.fleet_username
    prometheus_url      = var.prometheus_url
    prometheus_username = var.prometheus_username
    loki_url            = var.loki_url
    loki_username       = var.loki_username
  })

  labels = {
    purpose = "fleet-test"
  }

  timeouts {
    create = "10m"
  }
}

# ---------------------------------------------------------------------------
# Windows VM (Server 2022)
# ---------------------------------------------------------------------------
resource "google_compute_instance" "windows" {
  name         = "fleet-test-windows"
  machine_type = "n2-standard-2"
  tags         = ["fleet-test"]

  boot_disk {
    initialize_params {
      image = "projects/windows-cloud/global/images/family/windows-2022"
      size  = 50
      type  = "pd-ssd"
    }
  }

  network_interface {
    network = google_compute_network.fleet_test.name
    access_config {}
  }

  metadata = {
    windows-startup-script-ps1 = templatefile("${path.module}/startup-windows.ps1.tftpl", {
      gcloud_rw_api_key   = var.gcloud_rw_api_key
      fleet_url           = var.fleet_url
      fleet_username      = var.fleet_username
      prometheus_url      = var.prometheus_url
      prometheus_username = var.prometheus_username
      loki_url            = var.loki_url
      loki_username       = var.loki_username
    })
  }

  labels = {
    purpose = "fleet-test"
  }

  timeouts {
    create = "15m"
  }
}

# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------
output "linux_ip" {
  value = google_compute_instance.linux.network_interface[0].access_config[0].nat_ip
}

output "windows_ip" {
  value = google_compute_instance.windows.network_interface[0].access_config[0].nat_ip
}

output "linux_name" {
  value = google_compute_instance.linux.name
}

output "windows_name" {
  value = google_compute_instance.windows.name
}
