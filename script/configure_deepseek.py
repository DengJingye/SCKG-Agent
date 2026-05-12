import argparse
from pathlib import Path


def update_env(path: Path, updates: dict[str, str]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    output = []
    seen = set()

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            output.append(line)
            continue

        key = line.split("=", 1)[0].strip()
        if key in updates:
            output.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            output.append(line)

    for key, value in updates.items():
        if key not in seen:
            output.append(f"{key}={value}")

    path.write_text("\n".join(output) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Configure DeepSeek V4 in .env.")
    parser.add_argument("--api-key", required=True, help="DeepSeek API key.")
    parser.add_argument("--model", default="deepseek-v4-pro")
    parser.add_argument("--base-url", default="https://api.deepseek.com")
    parser.add_argument("--env-path", type=Path, default=Path(".env"))
    args = parser.parse_args()

    update_env(
        args.env_path,
        {
            "OPENAI_API_BASE": args.base_url,
            "OPENAI_API_KEY": args.api_key,
            "DEEPSEEK_API_KEY": args.api_key,
            "MODEL_NAME": args.model,
            "EXTRACT_MODEL": args.model,
            "CHAT_API_BASE": args.base_url,
            "SILICONFLOW_API_KEY": "",
        },
    )
    print(f"Configured DeepSeek model {args.model} in {args.env_path}")


if __name__ == "__main__":
    main()
