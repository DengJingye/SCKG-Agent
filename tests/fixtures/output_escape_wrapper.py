from pathlib import Path


def main() -> int:
    artifacts = Path("artifacts")
    artifacts.mkdir(exist_ok=True)
    (artifacts / "escaped").symlink_to(Path.cwd().parent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
