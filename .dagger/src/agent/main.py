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
            .with_string_output("summary", "explanation of the changes made")
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
        - Once done, return the modified workspace and a summary of the changes made
        - The summary should be a short explanation of the changes made
        """
        work = (
            dag.llm()
            .with_env(environment)
            .with_prompt(prompt)
        )

        summary = await (
            work
            .env()
            .output("summary")
            .as_string()
        )

        diff = await (
            work
            .env()
            .output("after")
            .as_workspace()
            .container()
            .with_exec(["git", "diff"])
            .stdout()
        )


        #diff = await work.last_reply()

        #environment = (
        #    dag.env()
        #    .with_workspace_input("before", dag.workspace(source=source), "the workspace to use for code and tests")
        #    .with_string_input("diff", diff, "the code diff")
        #    #.with_string_output("proposal", "the summary proposal including the diff")
        #)

        #work = (
        #    dag.llm()
        #    .with_env(environment)
        #    .with_prompt("Read the code in the workspace. Read the code diff in $diff. Summarize the changes as a proposal for the reader. Include the proposal plus the code diff in $diff in your final response.")
        #)

        #summary = await work.last_reply()
        comment = f"diff: {diff}\n\nsummary: {summary}"
        return await dag.workspace(source=source, token=token).comment(repository, ref, summary)

        #print(f"diff: {diff}\n\nsummary: {summary}")
        #return f"diff: {diff}\n\nsummary: {summary}"
