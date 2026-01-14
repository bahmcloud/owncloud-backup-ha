from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_BACKUP_PATH,
    CONF_BASE_URL,
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    DATA_BACKUP_AGENT_LISTENERS,
    DATA_CLIENT,
    DOMAIN,
)
from .webdav_client import WebDavClient

_LOGGER = logging.getLogger(__name__)


@callback
def _notify_backup_listeners(hass: HomeAssistant) -> None:
    for listener in hass.data.get(DATA_BACKUP_AGENT_LISTENERS, []):
        listener()


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up ownCloud Backup from a config entry."""
    session = async_get_clientsession(hass, verify_ssl=entry.data[CONF_VERIFY_SSL])

    client = WebDavClient(
        session=session,
        base_url=entry.data[CONF_BASE_URL],
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        backup_path=entry.data[CONF_BACKUP_PATH],
    )

    # Ensure folder exists (best-effort). If this fails, the integration still loads,
    # but backup operations will likely fail. This gives better UX for debugging.
    try:
        await client.ensure_backup_folder()
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Could not ensure backup folder exists: %s", err)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {DATA_CLIENT: client}

    # Notify HA to reload backup agents when entry state changes
    entry.async_on_unload(entry.async_on_state_change(lambda: _notify_backup_listeners(hass)))

    _notify_backup_listeners(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload config entry."""
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    _notify_backup_listeners(hass)
    return True
