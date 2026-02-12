# Hall Monitor

Automated workflow for monitoring Quay.io repositories and updating Tekton SC pipeline configurations.

## Overview

Hall Monitor coordinates two operations:
1. **Check Quay repositories** for stale services (no recent container images)
2. **Update Tekton SC files** in those stale service repositories

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
│   ├── coordinator.py           # Main orchestration script
│   └── utils/
│       ├── quay_image_checker.py  # Quay repository monitoring
│       ├── update_tekton_sc.py    # Tekton pipeline updater
│       └── parse_repos.py         # Utility to generate repos.json
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
# Full workflow (check Quay + update repos)
python -m main.coordinator

# Dry run (preview changes)
python -m main.coordinator --dry-run

# Check only (don't update repos)
python -m main.coordinator --check-only

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

### Step 3: Report Unremedied Stale Services
After the update process, the tool logs any stale services where no changes were made. This is critical because it indicates the stale status persists and the Tekton SC update didn't resolve the underlying issue. The log shows:
- Services where the target branch doesn't exist
- Services with no SC files in the `.tekton` directory
- Services where SC files already use the `main` branch (most common case)

## Command Line Options

```
--config CONFIG        Path to config file (default: config.yaml)
--dry-run              Preview changes without making modifications
--services SERVICE...  Process only specific services
--check-only           Only check for stale services, skip updates
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

## Examples

**Daily stale service check and update:**
```bash
python -m main.coordinator
```

**Test workflow before running:**
```bash
python -m main.coordinator --dry-run --check-only
```

**Emergency update specific services:**
```bash
python -m main.coordinator --services critical-service1 critical-service2 --dry-run
# Review output, then run without --dry-run
python -m main.coordinator --services critical-service1 critical-service2
```

## Output and Logging

When stale services are processed but not remedied by the update, you'll see a warning report:

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

These services require further investigation to determine why they're stale despite having correct Tekton configurations.

## Image Pattern

The tool searches for images with this tag pattern:
- `sc-{YYYYMMDD}-{7-char-sha}` (e.g., `sc-20260208-abc1234`)
