"""Per-worktree JSONL task decomposition manager.

Factory worktrees deliberately do not use the host Beads database. Every task
operation is applied directly to ``.beads/issues.jsonl`` under a bounded file
lock and persisted with an atomic replacement. Tracked Beads metadata may
still describe a historical Dolt/server store; this module never reads it and
never starts, migrates, or connects to a database.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import secrets
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from file_util import descriptor_lock, file_lock_fd

if TYPE_CHECKING:
    from task_graph import TaskGraphPhase

# Priority mapping: Task Graph phases without deps are P0 (critical), others P1.
_PRIORITY_NO_DEPS = "0"
_PRIORITY_HAS_DEPS = "1"

_BEADS_DIR_MODE = 0o700
_BEADS_FILE_MODE = 0o600
_ISSUES_FILE = "issues.jsonl"
_LOCK_FILE = ".issues.jsonl.lock"
_MAX_ID_ATTEMPTS = 32
_VALID_STATUSES = frozenset({"open", "in_progress", "closed"})
_PHASE_REF_PREFIX = "hydraflow-factory"


@dataclass
class _StoreHandle:
    """Open, verified descriptors for one locked worktree task store."""

    cwd_fd: int
    directory_fd: int
    lock_fd: int
    issues_fd: int
    directory_path: Path
    issues_path: Path
    lock_path: Path


class BeadsNotInstalledError(RuntimeError):
    """Legacy compatibility exception for callers importing this symbol.

    The JSONL manager has no external executable dependency and therefore
    never raises this exception itself.
    """


class BeadTask(BaseModel):
    """A single task in the worktree-local JSONL store."""

    id: str
    title: str
    status: str = "open"
    priority: int = 2
    depends_on: list[str] = Field(default_factory=list)


class BeadsManager:
    """Manage an isolated worktree's ``.beads/issues.jsonl`` task graph.

    All public methods retain the former async API so pipeline collaborators
    and :class:`mockworld.fakes.fake_beads.FakeBeads` remain interchangeable.
    Blocking filesystem work runs in a worker thread. Mutations take a bounded
    cross-process lock and replace the JSONL file atomically.
    """

    async def ensure_installed(self) -> None:
        """Retained API hook; JSONL mode requires no ``bd`` installation."""

    async def init(self, cwd: Path) -> None:
        """Initialize and validate the worktree-local JSONL store.

        Existing valid ``issues.jsonl`` content is never rewritten, so init is
        byte-preserving and idempotent. Invalid JSONL fails loudly instead of
        being overwritten.
        """

        await asyncio.to_thread(self._init_sync, cwd)

    async def export(self, cwd: Path) -> None:
        """Validate the canonical JSONL artifact without rewriting it.

        JSONL is already the source of truth, not an export of another store.
        This method remains for API compatibility with existing callers.
        """

        await asyncio.to_thread(self._validate_sync, cwd)

    async def create_task(self, title: str, priority: str, cwd: Path) -> str:
        """Create a task atomically and return its collision-safe ID."""

        return await asyncio.to_thread(self._create_task_sync, title, priority, cwd)

    async def add_dependency(self, child: str, parent: str, cwd: Path) -> None:
        """Record that *child* depends on *parent*."""

        await asyncio.to_thread(self._add_dependency_sync, child, parent, cwd)

    async def claim(self, bead_id: str, cwd: Path) -> None:
        """Set a task's status to ``in_progress``."""

        await asyncio.to_thread(self._set_status_sync, bead_id, "in_progress", cwd)

    async def close(self, bead_id: str, reason: str, cwd: Path) -> None:
        """Close a task and retain the supplied close reason."""

        await asyncio.to_thread(self._close_sync, bead_id, reason, cwd)

    async def list_ready(self, cwd: Path) -> list[BeadTask]:
        """Return non-closed tasks whose known dependencies are closed."""

        return await asyncio.to_thread(self._list_ready_sync, cwd)

    async def show(self, bead_id: str, cwd: Path) -> BeadTask:
        """Return one task, raising ``KeyError`` when it does not exist."""

        return await asyncio.to_thread(self._show_sync, bead_id, cwd)

    async def create_from_phases(
        self,
        phases: list[TaskGraphPhase],
        issue_number: int,
        cwd: Path,
    ) -> dict[str, str]:
        """Create a phase graph in one locked, atomic JSONL transaction."""

        return await asyncio.to_thread(
            self._create_from_phases_sync,
            phases,
            issue_number,
            cwd,
        )

    @classmethod
    def _init_sync(cls, cwd: Path) -> None:
        with cls._locked_store(cwd) as path:
            cls._read_validated_records(path)

    @classmethod
    def _validate_sync(cls, cwd: Path) -> None:
        with cls._locked_store(cwd) as path:
            cls._read_validated_records(path)

    @classmethod
    def _create_task_sync(cls, title: str, priority: str, cwd: Path) -> str:
        if not isinstance(title, str) or not title.strip():
            raise ValueError("Beads task title must be a non-empty string")
        parsed_priority = cls._parse_priority(priority)
        with cls._locked_store(cwd) as path:
            records = cls._read_validated_records(path)
            bead_id = cls._new_id(cwd, records)
            record: dict[str, Any] = {
                "_type": "issue",
                "id": bead_id,
                "title": title,
                "status": "open",
                "priority": parsed_priority,
                "dependencies": [],
            }
            cls._validate_issue_record(record)
            records.append(record)
            cls._write_records(path, records)
        return bead_id

    @classmethod
    def _add_dependency_sync(
        cls,
        child: str,
        parent: str,
        cwd: Path,
    ) -> None:
        with cls._locked_store(cwd) as path:
            records = cls._read_validated_records(path)
            issues = cls._issue_index(records)
            if child not in issues:
                raise KeyError(f"unknown bead task: {child}")
            if parent not in issues:
                raise KeyError(f"unknown bead task: {parent}")

            record = issues[child]
            dependency_field = (
                "depends_on"
                if "depends_on" in record and "dependencies" not in record
                else "dependencies"
            )
            dependencies = record.setdefault(dependency_field, [])
            if not isinstance(dependencies, list):
                raise RuntimeError(f"invalid dependencies for bead task: {child}")
            if parent in cls._dependency_ids(record):
                return
            if dependency_field == "depends_on":
                dependencies.append(parent)
            else:
                dependencies.append(
                    {
                        "issue_id": child,
                        "depends_on_id": parent,
                        "type": "blocks",
                    }
                )
            cls._validate_records(records)
            cls._write_records(path, records)

    @classmethod
    def _set_status_sync(cls, bead_id: str, status: str, cwd: Path) -> None:
        with cls._locked_store(cwd) as path:
            records = cls._read_validated_records(path)
            record = cls._require_issue(records, bead_id)
            current = record.get("status", "open")
            if current == status:
                return
            if current == "closed" and status == "in_progress":
                raise RuntimeError(f"cannot claim closed bead task: {bead_id}")
            record["status"] = status
            cls._write_records(path, records)

    @classmethod
    def _close_sync(cls, bead_id: str, reason: str, cwd: Path) -> None:
        with cls._locked_store(cwd) as path:
            records = cls._read_validated_records(path)
            record = cls._require_issue(records, bead_id)
            record["status"] = "closed"
            record["close_reason"] = reason
            cls._write_records(path, records)

    @classmethod
    def _list_ready_sync(cls, cwd: Path) -> list[BeadTask]:
        with cls._locked_store(cwd) as path:
            records = cls._read_validated_records(path)
        issues = cls._issue_index(records)
        ready: list[BeadTask] = []
        for record in records:
            bead_id = record.get("id")
            if not cls._is_issue(record) or not isinstance(bead_id, str):
                continue
            if record.get("status", "open") == "closed":
                continue
            dependencies = (
                issues[dependency] for dependency in cls._dependency_ids(record)
            )
            if all(
                dependency.get("status", "open") == "closed"
                for dependency in dependencies
            ):
                ready.append(cls._record_to_task(record))
        return ready

    @classmethod
    def _show_sync(cls, bead_id: str, cwd: Path) -> BeadTask:
        with cls._locked_store(cwd) as path:
            records = cls._read_validated_records(path)
        return cls._record_to_task(cls._require_issue(records, bead_id))

    @classmethod
    def _create_from_phases_sync(
        cls,
        phases: list[TaskGraphPhase],
        issue_number: int,
        cwd: Path,
    ) -> dict[str, str]:
        phase_ids = [phase.id for phase in phases]
        if len(phase_ids) != len(set(phase_ids)):
            raise ValueError("task graph phase IDs must be unique")
        known_phase_ids = set(phase_ids)
        for phase in phases:
            unknown = set(phase.depends_on) - known_phase_ids
            if unknown:
                raise KeyError(
                    f"phase {phase.id} references unknown dependencies: {sorted(unknown)}"
                )
        cls._reject_dependency_cycles(
            {phase.id: list(phase.depends_on) for phase in phases},
            context="task graph phases",
        )

        with cls._locked_store(cwd) as path:
            records = cls._read_validated_records(path)
            existing = cls._existing_phase_mapping(
                records,
                phases,
                issue_number,
            )
            if existing is not None:
                return existing
            mapping: dict[str, str] = {}
            reserved_ids = set(cls._issue_index(records))
            for phase in phases:
                bead_id = cls._new_id(cwd, records, reserved_ids=reserved_ids)
                reserved_ids.add(bead_id)
                mapping[phase.id] = bead_id
                records.append(
                    {
                        "_type": "issue",
                        "id": bead_id,
                        "title": f"Issue #{issue_number} — {phase.name}",
                        "status": "open",
                        "priority": int(
                            _PRIORITY_NO_DEPS
                            if not phase.depends_on
                            else _PRIORITY_HAS_DEPS
                        ),
                        "external_ref": cls._phase_external_ref(
                            issue_number,
                            phase.id,
                        ),
                        "dependencies": [],
                    }
                )

            issues = cls._issue_index(records)
            for phase in phases:
                child = mapping[phase.id]
                dependencies = issues[child]["dependencies"]
                for dependency in phase.depends_on:
                    dependencies.append(
                        {
                            "issue_id": child,
                            "depends_on_id": mapping[dependency],
                            "type": "blocks",
                        }
                    )
            cls._validate_records(records)
            cls._write_records(path, records)
        return mapping

    @classmethod
    def _existing_phase_mapping(
        cls,
        records: list[dict[str, Any]],
        phases: list[TaskGraphPhase],
        issue_number: int,
    ) -> dict[str, str] | None:
        """Recover an already-created graph by its stable issue/phase identity."""
        prefix = f"{_PHASE_REF_PREFIX}:issue:{issue_number}:phase:"
        expected_refs = {
            phase.id: cls._phase_external_ref(issue_number, phase.id)
            for phase in phases
        }
        identified = [
            record
            for record in records
            if cls._is_issue(record)
            and isinstance(record.get("external_ref"), str)
            and record["external_ref"].startswith(prefix)
        ]
        if not identified:
            return None

        by_ref: dict[str, dict[str, Any]] = {}
        for record in identified:
            external_ref = str(record["external_ref"])
            if external_ref in by_ref:
                raise RuntimeError(
                    f"duplicate factory phase identity in JSONL store: {external_ref}"
                )
            by_ref[external_ref] = record
        if set(by_ref) != set(expected_refs.values()):
            raise RuntimeError(
                f"incomplete factory phase graph for issue #{issue_number}"
            )

        mapping = {
            phase_id: str(by_ref[external_ref]["id"])
            for phase_id, external_ref in expected_refs.items()
        }
        for phase in phases:
            actual = set(cls._dependency_ids(by_ref[expected_refs[phase.id]]))
            expected = {mapping[dependency] for dependency in phase.depends_on}
            if actual != expected:
                raise RuntimeError(
                    f"stored factory phase dependencies do not match {phase.id}"
                )
        return mapping

    @staticmethod
    def _phase_external_ref(issue_number: int, phase_id: str) -> str:
        return f"{_PHASE_REF_PREFIX}:issue:{issue_number}:phase:{phase_id}"

    @classmethod
    @contextmanager
    def _locked_store(cls, cwd: Path) -> Iterator[_StoreHandle]:
        beads_dir = cwd / ".beads"
        path = beads_dir / _ISSUES_FILE
        lock_path = beads_dir / _LOCK_FILE
        directory_fd = -1
        issues_fd = -1
        handle: _StoreHandle | None = None
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
        cwd_fd = os.open(cwd, directory_flags)
        try:
            # The worktree directory inode is the authoritative lock. A named
            # lock file can be unlinked and replaced while its old inode remains
            # flocked; locking this already-open stable parent keeps every
            # compliant writer serialized across that replacement race.
            with descriptor_lock(cwd_fd, display_path=beads_dir):
                with contextlib.suppress(FileExistsError):
                    os.mkdir(".beads", _BEADS_DIR_MODE, dir_fd=cwd_fd)
                try:
                    directory_fd = os.open(".beads", directory_flags, dir_fd=cwd_fd)
                except OSError as exc:
                    raise RuntimeError(
                        "unsafe Beads path is a symlink or not a directory: "
                        f"{beads_dir}"
                    ) from exc
                os.fchmod(directory_fd, _BEADS_DIR_MODE)
                cls._verify_named_fd(
                    cwd_fd, ".beads", directory_fd, beads_dir, directory=True
                )

                try:
                    with file_lock_fd(
                        directory_fd,
                        _LOCK_FILE,
                        display_path=lock_path,
                    ) as lock_fd:
                        cls._verify_named_fd(
                            directory_fd, _LOCK_FILE, lock_fd, lock_path
                        )
                        issues_fd = cls._open_regular_file(
                            directory_fd,
                            _ISSUES_FILE,
                            path,
                            create=True,
                        )
                        handle = _StoreHandle(
                            cwd_fd=cwd_fd,
                            directory_fd=directory_fd,
                            lock_fd=lock_fd,
                            issues_fd=issues_fd,
                            directory_path=beads_dir,
                            issues_path=path,
                            lock_path=lock_path,
                        )
                        try:
                            yield handle
                        finally:
                            cls._verify_store_identity(handle)
                except OSError as exc:
                    if lock_path.is_symlink():
                        raise RuntimeError(
                            f"unsafe Beads path is a symlink: {lock_path}"
                        ) from exc
                    raise
        finally:
            if handle is not None:
                os.close(handle.issues_fd)
            elif issues_fd >= 0:
                os.close(issues_fd)
            if directory_fd >= 0:
                os.close(directory_fd)
            os.close(cwd_fd)

    @classmethod
    def _open_regular_file(
        cls,
        directory_fd: int,
        name: str,
        display_path: Path,
        *,
        create: bool,
    ) -> int:
        flags = os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW
        if create:
            flags |= os.O_CREAT
        try:
            fd = os.open(name, flags, _BEADS_FILE_MODE, dir_fd=directory_fd)
        except OSError as exc:
            raise RuntimeError(
                f"unsafe Beads path is a symlink or not a regular file: {display_path}"
            ) from exc
        try:
            opened = os.fstat(fd)
            if not stat.S_ISREG(opened.st_mode):
                raise RuntimeError(
                    f"unsafe Beads path is not a regular file: {display_path}"
                )
            os.fchmod(fd, _BEADS_FILE_MODE)
            cls._verify_named_fd(directory_fd, name, fd, display_path)
        except BaseException:
            os.close(fd)
            raise
        return fd

    @staticmethod
    def _verify_named_fd(
        directory_fd: int,
        name: str,
        fd: int,
        display_path: Path,
        *,
        directory: bool = False,
    ) -> None:
        try:
            named = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            opened = os.fstat(fd)
        except OSError as exc:
            raise RuntimeError(f"unsafe Beads path changed: {display_path}") from exc
        expected_type = stat.S_ISDIR if directory else stat.S_ISREG
        if (
            not expected_type(named.st_mode)
            or not expected_type(opened.st_mode)
            or (named.st_dev, named.st_ino) != (opened.st_dev, opened.st_ino)
        ):
            raise RuntimeError(f"unsafe Beads path changed: {display_path}")

    @classmethod
    def _verify_store_identity(cls, handle: _StoreHandle) -> None:
        cls._verify_named_fd(
            handle.cwd_fd,
            ".beads",
            handle.directory_fd,
            handle.directory_path,
            directory=True,
        )
        cls._verify_named_fd(
            handle.directory_fd,
            _LOCK_FILE,
            handle.lock_fd,
            handle.lock_path,
        )
        cls._verify_named_fd(
            handle.directory_fd,
            _ISSUES_FILE,
            handle.issues_fd,
            handle.issues_path,
        )
        os.fchmod(handle.directory_fd, _BEADS_DIR_MODE)
        os.fchmod(handle.lock_fd, _BEADS_FILE_MODE)
        os.fchmod(handle.issues_fd, _BEADS_FILE_MODE)

    @classmethod
    def _read_records(cls, handle: _StoreHandle) -> list[dict[str, Any]]:
        cls._verify_named_fd(
            handle.directory_fd,
            _ISSUES_FILE,
            handle.issues_fd,
            handle.issues_path,
        )
        try:
            duplicate = os.dup(handle.issues_fd)
            with os.fdopen(duplicate, "r", encoding="utf-8") as stream:
                stream.seek(0)
                content = stream.read()
        except (OSError, UnicodeError) as exc:
            raise RuntimeError(
                f"failed reading Beads JSONL store {handle.issues_path}: {exc}"
            ) from exc
        cls._verify_named_fd(
            handle.directory_fd,
            _ISSUES_FILE,
            handle.issues_fd,
            handle.issues_path,
        )

        records: list[dict[str, Any]] = []
        for line_number, raw_line in enumerate(content.splitlines(), start=1):
            if not raw_line.strip():
                continue
            try:
                record = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"invalid Beads JSONL at {handle.issues_path}:{line_number}: "
                    f"{exc.msg}"
                ) from exc
            if not isinstance(record, dict):
                raise RuntimeError(
                    f"invalid Beads JSONL at {handle.issues_path}:{line_number}: "
                    "expected object"
                )
            records.append(record)
        return records

    @classmethod
    def _read_validated_records(cls, handle: _StoreHandle) -> list[dict[str, Any]]:
        records = cls._read_records(handle)
        cls._validate_records(records)
        return records

    @classmethod
    def _validate_records(cls, records: list[dict[str, Any]]) -> None:
        """Validate issue schema plus complete, acyclic dependencies."""
        issues = cls._issue_index(records)
        dependencies_by_id: dict[str, list[str]] = {}
        for bead_id, record in issues.items():
            dependencies = cls._dependency_ids(record)
            missing = [
                dependency for dependency in dependencies if dependency not in issues
            ]
            if missing:
                raise RuntimeError(
                    f"bead task {bead_id} has unknown dependencies: {missing}"
                )
            dependencies_by_id[bead_id] = dependencies
        cls._reject_dependency_cycles(
            dependencies_by_id,
            context="Beads task graph",
        )

    @staticmethod
    def _reject_dependency_cycles(
        dependencies_by_id: dict[str, list[str]],
        *,
        context: str,
    ) -> None:
        """Reject self-dependencies and cycles using an iterative Kahn pass."""
        for node, dependencies in dependencies_by_id.items():
            if node in dependencies:
                raise RuntimeError(f"{context} contains a self-dependency: {node}")

        remaining_dependencies = {
            node: len(dependencies) for node, dependencies in dependencies_by_id.items()
        }
        dependents: dict[str, list[str]] = {node: [] for node in dependencies_by_id}
        for child, dependencies in dependencies_by_id.items():
            for parent in dependencies:
                dependents[parent].append(child)

        ready = [
            node
            for node, dependency_count in remaining_dependencies.items()
            if dependency_count == 0
        ]
        visited = 0
        while ready:
            parent = ready.pop()
            visited += 1
            for child in dependents[parent]:
                remaining_dependencies[child] -= 1
                if remaining_dependencies[child] == 0:
                    ready.append(child)

        if visited != len(dependencies_by_id):
            cyclic = sorted(
                node
                for node, dependency_count in remaining_dependencies.items()
                if dependency_count > 0
            )
            raise RuntimeError(f"{context} contains a dependency cycle: {cyclic}")

    @classmethod
    def _write_records(
        cls,
        handle: _StoreHandle,
        records: list[dict[str, Any]],
    ) -> None:
        cls._validate_records(records)
        cls._verify_store_identity(handle)
        payload = "".join(
            json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
            for record in records
        ).encode("utf-8")
        temp_name = f".{_ISSUES_FILE}-{secrets.token_hex(8)}.tmp"
        temp_fd = -1
        try:
            temp_fd = os.open(
                temp_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
                _BEADS_FILE_MODE,
                dir_fd=handle.directory_fd,
            )
            os.fchmod(temp_fd, _BEADS_FILE_MODE)
            view = memoryview(payload)
            while view:
                written = os.write(temp_fd, view)
                if written == 0:
                    raise OSError("short write to Beads JSONL temporary file")
                view = view[written:]
            os.fsync(temp_fd)
            cls._verify_named_fd(
                handle.directory_fd,
                _ISSUES_FILE,
                handle.issues_fd,
                handle.issues_path,
            )
            os.replace(
                temp_name,
                _ISSUES_FILE,
                src_dir_fd=handle.directory_fd,
                dst_dir_fd=handle.directory_fd,
            )
            os.fsync(handle.directory_fd)
            replacement_fd = cls._open_regular_file(
                handle.directory_fd,
                _ISSUES_FILE,
                handle.issues_path,
                create=False,
            )
            os.close(handle.issues_fd)
            handle.issues_fd = replacement_fd
        finally:
            if temp_fd >= 0:
                os.close(temp_fd)
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temp_name, dir_fd=handle.directory_fd)

    @classmethod
    def _new_id(
        cls,
        cwd: Path,
        records: list[dict[str, Any]],
        *,
        reserved_ids: set[str] | None = None,
    ) -> str:
        prefix = re.sub(r"[^a-z0-9]+", "-", cwd.name.lower()).strip("-")
        prefix = prefix[:24].rstrip("-") or "bead"
        existing = set(cls._issue_index(records))
        if reserved_ids:
            existing.update(reserved_ids)
        for _ in range(_MAX_ID_ATTEMPTS):
            candidate = f"{prefix}-{secrets.token_hex(4)}"
            if candidate not in existing:
                return candidate
        raise RuntimeError("failed generating a unique Beads task ID")

    @staticmethod
    def _parse_priority(priority: str) -> int:
        try:
            parsed = int(priority)
        except ValueError as exc:
            raise ValueError(f"invalid Beads priority: {priority!r}") from exc
        if not 0 <= parsed <= 4:
            raise ValueError(f"invalid Beads priority: {priority!r}")
        return parsed

    @classmethod
    def _issue_index(
        cls,
        records: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        issues: dict[str, dict[str, Any]] = {}
        for record in records:
            if not cls._is_issue(record):
                continue
            cls._validate_issue_record(record)
            bead_id = str(record["id"])
            if bead_id in issues:
                raise RuntimeError(f"duplicate Beads task ID in JSONL store: {bead_id}")
            issues[bead_id] = record
        return issues

    @staticmethod
    def _validate_issue_record(record: dict[str, Any]) -> None:
        bead_id = record.get("id")
        if not isinstance(bead_id, str) or not bead_id or bead_id != bead_id.strip():
            raise RuntimeError("invalid or missing Beads task ID in JSONL store")

        title = record.get("title")
        if not isinstance(title, str) or not title.strip():
            raise RuntimeError(f"invalid title for bead task: {bead_id}")

        status = record.get("status", "open")
        if not isinstance(status, str) or status not in _VALID_STATUSES:
            raise RuntimeError(f"invalid status for bead task: {bead_id}")

        priority = record.get("priority", 2)
        if (
            isinstance(priority, bool)
            or not isinstance(priority, int)
            or not 0 <= priority <= 4
        ):
            raise RuntimeError(f"invalid priority for bead task: {bead_id}")

    @classmethod
    def _require_issue(
        cls,
        records: list[dict[str, Any]],
        bead_id: str,
    ) -> dict[str, Any]:
        try:
            return cls._issue_index(records)[bead_id]
        except KeyError:
            raise KeyError(f"unknown bead task: {bead_id}") from None

    @staticmethod
    def _is_issue(record: dict[str, Any]) -> bool:
        return record.get("_type", "issue") == "issue"

    @staticmethod
    def _dependency_ids(record: dict[str, Any]) -> list[str]:
        raw_dependencies = record.get("dependencies", record.get("depends_on", []))
        if not isinstance(raw_dependencies, list):
            raise RuntimeError(
                f"invalid dependencies for bead task: {record.get('id', '<unknown>')}"
            )
        dependencies: list[str] = []
        for dependency in raw_dependencies:
            if isinstance(dependency, str) and dependency:
                dependencies.append(dependency)
            elif isinstance(dependency, dict):
                depends_on_id = dependency.get("depends_on_id")
                if isinstance(depends_on_id, str) and depends_on_id:
                    dependencies.append(depends_on_id)
                else:
                    raise RuntimeError(
                        "invalid dependency object for bead task: "
                        f"{record.get('id', '<unknown>')}"
                    )
            else:
                raise RuntimeError(
                    "invalid dependency entry for bead task: "
                    f"{record.get('id', '<unknown>')}"
                )
        return dependencies

    @classmethod
    def _record_to_task(cls, record: dict[str, Any]) -> BeadTask:
        return BeadTask(
            id=str(record.get("id", "")),
            title=str(record.get("title", "")),
            status=str(record.get("status", "open")),
            priority=int(record.get("priority", 2)),
            depends_on=cls._dependency_ids(record),
        )

    @staticmethod
    def _parse_ready_json(output: str) -> list[BeadTask]:
        """Parse historical ready-task JSON output for API compatibility."""

        data = json.loads(output)
        if not isinstance(data, list):
            return []
        tasks: list[BeadTask] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            tasks.append(BeadsManager._record_to_task(item))
        return tasks

    @staticmethod
    def _parse_show_json(output: str) -> BeadTask | None:
        """Parse historical single-task JSON output for API compatibility."""

        data: Any = json.loads(output)
        if isinstance(data, list):
            if not data:
                return None
            data = data[0]
        if not isinstance(data, dict):
            return None
        return BeadsManager._record_to_task(data)
