"""Tests are hermetic: a developer's local `.env` (real model keys, providers) never reaches them.

Every suite runs on built-in defaults plus what each test sets explicitly. Real-model checks are run
against the running app instead (see docs/implementation-status.md).
"""

from services.platform.config import Settings, get_settings

Settings.model_config["env_file"] = None
get_settings.cache_clear()
