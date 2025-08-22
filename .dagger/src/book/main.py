import random
from typing import Annotated
from datetime import datetime

import dagger
from dagger import Container, dag, field, Directory, DefaultPath, Doc, File, Secret, function, object_type, ReturnType

@object_type
class Result:
    """Custom type to handle the result of local and GitHub fixes"""
    fdirectory: dagger.Directory = field()
    fsummary: str = field()

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
    async def test(self) -> str:
        """Runs the tests in the source code and returns the output"""
        postgresdb =  (
            dag.container()
            .from_("postgres:alpine")
            .with_env_variable("POSTGRES_DB", "app_test")
            .with_env_variable("POSTGRES_PASSWORD", "app_test_secret")
            .with_exposed_port(5432)
            .as_service(args=[], use_entrypoint=True)
        )

        cmd = (
            self.env()
            .with_service_binding("db", postgresdb)
            .with_env_variable("DATABASE_URL", "postgresql://postgres:app_test_secret@db/app_test")
            .with_env_variable("CACHEBUSTER", str(datetime.now()))
            .with_exec(["sh", "-c", "PYTHONPATH=$(pwd) pytest --tb=short"], expect=ReturnType.ANY)
        )
        if await cmd.exit_code() != 0:
            stderr = await cmd.stderr()
            stdout = await cmd.stdout()
            raise Exception(f"Tests failed. \nError: {stderr} \nOutput: {stdout}")
        return await cmd.stdout()

    @function
    def serve(self) -> dagger.Service:
        """Serves the application"""
        postgresdb =  (
            dag.container()
            .from_("postgres:alpine")
            .with_env_variable("POSTGRES_DB", "app")
            .with_env_variable("POSTGRES_PASSWORD", "app_secret")
            .with_exposed_port(5432)
            .as_service(args=[], use_entrypoint=True)
        )

        return (
            self.build()
            .with_service_binding("db", postgresdb)
            .with_env_variable("DATABASE_URL", "postgresql://postgres:app_secret@db/app")
            .as_service(args=[], use_entrypoint=True)
        )

    @function
    def build(self) -> dagger.Container:
        """Builds the application container"""
        return (
            self.env()
            .with_exposed_port(8000)
            #.with_entrypoint(["fastapi", "run", "main.py", "--host", "0.0.0.0", "--port", "8000"])
            .with_entrypoint(["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "trace"])
        )

    @function
    async def publish(self) -> str:
        """Builds and publishes the application container to a registry"""
        await self.test()
        return await (
            self.build()
            .publish(f"ttl.sh/my-fastapi-app-{random.randrange(10**8)}")
        )


    @function
    async def fix(
        self,
        source: Annotated[dagger.Directory, DefaultPath("/")],
        repository: Annotated[str, Doc("Owner and repository name")] | None = None,
        ref: Annotated[str, Doc("Git ref")] | None = None,
        token: Annotated[Secret, Doc("GitHub API token")] | None = None,
    ) -> Result:
        """Diagnoses test failures in the source code and fixes them"""
        if repository and ref and token:
            fsummary = await self.fix_github(source, repository, ref, token)
            fdirectory = None
        else:
            fdirectory = await self.fix_local(source)
            fsummary = "Local fix completed"
        return Result(fdirectory=fdirectory, fsummary=fsummary)

    async def fix_local(
        self,
        source: Annotated[dagger.Directory, DefaultPath("/")],
    ) -> dagger.Directory:
        """Diagnoses test failures in the source directory and fixes them"""
        environment = (
            dag.env(privileged=True)
            .with_workspace_input("before", dag.workspace(source=source), "the workspace to use for code and tests")
            .with_workspace_output("after", "the workspace with the modified code")
            .with_string_output("summary", "list of changes made")
        )

        prompt_file = dag.current_module().source().file("src/book/prompt.fix.txt")

        work = (
            dag.llm()
            .with_env(environment)
            .with_prompt_file(prompt_file)
        )

        return await work.env().output("after").as_workspace().container().directory("/app")

    async def fix_github(
        self,
        source: Annotated[dagger.Directory, DefaultPath("/")],
        repository: Annotated[str, Doc("Owner and repository name")],
        ref: Annotated[str, Doc("Git ref")],
        token: Annotated[Secret, Doc("GitHub API token")],
    ) -> str:
        """Diagnoses test failures in the source repository and opens a PR with fixes"""
        environment = (
            dag.env(privileged=True)
            .with_workspace_input("before", dag.workspace(source=source), "the workspace to use for code and tests")
            .with_workspace_output("after", "the workspace with the modified code")
            .with_string_output("summary", "list of changes made")
        )

        prompt_file = dag.current_module().source().file("src/book/prompt.fix.txt")

        work = (
            dag.llm()
            .with_env(environment)
            .with_prompt_file(prompt_file)
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

        # open PR with changes
        pr_url = await dag.github_api().create_pr(repository, ref, diff_file, token)

        # post comment with changes
        diff = await diff_file.contents()
        comment_body = f"{summary}\n\nDiff:\n\n```{diff}```"
        comment_body += f"\n\nPR with fixes: {pr_url}"
        comment_url = await dag.github_api().create_comment(repository, ref, comment_body, token)

        return f"Comment posted: {comment_url}"
