from typing import Annotated

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
        - Once all the tests pass, you are done. End your assignment and return a diff of the changes you made.
        """
        after = await (
            dag.llm()
            .with_workspace(before)
            .with_prompt(prompt)
            .sync()
        )

        diff = after.last_reply()

        summary = await (
            dag.llm()
            .with_workspace(before)
            .with_prompt_var("diff", diff)
            .with_prompt("Read the code in the workspace. Read the diff below. Summarize the changes made to the code using the diff. Include the diff in your final response. <diff>$diff</diff>")
            .last_reply()
        )

        # await after.with_prompt("After all tests pass, you are done. Summarize your changes. Use the diff tool from the workspace to obtain a list of all the changes you made. Include that diff in your summary.").last_reply()

        return await dag.workspace(source=source, token=token).comment(repository, ref, summary)
