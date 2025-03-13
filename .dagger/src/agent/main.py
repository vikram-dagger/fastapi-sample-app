from typing import Annotated
# for suggestions
import re


import dagger
from dagger import DefaultPath, Secret, Doc, dag, function, object_type


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

    def parse_git_diff(diff: str):
        changes = []
        current_file = None
        line_number = 0

        # Split the diff into sections based on file changes
        file_changes = re.split(r"^\+\+\+ b/(.+)$", diff, flags=re.MULTILINE)

        for section in file_changes:
            if section.strip() == '':
                continue

            lines = section.strip().splitlines()
            if lines:
                # The file name is in the second part after "+++" header
                file_path = lines[0].split()[1]
                current_file = file_path
                line_number = 0  # Reset line number for each file

                # Process the diff for this particular file
                for line in lines[1:]:
                    line_number += 1
                    if line.startswith('+'):
                        # This is an added line
                        changes.append(Change(file_path=current_file, change_type='added', line_number=line_number, content=line[1:]))
                    elif line.startswith('-'):
                        # This is a removed line
                        changes.append(Change(file_path=current_file, change_type='removed', line_number=line_number, content=line[1:]))
                    # Modified lines are generally represented by both a '+' and a '-' in the diff, so handle them accordingly.
                    elif line.startswith(' '):
                        # This is an unchanged line (context line), you can also track these if necessary.
                        pass

        return changes

class Change:
    def __init__(self, file_path, change_type, line_number, content):
        self.file_path = file_path
        self.change_type = change_type  # 'added', 'removed', 'modified'
        self.line_number = line_number
        self.content = content

    def __repr__(self):
        return f"Change(file_path={self.file_path}, change_type={self.change_type}, line_number={self.line_number}, content={self.content})"
