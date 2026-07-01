"""Bootstrap Stratum workspace directories and obase logging/config."""
from __future__ import annotations

from pathlib import Path

from oprim._config import cfg
from oprim._logging import log as olog


def bootstrap(config_path: Path | None = None, log_level: str = "INFO") -> None:
    """Initialize Stratum runtime: logging, config, and ~/.stratum directory tree."""
    olog.setup_logging(log_level)
    cfg.load_config(config_path)
    stratum_dir = Path.home() / ".stratum"
    for subdir in [
        "inbox",
        "data/substrate",
        "_archive",
        "index/lance",
        "index/tantivy",
    ]:
        (stratum_dir / subdir).mkdir(parents=True, exist_ok=True)
    olog.info("oprim.bootstrap.done", stratum_dir=str(stratum_dir))
