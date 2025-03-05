from typing import Annotated, Self
from dagger import Container, dag, Directory, DefaultPath, Doc, Secret, function, object_type, ReturnType
import re

@object_type
class Workspace:
    ctr: Container
    source: Directory
    token: Secret | None = None

    @classmethod
    async def create(
        cls,
        source: Annotated[Directory, Doc("The context for the workspace"), DefaultPath("/")],
        token: Annotated[Secret | None, Doc("GitHub API token")],
    ):
        ctr = (
            dag
            .container()
            .from_("python:3.11")
            .with_workdir("/app")
            .with_directory("/app", source)
            .with_mounted_cache("/root/.cache/pip", dag.cache_volume("python-pip"))
            .with_exec(["pip", "install", "-r", "requirements.txt"])
        )
        return cls(ctr=ctr, source=source, token=token)

    @function
    async def read_file(
        self,
        path: Annotated[str, Doc("File path to read a file from")]
    ) -> str:
        """Returns the contents of a file in the workspace at the provided path"""
        return await self.ctr.file(path).contents()

    @function
    def write_file(
        self,
        path: Annotated[str, Doc("File path to write a file to")],
        contents: Annotated[str, Doc("File contents to write")]
    ) -> Self:
        """Writes the provided contents to a file in the workspace at the provided path"""
        self.ctr = self.ctr.with_new_file(path, contents)
        return self

    @function
    async def ls(
        self,
        path: Annotated[str, Doc("Path to get the list of files from")]
    ) -> list[str]:
        """Returns the list of files in the workspace at the provided path"""
        return await self.ctr.directory(path).entries()

    @function
    async def test(
        self
    ) -> str:
        postgresdb = (
            dag.container()
            .from_("postgres:alpine")
            .with_env_variable("POSTGRES_DB", "app_test")
            .with_env_variable("POSTGRES_PASSWORD", "secret")
            .with_exposed_port(5432)
            .as_service(args=[], use_entrypoint=True)
        )

        cmd = (
            self.ctr
            .with_service_binding("db", postgresdb)
            .with_env_variable("DATABASE_URL", "postgresql://postgres:secret@db/app_test")
            .with_exec(["sh", "-c", "pytest"], expect=ReturnType.ANY)
            #.with_exec(["pytest"])
        )
        if await cmd.exit_code() != 0:
            raise Exception(f"Tests failed. \nError: {await cmd.stderr()}")
        return await cmd.stdout()

    @function
    async def diff(
        self
    ) -> str:
        """Returns the changes in the workspace so far"""
        source = dag.container().from_("alpine/git").with_workdir("/app").with_directory("/app", self.source)
        # make sure source is a git directory
        if ".git" not in await self.source.entries():
            source = source.with_exec(["git", "init"]).with_exec(["git", "add", "."]).with_exec(["git", "commit", "-m", "'initial'"])
        # return the git diff of the changes in the workspace
        return await source.with_directory(".", self.ctr.directory(".")).with_exec(["git", "diff"]).stdout()

    @function
    async def comment(
        self,
        repository: Annotated[str, Doc("The owner and repository name")],
        ref: Annotated[str, Doc("The ref name")],
        body: Annotated[str, Doc("The comment body")],
    ) -> str:
        """Adds a comment to the PR"""
        repository_url = f"https://github.com/{repository}"
        pr_number = int(re.search(r"(\d+)", ref).group(1))
        return await (
          dag
          .github_comment(self.token, repository_url, issue=pr_number)
          .create(body)
        )



    @function
    def container(
        self
    ) -> Container:
        """Returns the container for the workspace"""
        return self.ctr
