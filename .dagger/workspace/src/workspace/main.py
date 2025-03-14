import base64
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Dict, List, Optional, Self

from dagger import (
    Container,
    DefaultPath,
    Directory,
    Doc,
    ReturnType,
    Secret,
    dag,
    function,
    object_type,
)
from github import Commit, Github, GithubException, InputGitTreeElement


class GitHubClient:
    """Client for interacting with GitHub API for PR reviews and suggestions"""

    def __init__(self, token):
        """Initialize the GitHub client with an access token"""
        self.token = token
        self.github = None  # Will be initialized in async init

    async def init(self):
        """Initialize the GitHub client with the token"""
        token_text = await self.token.plaintext()
        self.github = Github(token_text)
        return self

    async def get_pr_for_commit(self, repo: str, commit: str) -> int:
        """Get the pull request number associated with a commit"""
        if not self.github:
            await self.init()
        repository = self.github.get_repo(repo)
        # Get all PRs that contain this commit
        pulls = repository.get_pulls(state="open")
        for pr in pulls:
            if pr.get_commits().reversed[0].sha == commit:
                return pr.number
        raise ValueError(f"No pull requests found for commit {commit}")

    async def create_branch_from_pr(
        self, repository: str, pr_number: int, branch_name: Optional[str] = None
    ) -> str:
        """Create a new branch from the head of a PR

        Args:
            repository: Full repository name (e.g., "owner/repo")
            pr_number: Pull request number
            branch_name: Name for the new branch (optional, will generate if not provided)

        Returns:
            The name of the created branch
        """
        if not self.github:
            await self.init()

        repo = self.github.get_repo(repository)
        pr = repo.get_pull(pr_number)

        # Get the head commit SHA
        head_sha = pr.head.sha

        # Generate a branch name if not provided
        if not branch_name:
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            branch_name = f"llm-fix-{timestamp}-{str(uuid.uuid4())[:8]}"

        # Create a new branch at the head commit
        try:
            repo.create_git_ref(f"refs/heads/{branch_name}", head_sha)
            print(f"Created branch {branch_name} from PR #{pr_number}")
            return branch_name
        except GithubException as e:
            print(f"Error creating branch: {e}")
            raise

    async def apply_file_changes(
        self,
        repository: str,
        branch_name: str,
        file_changes: Dict[str, str],
        commit_message: str,
    ) -> str:
        """Apply changes to files and commit them to a branch

        Args:
            repository: Full repository name (e.g., "owner/repo")
            branch_name: Name of the branch to commit to
            file_changes: Dictionary mapping file paths to their new content
            commit_message: Commit message

        Returns:
            The SHA of the created commit
        """
        if not self.github:
            await self.init()

        repo = self.github.get_repo(repository)

        # Get the reference to the branch
        ref = repo.get_git_ref(f"refs/heads/{branch_name}")

        # Get the latest commit on the branch
        latest_commit = repo.get_commit(ref.object.sha)
        base_tree = latest_commit.commit.tree

        # Create tree elements for each file change
        tree_elements = []
        for file_path, content in file_changes.items():
            try:
                # Check if file exists
                existing_content = repo.get_contents(file_path, ref=branch_name)
                mode = existing_content.mode
            except GithubException:
                # File doesn't exist, use default mode for new file
                mode = "100644"  # Regular file

            # Create a tree element for the file
            element = InputGitTreeElement(
                path=file_path, mode=mode, type="blob", content=content
            )
            tree_elements.append(element)

        # Create a new tree with the changes
        new_tree = repo.create_git_tree(tree_elements, base_tree)

        # Create a commit with the new tree
        parent = repo.get_git_commit(latest_commit.sha)
        commit = repo.create_git_commit(commit_message, new_tree, [parent])

        # Update the reference to point to the new commit
        ref.edit(commit.sha)

        print(f"Applied changes to {len(file_changes)} files in branch {branch_name}")
        return commit.sha

    async def create_pr_from_branch(
        self, repository: str, base_branch: str, head_branch: str, title: str, body: str
    ) -> int:
        """Create a new PR from a branch targeting another branch

        Args:
            repository: Full repository name (e.g., "owner/repo")
            base_branch: The target branch for the PR
            head_branch: The source branch for the PR
            title: PR title
            body: PR description

        Returns:
            The number of the created PR
        """
        if not self.github:
            await self.init()

        repo = self.github.get_repo(repository)

        # Create the PR
        pr = repo.create_pull(
            title=title, body=body, base=base_branch, head=head_branch
        )

        print(f"Created PR #{pr.number} from {head_branch} to {base_branch}")
        return pr.number

    async def get_file_content(self, repository: str, file_path: str, ref: str) -> str:
        """Get the content of a file from a repository

        Args:
            repository: Full repository name (e.g., "owner/repo")
            file_path: Path to the file
            ref: Branch, tag, or commit SHA

        Returns:
            The content of the file
        """
        if not self.github:
            await self.init()

        repo = self.github.get_repo(repository)

        try:
            content = repo.get_contents(file_path, ref=ref)
            if isinstance(content, list):
                raise ValueError(f"{file_path} is a directory, not a file")

            # Decode content from base64
            return base64.b64decode(content.content).decode("utf-8")
        except GithubException as e:
            print(f"Error getting file content: {e}")
            raise

    async def create_review(
        self,
        repository: str,
        pull_number: int,
        commit: Commit = None,
        body: str = None,
        event: str = "COMMENT",
        comments: List[Dict[str, any]] = None,
    ) -> None:
        """Create a review with inline comments on a pull request

        Args:
            repository: Full repository name (e.g., "owner/repo")
            pull_number: Pull request number
            commit: The commit object to review (optional)
            body: The review body text (optional)
            event: The review event (e.g., "COMMENT", "APPROVE", "REQUEST_CHANGES"), defaults to "COMMENT"
            comments: List of review comments with their positions (optional)
        """
        if not self.github:
            await self.init()
        repo = self.github.get_repo(repository)
        pr = repo.get_pull(pull_number)

        # Prepare post parameters
        post_parameters = {}
        if body is not None:
            post_parameters["body"] = body
        post_parameters["event"] = event
        if commit is not None:
            post_parameters["commit"] = commit
        post_parameters["comments"] = comments if comments is not None else []

        # Create the review with all comments
        pr.create_review(**post_parameters)

    async def create_review_comment(
        self,
        repository: str,
        pull_number: int,
        commit,
        path: str,
        line: int,
        body: str,
    ) -> None:
        """Create a review comment on a pull request

        Args:
            repository: Full repository name (e.g., "owner/repo")
            pull_number: Pull request number
            commit: The commit object to review
            path: File path to comment on
            line: Line number to comment on
            body: The comment text
        """
        if not self.github:
            await self.init()
        repo = self.github.get_repo(repository)
        pr = repo.get_pull(pull_number)

        # Create the review comment
        pr.create_review_comment(
            body=body, commit=commit, path=path, line=line, as_suggestion=True
        )

        return None


@dataclass
class CodeSuggestion:
    """Represents a code suggestion for a specific file and line"""

    file: str
    line: int
    suggestion: List[str]
    position: int  # Position in the diff (relative to the hunk header)
    diff_hunk: str  # The diff hunk context
    is_in_diff: bool = False


@object_type
class Workspace:
    ctr: Container
    source: Directory
    token: Secret | None = None

    @classmethod
    async def create(
        cls,
        source: Annotated[
            Directory, Doc("The context for the workspace"), DefaultPath("/")
        ],
        token: Annotated[Secret | None, Doc("GitHub API token")],
    ):
        ctr = (
            dag.container()
            .from_("python:3.11")
            .with_workdir("/app")
            .with_directory("/app", source)
            .with_mounted_cache("/root/.cache/pip", dag.cache_volume("python-pip"))
            .with_exec(["pip", "install", "-r", "requirements.txt"])
        )
        return cls(ctr=ctr, source=source, token=token)

    @function
    async def read_file(
        self, path: Annotated[str, Doc("File path to read a file from")]
    ) -> str:
        """Returns the contents of a file in the workspace at the provided path"""
        return await self.ctr.file(path).contents()

    @function
    def write_file(
        self,
        path: Annotated[str, Doc("File path to write a file to")],
        contents: Annotated[str, Doc("File contents to write")],
    ) -> Self:
        """Writes the provided contents to a file in the workspace at the provided path"""
        self.ctr = self.ctr.with_new_file(path, contents)
        return self

    @function
    async def ls(
        self, path: Annotated[str, Doc("Path to get the list of files from")]
    ) -> list[str]:
        """Returns the list of files in the workspace at the provided path"""
        return await self.ctr.directory(path).entries()

    @function
    async def test(self) -> str:
        postgresdb = (
            dag.container()
            .from_("postgres:alpine")
            .with_env_variable("POSTGRES_DB", "app_test")
            .with_env_variable("POSTGRES_PASSWORD", "secret")
            .with_exposed_port(5432)
            .as_service(args=[], use_entrypoint=True)
        )

        cmd = (
            self.ctr.with_service_binding("db", postgresdb)
            .with_env_variable(
                "DATABASE_URL", "postgresql://postgres:secret@db/app_test"
            )
            .with_env_variable("CACHEBUSTER", str(datetime.now()))
            .with_exec(["sh", "-c", "pytest --tb=short"], expect=ReturnType.ANY)
            # .with_exec(["pytest"])
        )
        if await cmd.exit_code() != 0:
            stderr = await cmd.stderr()
            stdout = await cmd.stdout()
            raise Exception(f"Tests failed. \nError: {stderr} \nOutput: {stdout}")
        return await cmd.stdout()

    @function
    async def diff(self) -> str:
        """Returns the changes in the workspace so far"""
        source = (
            dag.container()
            .from_("alpine/git")
            .with_workdir("/app")
            .with_directory("/app", self.source)
        )
        # make sure source is a git directory
        if ".git" not in await self.source.entries():
            source = (
                source.with_exec(["git", "init"])
                .with_exec(["git", "add", "."])
                .with_exec(["git", "commit", "-m", "'initial'"])
            )
        # return the git diff of the changes in the workspace
        return (
            await source.with_directory(".", self.ctr.directory("."))
            .with_exec(["git", "diff"])
            .stdout()
        )

    def parse_diff(self, diff_text: str) -> List[CodeSuggestion]:
        """Parse a unified diff format text into code suggestions"""
        suggestions = []
        current_file = ""
        current_hunk_start_line = 0
        position_in_hunk = 0
        added_lines = []
        added_line_numbers = []
        current_diff_hunk = []

        # Keep track of which lines were actually modified in the diff
        modified_files = {}  # file -> set of modified line numbers

        # For debugging
        print(f"Parsing diff of length {len(diff_text)}")

        # Regular expressions for file and hunk detection
        file_regex = re.compile(r"^diff --git a/.*? b/(.*?)$")
        hunk_regex = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@.*$")

        lines = diff_text.splitlines()
        i = 0

        # For tracking line pairs (removed and added)
        removed_line = None
        removed_line_number = 0

        while i < len(lines):
            line = lines[i]

            # Check for file header
            file_match = file_regex.match(line)
            if file_match:
                # Process any pending suggestions before moving to a new file
                if added_lines and current_file and current_diff_hunk:
                    suggestions.append(
                        CodeSuggestion(
                            file=current_file,
                            line=added_line_numbers[0],  # Use the first line number
                            suggestion=added_lines,
                            position=position_in_hunk,
                            diff_hunk="\n".join(
                                current_diff_hunk[-10:]
                            ),  # Last 10 lines of context
                        )
                    )
                    added_lines = []
                    added_line_numbers = []

                current_file = file_match.group(1)
                if current_file not in modified_files:
                    modified_files[current_file] = set()
                current_diff_hunk = []
                removed_line = None
                removed_line_number = 0
                i += 1
                continue

            # Check for hunk header
            hunk_match = hunk_regex.match(line)
            if hunk_match:
                # Process any pending suggestions before moving to a new hunk
                if added_lines and current_file and current_diff_hunk:
                    suggestions.append(
                        CodeSuggestion(
                            file=current_file,
                            line=added_line_numbers[0],  # Use the first line number
                            suggestion=added_lines,
                            position=position_in_hunk,
                            diff_hunk="\n".join(
                                current_diff_hunk[-10:]
                            ),  # Last 10 lines of context
                        )
                    )
                    added_lines = []
                    added_line_numbers = []

                # Get both the original and new line numbers from the hunk header
                original_start = int(hunk_match.group(1))
                new_start = int(hunk_match.group(2))

                current_hunk_start_line = new_start - 1  # 0-based for internal tracking
                position_in_hunk = 1  # Reset position counter for new hunk
                current_diff_hunk = [line]  # Start collecting the hunk
                removed_line = None
                removed_line_number = (
                    original_start - 1
                )  # 0-based for internal tracking
                i += 1
                continue

            # Collect the diff hunk
            if current_diff_hunk:
                current_diff_hunk.append(line)

            # Track position for each line after a hunk header
            if position_in_hunk > 0:
                position_in_hunk += 1

            # Track modified lines with better handling of line pairs
            if current_file and position_in_hunk > 0:
                if line.startswith("-") and not line.startswith("---"):
                    # This is a removed line - store it for potential pairing
                    removed_line = line[1:]  # Remove the '-' prefix
                    removed_line_number += 1
                elif line.startswith("+") and not line.startswith("+++"):
                    # This is an added line
                    current_line_number = current_hunk_start_line + 1

                    # Mark this line as modified
                    modified_files[current_file].add(current_line_number)

                    # If we have a removed line right before this, it's likely a modification
                    # rather than a pure addition
                    if removed_line is not None:
                        # This is a modified line (replacement)
                        # We've already marked it as modified above
                        removed_line = None  # Reset for next pair

                    current_hunk_start_line += 1
                else:
                    # This is a context line
                    if not line.startswith(
                        "\\"
                    ):  # Ignore "\ No newline at end of file"
                        current_hunk_start_line += 1
                        removed_line_number += 1
                        removed_line = None  # Reset removed line tracking

            # Collect added lines (additions)
            if line.startswith("+") and not line.startswith("+++"):
                # Skip the + prefix
                content = line[1:]
                # Only collect meaningful additions (not just whitespace changes)
                if content.strip():
                    if not added_lines:
                        # This is the first line of a new addition
                        line_number = current_hunk_start_line
                        added_line_numbers.append(line_number)
                    added_lines.append(content)
            elif added_lines and current_file and current_diff_hunk:
                # We've reached the end of a block of additions
                # Create a suggestion for the accumulated added lines
                suggestions.append(
                    CodeSuggestion(
                        file=current_file,
                        line=added_line_numbers[0],  # Use the first line number
                        suggestion=added_lines,
                        position=position_in_hunk
                        - len(added_lines),  # Adjust position to start of block
                        diff_hunk="\n".join(
                            current_diff_hunk[-10:]
                        ),  # Last 10 lines of context
                    )
                )
                added_lines = []
                added_line_numbers = []

            i += 1

        # Handle any remaining added lines at the end of the file
        if added_lines and current_file and current_diff_hunk:
            suggestions.append(
                CodeSuggestion(
                    file=current_file,
                    line=added_line_numbers[0],
                    suggestion=added_lines,
                    position=position_in_hunk - len(added_lines) + 1,
                    diff_hunk="\n".join(
                        current_diff_hunk[-10:]
                    ),  # Last 10 lines of context
                )
            )

        # Print the modified files and lines for debugging
        for file, lines in modified_files.items():
            print(f"Modified file: {file}, lines: {sorted(lines)}")

        # Store the modified files information for validation
        for suggestion in suggestions:
            suggestion.is_in_diff = (
                suggestion.file in modified_files
                and suggestion.line in modified_files[suggestion.file]
            )
            print(
                f"Suggestion for {suggestion.file}:{suggestion.line} is_in_diff={suggestion.is_in_diff}"
            )

        return suggestions

    @function
    async def suggest(
        self,
        repository: Annotated[str, Doc("The owner and repository name")],
        commit: Annotated[str, Doc("The commit SHA")],
        diff_text: Annotated[str, Doc("The diff text to parse for suggestions")],
    ) -> str:
        """Posts code suggestions as inline comments on a PR or creates a new PR for suggestions outside the diff

        Args:
            repository: Full repository name (e.g., "owner/repo")
            commit: The commit SHA to attach comments to
            diff_text: The diff text to parse for suggestions
        """
        if not self.token:
            raise ValueError("GitHub token is required for suggesting changes")

        # Create and initialize GitHub client
        github = await GitHubClient(self.token).init()

        # Get PR number from commit SHA
        pr_number = await github.get_pr_for_commit(repository, commit)

        # Get the repository and commit objects
        repo = github.github.get_repo(repository)
        commit_obj = repo.get_commit(commit)
        pr = repo.get_pull(pr_number)

        # Parse the diff into suggestions
        suggestions = self.parse_diff(diff_text)
        if not suggestions:
            return "No suggestions to make"

        # Separate suggestions into those in the diff and those outside the diff
        in_diff_suggestions = []
        out_of_diff_suggestions = []

        for suggestion in suggestions:
            if hasattr(suggestion, "is_in_diff") and suggestion.is_in_diff:
                in_diff_suggestions.append(suggestion)
            else:
                out_of_diff_suggestions.append(suggestion)

        print(
            f"Found {len(in_diff_suggestions)} suggestions in diff and {len(out_of_diff_suggestions)} suggestions outside diff"
        )

        # Process suggestions in the diff as review comments
        successful_suggestions = 0
        fallback_suggestions = 0

        for i, suggestion in enumerate(in_diff_suggestions):
            suggestion_text = "\n".join(suggestion.suggestion)

            print(
                f"Processing in-diff suggestion {i + 1}/{len(in_diff_suggestions)} for file {suggestion.file}, line {suggestion.line}"
            )

            # Try to create a review comment
            try:
                # Create individual review comments
                pr.create_review_comment(
                    body=f"```suggestion\n{suggestion_text}\n```",
                    commit=commit_obj,
                    path=suggestion.file,
                    line=suggestion.line,  # Use line instead of position
                    as_suggestion=True,
                )
                successful_suggestions += 1
                print(f"Successfully created review comment for {suggestion.file}")
            except Exception as e:
                print(f"Error creating review comment for {suggestion.file}: {e}")

                # Try fallback to regular issue comment
                try:
                    pr.create_issue_comment(
                        f"Suggestion for `{suggestion.file}` line {suggestion.line}:\n```suggestion\n{suggestion_text}\n```"
                    )
                    fallback_suggestions += 1
                    print(f"Created fallback issue comment for {suggestion.file}")
                except Exception as e2:
                    print(f"Error creating fallback comment: {e2}")

        # Process suggestions outside the diff by creating a new PR
        created_prs = []

        if out_of_diff_suggestions:
            # Group suggestions by file
            file_to_suggestions = {}
            for suggestion in out_of_diff_suggestions:
                if suggestion.file not in file_to_suggestions:
                    file_to_suggestions[suggestion.file] = []
                file_to_suggestions[suggestion.file].append(suggestion)

            # Create a new branch from the PR head
            branch_name = await github.create_branch_from_pr(repository, pr_number)

            # For each file with suggestions, apply the changes
            for file_path, file_suggestions in file_to_suggestions.items():
                try:
                    # Get the current content of the file
                    current_content = await github.get_file_content(
                        repository, file_path, branch_name
                    )

                    # Apply all suggestions to the file content
                    new_content = current_content
                    lines = new_content.splitlines()

                    # Sort suggestions by line number in descending order to avoid offset issues
                    file_suggestions.sort(key=lambda s: s.line, reverse=True)

                    for suggestion in file_suggestions:
                        # Convert 1-indexed line to 0-indexed
                        line_idx = suggestion.line - 1

                        # Replace the line with the suggestion
                        if 0 <= line_idx < len(lines):
                            # Remove the original line and insert the suggestion lines
                            lines.pop(line_idx)
                            for i, suggestion_line in enumerate(
                                reversed(suggestion.suggestion)
                            ):
                                lines.insert(line_idx, suggestion_line)

                    # Join the lines back into a string
                    new_content = "\n".join(lines)

                    # Apply the changes to the branch
                    file_changes = {file_path: new_content}
                    commit_message = f"Apply LLM suggestions to {file_path}"
                    await github.apply_file_changes(
                        repository, branch_name, file_changes, commit_message
                    )

                except Exception as e:
                    print(f"Error applying changes to {file_path}: {e}")

            # Create a PR with the changes
            pr_title = f"LLM suggested fixes for PR #{pr_number}"
            pr_body = (
                f"This PR contains fixes suggested by an LLM that couldn't be applied directly to PR #{pr_number} "
                f"because they affect lines outside the original diff.\n\n"
                f"Original PR: #{pr_number}\n"
                f"Generated by: AI assistant\n\n"
                f"## Suggestions applied:\n"
            )

            # Add details about each suggestion to the PR body
            for file_path, file_suggestions in file_to_suggestions.items():
                pr_body += f"\n### {file_path}\n"
                for suggestion in file_suggestions:
                    suggestion_text = "\n".join(suggestion.suggestion)
                    pr_body += (
                        f"- Line {suggestion.line}:\n```\n{suggestion_text}\n```\n"
                    )

            # Create the PR
            try:
                # Get the base branch of the original PR
                base_branch = pr.base.ref

                # Create a new PR targeting the base branch of the original PR
                new_pr_number = await github.create_pr_from_branch(
                    repository, base_branch, branch_name, pr_title, pr_body
                )

                # Add a comment to the original PR linking to the new PR
                pr.create_issue_comment(
                    f"I've created a new PR with suggested fixes that couldn't be applied directly to this PR: #{new_pr_number}"
                )

                created_prs.append(new_pr_number)
            except Exception as e:
                print(f"Error creating PR: {e}")

                # Add a comment to the original PR with the branch name
                try:
                    pr.create_issue_comment(
                        f"I've created a branch with suggested fixes that couldn't be applied directly to this PR: `{branch_name}`\n"
                        f"However, I couldn't create a PR due to an error: {str(e)}"
                    )
                except Exception as e2:
                    print(f"Error creating comment: {e2}")

        # Build the result message
        result = (
            f"Posted {successful_suggestions} suggestions directly as review comments"
        )
        if fallback_suggestions > 0:
            result += f", {fallback_suggestions} as regular comments"

        if created_prs:
            result += f". Created {len(created_prs)} PR(s) for suggestions outside the diff: {', '.join([f'#{pr_num}' for pr_num in created_prs])}"
        elif out_of_diff_suggestions:
            result += f". Created branch '{branch_name}' for {len(out_of_diff_suggestions)} suggestions outside the diff"

        return result

    @function
    async def comment(
        self,
        repository: Annotated[str, Doc("The owner and repository name")],
        ref: Annotated[str, Doc("The ref name")],
        body: Annotated[str, Doc("The comment body")],
    ) -> str:
        """Adds a comment to the PR"""
        repository_url = f"https://github.com/{repository}"
        pr_number = int(re.search(r"(\d+)", ref).group(1))
        return await dag.github_comment(
            self.token, repository_url, issue=pr_number
        ).create(body)

    @function
    def container(self) -> Container:
        """Returns the container for the workspace"""
        return self.ctr
