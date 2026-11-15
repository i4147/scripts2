from concurrent.futures import InterpreterPoolExecutor
from pathlib import Path
from loguru import logger
def prepend_prompt(target: Path, prompt_content: bytes) -> tuple[Path, str]:
    try:
        original_content: bytes = target.read_bytes()
        separator: bytes = (
            b"\n"
            if prompt_content
            and original_content
            and not prompt_content.endswith((b"\n", b"\r"))
            else b""
        )
        target.write_bytes(prompt_content + separator + original_content)
        return target, "updated"
    except OSError as error:
        return target, f"error: {error}"
def main() -> None:
    prompt_path: Path = Path("prompt.md")
    try:
        prompt_content: bytes = prompt_path.read_bytes()
    except OSError as error:
        logger.error("Could not read {}: {}", prompt_path, error)
        return
    files: list[Path] = [
        path
        for path in Path(".").glob("*.md")
        if path.is_file() and path.name != "prompt.md"
    ]
    files.sort(key=lambda path: path.name)
    if not files:
        logger.info("No other .md files found in the current folder.")
        return
    with InterpreterPoolExecutor(max_workers=4) as executor:
        results: list[tuple[Path, str]] = list(
            executor.map(prepend_prompt, files, [prompt_content] * len(files))
        )
    for path, status in results:
        if status == "updated":
            logger.info("Updated {}", path)
        else:
            logger.error("Could not update {}: {}", path, status)
if __name__ == "__main__":
    main()
