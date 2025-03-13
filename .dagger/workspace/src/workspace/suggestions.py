import re
from dataclasses import dataclass
from typing import List


@dataclass
class CodeSuggestion:
    """Represents a code suggestion for a specific file and line"""

    file: str
    line: int
    suggestion: List[str]


def parse_diff(diff_text: str) -> List[CodeSuggestion]:
    """Parse a unified diff format text into code suggestions

    Args:
        diff_text: Raw diff text in unified format
    """
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
            current_line = (
                int(match.group(1)) - 1
            )  # Convert to 0-based index for tracking
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
            CodeSuggestion(file=current_file, line=current_line, suggestion=new_code)
        )

    return suggestions
