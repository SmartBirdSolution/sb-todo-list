from __future__ import annotations

import datetime
import logging
import os
from typing import Any, Callable
from dataclasses import dataclass, asdict

import voluptuous as vol

from homeassistant.components import frontend, websocket_api
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ENTITY_ID
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError, HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_component import EntityComponent
from homeassistant.helpers.event import async_track_time_interval  # Added import
from homeassistant.helpers.storage import STORAGE_DIR
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.storage import Store
from homeassistant.util.json import JsonValueType


from .const import (
    ATTR_DESCRIPTION,
    ATTR_DUE_DATE,
    ATTR_DUE_DATETIME,
    ATTR_ITEM,
    ATTR_RENAME,
    ATTR_STATUS,
    ATTR_REQUIRING,
    ATTR_PERIOD,
    DATA_COMPONENT,
    DOMAIN,
    TodoItemStatus,
    TodoListEntityFeature,
    TodoServices,
)
from .entity import MyTodoList, TodoItem

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = datetime.timedelta(seconds=60)
DYNAMIC_LISTS: dict[str, MyTodoList] = {}

# Storage key for persisting list names (to reload entities on restart)
STORAGE_KEY = f"{DOMAIN}_lists"
STORAGE_VERSION = 1

@dataclass
class TodoItemFieldDescription:
    service_field: str
    todo_item_field: str
    validation: Callable[[Any], Any]
    required_feature: TodoListEntityFeature

TODO_ITEM_FIELDS = [
    TodoItemFieldDescription(
        service_field=ATTR_DUE_DATE,
        validation=vol.Any(cv.date, None),
        todo_item_field=ATTR_DUE_DATE,
        required_feature=TodoListEntityFeature.SET_DUE_DATE_ON_ITEM,
    ),
    TodoItemFieldDescription(
        service_field=ATTR_DUE_DATETIME,
        validation=vol.Any(vol.All(cv.datetime, lambda dt: dt.astimezone()), None),
        todo_item_field=ATTR_DUE_DATETIME,
        required_feature=TodoListEntityFeature.SET_DUE_DATETIME_ON_ITEM,
    ),
    TodoItemFieldDescription(
        service_field=ATTR_DESCRIPTION,
        validation=vol.Any(cv.string, None),
        todo_item_field=ATTR_DESCRIPTION,
        required_feature=TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM,
    ),
    TodoItemFieldDescription(
        service_field=ATTR_REQUIRING,
        validation=vol.Boolean(),
        todo_item_field=ATTR_REQUIRING,
        required_feature=TodoListEntityFeature.CREATE_TODO_ITEM,
    ),
    TodoItemFieldDescription(
        service_field=ATTR_PERIOD,
        validation=vol.Any(None, vol.Match(r"^\d+(minute|hour|day|week|month|year)$")),
        todo_item_field=ATTR_PERIOD,
        required_feature=TodoListEntityFeature.CREATE_TODO_ITEM,
    ),
]

TODO_ITEM_FIELD_SCHEMA = {
    vol.Optional(desc.service_field): desc.validation for desc in TODO_ITEM_FIELDS
}


def _validate_supported_features(
    supported_features: int | None, call_data: dict[str, Any]
) -> None:
    for desc in TODO_ITEM_FIELDS:
        if desc.service_field not in call_data:
            continue
        if not supported_features or not supported_features & desc.required_feature:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="update_field_not_supported",
                translation_placeholders={"service_field": desc.service_field},
            )


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the sb_todo integration."""
    component = hass.data[DATA_COMPONENT] = EntityComponent[Entity](
        _LOGGER, DOMAIN, hass, SCAN_INTERVAL
    )

    # Register frontend panel with correct domain
    # frontend.async_register_built_in_panel(hass, DOMAIN, DOMAIN, "mdi:clipboard-list")

    # Storage to persist list names for reload on restart
    store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
    saved_lists = await store.async_load() or []

    # Load existing todo list entities
    for list_name in saved_lists:
        entity = MyTodoList(list_name)
        await entity.async_load_items()
        DYNAMIC_LISTS[list_name] = entity
    if DYNAMIC_LISTS:
        await component.async_add_entities(DYNAMIC_LISTS.values())

    # Register WebSocket commands
    websocket_api.async_register_command(hass, websocket_handle_subscribe_todo_items)
    websocket_api.async_register_command(hass, websocket_handle_todo_item_list)
    websocket_api.async_register_command(hass, websocket_handle_todo_item_move)

    # Register services with proper validation
    component.async_register_entity_service(
        TodoServices.ADD_ITEM,
        vol.All(
            cv.make_entity_service_schema(
                {
                    vol.Required(ATTR_ITEM): vol.All(cv.string, str.strip, vol.Length(min=1)),
                    **TODO_ITEM_FIELD_SCHEMA,
                }
            )
        ),
        _async_add_todo_item,
        required_features=[TodoListEntityFeature.CREATE_TODO_ITEM],
    )

    component.async_register_entity_service(
        TodoServices.UPDATE_ITEM,
        vol.All(
            cv.make_entity_service_schema(
                {
                    vol.Required(ATTR_ITEM): vol.All(cv.string, vol.Length(min=1)),
                    vol.Optional(ATTR_RENAME): vol.All(cv.string, str.strip, vol.Length(min=1)),
                    vol.Optional(ATTR_STATUS): vol.In({TodoItemStatus.NEEDS_ACTION, TodoItemStatus.COMPLETED}),
                    **TODO_ITEM_FIELD_SCHEMA,
                }
            ),
            cv.has_at_least_one_key(
                ATTR_RENAME,
                ATTR_STATUS,
                *[desc.service_field for desc in TODO_ITEM_FIELDS],
            ),
        ),
        _async_update_todo_item,
        required_features=[TodoListEntityFeature.UPDATE_TODO_ITEM],
    )
    component.async_register_entity_service(
        TodoServices.REMOVE_ITEM,
        cv.make_entity_service_schema({vol.Required(ATTR_ITEM): vol.All(cv.ensure_list, [cv.string])}),
        _async_remove_todo_items,
        required_features=[TodoListEntityFeature.DELETE_TODO_ITEM],
    )
    component.async_register_entity_service(
        TodoServices.GET_ITEMS,
        cv.make_entity_service_schema({}),
        _async_get_todo_items,
    )
    component.async_register_entity_service(
        TodoServices.REMOVE_COMPLETED_ITEMS,
        None,
        _async_remove_completed_items,
        required_features=[TodoListEntityFeature.DELETE_TODO_ITEM],
    )

    async def cleanup_sb_todo_files(now=None):
        storage_dir = os.path.join(STORAGE_DIR, "sb_todo")
        os.makedirs(storage_dir, exist_ok=True)
        for filename in os.listdir(storage_dir):
            _LOGGER.info("Checking file: %s", filename)

            if not filename.endswith(".json"):
                _LOGGER.info("Skipping non-JSON file: %s", filename)
                continue

            name = filename[:-5]
            entity_id = f"sb_todo.{name}"
            state = hass.states.get(entity_id)
            _LOGGER.info("Entity %s state: %s", entity_id, state.state if state else "None")

            if state is None or state.state == "unavailable":
                file_path = os.path.join(storage_dir, filename)
                try:
                    os.remove(file_path)
                    _LOGGER.info("Deleted sb_todo file for unavailable entity: %s", entity_id)
                except Exception as e:
                    _LOGGER.error("Failed to delete %s: %s", file_path, e)


    # Register create_list service (async function)
    async def _create_list_service(call: ServiceCall) -> None:
        """Handle the create_list service."""
        name = call.data["name"].strip().lower().replace(" ", "_")
        if name in DYNAMIC_LISTS:
            _LOGGER.warning("List '%s' already exists", name)
            return
        entity = MyTodoList(name)
        await entity.async_load_items()
        DYNAMIC_LISTS[name] = entity
        await component.async_add_entities([entity])

        # Persist updated lists
        await store.async_save(list(DYNAMIC_LISTS.keys()))
        _LOGGER.info("Created new todo list: %s.%s", DOMAIN, name)

    async def _delete_list_service(call: ServiceCall) -> None:
        """Handle deleting a list."""
        name = call.data["name"].strip().lower().replace(" ", "_")
        entity = DYNAMIC_LISTS.pop(name, None)

        if not entity:
            _LOGGER.warning("List '%s' not found for deletion", name)
            return

        # Remove storage file
        try:
            os.remove(entity._storage_path)
            _LOGGER.info("Deleted storage file: %s", entity._storage_path)
        except FileNotFoundError:
            _LOGGER.warning("Storage file not found: %s", entity._storage_path)
        except Exception as e:
            _LOGGER.error("Failed to delete storage file for '%s': %s", name, e)

        # Remove from registry
        await component.async_remove_entity(f"{DOMAIN}.{name}")

        # Persist updated list of lists
        await store.async_save(list(DYNAMIC_LISTS.keys()))
        _LOGGER.info("Deleted todo list: %s", name)

    async def _rename_list_service(call: ServiceCall) -> None:
        """Handle renaming only the display name of a list."""
        entity_id = call.data["entity_id"].strip()
        new_display_name = call.data["new_name"].strip()

        # Extract list_id from entity_id (e.g., sb_todo.my_morning → my_morning)
        if not entity_id.startswith(f"{DOMAIN}."):
            _LOGGER.warning("Invalid entity_id format: %s", entity_id)
            return
        list_id = entity_id.split(".", 1)[1]

        entity = DYNAMIC_LISTS.get(list_id)
        if not entity:
            _LOGGER.warning("List '%s' not found for display name change", list_id)
            return

        if entity._display_name == new_display_name:
            _LOGGER.info("Display name for list '%s' is already '%s'", list_id, new_display_name)
            return

        entity._display_name = new_display_name     # for internal use and persistence
        entity._attr_name = new_display_name        # tells HA to show this as friendly name
        await entity._save_and_refresh()            # persist display name and trigger UI update

        _LOGGER.info("Renamed list '%s' display name to '%s'", list_id, new_display_name)

    hass.services.async_register(
        DOMAIN,
        "rename_list",
        _rename_list_service,
        schema=vol.Schema({
            vol.Required("entity_id"): cv.string,  # Full entity ID: sb_todo.<list_id>
            vol.Required("new_name"): cv.string,   # New display name
        }),
    )


    hass.services.async_register(
        DOMAIN,
        "delete_list",
        _delete_list_service,
        schema=vol.Schema({vol.Required("name"): cv.string}),
    )


    hass.services.async_register(
        DOMAIN,
        "create_list",
        _create_list_service,
        schema=vol.Schema({vol.Required("name"): cv.string}),
    )

    # Add periodic call to async_update_requiring_items every 5 seconds
    async def periodic_update(now: datetime.datetime) -> None:
        _LOGGER.info("Entities being checked: %s", list(DYNAMIC_LISTS.keys()))
        for entity in DYNAMIC_LISTS.values():
            await entity.async_update_requiring_items()

    @callback
    def periodic_cleanup(now):
        hass.async_create_task(cleanup_sb_todo_files())

    # Register the recurring task every minute (for testing)
    async_track_time_interval(
        hass,
        periodic_cleanup,
        datetime.timedelta(hours=23)
    )

    await component.async_setup(config)
    return True

async def _async_add_todo_item(entity: Entity, call: ServiceCall) -> None:
    _validate_supported_features(getattr(entity, "supported_features", None), call.data)
    item = TodoItem(
        uid=None,
        summary=call.data[ATTR_ITEM],
        status=TodoItemStatus.NEEDS_ACTION,
        **{
            desc.todo_item_field: call.data.get(desc.service_field)
            for desc in TODO_ITEM_FIELDS
            if desc.service_field in call.data
        },
    )
    await entity.async_create_todo_item(item)


async def _async_update_todo_item(entity: Entity, call: ServiceCall) -> None:
    _validate_supported_features(getattr(entity, "supported_features", None), call.data)
    item_name = call.data["item"]
    current_items = getattr(entity, "todo_items", None) or []

    found = next((i for i in current_items if item_name in (i.uid, i.summary)), None)

    if not found:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="item_not_found",
            translation_placeholders={"item": item_name},
        )

    updated_data = asdict(found)
    if summary := call.data.get("rename"):
        updated_data["summary"] = summary
    if status := call.data.get("status"):
        updated_data["status"] = status

    for desc in TODO_ITEM_FIELDS:
        if desc.service_field in call.data:
            updated_data[desc.todo_item_field] = call.data[desc.service_field]

    updated_item = TodoItem(**updated_data)
    await entity.async_update_todo_item(updated_item)


async def _async_remove_todo_items(entity: Entity, call: ServiceCall) -> None:
    uids = []
    for item_name in call.data.get("item", []):
        current_items = getattr(entity, "todo_items", None) or []
        found = next((i for i in current_items if item_name in (i.uid, i.summary)), None)
        if not found or not found.uid:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="item_not_found",
                translation_placeholders={"item": item_name},
            )
        uids.append(found.uid)
    await entity.async_delete_todo_items(uids=uids)


async def _async_get_todo_items(entity: Entity, call: ServiceCall) -> dict[str, Any]:
    statuses = call.data.get("status") if call.data else None
    return {
        "items": [
            asdict(item)
            for item in getattr(entity, "todo_items", [])
            if not statuses or item.status in statuses
        ]
    }


async def _async_remove_completed_items(entity: Entity, _: ServiceCall) -> None:
    uids = [
        item.uid
        for item in getattr(entity, "todo_items", [])
        if item.status == TodoItemStatus.COMPLETED and item.uid
    ]
    if uids:
        await entity.async_delete_todo_items(uids=uids)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a config entry."""
    return await hass.data[DATA_COMPONENT].async_setup_entry(entry)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.data[DATA_COMPONENT].async_unload_entry(entry)


#
# WebSocket API handlers
#

@websocket_api.websocket_command(
    {
        vol.Required("type"): "sb_todo/item/subscribe",
        vol.Required("entity_id"): cv.entity_domain(DOMAIN),
    }
)
@websocket_api.async_response
async def websocket_handle_subscribe_todo_items(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Subscribe to sb_todo list item updates."""
    entity_id: str = msg["entity_id"]

    if not (entity := hass.data[DATA_COMPONENT].get_entity(entity_id)):
        connection.send_error(
            msg["id"],
            "invalid_entity_id",
            f"To-do list entity not found: {entity_id}",
        )
        return

    @callback
    def todo_item_listener(todo_items: list[JsonValueType] | None) -> None:
        """Push updated list items to websocket."""
        connection.send_message(
            websocket_api.event_message(
                msg["id"],
                {
                    "items": todo_items,
                },
            )
        )

    connection.subscriptions[msg["id"]] = entity.async_subscribe_updates(
        todo_item_listener
    )
    connection.send_result(msg["id"])

    # Push initial data
    entity.async_update_listeners()


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sb_todo/item/list",
        vol.Required("entity_id"): cv.entity_id,
    }
)
@websocket_api.async_response
async def websocket_handle_todo_item_list(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return the list of sb_todo items."""
    entity_id = msg[CONF_ENTITY_ID]
    if not (entity := hass.data[DATA_COMPONENT].get_entity(entity_id)):
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Entity not found")
        return

    items: list[TodoItem] = getattr(entity, "todo_items", []) or []
    connection.send_message(
        websocket_api.result_message(
            msg["id"],
            {
                "items": [asdict(item) for item in items],
            },
        )
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sb_todo/item/move",
        vol.Required("entity_id"): cv.entity_id,
        vol.Required("uid"): cv.string,
        vol.Optional("previous_uid"): cv.string,
    }
)
@websocket_api.async_response
async def websocket_handle_todo_item_move(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Handle moving an item within the sb_todo list."""
    if not (entity := hass.data[DATA_COMPONENT].get_entity(msg["entity_id"])):
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Entity not found")
        return

    if (
        not getattr(entity, "supported_features", 0)
        or not entity.supported_features & TodoListEntityFeature.MOVE_TODO_ITEM
    ):
        connection.send_message(
            websocket_api.error_message(
                msg["id"],
                websocket_api.ERR_NOT_SUPPORTED,
                "To-do list does not support item reordering",
            )
        )
        return
    try:
        await entity.async_move_todo_item(uid=msg["uid"], previous_uid=msg.get("previous_uid"))
    except HomeAssistantError as ex:
        connection.send_error(msg["id"], "failed", str(ex))
    else:
        connection.send_result(msg["id"])
