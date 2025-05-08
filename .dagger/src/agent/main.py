from typing import Annotated, List
import re
import requests

import dagger
from dagger import DefaultPath, Secret, Doc, File, dag, function, object_type

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
        fix: Annotated[bool, Doc("Whether to open a new PR with the changes or not")] = True,
    ) -> str:
        environment = (
            dag.env()
            .with_workspace_input("before", dag.workspace(source=source), "the workspace to use for code and tests")
            .with_workspace_output("after", "the workspace with the modified code")
            .with_string_output("summary", "proposal describing the changes the reader should make")
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
        - Once done, summarize your changes, then rewrite as proposed actions the reader "should" take
        - Return the modified workspace along with your summary
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

        # diff of the changes in a file
        diff_file = await (
            work
            .env()
            .output("after")
            .as_workspace()
            .container()
            .with_exec(["sh", "-c", "git diff > /tmp/a.diff"])
            .file("/tmp/a.diff")
        )

        diff = await diff_file.contents()

        # post comment with changes
        comment = f"{summary}\n\nDiff:\n\n```{diff}```"
        comment_url = await dag.workspace(source=source, token=token).comment(repository, ref, comment)
        result_str = f"Comment posted: {comment_url}"

        if fix:
            # create new PR with the changes
            pr_url = await dag.workspace(source=source, token=token).open_pr(repository, ref, diff_file)
            result_str += f"\n\nPR created: {pr_url}"

        return result_str
