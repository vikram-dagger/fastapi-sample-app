import re
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Dict, List, Self

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
from github import Commit, Github


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


@dataclass
class CodeSuggestion:
    """Represents a code suggestion for a specific file and line"""

    file: str
    line: int
    suggestion: List[str]


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
        current_line = 0
        new_code = []
        removal_reached = False

        # Regular expressions for file detection and line number parsing
        file_regex = re.compile(r"^\+\+\+ b/(.+)")
        line_regex = re.compile(r"^@@ .* \+(\d+),?")

        for line in diff_text.splitlines():
            # Detect file name
            if match := file_regex.match(line):
                current_file = match.group(1)
                continue

            # Detect modified line number in the new file
            if match := line_regex.match(line):
                current_line = int(match.group(1)) - 1  # Convert to 0-based index
                new_code = []  # Reset new code buffer
                removal_reached = False
                continue

            # Extract new code (ignoring metadata lines)
            if line.startswith("+") and not line.startswith("+++"):
                new_code.append(line[1:])  # Remove '+'
                continue

            if not removal_reached:
                current_line += 1  # Track line modifications

            # If a removed line ('-') appears after '+' lines, store the suggestion
            if line.startswith("-") and not line.startswith("---"):
                if new_code and current_file:
                    suggestions.append(
                        CodeSuggestion(
                            file=current_file, line=current_line, suggestion=new_code
                        )
                    )
                    new_code = []  # Reset new code buffer
                removal_reached = True

        # If there's a pending multi-line suggestion, add it
        if new_code and current_file:
            suggestions.append(
                CodeSuggestion(
                    file=current_file, line=current_line, suggestion=new_code
                )
            )

        return suggestions

    @function
    async def suggest(
        self,
        repository: Annotated[str, Doc("The owner and repository name")],
        commit: Annotated[str, Doc("The commit SHA")],
        diff_text: Annotated[str, Doc("The diff text to parse for suggestions")],
    ) -> str:
        """Posts code suggestions as inline comments on a PR

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

        # Parse the diff into suggestions
        suggestions = self.parse_diff(diff_text)
        if not suggestions:
            return "No suggestions to make"

        # Format all suggestions as review comments
        review_comments = []
        for suggestion in suggestions:
            suggestion_text = "\n".join(suggestion.suggestion)
            review_comments.append(
                {
                    "path": suggestion.file,
                    "line": suggestion.line,
                    "body": f"```suggestion\n{suggestion_text}\n```",
                    "side": "RIGHT",
                }
            )

        # Create the review with all comments
        await github.create_review(
            repository=repository,
            pull_number=pr_number,
            commit=commit_obj,
            body="Code suggestions from automated review",
            event="COMMENT",
            comments=review_comments,
        )

        return f"Posted {len(suggestions)} suggestions"

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
