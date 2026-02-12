#!/usr/bin/env python3
"""
Script to update Tekton SC files in local repositories.

This script:
1. Scans a directory for git repositories (or processes specific repos with --repos flag)
2. Checks out the security-compliance branch
3. Updates .tekton/*-sc*.yaml files to replace version tags with 'main' in pipeline URLs
4. Commits and pushes the changes
"""

import argparse
import re
import subprocess
from pathlib import Path
from typing import List, Optional
import yaml


class TektonUpdater:
    def __init__(self, parent_dir: str, branch: str = "security-compliance", specific_repos: Optional[List[str]] = None, dry_run: bool = False):
        self.parent_dir = Path(parent_dir)
        self.branch = branch
        self.specific_repos = specific_repos
        self.dry_run = dry_run
        self.url_pattern = re.compile(
            r'(https://github\.com/[^/]+/[^/]+/raw/)v[\d.]+(/.*)'
        )
        self.commit_log = []  # Store (repo_name, commit_sha) tuples
        self.no_changes_log = []  # Store (repo_name, reason) for repos with no changes

    def run_git_command(self, repo_path: Path, command: List[str]) -> tuple[bool, str]:
        """Run a git command in the specified repository."""
        try:
            result = subprocess.run(
                command,
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=True
            )
            return True, result.stdout
        except subprocess.CalledProcessError as e:
            return False, e.stderr

    def is_git_repo(self, path: Path) -> bool:
        """Check if the path is a git repository."""
        return (path / '.git').exists()

    def find_repositories(self) -> List[Path]:
        """Find all git repositories in the target directory or specific repos."""
        repos = []

        if not self.parent_dir.exists():
            print(f"Error: Directory {self.parent_dir} does not exist")
            return repos

        # If specific repos are provided, use only those
        if self.specific_repos:
            for repo_name in self.specific_repos:
                repo_path = self.parent_dir / repo_name
                if not repo_path.exists():
                    print(f"Warning: Repository {repo_name} does not exist in {self.parent_dir}")
                    continue
                if not self.is_git_repo(repo_path):
                    print(f"Warning: {repo_name} is not a git repository")
                    continue
                repos.append(repo_path)
        else:
            # Scan all subdirectories for git repositories
            for item in self.parent_dir.iterdir():
                if item.is_dir() and self.is_git_repo(item):
                    repos.append(item)

        return repos

    def checkout_and_pull(self, repo_path: Path) -> bool:
        """Checkout the target branch and pull latest changes."""

        # Fetch latest changes
        print(f"  Fetching latest changes...")
        success, output = self.run_git_command(repo_path, ['git', 'fetch', 'upstream'])
        if not success:
            print(f"  Warning: Failed to fetch: {output}")

        # Check if branch exists locally
        success, output = self.run_git_command(
            repo_path,
            ['git', 'rev-parse', '--verify', self.branch]
        )
        branch_exists_locally = success

        # Check if branch exists on remote
        success, output = self.run_git_command(
            repo_path,
            ['git', 'rev-parse', '--verify', f'upstream/{self.branch}']
        )
        branch_exists_remotely = success

        if not branch_exists_remotely:
            print(f"  Branch '{self.branch}' does not exist on remote. Skipping.")
            return False

        # Checkout the branch
        if branch_exists_locally:
            success, output = self.run_git_command(repo_path, ['git', 'checkout', self.branch])
        else:
            success, output = self.run_git_command(
                repo_path,
                ['git', 'checkout', '-b', self.branch, f'upstream/{self.branch}']
            )

        if not success:
            print(f"  Failed to checkout branch: {output}")
            return False

        # Check if local and remote have diverged
        if branch_exists_locally:
            print(f"  Checking branch status...")
            success, status_output = self.run_git_command(repo_path, ['git', 'status'])

            if success and 'have diverged' in status_output or 'Your branch is ahead of' in status_output:
                print(f"  Local and remote branches have diverged or are ahead!")
                print(f"  Resetting local branch to upstream/{self.branch}...")
                success, output = self.run_git_command(
                    repo_path,
                    ['git', 'reset', '--hard', f'upstream/{self.branch}']
                )
                if not success:
                    print(f"  Failed to reset branch: {output}")
                    return False
                print(f"  Successfully reset to upstream/{self.branch}")
            else:
                # Pull latest changes
                print(f"  Pulling latest changes from upstream/{self.branch}...")
                success, output = self.run_git_command(repo_path, ['git', 'pull', 'upstream', self.branch])
                if not success:
                    print(f"  Warning: Failed to pull: {output}")

        return True

    def find_sc_files(self, repo_path: Path) -> List[Path]:
        """Find all .tekton files with '-sc' in the name."""
        tekton_dir = repo_path / '.tekton'
        if not tekton_dir.exists():
            return []

        sc_files = []
        for file_path in tekton_dir.glob('*-sc*.yaml'):
            sc_files.append(file_path)
        for file_path in tekton_dir.glob('*-sc*.yml'):
            sc_files.append(file_path)

        return sc_files

    def update_yaml_file(self, file_path: Path) -> bool:
        """Update the pipeline URL in a YAML file."""
        try:
            with open(file_path, 'r') as f:
                content = f.read()

            # Load YAML
            data = yaml.safe_load(content)

            # Navigate to the pipeline annotation
            if not data or 'metadata' not in data:
                print(f"    No metadata found in {file_path.name}")
                return False

            annotations = data.get('metadata', {}).get('annotations', {})
            pipeline_key = 'pipelinesascode.tekton.dev/pipeline'

            if pipeline_key not in annotations:
                print(f"    No pipeline annotation found in {file_path.name}")
                return False

            original_url = annotations[pipeline_key]

            # Replace version tag with 'main'
            updated_url = self.url_pattern.sub(r'\1main\2', original_url)

            if original_url == updated_url:
                print(f"    No changes needed for {file_path.name}")
                return False

            # Update the annotation
            annotations[pipeline_key] = updated_url

            # Write back to file, preserving formatting as much as possible
            # We'll do a simple string replacement to preserve original formatting
            updated_content = content.replace(original_url, updated_url)

            if self.dry_run:
                print(f"    [DRY RUN] Would update {file_path.name}")
                print(f"      Old: {original_url}")
                print(f"      New: {updated_url}")
            else:
                with open(file_path, 'w') as f:
                    f.write(updated_content)

                print(f"    Updated {file_path.name}")
                print(f"      Old: {original_url}")
                print(f"      New: {updated_url}")

            return True

        except Exception as e:
            print(f"    Error updating {file_path.name}: {e}")
            return False

    def commit_and_push(self, repo_path: Path, files_changed: List[Path]) -> bool:
        """Commit and push the changes."""
        if not files_changed:
            return False

        if self.dry_run:
            print(f"  [DRY RUN] Would commit and push {len(files_changed)} file(s):")
            for file_path in files_changed:
                rel_path = file_path.relative_to(repo_path)
                print(f"    - {rel_path}")
            print(f"  [DRY RUN] Commit message: Update Tekton SC pipeline URLs to use main branch")
            print(f"  [DRY RUN] Would push to origin/{self.branch}")
            return True

        # Add files
        for file_path in files_changed:
            rel_path = file_path.relative_to(repo_path)
            success, output = self.run_git_command(repo_path, ['git', 'add', str(rel_path)])
            if not success:
                print(f"  Failed to add {rel_path}: {output}")
                return False

        # Commit
        commit_message = "Update Tekton SC pipeline URLs to use main branch"
        success, output = self.run_git_command(
            repo_path,
            ['git', 'commit', '-m', commit_message]
        )
        if not success:
            print(f"  Failed to commit: {output}")
            return False

        print(f"  Committed changes: {commit_message}")

        # Get commit SHA
        success, commit_sha = self.run_git_command(
            repo_path,
            ['git', 'rev-parse', 'HEAD']
        )
        if success:
            commit_sha = commit_sha.strip()
        else:
            commit_sha = "unknown"

        # Push
        success, output = self.run_git_command(
            repo_path,
            ['git', 'push', 'upstream', self.branch]
        )
        if not success:
            print(f"  Failed to push: {output}")
            return False

        print(f"  Pushed changes to upstream/{self.branch}")
        print(f"  Commit SHA: {commit_sha}")

        # Log the commit SHA
        self.commit_log.append((repo_path.name, commit_sha))

        return True

    def process_repository(self, repo_path: Path) -> None:
        """Process a single repository."""
        repo_name = repo_path.name
        print(f"\nProcessing: {repo_name}")
        print("=" * 60)

        # Checkout and pull
        if not self.checkout_and_pull(repo_path):
            # Track as no changes (couldn't process due to missing branch)
            self.no_changes_log.append((repo_name, f"Branch '{self.branch}' not found on remote"))
            return

        # Find SC files
        sc_files = self.find_sc_files(repo_path)
        if not sc_files:
            print(f"  No -sc files found in .tekton directory")
            # Track as no changes (no SC files to update)
            self.no_changes_log.append((repo_name, "No -sc files found in .tekton directory"))
            return

        print(f"  Found {len(sc_files)} SC file(s)")

        # Update files
        files_changed = []
        for file_path in sc_files:
            if self.update_yaml_file(file_path):
                files_changed.append(file_path)

        # Commit and push
        if files_changed:
            self.commit_and_push(repo_path, files_changed)
        else:
            print(f"  No changes made")
            # Track repos with no changes (stale services that weren't remedied)
            self.no_changes_log.append((repo_name, "SC files already use 'main' branch"))

    def run(self) -> None:
        """Main execution method."""
        if self.dry_run:
            print("=" * 60)
            print("DRY RUN MODE - No changes will be made")
            print("=" * 60)

        if self.specific_repos:
            print(f"Processing specific repositories in: {self.parent_dir}")
            print(f"Repositories: {', '.join(self.specific_repos)}")
        else:
            print(f"Scanning for repositories in: {self.parent_dir}")
        print(f"Target branch: {self.branch}")
        print()

        repos = self.find_repositories()
        if not repos:
            print("No git repositories found")
            return

        print(f"Found {len(repos)} repository/repositories")

        for repo_path in repos:
            self.process_repository(repo_path)

        print("\n" + "=" * 60)
        if self.commit_log:
            print("Commit SHAs for pushed changes:")
            print("-" * 60)
            for repo_name, commit_sha in self.commit_log:
                print(f"  {repo_name}: {commit_sha}")
            print("=" * 60)

        if self.no_changes_log:
            print("\n" + "=" * 60)
            print("⚠ WARNING: STALE SERVICES WITH NO CHANGES")
            print("=" * 60)
            print("The following stale services were processed but had no")
            print("changes made to their Tekton SC files. This indicates the")
            print("stale status was NOT remedied by the update:")
            print("-" * 60)
            for repo_name, reason in self.no_changes_log:
                print(f"  {repo_name}")
                print(f"    Reason: {reason}")
            print("=" * 60)
            print(f"Total: {len(self.no_changes_log)} service(s) require investigation")
            print("=" * 60)

        # Summary
        total_processed = len(repos)
        total_updated = len(self.commit_log)
        total_no_changes = len(self.no_changes_log)
        print(f"\nSummary: {total_updated} updated, {total_no_changes} no changes, {total_processed} total")
        print("Done!")


def main():
    parser = argparse.ArgumentParser(
        description='Update Tekton SC pipeline files to use main branch instead of version tags'
    )
    parser.add_argument(
        'parent_dir',
        help='Parent directory containing git repositories'
    )
    parser.add_argument(
        '--repos',
        nargs='+',
        help='Specific repository subdirectories to process (optional). If not provided, all repos in parent_dir will be processed.'
    )
    parser.add_argument(
        '--branch',
        default='security-compliance',
        help='Branch to checkout (default: security-compliance)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be changed without making any modifications'
    )

    args = parser.parse_args()

    updater = TektonUpdater(args.parent_dir, args.branch, args.repos, args.dry_run)
    updater.run()


if __name__ == '__main__':
    main()
