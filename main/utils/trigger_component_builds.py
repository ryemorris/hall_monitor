#!/usr/bin/env python3
"""
Trigger Component Builds - Annotate Konflux components to trigger PAC builds

This module uses the `oc` command to annotate specific components in Konflux
tenant namespaces, triggering post-merge builds for stale services.
"""

import argparse
import json
import subprocess
import sys
from typing import List, Dict, Optional, Tuple


class ComponentBuildTrigger:
    """Manage triggering builds for Konflux components."""

    def __init__(self, repos_config: Dict[str, str], dry_run: bool = False):
        """
        Initialize the build trigger.

        Args:
            repos_config: Dictionary mapping service names to Quay repository URLs
            dry_run: If True, only show what would be done without making changes
        """
        self.repos_config = repos_config
        self.dry_run = dry_run
        self.annotation = "build.appstudio.openshift.io/request=trigger-pac-build"

    def check_oc_available(self) -> bool:
        """Check if oc command is available."""
        try:
            result = subprocess.run(
                ['oc', 'version'],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0
        except (subprocess.SubprocessError, FileNotFoundError):
            return False

    def parse_quay_url(self, quay_url: str) -> Optional[Tuple[str, str]]:
        """
        Parse Quay URL to extract tenant namespace and component name.

        URL format: quay.io/redhat-services-prod/{tenant}/{app}/{component}
        Or: quay.io/redhat-services-prod/{tenant}/{component}

        Args:
            quay_url: Quay repository URL from repos.json

        Returns:
            Tuple of (tenant_namespace, component_name) or None if parsing fails
        """
        try:
            # Remove 'quay.io/' prefix if present
            if quay_url.startswith('quay.io/'):
                quay_url = quay_url[8:]  # Remove 'quay.io/'

            # Split the path
            parts = quay_url.split('/')

            # Expected format: redhat-services-prod/{tenant}/{app}/{component}
            # Or: redhat-services-prod/{tenant}/{component}
            if len(parts) < 3:
                return None

            # Index 0: redhat-services-prod (registry namespace, ignore)
            # Index 1: Konflux tenant namespace
            # Index 2+: Last part is component name
            tenant_namespace = parts[1]
            component_name = parts[-1]  # Last part is always the component

            return tenant_namespace, component_name

        except Exception as e:
            print(f"  Error parsing Quay URL '{quay_url}': {e}", file=sys.stderr)
            return None

    def annotate_component(self, component_name: str, namespace: str) -> bool:
        """
        Annotate a component to trigger a PAC build.

        Args:
            component_name: Name of the component
            namespace: Namespace containing the component

        Returns:
            True if successful, False otherwise
        """
        if self.dry_run:
            print(f"  [DRY RUN] Would annotate: {component_name} in {namespace}")
            return True

        try:
            result = subprocess.run(
                ['oc', 'annotate', 'component', component_name, '-n', namespace,
                 self.annotation, '--overwrite'],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                print(f"  ✓ Annotated: {component_name} in {namespace}")
                return True
            else:
                print(f"  ✗ Failed to annotate {component_name}: {result.stderr.strip()}", file=sys.stderr)
                return False

        except subprocess.SubprocessError as e:
            print(f"  ✗ Error annotating {component_name}: {e}", file=sys.stderr)
            return False

    def trigger_builds_for_services(self, service_names: List[str]) -> Dict[str, str]:
        """
        Trigger builds for a list of services.

        Args:
            service_names: List of service names to trigger builds for

        Returns:
            Dictionary mapping service names to status:
            - "success": Component found and annotated
            - "not_found": Service not found in repos config
            - "parse_error": Failed to parse Quay URL
            - "error": Error during annotation
        """
        results = {}

        print("=" * 80)
        print(f"Triggering builds for {len(service_names)} service(s)")
        print("=" * 80)
        if self.dry_run:
            print("DRY RUN MODE - No annotations will be applied")
            print()

        for service_name in sorted(service_names):
            print(f"\nProcessing: {service_name}")

            # Look up service in repos config
            if service_name not in self.repos_config:
                print(f"  ✗ Service not found in repos.json")
                results[service_name] = "not_found"
                continue

            quay_url = self.repos_config[service_name]
            print(f"  Quay URL: {quay_url}")

            # Parse the Quay URL to get namespace and component name
            parsed = self.parse_quay_url(quay_url)
            if parsed is None:
                print(f"  ✗ Failed to parse Quay URL")
                results[service_name] = "parse_error"
                continue

            namespace, component_name = parsed
            print(f"  Namespace: {namespace}")
            print(f"  Component: {component_name}")

            # Annotate the component
            success = self.annotate_component(component_name, namespace)
            results[service_name] = "success" if success else "error"

        return results

    def print_summary(self, results: Dict[str, str]) -> None:
        """Print a summary of the trigger results."""
        print("\n" + "=" * 80)
        print("BUILD TRIGGER SUMMARY")
        print("=" * 80)

        success_count = sum(1 for status in results.values() if status == "success")
        not_found_count = sum(1 for status in results.values() if status == "not_found")
        parse_error_count = sum(1 for status in results.values() if status == "parse_error")
        error_count = sum(1 for status in results.values() if status == "error")

        if success_count > 0:
            print(f"\n✓ Successfully triggered: {success_count}")
            for service, status in sorted(results.items()):
                if status == "success":
                    print(f"  - {service}")

        if not_found_count > 0:
            print(f"\n✗ Services not found in repos.json: {not_found_count}")
            for service, status in sorted(results.items()):
                if status == "not_found":
                    print(f"  - {service}")

        if parse_error_count > 0:
            print(f"\n⚠ Failed to parse Quay URLs: {parse_error_count}")
            for service, status in sorted(results.items()):
                if status == "parse_error":
                    print(f"  - {service}")

        if error_count > 0:
            print(f"\n⚠ Errors during annotation: {error_count}")
            for service, status in sorted(results.items()):
                if status == "error":
                    print(f"  - {service}")

        print("=" * 80)
        if self.dry_run:
            print("(Dry-run mode: no annotations applied)")


def load_repos_config(config_path: str) -> Dict[str, str]:
    """Load repository configuration from JSON file."""
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in config file: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description='Trigger Konflux component builds by annotating components',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Trigger builds for specific services
  %(prog)s --repos-config repos.json --services chrome-service advisor-backend

  # Dry run to see what would happen
  %(prog)s --repos-config repos.json --services chrome-service --dry-run

  # Read services from a file (one per line)
  %(prog)s --repos-config repos.json --services-file stale_services.txt
        """
    )

    parser.add_argument(
        '--repos-config',
        default='repos.json',
        help='Path to repos.json (service to Quay URL mappings)'
    )

    parser.add_argument(
        '--services',
        nargs='+',
        help='Service names to trigger builds for (space-separated)'
    )

    parser.add_argument(
        '--services-file',
        help='File containing service names (one per line)'
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without making changes'
    )

    args = parser.parse_args()

    # Collect service names
    service_names = []

    if args.services:
        service_names.extend(args.services)

    if args.services_file:
        try:
            with open(args.services_file, 'r') as f:
                for line in f:
                    service = line.strip()
                    if service and not service.startswith('#'):
                        service_names.append(service)
        except FileNotFoundError:
            print(f"Error: File not found: {args.services_file}", file=sys.stderr)
            sys.exit(1)

    if not service_names:
        parser.error("No services specified. Use --services or --services-file")

    # Load repos configuration
    repos_config = load_repos_config(args.repos_config)
    print(f"Loaded {len(repos_config)} service(s) from {args.repos_config}\n")

    # Create trigger instance
    trigger = ComponentBuildTrigger(
        repos_config=repos_config,
        dry_run=args.dry_run
    )

    # Check if oc is available
    if not trigger.check_oc_available():
        print("Error: 'oc' command not found or not configured", file=sys.stderr)
        print("Please ensure you have the OpenShift CLI installed and are logged in", file=sys.stderr)
        sys.exit(1)

    # Trigger builds
    results = trigger.trigger_builds_for_services(service_names)

    # Print summary
    trigger.print_summary(results)

    # Exit with error code if any failures
    if any(status != "success" for status in results.values()):
        sys.exit(1)


if __name__ == '__main__':
    main()
