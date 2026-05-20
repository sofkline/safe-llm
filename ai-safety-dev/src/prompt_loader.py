import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

def load_prompt(env_var: str, default: Optional[str] = None) -> Optional[str]:
    path = os.environ.get(env_var, "").strip()
    logger.info("load_prompt: env_var=%s path=%r exists=%s", 
                env_var, path, os.path.exists(path) if path else "N/A")
    if path and os.path.exists(path):
        content = open(path, encoding="utf-8").read().strip()
        logger.info("load_prompt: loaded %d chars from %s", len(content), path)
        return content
    if path:
        logger.warning("load_prompt: file not found: %s", path)
    return default