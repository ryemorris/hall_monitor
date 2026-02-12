#!/usr/bin/env python3
"""
Quay Image Checker - Search for images in Quay repositories by SHA or date range
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import urllib.request
import urllib.error


def load_repo_config(config_path: str) -> Dict[str, str]:
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


def parse_quay_repo(repo_url: str) -> tuple[str, str]:
    """
    Parse quay.io URL into namespace and repository path.
    Expected format: quay.io/namespace/repository or quay.io/namespace/path/to/repository
    """
    if repo_url.startswith('quay.io/'):
        repo_url = repo_url[8:]  # Remove 'quay.io/' prefix

    parts = repo_url.split('/', 1)
    if len(parts) < 2:
        raise ValueError(f"Invalid repo format: {repo_url}. Expected: namespace/repository")

    return parts[0], parts[1]


def get_quay_tags(namespace: str, repository: str, page: int = 1, page_size: int = 100) -> Dict:
    """
    Fetch tags from Quay repository using public API.
    Returns the JSON response containing tags.
    """
    url = f"https://quay.io/api/v1/repository/{namespace}/{repository}/tag/?page={page}&limit={page_size}"

    try:
        with urllib.request.urlopen(url) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"Error: Repository {namespace}/{repository} not found or not public", file=sys.stderr)
        else:
            print(f"Error: HTTP {e.code} fetching tags from {namespace}/{repository}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Error fetching tags: {e}", file=sys.stderr)
        return None


def get_all_tags(namespace: str, repository: str) -> List[Dict]:
    """Fetch all tags from a Quay repository, handling pagination."""
    all_tags = []
    page = 1

    while True:
        response = get_quay_tags(namespace, repository, page=page)
        if not response or 'tags' not in response:
            break

        tags = response['tags']
        if not tags:
            break

        all_tags.extend(tags)

        # Check if there are more pages
        if not response.get('has_additional', False):
            break

        page += 1

    return all_tags


def is_sha_tag(tag_name: str, sha: str) -> bool:
    """Check if tag matches the 7-character SHA."""
    return tag_name == sha or tag_name.endswith(f"-{sha}")


def is_sc_tag_in_range(tag_name: str, start_date: Optional[str], end_date: Optional[str]) -> tuple[bool, Optional[str]]:
    """
    Check if tag matches sc-{YYYYMMDD}-{sha} pattern and falls within date range.
    Returns (matches, date_string)
    """
    if not tag_name.startswith('sc-'):
        return False, None

    parts = tag_name.split('-')
    if len(parts) < 3:
        return False, None

    date_str = parts[1]

    # Validate date format (YYYYMMDD)
    if len(date_str) != 8 or not date_str.isdigit():
        return False, None

    # Check date range if provided
    if start_date and date_str < start_date:
        return False, date_str
    if end_date and date_str > end_date:
        return False, date_str

    return True, date_str


def search_by_date_range(repos: Dict[str, str], start_date: Optional[str], end_date: Optional[str],
                         services: Optional[List[str]] = None, report_mode: bool = False):
    """
    Search repositories for sc-{date}-{sha} images within date range.
    Returns tuple: (found_any, repos_without_updates)
    """
    found_any = False

    # For reporting
    repos_with_updates = []
    repos_without_updates = []
    repos_with_errors = []

    total_services = len([s for s in repos.keys() if not services or s in services])
    current = 0

    for service, repo_url in repos.items():
        if services and service not in services:
            continue

        current += 1

        try:
            namespace, repository = parse_quay_repo(repo_url)
        except ValueError as e:
            repos_with_errors.append((service, f"Invalid repo format: {e}"))
            if not report_mode:
                print(f"[{current}/{total_services}] Skipping {service}: {e}", file=sys.stderr)
            continue

        date_range_str = ""
        if start_date and end_date:
            date_range_str = f" ({start_date} to {end_date})"
        elif start_date:
            date_range_str = f" (from {start_date})"
        elif end_date:
            date_range_str = f" (until {end_date})"

        if not report_mode:
            print(f"\n[{current}/{total_services}] Searching {service} ({namespace}/{repository}){date_range_str}...")

        tags = get_all_tags(namespace, repository)

        if not tags:
            repos_with_errors.append((service, "No tags found or error accessing repository"))
            if not report_mode:
                print(f"  No tags found or error accessing repository")
            continue

        matches = []
        for tag in tags:
            is_match, date_str = is_sc_tag_in_range(tag['name'], start_date, end_date)
            if is_match:
                matches.append((tag, date_str))

        if matches:
            found_any = True
            repos_with_updates.append((service, matches))
            if not report_mode:
                print(f"  ✓ Found {len(matches)} match(es):")
                for tag, date_str in matches:
                    manifest_digest = tag.get('manifest_digest', 'N/A')
                    print(f"    - {tag['name']} (date: {date_str}, digest: {manifest_digest[:19]}...)")
        else:
            repos_without_updates.append(service)
            if not report_mode:
                print(f"  ✗ No matches found")

    # Print report if in report mode
    if report_mode:
        print("\n" + "="*80)
        print("REPOSITORY UPDATE REPORT")
        print("="*80)

        print(f"\n✓ REPOSITORIES WITH UPDATES ({len(repos_with_updates)}):")
        print("-" * 80)
        for service, matches in sorted(repos_with_updates):
            latest = matches[0]  # First match
            print(f"  {service:<40} {latest[0]['name']}")

        print(f"\n✗ REPOSITORIES WITHOUT UPDATES ({len(repos_without_updates)}):")
        print("-" * 80)
        for service in sorted(repos_without_updates):
            print(f"  {service}")

        print(f"\n⚠ REPOSITORIES WITH ERRORS ({len(repos_with_errors)}):")
        print("-" * 80)
        for service, error in sorted(repos_with_errors):
            print(f"  {service:<40} {error}")

        print("\n" + "="*80)
        print(f"SUMMARY: {len(repos_with_updates)} updated, {len(repos_without_updates)} not updated, {len(repos_with_errors)} errors")
        print("="*80)

    return found_any, repos_without_updates


def main():
    parser = argparse.ArgumentParser(
        description='Check Quay repositories for images by SHA or date range',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Quick mode: Search all repos for images from the last 14 days (with report)
  %(prog)s --config repos.json --quick

  # Quick mode with specific services only
  %(prog)s --config repos.json --quick --services service1 service2

  # Deep mode: Search each service for its specific SHA
  %(prog)s --config repos.json --deep sha_mappings.json

  # Deep mode with specific services only
  %(prog)s --config repos.json --deep sha_mappings.json --services service1 service2
        """
    )

    parser.add_argument(
        '--config',
        required=True,
        help='Path to JSON config file with service-to-repo mappings'
    )

    parser.add_argument(
        '--quick',
        action='store_true',
        help='Quick mode: Search all repos for images from the last 14 days and generate a report'
    )

    parser.add_argument(
        '--services',
        nargs='+',
        help='Specific service(s) to check (space-separated)'
    )

    parser.add_argument(
        '--output-stale',
        metavar='FILE',
        help='Output services without updates to a file (one per line)'
    )

    args = parser.parse_args()

    
    if not args.quick:
        parser.error("Must specify --quick mode")

    # Load repository configuration
    repos = load_repo_config(args.config)

    if not repos:
        print("Error: No repositories found in config file", file=sys.stderr)
        sys.exit(1)

    print(f"Loaded {len(repos)} repository configuration(s)")

    # Handle quick mode
    if args.quick:
        # Calculate date range for last 14 days
        end_date = datetime.now()
        start_date = end_date - timedelta(days=14)
        start_date_str = start_date.strftime('%Y%m%d')
        end_date_str = end_date.strftime('%Y%m%d')
        print(f"Quick mode: Searching for images from last 14 days ({start_date_str} to {end_date_str})\n")

        found, stale_services = search_by_date_range(repos, start_date_str, end_date_str, args.services, report_mode=True)

        # Write stale services to file if requested
        if args.output_stale and stale_services:
            try:
                with open(args.output_stale, 'w') as f:
                    for service in sorted(stale_services):
                        f.write(f"{service}\n")
                print(f"\nWrote {len(stale_services)} stale service(s) to {args.output_stale}")
            except Exception as e:
                print(f"Error writing to file: {e}", file=sys.stderr)
                sys.exit(1)

    if not found:
        print("\nNo matching images found.")
        sys.exit(1)
    else:
        print("\nSearch complete.")
        sys.exit(0)


if __name__ == '__main__':
    main()
