#!/usr/bin/env python3
"""Parse Konflux service references markdown and create repos.json"""

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

def extract_quay_url(markdown_line):
    """Extract Quay.io URL from markdown link format"""
    # Pattern: [quay.io](https://quay.io/repository/...)
    match = re.search(r'\[quay\.io\]\((https://quay\.io/repository/[^)]+)\)', markdown_line)
    if match:
        full_url = match.group(1)
        # Extract path after /repository/
        # https://quay.io/repository/redhat-services-prod/tenant/app/component
        # -> quay.io/redhat-services-prod/tenant/app/component
        repo_path = full_url.replace('https://quay.io/repository/', 'quay.io/')
        return repo_path
    return None

def parse_markdown_table(md_file_path):
    """Parse the markdown table and extract service -> repo mappings"""
    repos = {}

    with open(md_file_path, 'r') as f:
        lines = f.readlines()

    # Skip header lines (first 8 lines based on the file structure)
    for line in lines[8:]:
        line = line.strip()

        # Skip empty lines and separator lines
        if not line or line.startswith('##') or '|---' in line:
            continue

        # Parse table row: | Service Name | [quay.io](...) | ... |
        if line.startswith('|'):
            parts = [p.strip() for p in line.split('|')]
            if len(parts) >= 3:
                service_name = parts[1]
                quay_column = parts[2]

                quay_url = extract_quay_url(quay_column)
                if service_name and quay_url:
                    repos[service_name] = quay_url

    return repos

def load_config(config_path: str) -> dict:
    """Load configuration from YAML file."""
    if not yaml:
        return {}

    try:
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        return {}
    except yaml.YAMLError as e:
        print(f"Warning: Invalid YAML in config file: {e}", file=sys.stderr)
        return {}


def main():
    parser = argparse.ArgumentParser(
        description='Parse Konflux service references markdown and create repos.json',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Using command line arguments
  %(prog)s --markdown /path/to/Konflux-service-references.md --output repos.json

  # Using config file
  %(prog)s --config config.yaml

  # Explicit paths override config file
  %(prog)s --config config.yaml --output custom_repos.json
        """
    )

    parser.add_argument(
        '--markdown',
        help='Path to the Konflux service references markdown file'
    )

    parser.add_argument(
        '--output',
        help='Path to output repos.json file (default: repos.json)'
    )

    parser.add_argument(
        '--config',
        default='config.yaml',
        help='Path to configuration file (default: config.yaml)'
    )

    args = parser.parse_args()

    # Load config file
    config = load_config(args.config)

    # Determine markdown file path
    md_file = args.markdown or config.get('markdown_path')
    if not md_file:
        print("Error: Markdown file path not specified.", file=sys.stderr)
        print("Provide --markdown argument or set 'markdown_path' in config.yaml", file=sys.stderr)
        sys.exit(1)

    # Determine output file path
    output_file = args.output or config.get('repos_config', 'repos.json')

    # Validate markdown file exists
    if not Path(md_file).exists():
        print(f"Error: Markdown file not found: {md_file}", file=sys.stderr)
        sys.exit(1)

    print(f"Parsing {md_file}...")
    repos = parse_markdown_table(md_file)

    print(f"Found {len(repos)} services")

    # Write to JSON file
    with open(output_file, 'w') as f:
        json.dump(repos, f, indent=2, sort_keys=True)

    print(f"Created {output_file}")

    # Print first few entries as sample
    print("\nSample entries:")
    for i, (service, repo) in enumerate(sorted(repos.items())[:5]):
        print(f"  {service}: {repo}")


if __name__ == '__main__':
    main()
