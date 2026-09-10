#!/usr/bin/env python
"""Build a safe, read-only deployment plan for cataloged skills."""

from __future__ import annotations

import argparse
import errno
import hashlib
import os
import shutil
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

try:
    from .validate_catalog import load_yaml, parse_skill_frontmatter, validate_catalog
except ImportError:  # Direct execution: python scripts/deploy_dry_run.py
    from validate_catalog import load_yaml, parse_skill_frontmatter, validate_catalog

CREATE = "CREATE"
IDENTICAL = "IDENTICAL"
LOCAL_DRIFT = "LOCAL_DRIFT"
UNMANAGED_CONFLICT = "UNMANAGED_CONFLICT"
NAME_COLLISION = "NAME_COLLISION"
STRUCTURAL_CONFLICT = "STRUCTURAL_CONFLICT"
MISSING_DEPENDENCY = "MISSING_DEPENDENCY"
BLOCKED = "BLOCKED"

SAFE_STATUSES = {CREATE, IDENTICAL}
BLOCKING_STATUSES = {
    LOCAL_DRIFT,
    UNMANAGED_CONFLICT,
    NAME_COLLISION,
    STRUCTURAL_CONFLICT,
    MISSING_DEPENDENCY,
    BLOCKED,
}
REQUIRED_LOCAL_DEPENDENCY_KEYS = ("bundled_scripts", "bundled_resources", "project_files")


class StructuralError(ValueError):
    """Raised when a bundle contains an unsafe filesystem object."""


class ApplyError(RuntimeError):
    """Raised when a deployment cannot complete safely."""

    def __init__(
        self,
        message: str,
        plan: DeploymentPlan,
        completed: Sequence[PlanOperation] = (),
    ) -> None:
        super().__init__(message)
        self.plan = plan
        self.completed = tuple(completed)


@dataclass(frozen=True)
class DestinationInventory:
    valid_names: dict[str, tuple[Path, ...]]
    directory_names: dict[str, tuple[Path, ...]]
    invalid_skill_dirs: dict[Path, str]


@dataclass(frozen=True)
class PlanOperation:
    skill: str
    targets: tuple[str, ...]
    source: Path
    root: Path | None
    destination: Path | None
    status: str
    detail: str


@dataclass(frozen=True)
class DeploymentPlan:
    operations: tuple[PlanOperation, ...]

    @property
    def blocked(self) -> bool:
        return any(operation.status in BLOCKING_STATUSES for operation in self.operations)


@dataclass(frozen=True)
class ApplyResult:
    preflight: DeploymentPlan
    created: tuple[PlanOperation, ...]
    unchanged: tuple[PlanOperation, ...]


def _configured_absolute_path(value: str | os.PathLike[str], label: str) -> Path:
    expanded = Path(os.path.expandvars(os.path.expanduser(os.fspath(value))))
    if not expanded.is_absolute():
        raise ValueError(f"{label} must be an absolute path: {value}")
    return Path(os.path.abspath(expanded))


def destination_roots(
    home: Path | None = None,
    hermes_home: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Path]:
    """Resolve platform roots without embedding a machine-specific user path."""
    environment = os.environ if env is None else env
    resolved_home = _configured_absolute_path(home or Path.home(), "home")

    shared_agents = environment.get("AGENTS_SKILLS_DIR")
    default_agents = resolved_home / ".agents" / "skills"
    codex_value = environment.get("CODEX_SKILLS_DIR") or shared_agents or default_agents
    gemini_value = environment.get("GEMINI_CLI_SKILLS_DIR") or shared_agents or default_agents
    antigravity_value = environment.get("ANTIGRAVITY_SKILLS_DIR") or (
        resolved_home / ".gemini" / "config" / "skills"
    )

    if environment.get("HERMES_SKILLS_DIR"):
        hermes_value: str | os.PathLike[str] = environment["HERMES_SKILLS_DIR"]
    else:
        configured_hermes_home: str | os.PathLike[str] = (
            hermes_home or environment.get("HERMES_HOME") or (resolved_home / ".hermes")
        )
        hermes_value = _configured_absolute_path(configured_hermes_home, "HERMES_HOME") / "skills"

    return {
        "codex": _configured_absolute_path(codex_value, "CODEX_SKILLS_DIR"),
        "gemini-cli": _configured_absolute_path(gemini_value, "GEMINI_CLI_SKILLS_DIR"),
        "antigravity": _configured_absolute_path(antigravity_value, "ANTIGRAVITY_SKILLS_DIR"),
        "hermes": _configured_absolute_path(hermes_value, "HERMES_SKILLS_DIR"),
    }


def destination_for(target: str, root: Path, name: str) -> Path:
    return root / "canonical" / name if target == "hermes" else root / name


def _is_reparse_point(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    attributes = getattr(info, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return path.is_symlink() or bool(attributes & reparse_flag)


def _existing_components(path: Path) -> list[Path]:
    absolute = Path(os.path.abspath(path))
    components = [absolute]
    components.extend(absolute.parents)
    components.reverse()
    return [component for component in components if component.exists() or component.is_symlink()]


def destination_safety_issue(root: Path, destination: Path) -> str | None:
    root = Path(os.path.abspath(root))
    destination = Path(os.path.abspath(destination))
    try:
        if os.path.commonpath([os.path.normcase(str(root)), os.path.normcase(str(destination))]) != os.path.normcase(
            str(root)
        ):
            return f"destination escapes configured root: {destination}"
    except ValueError:
        return f"destination escapes configured root: {destination}"

    for component in _existing_components(destination):
        if _is_reparse_point(component):
            return f"symlink or junction in destination path: {component}"

    resolved_root = root.resolve(strict=False)
    resolved_destination = destination.resolve(strict=False)
    try:
        resolved_destination.relative_to(resolved_root)
    except ValueError:
        return f"resolved destination escapes configured root: {resolved_destination}"
    return None


def _regular_directory(path: Path) -> bool:
    return path.is_dir() and not _is_reparse_point(path)


def bundle_manifest(root: Path) -> dict[str, str]:
    """Hash every regular file recursively without following links or junctions."""
    root = Path(root)
    if not _regular_directory(root):
        raise StructuralError(f"bundle is not a regular directory: {root}")

    manifest: dict[str, str] = {}
    for base, directory_names, file_names in os.walk(root, topdown=True, followlinks=False):
        base_path = Path(base)
        safe_directories: list[str] = []
        for name in sorted(directory_names):
            child = base_path / name
            if _is_reparse_point(child):
                raise StructuralError(f"symlink or junction inside bundle: {child}")
            if not child.is_dir():
                raise StructuralError(f"non-directory object in directory list: {child}")
            safe_directories.append(name)
        directory_names[:] = safe_directories

        for name in sorted(file_names):
            file_path = base_path / name
            if _is_reparse_point(file_path) or not file_path.is_file():
                raise StructuralError(f"non-regular file inside bundle: {file_path}")
            relative = file_path.relative_to(root).as_posix()
            digest = hashlib.sha256()
            with file_path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            manifest[relative] = digest.hexdigest()
    return manifest


def inventory_destination(root: Path) -> DestinationInventory:
    valid: dict[str, list[Path]] = {}
    directory_names: dict[str, list[Path]] = {}
    invalid: dict[Path, str] = {}
    root = Path(root)
    if not root.exists() or not _regular_directory(root):
        return DestinationInventory({}, {}, {})

    for base, child_directories, file_names in os.walk(root, topdown=True, followlinks=False):
        base_path = Path(base)
        safe_children: list[str] = []
        for name in sorted(child_directories):
            child = base_path / name
            directory_names.setdefault(name, []).append(child)
            if _is_reparse_point(child):
                invalid[child] = "symlink or junction"
                continue
            safe_children.append(name)
        child_directories[:] = safe_children

        if "SKILL.md" not in file_names:
            continue
        skill_md = base_path / "SKILL.md"
        try:
            metadata = parse_skill_frontmatter(skill_md)
            name = metadata.get("name")
            if not isinstance(name, str) or not name:
                raise ValueError("missing frontmatter name")
        except (OSError, UnicodeError, ValueError) as exc:
            invalid[base_path] = str(exc)
            continue
        valid.setdefault(name, []).append(base_path)

    return DestinationInventory(
        valid_names={name: tuple(sorted(paths)) for name, paths in valid.items()},
        directory_names={name: tuple(sorted(paths)) for name, paths in directory_names.items()},
        invalid_skill_dirs=invalid,
    )


def missing_local_dependencies(skill: Mapping[str, object], source: Path) -> list[str]:
    dependencies = skill.get("dependencies")
    if not isinstance(dependencies, Mapping):
        return []
    missing: list[str] = []
    source_absolute = Path(os.path.abspath(source))
    for key in REQUIRED_LOCAL_DEPENDENCY_KEYS:
        references = dependencies.get(key, [])
        if not isinstance(references, Sequence) or isinstance(references, (str, bytes)):
            missing.append(f"dependencies.{key} is not a list")
            continue
        for reference in references:
            if not isinstance(reference, str) or not reference:
                missing.append(f"dependencies.{key} contains an invalid path")
                continue
            candidate = Path(os.path.abspath(source_absolute / reference))
            try:
                candidate.relative_to(source_absolute)
            except ValueError:
                missing.append(f"dependencies.{key} escapes bundle: {reference}")
                continue
            if not candidate.exists():
                missing.append(reference)
    return sorted(set(missing))


def _physical_key(path: Path) -> str:
    return os.path.normcase(str(Path(os.path.abspath(path)).resolve(strict=False)))


def _classify_destination(
    name: str,
    source_manifest: dict[str, str],
    root: Path,
    destination: Path,
    inventory: DestinationInventory,
) -> tuple[str, str]:
    safety_issue = destination_safety_issue(root, destination)
    if safety_issue:
        return STRUCTURAL_CONFLICT, safety_issue

    expected_key = _physical_key(destination)
    valid_candidates = list(inventory.valid_names.get(name, ()))
    matching_candidates = [candidate for candidate in valid_candidates if _physical_key(candidate) != expected_key]
    named_directories = list(inventory.directory_names.get(name, ()))
    invalid_named = [
        candidate
        for candidate in named_directories
        if _physical_key(candidate) != expected_key and candidate not in valid_candidates
    ]

    if destination.exists() or destination.is_symlink():
        if _is_reparse_point(destination) or not destination.is_dir():
            return STRUCTURAL_CONFLICT, f"destination is not a regular directory: {destination}"
        if matching_candidates or invalid_named:
            locations = sorted({str(path) for path in matching_candidates + invalid_named})
            return NAME_COLLISION, "same name also exists at " + ", ".join(locations)

        skill_md = destination / "SKILL.md"
        if not skill_md.is_file() or _is_reparse_point(skill_md):
            return UNMANAGED_CONFLICT, f"existing directory is not a valid managed skill: {destination}"
        try:
            metadata = parse_skill_frontmatter(skill_md)
        except (OSError, UnicodeError, ValueError) as exc:
            return UNMANAGED_CONFLICT, f"invalid existing SKILL.md: {exc}"
        if metadata.get("name") != name:
            return UNMANAGED_CONFLICT, f"existing SKILL.md name is {metadata.get('name')!r}"
        try:
            destination_manifest = bundle_manifest(destination)
        except StructuralError as exc:
            return STRUCTURAL_CONFLICT, str(exc)
        if destination_manifest == source_manifest:
            return IDENTICAL, "destination recursively matches canonical source"
        return LOCAL_DRIFT, "existing skill differs recursively from canonical source"

    candidates = matching_candidates
    if invalid_named:
        locations = sorted(str(path) for path in invalid_named)
        return NAME_COLLISION, "same-named directory is not a valid skill at " + ", ".join(locations)
    if len(candidates) > 1:
        return NAME_COLLISION, "multiple same-name skills exist at " + ", ".join(
            str(path) for path in sorted(candidates)
        )
    if len(candidates) == 1:
        candidate = candidates[0]
        try:
            candidate_manifest = bundle_manifest(candidate)
        except StructuralError as exc:
            return STRUCTURAL_CONFLICT, str(exc)
        if candidate_manifest == source_manifest:
            return IDENTICAL, f"identical skill already exists at {candidate}"
        return NAME_COLLISION, f"different same-name skill exists at {candidate}"
    return CREATE, "destination does not exist"


def build_plan(catalog: Mapping[str, object], repo_root: Path, roots: Mapping[str, Path]) -> DeploymentPlan:
    """Build the complete plan. This function performs reads only."""
    repo_root = Path(os.path.abspath(repo_root))
    entries = catalog.get("skills")
    if not isinstance(entries, list):
        return DeploymentPlan(
            (
                PlanOperation(
                    skill="<catalog>",
                    targets=(),
                    source=repo_root,
                    root=None,
                    destination=None,
                    status=BLOCKED,
                    detail="catalog skills is not a list",
                ),
            )
        )

    inventories: dict[str, DestinationInventory] = {}
    for root in roots.values():
        key = _physical_key(root)
        if key not in inventories:
            inventories[key] = inventory_destination(root)

    grouped: dict[tuple[str, str], dict[str, object]] = {}
    source_state: dict[str, tuple[dict[str, str] | None, str | None, str | None]] = {}

    for skill in sorted(entries, key=lambda item: str(item.get("name", "")) if isinstance(item, Mapping) else ""):
        if not isinstance(skill, Mapping):
            continue
        name = str(skill.get("name", "<unnamed>"))
        path_value = skill.get("path")
        source = repo_root / str(path_value) if isinstance(path_value, str) else repo_root

        try:
            source_manifest = bundle_manifest(source)
            missing = missing_local_dependencies(skill, source)
            if missing:
                source_state[name] = (source_manifest, MISSING_DEPENDENCY, "missing: " + ", ".join(missing))
            else:
                source_state[name] = (source_manifest, None, None)
        except (OSError, StructuralError, ValueError) as exc:
            source_state[name] = (None, BLOCKED, f"canonical source cannot be hashed safely: {exc}")

        targets = skill.get("targets")
        if not isinstance(targets, list):
            targets = []
        for target_value in targets:
            target = str(target_value)
            root = roots.get(target)
            if root is None:
                group_key = (name, f"missing-root:{target}")
                grouped[group_key] = {
                    "skill": name,
                    "targets": [target],
                    "source": source,
                    "root": None,
                    "destination": None,
                    "forced_status": BLOCKED,
                    "forced_detail": f"no destination root configured for target {target}",
                }
                continue
            destination = destination_for(target, root, name)
            group_key = (name, _physical_key(destination))
            existing = grouped.get(group_key)
            if existing is None:
                grouped[group_key] = {
                    "skill": name,
                    "targets": [target],
                    "source": source,
                    "root": Path(root),
                    "destination": destination,
                }
            else:
                existing_targets = existing["targets"]
                assert isinstance(existing_targets, list)
                existing_targets.append(target)

    operations: list[PlanOperation] = []
    for group in grouped.values():
        name = str(group["skill"])
        targets = tuple(sorted(str(target) for target in group["targets"]))
        source = Path(group["source"])
        root_value = group.get("root")
        destination_value = group.get("destination")
        root = Path(root_value) if root_value is not None else None
        destination = Path(destination_value) if destination_value is not None else None

        forced_status = group.get("forced_status")
        if isinstance(forced_status, str):
            status = forced_status
            detail = str(group.get("forced_detail", "blocked"))
        else:
            source_manifest, source_status, source_detail = source_state[name]
            if source_status is not None or source_manifest is None:
                status = source_status or BLOCKED
                detail = source_detail or "canonical source is unavailable"
            else:
                assert root is not None and destination is not None
                inventory = inventories[_physical_key(root)]
                status, detail = _classify_destination(name, source_manifest, root, destination, inventory)

        operations.append(
            PlanOperation(
                skill=name,
                targets=targets,
                source=source,
                root=root,
                destination=destination,
                status=status,
                detail=detail,
            )
        )

    operations.sort(key=lambda operation: (operation.skill, str(operation.destination), operation.targets))
    return DeploymentPlan(tuple(operations))


def _copy_bundle_safely(source: Path, temporary: Path) -> None:
    """Copy regular bundle contents without following links or reparse points."""
    if not _regular_directory(source):
        raise StructuralError(f"bundle is not a regular directory: {source}")
    if not _regular_directory(temporary):
        raise StructuralError(f"temporary path is not a regular directory: {temporary}")

    for base, directory_names, file_names in os.walk(source, topdown=True, followlinks=False):
        base_path = Path(base)
        if _is_reparse_point(base_path):
            raise StructuralError(f"symlink or junction inside bundle: {base_path}")
        relative_base = base_path.relative_to(source)
        target_base = temporary / relative_base
        target_base.mkdir(exist_ok=True)

        safe_directories: list[str] = []
        for name in sorted(directory_names):
            child = base_path / name
            if _is_reparse_point(child) or not child.is_dir():
                raise StructuralError(f"unsafe directory inside bundle: {child}")
            (target_base / name).mkdir(exist_ok=False)
            safe_directories.append(name)
        directory_names[:] = safe_directories

        for name in sorted(file_names):
            source_file = base_path / name
            if _is_reparse_point(source_file) or not source_file.is_file():
                raise StructuralError(f"non-regular file inside bundle: {source_file}")
            shutil.copy2(source_file, target_base / name)


def _remove_owned_temporary(path: Path) -> None:
    """Remove only an unpromoted temporary directory created by this process."""
    if not path.exists() and not path.is_symlink():
        return
    if _is_reparse_point(path):
        try:
            path.unlink()
        except OSError:
            os.rmdir(path)
        return
    shutil.rmtree(path)


def _windows_promote_noreplace(temporary: Path, destination: Path) -> None:
    """Rename relative to a pinned Windows parent handle without replacement."""
    import ctypes
    from ctypes import wintypes

    file_list_directory = 0x0001
    file_add_subdirectory = 0x0004
    file_read_attributes = 0x0080
    delete_access = 0x00010000
    share_all = 0x00000001 | 0x00000002 | 0x00000004
    open_existing = 3
    backup_semantics = 0x02000000
    open_reparse_point = 0x00200000
    file_attribute_reparse_point = 0x00000400
    file_attribute_tag_info_class = 9
    file_rename_info_class = 3

    class FileAttributeTagInfo(ctypes.Structure):
        _fields_ = [("FileAttributes", wintypes.DWORD), ("ReparseTag", wintypes.DWORD)]

    class FileRenameInfo(ctypes.Structure):
        _fields_ = [
            ("ReplaceIfExists", ctypes.c_ubyte),
            ("RootDirectory", wintypes.HANDLE),
            ("FileNameLength", wintypes.DWORD),
            ("FileName", wintypes.WCHAR * 1),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    get_info = kernel32.GetFileInformationByHandleEx
    get_info.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    get_final_path = kernel32.GetFinalPathNameByHandleW
    get_final_path.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    set_info = kernel32.SetFileInformationByHandle
    set_info.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]

    invalid_handle = wintypes.HANDLE(-1).value

    def open_directory(path: Path, access: int, share: int = share_all) -> int:
        handle = create_file(
            str(path),
            access,
            share,
            None,
            open_existing,
            backup_semantics | open_reparse_point,
            None,
        )
        if handle == invalid_handle:
            raise ctypes.WinError(ctypes.get_last_error())
        return handle

    def reject_reparse(handle: int, label: str) -> None:
        info = FileAttributeTagInfo()
        if not get_info(handle, file_attribute_tag_info_class, ctypes.byref(info), ctypes.sizeof(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        if info.FileAttributes & file_attribute_reparse_point:
            raise StructuralError(f"{label} is a symlink or junction")

    def final_path(handle: int) -> str:
        buffer = ctypes.create_unicode_buffer(32768)
        length = get_final_path(handle, buffer, len(buffer), 0)
        if not length or length >= len(buffer):
            raise ctypes.WinError(ctypes.get_last_error())
        value = buffer.value
        if value.startswith("\\\\?\\UNC\\"):
            return "\\\\" + value[8:]
        if value.startswith("\\\\?\\"):
            return value[4:]
        return value

    parent_handle = open_directory(
        destination.parent,
        file_list_directory | file_add_subdirectory | file_read_attributes,
        0x00000001 | 0x00000002,
    )
    temporary_handle: int | None = None
    try:
        reject_reparse(parent_handle, f"destination parent {destination.parent}")
        opened_parent_path = final_path(parent_handle)
        expected_parent = os.path.normcase(os.path.abspath(destination.parent))
        opened_parent = os.path.normcase(os.path.abspath(opened_parent_path))
        if opened_parent != expected_parent:
            raise StructuralError(f"destination parent changed before promotion: {destination.parent}")

        temporary_handle = open_directory(temporary, delete_access | file_read_attributes)
        reject_reparse(temporary_handle, f"temporary directory {temporary}")

        encoded_name = str(Path(opened_parent_path) / destination.name).encode("utf-16-le")
        info_size = ctypes.sizeof(FileRenameInfo) + len(encoded_name)
        buffer = ctypes.create_string_buffer(info_size)
        rename_info = ctypes.cast(buffer, ctypes.POINTER(FileRenameInfo)).contents
        rename_info.ReplaceIfExists = 0
        rename_info.RootDirectory = None
        rename_info.FileNameLength = len(encoded_name)
        ctypes.memmove(ctypes.addressof(buffer) + FileRenameInfo.FileName.offset, encoded_name, len(encoded_name))
        if not set_info(temporary_handle, file_rename_info_class, buffer, info_size):
            error = ctypes.get_last_error()
            if error in (80, 183):
                raise FileExistsError(error, f"destination appeared before promotion: {destination}")
            raise ctypes.WinError(error)
    finally:
        if temporary_handle is not None:
            close_handle(temporary_handle)
        close_handle(parent_handle)


def _posix_promote_noreplace(temporary: Path, destination: Path) -> None:
    """Use Linux renameat2 relative to a pinned no-follow parent descriptor."""
    import ctypes

    required_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    parent_fd = os.open(destination.parent, required_flags)
    try:
        opened = os.fstat(parent_fd)
        current = os.stat(destination.parent, follow_symlinks=False)
        if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
            raise StructuralError(f"destination parent changed before promotion: {destination.parent}")

        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = getattr(libc, "renameat2", None)
        if renameat2 is None:
            raise OSError(errno.ENOTSUP, "atomic no-replace promotion is unavailable on this POSIX platform")
        renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        renameat2.restype = ctypes.c_int
        result = renameat2(
            parent_fd,
            os.fsencode(temporary.name),
            parent_fd,
            os.fsencode(destination.name),
            1,
        )
        if result != 0:
            error = ctypes.get_errno()
            if error == errno.EEXIST:
                raise FileExistsError(error, f"destination appeared before promotion: {destination}")
            raise OSError(error, os.strerror(error), str(destination))
    finally:
        os.close(parent_fd)


def _promote_noreplace(temporary: Path, destination: Path, root: Path) -> None:
    """Atomically promote inside a pinned parent, or fail closed if unsupported."""
    if temporary.parent != destination.parent:
        raise StructuralError("temporary directory is not a sibling of destination")
    safety_issue = destination_safety_issue(root, destination)
    if safety_issue:
        raise StructuralError(safety_issue)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"destination appeared before promotion: {destination}")

    if os.name == "nt":
        _windows_promote_noreplace(temporary, destination)
    elif os.name == "posix":
        _posix_promote_noreplace(temporary, destination)
    else:
        raise OSError(errno.ENOTSUP, f"atomic no-replace promotion is unsupported on {os.name}")


def _apply_create(operation: PlanOperation) -> None:
    source = operation.source
    root = operation.root
    destination = operation.destination
    if root is None or destination is None:
        raise ValueError("CREATE operation has no resolved root or destination")

    safety_issue = destination_safety_issue(root, destination)
    if safety_issue:
        raise StructuralError(safety_issue)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"destination appeared after preflight: {destination}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    safety_issue = destination_safety_issue(root, destination)
    if safety_issue:
        raise StructuralError(safety_issue)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"destination appeared after preflight: {destination}")

    temporary = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}.deploy-", dir=destination.parent)
    )
    promoted = False
    try:
        _copy_bundle_safely(source, temporary)
        source_manifest = bundle_manifest(source)
        temporary_manifest = bundle_manifest(temporary)
        if temporary_manifest != source_manifest:
            raise ValueError(f"temporary copy hash mismatch for {operation.skill}")

        _promote_noreplace(temporary, destination, root)
        promoted = True
    finally:
        if not promoted:
            _remove_owned_temporary(temporary)


def apply_deployment(
    catalog: Mapping[str, object],
    repo_root: Path,
    roots: Mapping[str, Path],
) -> ApplyResult:
    """Run a fresh preflight and create only absent governed skills."""
    preflight = build_plan(catalog, repo_root, roots)
    if preflight.blocked:
        raise ApplyError("preflight contains blocking operations", preflight)

    created: list[PlanOperation] = []
    unchanged: list[PlanOperation] = []
    for operation in preflight.operations:
        if operation.status == IDENTICAL:
            unchanged.append(operation)
            continue
        if operation.status != CREATE:
            raise ApplyError(
                f"unsupported preflight status {operation.status} for {operation.skill}",
                preflight,
                created,
            )
        try:
            _apply_create(operation)
        except (OSError, StructuralError, ValueError) as exc:
            raise ApplyError(
                f"failed to create {operation.skill} at {operation.destination}: {exc}",
                preflight,
                created,
            ) from exc
        created.append(operation)

    return ApplyResult(preflight, tuple(created), tuple(unchanged))


def render_plan(plan: DeploymentPlan) -> str:
    lines = [
        "PLAN ONLY — no files will be copied, deleted, overwritten, linked, or created.",
        "skill | platforms | destination | status | detail",
        "--- | --- | --- | --- | ---",
    ]
    for operation in plan.operations:
        targets = ",".join(operation.targets) or "-"
        destination = str(operation.destination) if operation.destination is not None else "-"
        lines.append(
            f"{operation.skill} | {targets} | {destination} | {operation.status} | {operation.detail}"
        )
    counts: dict[str, int] = {}
    for operation in plan.operations:
        counts[operation.status] = counts.get(operation.status, 0) + 1
    summary = ", ".join(f"{status}={counts[status]}" for status in sorted(counts))
    lines.append(f"Physical operations: {len(plan.operations)}; {summary}")
    lines.append("PLAN BLOCKED" if plan.blocked else "PLAN SAFE")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--home", type=Path, help="Override the user home used for default roots")
    parser.add_argument("--codex-root", type=Path)
    parser.add_argument("--gemini-cli-root", type=Path)
    parser.add_argument("--antigravity-root", type=Path)
    parser.add_argument("--hermes-root", type=Path)
    parser.add_argument("--apply", action="store_true", help="Create absent governed skills after a safe preflight")
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    catalog_path = args.catalog.resolve() if args.catalog else repo_root / "catalog.yaml"
    validation = validate_catalog(repo_root, catalog_path)
    if not validation.ok:
        for error in validation.errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 2

    try:
        roots = destination_roots(home=args.home)
        overrides = {
            "codex": args.codex_root,
            "gemini-cli": args.gemini_cli_root,
            "antigravity": args.antigravity_root,
            "hermes": args.hermes_root,
        }
        for target, value in overrides.items():
            if value is not None:
                roots[target] = _configured_absolute_path(value, f"{target} root")
    except ValueError as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2

    catalog = load_yaml(catalog_path)
    if not args.apply:
        plan = build_plan(catalog, repo_root, roots)
        print(render_plan(plan))
        return 2 if plan.blocked else 0

    try:
        result = apply_deployment(catalog, repo_root, roots)
    except ApplyError as exc:
        print(render_plan(exc.plan))
        print(f"APPLY ABORTED: {exc}", file=sys.stderr)
        if exc.completed:
            print("Completed before failure:", file=sys.stderr)
            for operation in exc.completed:
                print(f"- {operation.skill} -> {operation.destination}", file=sys.stderr)
        else:
            print("Completed before failure: none", file=sys.stderr)
        return 2 if exc.plan.blocked else 1

    print(render_plan(result.preflight))
    print(f"APPLY COMPLETE: created={len(result.created)}, identical={len(result.unchanged)}")
    for operation in result.created:
        print(f"CREATED: {operation.skill} -> {operation.destination}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
