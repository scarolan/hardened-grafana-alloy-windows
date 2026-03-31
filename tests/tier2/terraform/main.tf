###############################################################################
# Tier 2: Windows Server VM provisioning for real-exporter testing
#
# Provisions Windows Server VMs on GCP with:
#   - Grafana Alloy installed as a Windows service
#   - The hardened config deployed
#   - A local Prometheus instance for test assertions
#
# Tested images:
#   - Windows Server 2019 Datacenter
#   - Windows Server 2022 Datacenter
#   - Windows Server 2025 Datacenter
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

variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region"
  type        = string
  default     = "us-central1"
}

variable "zone" {
  description = "GCP zone"
  type        = string
  default     = "us-central1-a"
}

variable "machine_type" {
  description = "GCP machine type for test VMs"
  type        = string
  default     = "n2-standard-2"
}

# ---------------------------------------------------------------------------
# Windows Server images
# ---------------------------------------------------------------------------
locals {
  windows_images = {
    "win2019" = {
      image_family  = "windows-2019"
      image_project = "windows-cloud"
      display_name  = "Windows Server 2019"
    }
    "win2022" = {
      image_family  = "windows-2022"
      image_project = "windows-cloud"
      display_name  = "Windows Server 2022"
    }
    "win2025" = {
      image_family  = "windows-2025"
      image_project = "windows-cloud"
      display_name  = "Windows Server 2025"
    }
  }
}

# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------
resource "google_compute_network" "test" {
  name                    = "alloy-windows-test"
  auto_create_subnetworks = true
}

resource "google_compute_firewall" "allow_rdp" {
  name    = "alloy-windows-test-rdp"
  network = google_compute_network.test.name

  allow {
    protocol = "tcp"
    ports    = ["3389"]
  }

  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["alloy-test"]
}

resource "google_compute_firewall" "allow_winrm" {
  name    = "alloy-windows-test-winrm"
  network = google_compute_network.test.name

  allow {
    protocol = "tcp"
    ports    = ["5985", "5986"]
  }

  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["alloy-test"]
}

resource "google_compute_firewall" "allow_prometheus" {
  name    = "alloy-windows-test-prometheus"
  network = google_compute_network.test.name

  allow {
    protocol = "tcp"
    ports    = ["9090"]
  }

  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["alloy-test"]
}

# ---------------------------------------------------------------------------
# Windows Server VMs
# ---------------------------------------------------------------------------
resource "google_compute_instance" "windows" {
  for_each = local.windows_images

  name         = "alloy-test-${each.key}"
  machine_type = var.machine_type
  tags         = ["alloy-test"]

  boot_disk {
    initialize_params {
      image = "projects/${each.value.image_project}/global/images/family/${each.value.image_family}"
      size  = 50
      type  = "pd-ssd"
    }
  }

  network_interface {
    network = google_compute_network.test.name
    access_config {} # ephemeral public IP
  }

  # PowerShell startup script: install Alloy + Prometheus, deploy config
  metadata = {
    windows-startup-script-ps1 = templatefile("${path.module}/startup.ps1.tftpl", {
      config_alloy = file("${path.module}/../../../config.alloy")
    })
  }

  labels = {
    purpose = "alloy-tier2-test"
    os      = each.key
  }

  # Allow time for Windows to boot and run startup script
  timeouts {
    create = "15m"
  }
}

# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------
output "vm_ips" {
  description = "Map of VM name → external IP"
  value = {
    for k, v in google_compute_instance.windows : k => v.network_interface[0].access_config[0].nat_ip
  }
}

output "vm_details" {
  description = "VM details for test runner"
  value = {
    for k, v in google_compute_instance.windows : k => {
      ip           = v.network_interface[0].access_config[0].nat_ip
      display_name = local.windows_images[k].display_name
      zone         = var.zone
    }
  }
}
