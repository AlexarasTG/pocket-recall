"""Start the Pocket Recall background service."""

from pocket_recall.transport.pocket_recall_service import PocketRecallService


def main() -> int:
    try:
        PocketRecallService().serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
