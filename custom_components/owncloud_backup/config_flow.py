from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_BACKUP_PATH,
    CONF_BASE_URL,
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    DOMAIN,
)
from .webdav_client import WebDavClient

_LOGGER = logging.getLogger(__name__)


STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_BASE_URL): str,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_BACKUP_PATH, default="/HomeAssistant/Backups"): str,
        vol.Optional(CONF_VERIFY_SSL, default=True): bool,
    }
)


async def _validate_input(hass: HomeAssistant, data: dict[str, Any]) -> None:
    """Validate that we can connect and access the configured folder."""
    session = async_get_clientsession(hass, verify_ssl=data[CONF_VERIFY_SSL])
    client = WebDavClient(
        session=session,
        base_url=data[CONF_BASE_URL],
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        backup_path=data[CONF_BACKUP_PATH],
    )
    await client.ensure_backup_folder()
    await client.listdir()


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for ownCloud Backup."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                await _validate_input(self.hass, user_input)
            except Exception as err:  # noqa: BLE001
                _LOGGER.exception("Validation failed: %s", err)
                errors["base"] = "cannot_connect"
            else:
                title = f"ownCloud Backup ({user_input[CONF_USERNAME]})"
                return self.async_create_entry(title=title, data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )
