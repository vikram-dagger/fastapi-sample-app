from typing import List, Optional

import git
from git.diff import Diff

from .models import ChangeType, FileChange, LineChange
from .models import Diff as DiffModel


class DiffParser:
    """Parser for converting git diffs into structured data"""

    def __init__(self, repo_path: str):
        """Initialize the parser with a git repository path"""
        self.repo = git.Repo(repo_path)

    def parse_diff(self, base_commit: str, head_commit: str) -> DiffModel:
        """Parse a diff between two commits into a structured format"""
        base = self.repo.commit(base_commit)
        head = self.repo.commit(head_commit)

        diff_index = base.diff(head)
        files = []

        for diff in diff_index:
            file_change = self._parse_file_change(diff)
            if file_change:
                files.append(file_change)

        return DiffModel(files=files, base_commit=base_commit, head_commit=head_commit)

    def _parse_file_change(self, diff: Diff) -> Optional[FileChange]:
        """Parse a single file's changes from a git diff"""
        if diff.a_path is None and diff.b_path is None:
            return None

        # Handle binary files
        if diff.is_binary:
            return FileChange(file_path=diff.b_path or diff.a_path, is_binary=True)

        # Handle deleted files
        if diff.deleted_file:
            return FileChange(file_path=diff.a_path, is_deleted=True)

        # Handle new files
        if diff.new_file:
            return FileChange(
                file_path=diff.b_path, is_new=True, changes=self._parse_hunks(diff)
            )

        # Handle renamed files
        if diff.renamed_file:
            return FileChange(
                file_path=diff.b_path,
                old_file_path=diff.a_path,
                is_renamed=True,
                changes=self._parse_hunks(diff),
            )

        # Handle modified files
        return FileChange(file_path=diff.b_path, changes=self._parse_hunks(diff))

    def _parse_hunks(self, diff: Diff) -> List[LineChange]:
        """Parse the hunks of a diff into line changes"""
        changes = []
        current_line = 0

        for hunk in diff:
            # Handle context lines before the hunk
            for line in hunk.lines:
                if line.line_origin == " ":
                    current_line += 1
                    changes.append(
                        LineChange(
                            line_number=current_line,
                            content=line.content,
                            change_type=ChangeType.CONTEXT,
                        )
                    )
                elif line.line_origin == "+":
                    current_line += 1
                    changes.append(
                        LineChange(
                            line_number=current_line,
                            content=line.content,
                            change_type=ChangeType.ADDITION,
                        )
                    )
                elif line.line_origin == "-":
                    changes.append(
                        LineChange(
                            line_number=current_line,
                            content=line.content,
                            change_type=ChangeType.DELETION,
                        )
                    )
                    current_line += 1

        return changes
