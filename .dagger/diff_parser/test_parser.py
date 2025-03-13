import pytest
from git import Repo

from .models import ChangeType
from .parser import DiffParser


@pytest.fixture
def test_repo(tmp_path):
    """Create a temporary git repository for testing"""
    repo = Repo.init(tmp_path)

    # Create a test file
    test_file = tmp_path / "test.txt"
    test_file.write_text("line 1\nline 2\nline 3")
    repo.index.add(["test.txt"])
    repo.index.commit("Initial commit")

    # Create a branch and make changes
    repo.create_head("feature")
    repo.heads.feature.checkout()

    # Modify the file
    test_file.write_text("line 1\nline 2 modified\nline 3\nline 4")
    repo.index.add(["test.txt"])
    repo.index.commit("Modified file")

    return tmp_path


def test_parse_diff(test_repo):
    """Test parsing a diff between commits"""
    parser = DiffParser(str(test_repo))
    repo = Repo(test_repo)

    # Get the commits
    base = repo.heads.main.commit
    head = repo.heads.feature.commit

    # Parse the diff
    diff = parser.parse_diff(base.hexsha, head.hexsha)

    # Verify the diff structure
    assert len(diff.files) == 1
    file_change = diff.files[0]
    assert file_change.file_path == "test.txt"
    assert not file_change.is_binary
    assert not file_change.is_deleted
    assert not file_change.is_new
    assert not file_change.is_renamed

    # Verify the changes
    changes = file_change.changes
    assert len(changes) == 4  # 3 context lines + 1 addition

    # Verify line types
    assert changes[0].change_type == ChangeType.CONTEXT
    assert changes[1].change_type == ChangeType.CONTEXT
    assert changes[2].change_type == ChangeType.ADDITION
    assert changes[3].change_type == ChangeType.CONTEXT
