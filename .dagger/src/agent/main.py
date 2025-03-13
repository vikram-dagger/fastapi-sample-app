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
            .with_prompt("Read the code in the workspace. Read the code diff below. Summarize the changes as a proposal for the reader. Include the proposal plus the code diff in your final response. <diff>$diff</diff>")
            .last_reply()
        )

        return await dag.workspace(source=source, token=token).comment(repository, ref, summary)
