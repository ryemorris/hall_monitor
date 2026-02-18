# Hall Monitor

Automated workflow for monitoring Quay.io repositories and updating Tekton SC pipeline configurations.

## Overview

Hall Monitor coordinates three operations:
1. **Check Quay repositories** for stale services (no recent container images)
2. **Update Tekton SC files** in those stale service repositories
3. **Trigger component builds** for unremedied stale services (optional)

## Installation

```bash
# Clone the repository
git clone <repository-url>
cd hall_monitor

# Install dependencies
pip install -r requirements.txt

# Configure
cp config.yaml.example config.yaml
# Edit config.yaml with your settings
```

## Project Structure

```
hall_monitor/
├── main/
│   ├── coordinator.py              # Main orchestration script
│   └── utils/
│       ├── quay_image_checker.py      # Quay repository monitoring
│       ├── update_tekton_sc.py        # Tekton pipeline updater
│       ├── trigger_component_builds.py # Konflux component build trigger
│       └── parse_repos.py             # Utility to generate repos.json
├── config.yaml.example          # Configuration template
├── repos.json                   # Service to Quay repository mappings
├── requirements.txt             # Python dependencies
└── README.md                    # This file
```

## Quick Start

### 1. Configure

Edit `config.yaml` with your settings:

```yaml
repos_config: repos.json
git_repos_dir: /path/to/your/git/repos  # Directory containing your service repos
branch: security-compliance
quick_search_days: 14
services: []  # Leave empty to check all services
dry_run: false
```

### 2. Run

```bash
# Full workflow (check Quay + update repos + trigger builds)
python -m main.coordinator

# Dry run (preview changes)
python -m main.coordinator --dry-run

# Check only (don't update repos or trigger builds)
python -m main.coordinator --check-only

# Skip build triggering (Steps 1 and 2 only)
python -m main.coordinator --skip-build-trigger

# Process specific services
python -m main.coordinator --services chrome-service advisor-backend
```

## What It Does

### Step 1: Check Quay Repositories
Searches each service's Quay repository for `sc-{YYYYMMDD}-{sha}` images from the last N days (default: 14).

Generates a report showing:
- ✓ Services with recent images
- ✗ Services without recent images (stale)
- ⚠ Services with errors

### Step 2: Update Stale Repositories
For each stale service:
- Checks out the configured branch (default: `security-compliance`)
- Updates `.tekton/*-sc*.yaml` files to use `main` branch instead of version tags
- Commits and pushes changes

The tool tracks any stale services where no changes were made, which indicates the stale status persists:
- Services where the target branch doesn't exist
- Services with no SC files in the `.tekton` directory
- Services where SC files already use the `main` branch (most common case)

### Step 3: Trigger Component Builds (Optional)
For unremedied stale services (those where Step 2 made no changes):
- Parses `repos.json` to extract tenant namespace and component name from Quay URLs
- Uses `oc` command to annotate components with `build.appstudio.openshift.io/request=trigger-pac-build`
- Triggers post-merge PAC builds to generate fresh container images

This step can be skipped with `--skip-build-trigger` or by setting `skip_build_trigger: true` in config.

## Command Line Options

```
--config CONFIG           Path to config file (default: config.yaml)
--dry-run                 Preview changes without making modifications
--services SERVICE...     Process only specific services
--check-only              Only check for stale services, skip updates and build triggers
--skip-build-trigger      Skip triggering component builds (Steps 1 and 2 only)
```

## Configuration File

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `repos_config` | string | repos.json | Path to service→Quay repo mappings |
| `git_repos_dir` | string | required | Directory containing git repositories |
| `branch` | string | security-compliance | Git branch to update |
| `quick_search_days` | int | 14 | Days to look back for recent images |
| `services` | list | [] | Specific services to process (empty = all) |
| `dry_run` | bool | false | Preview mode (no changes made) |
| `skip_build_trigger` | bool | false | Skip component build triggering (Step 3) |

## Individual Tools

The coordinator uses these individual tools, which can also be run standalone:

### Quay Image Checker

Check Quay repositories for stale services:

```bash
python -m main.utils.quay_image_checker --config repos.json --quick --output-stale stale_services.txt

# With specific services
python -m main.utils.quay_image_checker --config repos.json --quick --services chrome-service advisor-backend
```

### Tekton Updater

Update Tekton SC pipeline files in repositories:

```bash
python -m main.utils.update_tekton_sc /path/to/repos --repos service1 service2 --dry-run

# Update all repos in directory
python -m main.utils.update_tekton_sc /path/to/repos --branch security-compliance
```

### Component Build Trigger

Trigger Konflux component builds by annotating components:

```bash
python -m main.utils.trigger_component_builds --repos-config repos.json --services service1 service2

# Dry run
python -m main.utils.trigger_component_builds --repos-config repos.json --services service1 --dry-run

# Read services from file
python -m main.utils.trigger_component_builds --repos-config repos.json --services-file stale_services.txt
```

**Requirements:** Requires `oc` CLI to be installed and authenticated to the Konflux cluster.

## Setup

### Repository Mappings

Create `repos.json` mapping service names to Quay repositories:

```json
{
  "service-name": "quay.io/namespace/path/to/repo",
  "another-service": "quay.io/namespace/another-repo"
}
```

You can generate this from the Konflux service references markdown:

```bash
# Using config.yaml (set markdown_path in config)
python -m main.utils.parse_repos --config config.yaml

# Using command line arguments
python -m main.utils.parse_repos --markdown /path/to/Konflux-service-references.md --output repos.json

# Specify custom config file
python -m main.utils.parse_repos --config custom_config.yaml
```

### Git Repository Setup

Your local git repositories must have:
- An `upstream` remote configured
- The target branch existing on the remote

## Requirements

- Python 3.7+
- PyYAML: `pip install pyyaml`
- Git repositories with `upstream` remote configured
- Quay repositories must be public
- OpenShift CLI (`oc`) - required only for Step 3 (component build triggering)
  - Must be authenticated to the Konflux cluster

## Examples

**Daily stale service check, update, and trigger builds:**
```bash
python -m main.coordinator
```

**Test workflow before running:**
```bash
python -m main.coordinator --dry-run
```

**Only check for stale services (no updates or build triggers):**
```bash
python -m main.coordinator --check-only
```

**Update Tekton files but skip build triggering:**
```bash
python -m main.coordinator --skip-build-trigger
```

**Emergency update specific services:**
```bash
python -m main.coordinator --services critical-service1 critical-service2 --dry-run
# Review output, then run without --dry-run
python -m main.coordinator --services critical-service1 critical-service2
```

## Output and Logging

When stale services are processed but not remedied by the update (Step 2), you'll see a warning report:

```
============================================================
⚠ WARNING: STALE SERVICES WITH NO CHANGES
============================================================
The following stale services were processed but had no
changes made to their Tekton SC files. This indicates the
stale status was NOT remedied by the update:
------------------------------------------------------------
  service-name-1
    Reason: SC files already use 'main' branch
  service-name-2
    Reason: No -sc files found in .tekton directory
  service-name-3
    Reason: Branch 'security-compliance' not found on remote
============================================================
Total: 3 service(s) require investigation
============================================================
```

If Step 3 is enabled (default), these unremedied services will then have their Konflux components annotated to trigger fresh builds:

```
============================================================
STEP 3: Triggering component builds for 3 unremedied service(s)
============================================================

Processing: service-name-1
  Quay URL: quay.io/redhat-services-prod/tenant/app/component-sc
  Namespace: tenant
  Component: component-sc
  ✓ Annotated: component-sc in tenant
...
============================================================
BUILD TRIGGER SUMMARY
============================================================

✓ Successfully triggered: 3
  - service-name-1
  - service-name-2
  - service-name-3
============================================================
```

## Image Pattern

The tool searches for images with this tag pattern:
- `sc-{YYYYMMDD}-{7-char-sha}` (e.g., `sc-20260208-abc1234`)
