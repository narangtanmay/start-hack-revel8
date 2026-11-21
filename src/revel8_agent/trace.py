"""Append and read run traces as JSON Lines."""

from pathlib import Path

from .schemas import RunTraceEntry


class RunTraceLogger:
    def __init__(self, run_id: str, runs_dir: str | Path = "runs") -> None:
        if not run_id or run_id in {".", ".."} or any(char in run_id for char in "/\\\x00"):
            raise ValueError("Run ID must be a non-empty filename component.")
        self.run_id = run_id
        self.path = Path(runs_dir) / f"{run_id}.jsonl"

    def append(self, entry: RunTraceEntry) -> None:
        if entry.run_id != self.run_id:
            raise ValueError("Trace entry run ID must match the logger's run ID.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(entry.model_dump_json() + "\n")

    def read(self) -> list[RunTraceEntry]:
        try:
            stream = self.path.open(encoding="utf-8")
        except FileNotFoundError:
            return []
        with stream:
            return [RunTraceEntry.model_validate_json(line) for line in stream if line.strip()]
