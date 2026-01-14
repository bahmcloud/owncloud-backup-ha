from __future__ import annotations

DOMAIN = "owncloud_backup"

CONF_BASE_URL = "base_url"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_BACKUP_PATH = "backup_path"
CONF_VERIFY_SSL = "verify_ssl"

DATA_CLIENT = "client"
DATA_BACKUP_AGENT_LISTENERS = "backup_agent_listeners"

TAR_PREFIX = "ha_backup_"
TAR_SUFFIX = ".tar"
META_SUFFIX = ".json"

# Spooling to temp file to avoid chunked WebDAV uploads
SPOOL_FLUSH_BYTES = 1024 * 1024  # 1 MiB
