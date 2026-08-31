"""Terminal commands that ask for approval before changing saved memories."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sqlite3
import sys

from memory_manager.config import MemoryConfig
from memory_manager.errors import MemoryLookupError
from memory_manager.memory_store import ConcurrentUpdateError, MemoryStore
from memory_manager.models import MemoryPreSaveDraft, MemoryRecord
from memory_manager.validation import validate_draft


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="memory", description="Manage your local memory library")
    parser.add_argument("--data-dir", type=Path, required=True, help="Directory containing memory.sqlite")
    commands = parser.add_subparsers(dest="command", required=True)
    save = commands.add_parser("save", help="Preview a new memory, or update an existing ID")
    save.add_argument("id", nargs="?", help="Existing memory ID; omit to create a memory")
    save.add_argument("--title")
    add_body_arguments(save)
    aliases = save.add_mutually_exclusive_group()
    aliases.add_argument("--alias", action="append", help="Replace aliases; repeat for multiple aliases")
    aliases.add_argument("--clear-aliases", action="store_true", help="Remove aliases from an existing memory")

    read = commands.add_parser("read", help="List summaries, or read one memory by ID")
    read.add_argument("id", nargs="?", help="Memory ID; omit to list summaries")
    selection = read.add_mutually_exclusive_group()
    selection.add_argument("--deleted", action="store_true", help="Read deleted memories available for recovery")
    selection.add_argument("--history", action="store_true", help="List archived versions of the supplied ID")
    selection.add_argument("--revision", help="Read one archived version of the supplied ID in full")
    add_page_arguments(read)

    search = commands.add_parser("search", help="Find compact memory candidates")
    search.add_argument("query", help="Focused words or a title/alias; quote multiword queries")

    delete = commands.add_parser("delete", help="Preview and soft-delete a memory")
    delete.add_argument("id")

    restore = commands.add_parser("restore", help="Preview and restore deleted or historical content")
    restore.add_argument("id")
    restore.add_argument("--revision", help="Retained version ID; omit to restore a deleted memory")

    maintenance = commands.add_parser("maintenance", help="Initialize, inspect, or rebuild local storage")
    actions = maintenance.add_subparsers(dest="maintenance_command", required=True)
    actions.add_parser("init", help="Initialize local storage and its search index")
    actions.add_parser("status", help="Check whether the search index is up to date")
    actions.add_parser("reindex", help="Rebuild search data from saved memories without changing them")
    return parser


def add_body_arguments(parser: argparse.ArgumentParser) -> None:
    body = parser.add_mutually_exclusive_group()
    body.add_argument("--body")
    body.add_argument("--body-file", type=Path, help="Read the body from a UTF-8 text file")


def add_page_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--limit", type=int, help="Listing size (default: 50); not for reading one version")
    parser.add_argument("--offset", type=int, help="Listing offset (default: 0); not for reading one version")


def read_body(args: argparse.Namespace) -> str | None:
    if args.body_file is not None:
        return args.body_file.expanduser().read_text(encoding="utf-8")
    return args.body


def print_json(value: object) -> None:
    # JSON escaping keeps stored control characters from acting as terminal commands.
    print(json.dumps(value, indent=2, default=str, ensure_ascii=True))


def record_summary(record: MemoryRecord) -> dict[str, object]:
    summary = asdict(record)
    del summary["body"]
    return summary


def preview_draft(draft: MemoryPreSaveDraft) -> None:
    validate_draft(draft)
    print_json(asdict(draft))
    print(f"Body: {len(draft.body)} / {MemoryConfig.RECORD_BODY_CHARACTER_LIMIT} characters")


def confirm() -> bool:
    try:
        approved = input("Type yes to approve: ").strip().lower() == "yes"
    except EOFError:
        approved = False
    if not approved:
        print("Cancelled; no changes made")
    return approved


def print_saved(record: MemoryRecord) -> None:
    print("Memory saved")
    print(f"ID: {record.id}")


class MemoryCLI:
    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    def run(self, args: argparse.Namespace) -> None:
        if args.command == "save":
            self.save(args)
        elif args.command == "read":
            self.read(args)
        elif args.command == "search":
            results = self.store.search(args.query)
            print_json(asdict(results))
            if results.index_update_pending:
                print("Index update pending; results may be incomplete", file=sys.stderr)
        elif args.command == "delete":
            self.delete(args.id)
        elif args.command == "restore":
            self.restore(args)
        elif args.command == "maintenance":
            self.maintenance(args)

    def save(self, args: argparse.Namespace) -> None:
        if args.id is not None:
            self.update(args)
        else:
            if args.clear_aliases:
                raise ValueError("--clear-aliases requires an existing memory ID")
            self.create(args)

    def read(self, args: argparse.Namespace) -> None:
        if args.id is None and (args.history or args.revision is not None):
            raise ValueError("--history and --revision require a memory ID")
        if args.id is not None and not args.history:
            if args.limit is not None or args.offset is not None:
                raise ValueError("--limit and --offset are only for listings, not reading one version")
            self.show(args)
            return

        limit = args.limit if args.limit is not None else 50
        offset = args.offset if args.offset is not None else 0
        if args.history:
            print_json([
                {**asdict(entry), "record": record_summary(entry.record)}
                for entry in self.store.history(args.id, limit=limit, offset=offset)
            ])
        else:
            listing = self.store.list_deleted if args.deleted else self.store.list_records
            print_json([record_summary(record) for record in listing(limit=limit, offset=offset)])

    def maintenance(self, args: argparse.Namespace) -> None:
        if args.maintenance_command == "init":
            self.store.initialize()
            print(f"Memory database ready: {self.store.config.memory_database}")
        elif args.maintenance_command == "reindex":
            self.store.reindex()
        self.print_index_status()

    def create(self, args: argparse.Namespace) -> None:
        body = read_body(args)
        if args.title is None or body is None:
            raise ValueError("Creating a memory requires --title and either --body or --body-file")
        draft = MemoryPreSaveDraft(title=args.title, body=body, aliases=tuple(args.alias or ()))
        print("Create memory:")
        preview_draft(draft)
        if confirm():
            print_saved(self.store.create(draft))
            self.print_index_status()

    def update(self, args: argparse.Namespace) -> None:
        current = self.store.fetch(args.id)
        body = read_body(args)
        if args.title is None and body is None and args.alias is None and not args.clear_aliases:
            raise ValueError("Provide a title, body, or alias change")
        aliases = current.aliases
        if args.clear_aliases:
            aliases = ()
        elif args.alias is not None:
            aliases = tuple(args.alias)
        draft = MemoryPreSaveDraft(
            title=args.title if args.title is not None else current.title,
            body=body if body is not None else current.body, aliases=aliases,
        )
        validate_draft(draft)
        print("Update memory:")
        print("Current memory:")
        print_json(asdict(current))
        print("Proposed memory:")
        preview_draft(draft)
        if confirm():
            print_saved(self.store.update(args.id, draft, expected_updated_at=current.updated_at))
            self.print_index_status()

    def delete(self, memory_id: str) -> None:
        current = self.store.fetch(memory_id)
        print("Memory to delete:")
        print_json(asdict(current))
        print(f"Recovery window: {self.store.config.recovery_retention_days} days")
        if confirm():
            self.store.delete(memory_id, expected_updated_at=current.updated_at)
            print("Memory deleted")
            self.print_index_status()

    def restore(self, args: argparse.Namespace) -> None:
        try:
            current = self.store.fetch(args.id)
        except MemoryLookupError:
            current = self.store.fetch_deleted(args.id)
        if args.revision is not None:
            content = self.store.fetch_revision(args.id, args.revision).record
        elif current.deleted_at is not None:
            content = current
        else:
            raise ValueError("Provide --revision when restoring an active memory")
        draft = MemoryPreSaveDraft(title=content.title, body=content.body, aliases=content.aliases)
        validate_draft(draft)
        print("Current memory:")
        print_json(asdict(current))
        print("Content to restore:")
        preview_draft(draft)
        if confirm():
            print_saved(self.store.restore(
                args.id, revision_id=args.revision, expected_updated_at=current.updated_at,
            ))
            self.print_index_status()

    def print_index_status(self) -> None:
        try:
            pending = self.store.index_update_pending()
        except (OSError, sqlite3.Error, ValueError) as error:
            print("Search index update pending")
            print(f"Index status unavailable: {error}", file=sys.stderr)
        else:
            print("Search index update pending" if pending else "Search index is up to date")

    def show(self, args: argparse.Namespace) -> None:
        if args.revision is not None:
            print_json(asdict(self.store.fetch_revision(args.id, args.revision)))
        elif args.deleted:
            print_json(asdict(self.store.fetch_deleted(args.id)))
        else:
            print_json(asdict(self.store.fetch(args.id)))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = MemoryConfig(data_directory=args.data_dir.expanduser().resolve())
        MemoryCLI(MemoryStore(config)).run(args)
    except (ValueError, MemoryLookupError, ConcurrentUpdateError, OSError, sqlite3.Error) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130
    return 0
