from typing import Annotated
from datetime import datetime

import dagger
from dagger import Container, dag, Directory, DefaultPath, Doc, File, Secret, function, object_type, ReturnType


@object_type
class Book:
    source: Annotated[dagger.Directory, DefaultPath(".")]

    @function
    def env(self, version: str = "3.11") -> dagger.Container:
        """Returns a container with the Python environment and the source code mounted"""
        return (
            dag.container()
            .from_(f"python:{version}")
            .with_directory("/app", self.source.without_directory(".dagger"))
            .with_workdir("/app")
            .with_mounted_cache("/root/.cache/pip", dag.cache_volume("python-pip"))
            .with_exec(["pip", "install", "-r", "requirements.txt"])
        )

    @function
    def run(self) -> dagger.Service:
        """Starts the FastAPI server and returns the service"""
        postgresdb = (
            dag.container()
            .from_("postgres:alpine")
            .with_env_variable("POSTGRES_DB", "app")
            .with_env_variable("POSTGRES_PASSWORD", "secret")
            .with_exposed_port(5432)
            .as_service(args=[], use_entrypoint=True)
        )

        return (
            self.env()
            .with_service_binding("db", postgresdb)
            .with_env_variable("DATABASE_URL", "postgresql://postgres:secret@db/app")
            .with_env_variable("CACHEBUSTER", str(datetime.now()))
            .with_exec(["fastapi", "run", "main.py"])
            .as_service()
        )



    @function
    async def test(self) -> str:
        """Runs the tests in the source code and returns the output"""
        postgresdb = (
            dag.container()
            .from_("postgres:alpine")
            .with_env_variable("POSTGRES_DB", "app_test")
            .with_env_variable("POSTGRES_PASSWORD", "secret")
            .with_exposed_port(5432)
            .as_service(args=[], use_entrypoint=True)
        )

        cmd = (
            self.env()
            .with_service_binding("db", postgresdb)
            .with_env_variable("DATABASE_URL", "postgresql://postgres:secret@db/app_test")
            .with_env_variable("CACHEBUSTER", str(datetime.now()))
            .with_exec(["sh", "-c", "pytest --tb=short"], expect=ReturnType.ANY)
        )
        if await cmd.exit_code() != 0:
            stderr = await cmd.stderr()
            stdout = await cmd.stdout()
            raise Exception(f"Tests failed. \nError: {stderr} \nOutput: {stdout}")
        return await cmd.stdout()

    @function
    def fix(
        self,
        source: Annotated[dagger.Directory, DefaultPath("/")]
    ) -> dagger.Directory:
        """Fixes the code in the source directory and returns the updated directory"""
        environment = (
            dag.env(privileged=True)
            .with_workspace_input("before", dag.workspace(source=source), "the workspace to use for code and tests")
            .with_workspace_output("after", "the workspace with the updated code")
        )

        prompt = f"""
        - You are an expert in the Python FastAPI framework.
        - You are also an expert in Pydantic, SQLAlchemy and the Repository pattern.
        - The tests are failing
        - You know that the errors are not related to database configuration or connectivity
        - You have access to a workspace with the code and the tests
        - The workspace has tools to let you read and write the code
        - In your workspace, fix the issues so that the tests pass
        - Be sure to always write your changes to the workspace
        - Do not delete any fields from the models.
        - Always run the test tool after writing changes to the workspace
        - You are not done until the test tool is successful
        - Focus only on Python files within the /app directory
        - Do not interact directly with the database; use the test tool only
        - Return the modified workspace once you are done
        """
        work = (
            dag.llm()
            .with_env(environment)
            .with_prompt(prompt)
        )

        return work.env().output("after").as_workspace().container().directory("/app")

    @function
    async def diagnose(
        self,
        source: Annotated[dagger.Directory, DefaultPath("/")],
        repository: Annotated[str, Doc("The owner and repository name")],
        ref: Annotated[str, Doc("The ref name")],
        token: Annotated[Secret, Doc("GitHub API token")],
        fix: Annotated[bool, Doc("Whether to open a new PR with the changes or not")] = True,
    ) -> str:
        """Diagnoses the code in the source directory and returns a comment and PR with the changes"""
        environment = (
            dag.env(privileged=True)
            .with_workspace_input("before", dag.workspace(source=source), "the workspace to use for code and tests")
            .with_workspace_output("after", "the workspace with the modified code")
            .with_string_output("summary", "proposal describing the changes the reader should make")
        )

        prompt = f"""
        - You are an expert in the Python FastAPI framework.
        - You are also an expert in Pydantic, SQLAlchemy and the Repository pattern.
        - The tests are failing
        - You know that the errors are not related to database configuration or connectivity
        - You have access to a workspace with the code and the tests
        - The workspace has tools to let you read and write the code
        - In your workspace, fix the issues so that the tests pass
        - Be sure to always write your changes to the workspace
        - Always run the test tool after writing changes to the workspace
        - You are not done until the test tool is successful
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

        if fix:
            # create new PR with the changes
            pr_url = await dag.workspace(source=source, token=token).open_pr(repository, ref, diff_file)

        diff = await diff_file.contents()

        # post comment with changes
        comment_body = f"{summary}\n\nDiff:\n\n```{diff}```"

        if fix:
            comment_body += f"\n\nPR with fixes: {pr_url}"

        comment_url = await dag.workspace(source=source, token=token).comment(repository, ref, comment_body)
        return f"Comment posted: {comment_url}"
