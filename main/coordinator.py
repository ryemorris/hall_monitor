#!/usr/bin/env python3
"""
Hall Monitor Coordinator

Orchestrates the workflow:
1. Check Quay repositories for stale services (no recent images)
2. Update Tekton SC files in those stale service repositories
3. Trigger component builds for unremedied stale services (optional)
"""

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

import yaml

# Import from our local modules
from main.utils.quay_image_checker import load_repo_config, search_by_date_range
from main.utils.update_tekton_sc import TektonUpdater
from main.utils.trigger_component_builds import ComponentBuildTrigger


def load_config(config_path: str) -> dict:
    """Load configuration from YAML file."""
    try:
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        print(f"Error: Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)
    except yaml.YAMLError as e:
        print(f"Error: Invalid YAML in config file: {e}", file=sys.stderr)
        sys.exit(1)


def check_stale_services(repos: dict, days: int, services: Optional[List[str]] = None) -> List[str]:
    """
    Check Quay repositories for stale services.
    Returns list of service names without recent images.
    """
    print("=" * 80)
    print("STEP 1: Checking Quay repositories for stale services")
    print("=" * 80)

    # Calculate date range
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    start_date_str = start_date.strftime('%Y%m%d')
    end_date_str = end_date.strftime('%Y%m%d')

    print(f"Searching for images from last {days} days ({start_date_str} to {end_date_str})\n")

    # Run the search with report mode
    found, stale_services = search_by_date_range(
        repos,
        start_date_str,
        end_date_str,
        services,
        report_mode=True
    )

    return stale_services


def map_service_to_repo(service_name: str) -> str:
    """
    Map service name to git repository name.
    Some services share the same git repository.
    """
    # Special cases where multiple services live in one repo
    service_to_repo = {
        # All notifications services live in notifications-backend
        'notifications-aggregator': 'notifications-backend',
        'notifications-connector-email': 'notifications-backend',
        'notifications-engine-sc': 'notifications-backend',
        'notifications-recipients-resolver': 'notifications-backend',
    }

    return service_to_repo.get(service_name, service_name)


def get_unremedied_services(stale_services: List[str], updater: TektonUpdater) -> List[str]:
    """
    Get list of stale services that were not remedied by Tekton updates.

    Args:
        stale_services: Original list of stale services
        updater: TektonUpdater instance after running updates

    Returns:
        List of service names that remain unremedied
    """
    # Get repos that had no changes from the updater
    unremedied_repos = {repo_name for repo_name, _ in updater.no_changes_log}

    # Find services that map to those repos
    unremedied_services = []
    for service in stale_services:
        repo = map_service_to_repo(service)
        if repo in unremedied_repos:
            unremedied_services.append(service)

    return unremedied_services


def trigger_component_builds(
    unremedied_services: List[str],
    repos: dict,
    dry_run: bool = False
) -> None:
    """
    Trigger Konflux component builds for unremedied stale services.

    Args:
        unremedied_services: List of service names that remain stale
        repos: Repository configuration (service -> Quay URL mappings)
        dry_run: If True, preview what would be done without making changes
    """
    if not unremedied_services:
        print("\n" + "=" * 80)
        print("No unremedied services to trigger builds for!")
        print("=" * 80)
        return

    print("\n" + "=" * 80)
    print(f"STEP 3: Triggering component builds for {len(unremedied_services)} unremedied service(s)")
    print("=" * 80)
    if dry_run:
        print("Mode: DRY RUN")
    print()

    # Create trigger instance
    trigger = ComponentBuildTrigger(
        repos_config=repos,
        dry_run=dry_run
    )

    # Check if oc is available
    if not trigger.check_oc_available():
        print("Warning: 'oc' command not found or not configured", file=sys.stderr)
        print("Skipping component build triggers. Please ensure you have the OpenShift CLI installed and are logged in.", file=sys.stderr)
        return

    # Trigger builds
    results = trigger.trigger_builds_for_services(unremedied_services)

    # Print summary
    trigger.print_summary(results)


def update_stale_repos(
    stale_services: List[str],
    git_repos_dir: str,
    branch: str = "security-compliance",
    dry_run: bool = False
) -> Optional[TektonUpdater]:
    """
    Update Tekton SC files in stale service repositories.

    Returns:
        TektonUpdater instance (so we can access no_changes_log), or None if no services to update
    """
    if not stale_services:
        print("\n" + "=" * 80)
        print("No stale services to update!")
        print("=" * 80)
        return None

    print("\n" + "=" * 80)
    print(f"STEP 2: Updating Tekton SC files in {len(stale_services)} stale service(s)")
    print("=" * 80)
    print(f"Target directory: {git_repos_dir}")
    print(f"Branch: {branch}")
    if dry_run:
        print("Mode: DRY RUN")
    print()

    # Map service names to git repository names
    # Some services may share the same repo (e.g., notifications)
    repo_names = sorted(set([map_service_to_repo(svc) for svc in stale_services]))

    if len(repo_names) < len(stale_services):
        print(f"Note: {len(stale_services)} services map to {len(repo_names)} repositories (some share repos)\n")

    # Create updater instance
    updater = TektonUpdater(
        parent_dir=git_repos_dir,
        branch=branch,
        specific_repos=repo_names,
        dry_run=dry_run
    )

    # Run the update process
    updater.run()

    return updater


def main():
    parser = argparse.ArgumentParser(
        description='Coordinate Quay image checking and Tekton SC file updates',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full workflow (check + update + trigger builds)
  python -m main.coordinator

  # Use specific config file
  python -m main.coordinator --config custom_config.yaml

  # Dry run to preview changes
  python -m main.coordinator --dry-run

  # Process specific services only
  python -m main.coordinator --services chrome-service advisor-backend

  # Skip the update step, only check for stale services
  python -m main.coordinator --check-only

  # Skip build triggering (run Steps 1 and 2 only)
  python -m main.coordinator --skip-build-trigger
        """
    )

    parser.add_argument(
        '--config',
        default='config.yaml',
        help='Path to configuration file (default: config.yaml)'
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without making any modifications (overrides config)'
    )

    parser.add_argument(
        '--services',
        nargs='+',
        help='Specific service(s) to process (overrides config)'
    )

    parser.add_argument(
        '--check-only',
        action='store_true',
        help='Only check for stale services, do not update repositories'
    )

    parser.add_argument(
        '--skip-build-trigger',
        action='store_true',
        help='Skip triggering component builds for unremedied services (Step 3)'
    )

    args = parser.parse_args()

    # Load configuration
    config = load_config(args.config)

    # Override config with command line arguments
    dry_run = args.dry_run or config.get('dry_run', False)
    services = args.services or config.get('services') or None
    skip_build_trigger = args.skip_build_trigger or config.get('skip_build_trigger', False)

    # Load repository configuration
    repos_config_path = config.get('repos_config', 'repos.json')
    repos = load_repo_config(repos_config_path)

    if not repos:
        print("Error: No repositories found in config file", file=sys.stderr)
        sys.exit(1)

    print(f"Loaded {len(repos)} repository configuration(s)")

    # Step 1: Check for stale services
    stale_services = check_stale_services(
        repos,
        config.get('quick_search_days', 14),
        services
    )

    # If check-only mode, stop here
    if args.check_only:
        print("\n" + "=" * 80)
        print("Check-only mode: Skipping repository updates")
        print("=" * 80)
        sys.exit(0)

    # Step 2: Update stale repositories
    updater = None
    if stale_services:
        git_repos_dir = config.get('git_repos_dir')
        if not git_repos_dir:
            print("\nError: git_repos_dir not configured in config file", file=sys.stderr)
            sys.exit(1)

        updater = update_stale_repos(
            stale_services,
            git_repos_dir,
            config.get('branch', 'security-compliance'),
            dry_run
        )

    # Step 3: Trigger builds for unremedied services (if enabled)
    if not skip_build_trigger and updater and updater.no_changes_log:
        unremedied_services = get_unremedied_services(stale_services, updater)
        if unremedied_services:
            trigger_component_builds(unremedied_services, repos, dry_run)

    print("\n" + "=" * 80)
    print("WORKFLOW COMPLETE")
    print("=" * 80)


if __name__ == '__main__':
    main()
