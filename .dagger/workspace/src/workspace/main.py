from typing import Annotated, Self
from datetime import datetime

from dagger import Container, dag, Directory, DefaultPath, Doc, File, Secret, function, object_type, ReturnType


@object_type
class Workspace:
    ctr: Container
    source: Directory

    @classmethod
    async def create(
        cls,
        source: Annotated[Directory, Doc("The context for the workspace"), DefaultPath("/")],
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
        return cls(ctr=ctr, source=source)

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
    async def list_files(
        self,
        path: Annotated[str, Doc("Path to get the list of files from")]
    ) -> list[str]:
        """Returns the list of files in the workspace at the provided path"""
        return await self.ctr.directory(path).entries()

    # TODO: duplication from main module, remove once self calls are supported
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
            self.ctr
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
    def container(
        self
    ) -> Container:
        """Returns the container for the workspace"""
        return self.ctr
