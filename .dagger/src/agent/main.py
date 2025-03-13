from typing import Annotated, List
import re

import dagger
from dagger import DefaultPath, Secret, Doc, dag, function, object_type
from .workspace import Change

@object_type
class Agent:
    @function
    def heal(
        self,
        source: Annotated[dagger.Directory, DefaultPath("/")]
    ) -> dagger.Directory:
        before = dag.workspace(source=source)

        prompt = f"""
        - You are an expert in the Python FastAPI framework.
        - You are also an expert in Pydantic, SQLAlchemy and the Repository pattern.
        - The tests are failing
        - You have access to a workspace with the code and the tests
        - The workspace has tools to let you read and write the code as well as run the tests
        - In your workspace, fix the issues so that the tests pass
        - Be sure to always write your changes to the workspace
        - Always run the test tool after writing changes to the workspace
        - You are not done until the test tool is successful
        - Do not assume that errors are related to database connectivity or initialization
        - Focus only on Python files within the /app directory
        - Do not interact directly with the database; use the test tool only
        """
        after = (
            dag.llm()
            .with_workspace(before)
            .with_prompt(prompt)
            .workspace()
        )

        return after.container().directory(".")

    @function
    async def diagnose(
        self,
        source: Annotated[dagger.Directory, DefaultPath("/")],
        repository: Annotated[str, Doc("The owner and repository name")],
        ref: Annotated[str, Doc("The ref name")],
        token: Annotated[Secret, Doc("GitHub API token")],
    ) -> str:
        #print(f"""{repository} {ref} {token}""")
        before = dag.workspace(source=source, token=token)

        prompt = f"""
        - You are an expert in the Python FastAPI framework.
        - You are also an expert in Pydantic, SQLAlchemy and the Repository pattern.
        - The tests are failing
        - You have access to a workspace with the code and the tests
        - The workspace has tools to let you read and write the code as well as run the tests
        - In your workspace, fix the issues so that the tests pass
        - Be sure to always write your changes to the workspace
        - Always run the test tool after writing changes to the workspace
        - You are not done until the test tool is successful
        - Do not assume that errors are related to database connectivity or initialization
        - Focus only on Python files within the /app directory
        - Do not interact directly with the database; use the test tool only
        """
        work = (
            dag.llm()
            .with_workspace(before)
            .with_prompt(prompt)
        )

        diff = await work.workspace().diff()

        summary = await (
            dag.llm()
            .with_workspace(before)
            .with_prompt_var("diff", diff)
            .with_prompt("Read the code in the workspace. Read the code diff below. Treat the changes made to the workspace as a proposal and summarize them. Include your proposal plus the code diff in your final response. <diff>$diff</diff>")
            .last_reply()
        )

        return await dag.workspace(source=source, token=token).comment(repository, ref, summary)

    @function
    async def suggest(
        self,
        source: Annotated[dagger.Directory, DefaultPath("/")],
        repository: Annotated[str, Doc("The owner and repository name")],
        ref: Annotated[str, Doc("The ref name")],
        token: Annotated[Secret, Doc("GitHub API token")],
    ) -> str:
        before = dag.workspace(source=source, token=token)

        prompt = f"""
        - You are an expert in the Python FastAPI framework.
        - You are also an expert in Pydantic, SQLAlchemy and the Repository pattern.
        - The tests are failing
        - You have access to a workspace with the code and the tests
        - The workspace has tools to let you read and write the code as well as run the tests
        - In your workspace, fix the issues so that the tests pass
        - Be sure to always write your changes to the workspace
        - Always run the test tool after writing changes to the workspace
        - You are not done until the test tool is successful
        - Do not assume that errors are related to database connectivity or initialization
        - Focus only on Python files within the /app directory
        - Do not interact directly with the database; use the test tool only
        """
        work = (
            dag.llm()
            .with_workspace(before)
            .with_prompt(prompt)
        )

        diff = await work.workspace().diff()

        changes = self.parse_git_diff(diff)

        await dag.workspace(source=source, token=token).suggest(repository, ref, changes)

        summary = await (
            dag.llm()
            .with_workspace(before)
            .with_prompt_var("diff", diff)
            .with_prompt("Read the code in the workspace. Read the code diff below. Treat the changes made to the workspace as a proposal and summarize them. Include your proposal plus the code diff in your final response. <diff>$diff</diff>")
            .last_reply()
        )

        return await dag.workspace(source=source, token=token).comment(repository, ref, summary)

    @function
    async def suggest2(
        self,
        source: Annotated[dagger.Directory, DefaultPath("/")],
        repository: Annotated[str, Doc("The owner and repository name")],
        ref: Annotated[str, Doc("The ref name")],
        token: Annotated[Secret, Doc("GitHub API token")],
    ) -> str:


        diff = """diff --git a/repositories.py b/repositories.py
index f7c2ce0..9ba318e 100644
--- a/repositories.py
+++ b/repositories.py
@@ -4,7 +4,7 @@ from . import models

# Create a new book
def create_book(db: Session, book: models.BookIn):
-    db_book = models.Book(title=book.title, author=book.author)
+    db_book = models.Book(title=book.title, author=book.author, price=book.price)
    db.add(db_book)
    db.commit()
    db.refresh(db_book)
@@ -27,6 +27,7 @@ def update_book(db: Session, book_id: int, book: models.BookIn):
    if db_book:
        db_book.title = book.title
        db_book.author = book.author
+        db_book.price = book.price
        db.commit()
        db.refresh(db_book)
        return db_book
"""
        changes = self.parse_git_diff(diff)
        print(changes)

        await dag.workspace(source=source, token=token).suggest(repository, ref, changes)

    def parse_git_diff(self, diff_text: str) -> List[Change]:
        changes = []
        file_pattern = re.compile(r'diff --git a/(.*?) b/.*')
        hunk_pattern = re.compile(r'@@ -(\d+),?\d* \+(\d+),?\d* @@')

        lines = diff_text.split('\n')
        current_file = None
        current_line_number = None
        old_line_number = None

        for i, line in enumerate(lines):
            file_match = file_pattern.match(line)
            if file_match:
                current_file = file_match.group(1)

            hunk_match = hunk_pattern.match(line)
            if hunk_match:
                old_line_number = int(hunk_match.group(1))
                current_line_number = int(hunk_match.group(2))

            if line.startswith('-') and not line.startswith('---'):
                old_line = line[1:].strip()
                new_line = lines[i + 1][1:].strip() if i + 1 < len(lines) and lines[i + 1].startswith('+') else None
                if new_line:
                    changes.append(Change(current_file, current_line_number, old_line, new_line))
                    current_line_number += 1
            elif line.startswith('+') and not line.startswith('+++'):
                if i == 0 or not lines[i - 1].startswith('-'):
                    new_line = line[1:].strip()
                    changes.append(Change(current_file, current_line_number, None, new_line))
                    current_line_number += 1

        return changes
