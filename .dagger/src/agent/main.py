from typing import Annotated, List
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
        environment = (
            dag.env()
            .with_workspace_input("before", dag.workspace(source=source), "the workspace to use for code and tests")
            .with_directory_output("after", "the current directory with the updated code")
        )

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
            .with_env(environment)
            .with_prompt(prompt)
        )

        return work.env().output("after").as_directory()

    @function
    async def diagnose(
        self,
        source: Annotated[dagger.Directory, DefaultPath("/")],
        repository: Annotated[str, Doc("The owner and repository name")],
        ref: Annotated[str, Doc("The ref name")],
        token: Annotated[Secret, Doc("GitHub API token")],
    ) -> str:
        environment = (
            dag.env()
            .with_workspace_input("before", dag.workspace(source=source), "the workspace to use for code and tests")
            .with_workspace_output("after", "the workspace with the modified code")
            .with_string_output("summary", "summary of changes for the tests to pass")
        )

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
        - Once done, return the modified workspace along with a clearly written list of suggested changes
        - Remember to describe each change as an action the reader could take, rather than a log of what was changed.
        """
        work = (
            dag.llm()
            .with_env(environment)
            .with_prompt(prompt)
        )

        # list of changes
        summary = await (
            work
            .env()
            .output("summary")
            .as_string()
        )

        # diff of the changes
        diff = await (
            work
            .env()
            .output("after")
            .as_workspace()
            .container()
            .with_exec(["git", "diff"])
            .stdout()
        )

        comment = f"{summary}\n\nDiff:\n\n```{diff}```"
        return await dag.workspace(source=source, token=token).comment(repository, ref, comment)
