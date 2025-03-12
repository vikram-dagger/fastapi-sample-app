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
        You are an expert in the Python FastAPI framework, with a deep understanding of its lifecycle and ecosystem. You are also an expert in Pydantic, SQLAlchemy and the Repository pattern.

        Your task is to resolve failing unit tests in a FastAPI application which uses Pydantic and SQLAlchemy. If the error is due to an additional or missing field, update the models and the test cases accordingly.

        You have access to a workspace with write_file, read_file, ls, diff, and test tools. You must use these tools to identify the errors and fix the failing tests. Once you are done, provide a brief explanation of your reasoning and process.

        Do not assume that errors are related to database connectivity or initialization. The database service is ephemeral. It can only be initialized and used with the test tool. Do not directly modify database configuration settings in your attempts to fix the failing tests.

        The write_file tool creates a new file. When making changes with the write_file tool, you must be extremely careful to avoid overwriting the entire file. To make changes with the write_file tool, read the original file contents, modify in place, and write the complete modified contents back. Double check that you have not deleted important code when modifying existing files.

        Additional requirements:

        Focus only on Python files within the current working directory.
        Begin by reading relevant files from the workspace.
        Use the write_file, read_file, ls, diff, and test tools only.
        Do not interact directly with the database; use the test tool only.
        Make the smallest change required to fix the failing tests.
        Write changes directly to the files in the workspace and only run the tests after.
        Use diff to compare your changes with the original files.
        Confirm the tests pass by running the test tool (not pytest or any other tool).
        Do not install new tools.
        Do not stop until all tests pass with the test tool.
        When all the tests pass, you are done and you should stop making further changes.
        """
        after = await (
            dag.llm()
            .with_workspace(before)
            .with_prompt(prompt)
            .sync()
        )

        # completed_work = after.workspace().container().directory("/app")

        summary = await after.with_prompt("After all tests pass, you are done. Summarize your changes. Use the diff tool from the workspace to obtain a list of all the changes you made. Include that diff in your summary.").last_reply()

        return await dag.workspace(source=source, token=token).comment(repository, ref, summary)
