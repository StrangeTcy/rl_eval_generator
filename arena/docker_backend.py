"""Docker execution backend for generated environments.

Only the host-side controller talks to the model API.  Agent and judge
containers are deliberately given no network and receive no API credentials.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class DockerBackendError(RuntimeError):
    """Raised when Docker cannot build or run an isolated task."""


@dataclass
class ImageInfo:
    name: str
    image_id: str | None
    digest: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {"name": self.name, "id": self.image_id, "digest": self.digest}


@dataclass
class ContainerResult:
    stdout: str
    stderr: str
    returncode: int
    command: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "stdout": self.stdout,
            "stderr": self.stderr,
            "returncode": self.returncode,
        }


def _run(
    command: list[str],
    *,
    cwd: Path | None = None,
    timeout: float | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=check,
            shell=False,
        )
    except FileNotFoundError as exc:
        raise DockerBackendError("Docker executable was not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise DockerBackendError("Docker command timed out") from exc


def _failure_message(proc: subprocess.CompletedProcess[str]) -> str:
    detail = (proc.stderr or proc.stdout or "").strip()
    return f"Docker command failed with exit status {proc.returncode}" + (
        f": {detail[-2000:]}" if detail else ""
    )


class DockerBackend:
    """Build and run the generated agent/judge images with fixed restrictions."""

    def __init__(
        self,
        *,
        docker: str = "docker",
        command_runner: Any = None,
        build_timeout: float = 1800,
        agent_timeout: float = 180,
        judge_timeout: float = 2100,
    ) -> None:
        self.docker = docker
        self.command_runner = command_runner
        self.build_timeout = build_timeout
        self.agent_timeout = agent_timeout
        self.judge_timeout = judge_timeout

    def _exec(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        timeout: float | None = None,
        check: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        if self.command_runner is not None:
            result = self.command_runner(
                command, cwd=cwd, timeout=timeout, check=check
            )
            if isinstance(result, subprocess.CompletedProcess):
                return result
            return subprocess.CompletedProcess(command, 0, stdout=str(result), stderr="")
        return _run(command, cwd=cwd, timeout=timeout, check=check)

    def check_available(self) -> str:
        proc = self._exec([self.docker, "version", "--format", "{{.Server.Version}}"], timeout=20)
        if proc.returncode != 0:
            raise DockerBackendError(_failure_message(proc))
        return proc.stdout.strip()

    def _inspect_image(self, image: str) -> ImageInfo:
        proc = self._exec(
            [
                self.docker,
                "image",
                "inspect",
                image,
                "--format",
                "{{json .}}",
            ],
            timeout=30,
        )
        if proc.returncode != 0:
            raise DockerBackendError(_failure_message(proc))
        try:
            info = json.loads(proc.stdout.strip())
        except json.JSONDecodeError as exc:
            raise DockerBackendError("Docker image inspect returned invalid JSON") from exc
        repo_digests = info.get("RepoDigests") or []
        digest = str(repo_digests[0]) if repo_digests else None
        return ImageInfo(name=image, image_id=info.get("Id"), digest=digest)

    def build_image(self, image: str, dockerfile: Path, context: Path) -> ImageInfo:
        command = [
            self.docker,
            "build",
            "-t",
            image,
            "-f",
            str(dockerfile),
            str(context),
        ]
        proc = self._exec(command, timeout=self.build_timeout)
        if proc.returncode != 0:
            raise DockerBackendError(_failure_message(proc))
        return self._inspect_image(image)

    def build_environment(self, env_dir: Path, episode_id: str) -> tuple[ImageInfo, ImageInfo]:
        """Build both images from the generated environment directory."""

        self.check_available()
        safe_id = "".join(ch if ch.isalnum() or ch in "_.-" else "_" for ch in episode_id)
        agent_name = f"rl-eval-{safe_id}-agent"
        judge_name = f"rl-eval-{safe_id}-judge"
        agent = self.build_image(
            agent_name, env_dir / "agent" / "Dockerfile", env_dir / "agent"
        )
        try:
            judge = self.build_image(judge_name, env_dir / "judge" / "Dockerfile", env_dir)
        except Exception:
            # Avoid leaving a tagged agent image behind when the second build
            # fails before an episode state can be written.
            try:
                self.remove_images(agent_name)
            except DockerBackendError:
                pass
            raise
        return agent, judge

    @staticmethod
    def _bind(path: Path, destination: str, *, readonly: bool = False) -> str:
        suffix = ",readonly" if readonly else ""
        return f"type=bind,src={path.resolve()},dst={destination}{suffix}"

    def agent_command(
        self,
        image: str,
        workspace: Path,
        tools: Path,
        command: str,
    ) -> list[str]:
        """Return the argument-vector for a no-network agent command."""

        return [
            self.docker,
            "run",
            "--rm",
            "--read-only",
            "--network",
            "none",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            "256",
            "--ulimit",
            "nofile=1024:1024",
            "--memory",
            "4g",
            "--cpus",
            "2",
            "--tmpfs",
            "/tmp:size=256m",
            "--mount",
            self._bind(workspace, "/workspace"),
            "--mount",
            self._bind(tools, "/tools", readonly=True),
            "--workdir",
            "/workspace",
            image,
            "/bin/sh",
            "-lc",
            command,
        ]

    def run_agent(
        self,
        image: str,
        workspace: Path,
        tools: Path,
        command: str,
    ) -> ContainerResult:
        argv = self.agent_command(image, workspace, tools, command)
        try:
            proc = self._exec(argv, timeout=self.agent_timeout)
        except DockerBackendError as exc:
            return ContainerResult("", str(exc), 125, argv)
        return ContainerResult(proc.stdout or "", proc.stderr or "", proc.returncode, argv)

    def judge_command(self, image: str, submission_dir: Path, seed: int) -> list[str]:
        """Return the restricted judge invocation.

        The only bind mount is the read-only submission directory.  Originals
        and judge code are already in the generated judge image.
        """

        return [
            self.docker,
            "run",
            "--rm",
            "--read-only",
            "--network",
            "none",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            "256",
            "--memory",
            "6g",
            "--cpus",
            "2",
            "--tmpfs",
            "/tmp:uid=10001,gid=10001,mode=1777,size=1g",
            "-e",
            f"JUDGE_SEED={seed}",
            "--mount",
            self._bind(submission_dir, "/submission", readonly=True),
            image,
        ]

    def run_judge(self, image: str, submission_dir: Path, seed: int) -> ContainerResult:
        argv = self.judge_command(image, submission_dir, seed)
        try:
            proc = self._exec(argv, timeout=self.judge_timeout)
        except DockerBackendError as exc:
            return ContainerResult("", str(exc), 125, argv)
        return ContainerResult(proc.stdout or "", proc.stderr or "", proc.returncode, argv)

    def remove_images(self, *images: str | None) -> list[str]:
        removed: list[str] = []
        for image in images:
            if not image:
                continue
            proc = self._exec([self.docker, "image", "rm", "-f", image], timeout=60)
            if proc.returncode == 0:
                removed.append(image)
        return removed


__all__ = [
    "ContainerResult",
    "DockerBackend",
    "DockerBackendError",
    "ImageInfo",
]
