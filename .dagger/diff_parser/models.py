from enum import Enum
from typing import List, Optional

from pydantic import BaseModel


class ChangeType(str, Enum):
    """Types of changes that can occur in a diff"""

    ADDITION = "addition"
    DELETION = "deletion"
    CONTEXT = "context"


class LineChange(BaseModel):
    """Represents a single line change in a diff"""

    line_number: int
    content: str
    change_type: ChangeType
    new_line_number: Optional[int] = None


class FileChange(BaseModel):
    """Represents changes to a single file in a diff"""

    file_path: str
    old_file_path: Optional[str] = None  # For renamed files
    changes: List[LineChange]
    is_binary: bool = False
    is_renamed: bool = False
    is_deleted: bool = False
    is_new: bool = False


class Diff(BaseModel):
    """Represents a complete diff with changes across multiple files"""

    files: List[FileChange]
    base_commit: Optional[str] = None
    head_commit: Optional[str] = None
