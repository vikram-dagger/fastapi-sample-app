from typing import Annotated, Self, List
from datetime import datetime
import requests
import json
import re

from dagger import Container, dag, Directory, DefaultPath, Doc, File, Secret, function, object_type, ReturnType


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
            .with_env_variable("CACHEBUSTER", str(datetime.now()))
            .with_exec(["sh", "-c", "pytest --tb=short"], expect=ReturnType.ANY)
            #.with_exec(["pytest"])
        )
        if await cmd.exit_code() != 0:
            stderr = await cmd.stderr()
            stdout = await cmd.stdout()
            raise Exception(f"Tests failed. \nError: {stderr} \nOutput: {stdout}")
        return await cmd.stdout()


    @function
    async def comment(
        self,
        repository: Annotated[str, Doc("The owner and repository name")],
        ref: Annotated[str, Doc("The ref name")],
        body: Annotated[str, Doc("The comment body")],
    ) -> str:
        """Adds a comment to the PR"""
        #repository_url = f"https://github.com/{repository}"
        pr_number = int(re.search(r"(\d+)", ref).group(1))

        url = f"https://api.github.com/repos/{repository}/issues/{pr_number}/comments"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json"
        }
        data = {
            "body": body
        }
        response = requests.post(url, headers=headers, json=data)

        if response.status_code == 201:
            return f"{response.json()['html_url']}"
        else:
            raise Exception(f"Failed to post comment: {response.status_code} - {response.text}")


    @function
    async def open_pr(
        self,
        repository: Annotated[str, Doc("The owner and repository name")],
        ref: Annotated[str, Doc("The ref name")],
        diff_file: Annotated[File, Doc("The diff file")],
    ) -> str:

        plaintext = await self.token.plaintext()
        pr_number = int(re.search(r"(\d+)", ref).group(1))
        new_branch = f"patch-from-pr-{pr_number}"
        remote_url = f"https://{plaintext}@github.com/{repository}.git"
        diff = await diff_file.contents()

        await (
            dag
            .container()
            .from_("alpine/git")
            .with_new_file("/tmp/a.diff", f"{diff}")
            .with_workdir("/app")
            .with_exec(["git", "init"])
            .with_exec(["git", "config", "user.name", "Dagger Agent"])
            .with_exec(["git", "config", "user.email", "vikram@dagger.io"])
            .with_exec(["git", "remote", "add", "origin", remote_url])
            .with_exec(["git", "fetch", "origin", f"pull/{pr_number}/head:{new_branch}"])
            .with_exec(["git", "checkout", new_branch])
            .with_exec(["git", "apply", "/tmp/a.diff"])
            .with_exec(["git", "add", "."])
            .with_exec(["git", "commit", "-m", f"Apply changes based on PR #{pr_number}"])
            .with_exec(["git", "push", "--set-upstream", "origin", new_branch])
            .stdout()
        )

        headers = {
            "Authorization": f"Bearer {plaintext}",
            "Accept": "application/vnd.github+json"
        }
        pr_url = f"https://api.github.com/repos/{repository}/pulls/{pr_number}"
        pr_response = requests.get(pr_url, headers=headers)

        if pr_response.status_code != 200:
            raise Exception(f"Failed to fetch original PR: {pr_response.text}")

        pr_data = pr_response.json()
        base_branch = pr_data["head"]["ref"]

        create_pr_url = f"https://api.github.com/repos/{repository}/pulls"
        head_user = repository.split("/")[0]
        head = f"{head_user}:{new_branch}"

        payload = {
            "title": f"Automated follow-up to PR #{pr_number}",
            "body": f"This PR fixes PR #{pr_number} using `{new_branch}`.",
            "head": head,
            "base": base_branch
        }

        create_response = requests.post(create_pr_url, headers=headers, json=payload)
        if create_response.status_code != 201:
            raise Exception(f"Failed to create new PR: {create_response.text}")

        new_pr = create_response.json()
        return f"{new_pr['html_url']}"


    @function
    def container(
        self
    ) -> Container:
        """Returns the container for the workspace"""
        return self.ctr
