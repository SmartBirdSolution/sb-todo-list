from __future__ import annotations

import dataclasses
import logging
import os
import json
import uuid
import re  # <-- Add this import for regular expressions
from datetime import datetime, timedelta  # <-- Add timedelta and datetime
from typing import Any, List, Optional, Callable

from homeassistant.helpers.entity import Entity
from homeassistant.helpers.storage import STORAGE_DIR
from homeassistant.core import CALLBACK_TYPE, callback
from homeassistant.util import dt as dt_util
from dateutil.relativedelta import relativedelta

from .const import DOMAIN, TodoItemStatus, TodoListEntityFeature

_LOGGER = logging.getLogger(__name__)

@dataclasses.dataclass
class TodoItem:
    uid: Optional[str]
    summary: str
    status: str = TodoItemStatus.NEEDS_ACTION
    due_date: Optional[str] = None
    due_datetime: Optional[str] = None
    description: Optional[str] = None
    requiring: Optional[bool] = None
    period: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        # Convert datetime fields to Unix timestamps
        def convert_to_timestamp(value):
            if isinstance(value, datetime):
                return value.timestamp()
            return value

        return {k: convert_to_timestamp(v) for k, v in dataclasses.asdict(self).items()}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TodoItem:
        # Convert Unix timestamps back to datetime objects
        # def convert_to_datetime(value):
        #     if isinstance(value, (int, float)):
        #         return datetime.fromtimestamp(value)
        #     return value

        return cls(
            uid=data.get("uid"),
            summary=data["summary"],
            status=data.get("status", TodoItemStatus.NEEDS_ACTION),
            due_date=data.get("due_date"),
            due_datetime=data.get("due_datetime"),
            description=data.get("description"),
            requiring=data.get("requiring"),
            period=data.get("period"),
        )


class MyTodoList(Entity):
    def __init__(self, name: str, display_name: str | None = None):
        self._name = name
        self._display_name = display_name or name.replace("_", " ").title()  # display name for UI
        self._attr_name = self._display_name
        self._attr_unique_id = f"{DOMAIN}_{name}"
        self._todo_items: List[TodoItem] = []
        self._attr_extra_state_attributes = {}
        self._storage_path = os.path.join(STORAGE_DIR, "sb_todo", f"{self._name}.json")
        self._listeners: list[Callable[[list[TodoItem] | None], None]] = []

    @property
    def unique_id(self) -> str:
        return self._attr_unique_id

    @property
    def state(self) -> str:
        count = sum(1 for item in self._todo_items if item.status == TodoItemStatus.NEEDS_ACTION)
        return str(count)

    @property
    def todo_items(self) -> List[TodoItem]:
        return self._todo_items

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "friendly_name": self._display_name,
            "todo_items": [item.to_dict() for item in self._todo_items]
        }

    @property
    def supported_features(self) -> int:
        return (
                TodoListEntityFeature.CREATE_TODO_ITEM
                | TodoListEntityFeature.UPDATE_TODO_ITEM
                | TodoListEntityFeature.DELETE_TODO_ITEM
                | TodoListEntityFeature.SET_DUE_DATE_ON_ITEM
                | TodoListEntityFeature.SET_DUE_DATETIME_ON_ITEM
                | TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM
                | TodoListEntityFeature.SET_REQUIRING_ON_ITEM
                | TodoListEntityFeature.SET_PERIOD_ON_ITEM
                | TodoListEntityFeature.MOVE_TODO_ITEM
        )

    async def async_added_to_hass(self) -> None:
        await self.async_load_items()

    async def async_load_items(self) -> None:
        if os.path.exists(self._storage_path):
            try:
                with open(self._storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                    if isinstance(data, dict):
                        stored_display_name = data.get("display_name")
                        items_list = data.get("todo_items", [])

                        if stored_display_name:
                            self._display_name = stored_display_name
                            self._attr_name = stored_display_name  # update entity name
                            self.async_write_ha_state()  # update Home Assistant state with new name
                    else:
                        items_list = data

                    # Convert Unix timestamps to ISO strings for due_datetime
                    # for item in items_list:
                    #     due_dt = item.get("due_datetime")
                    #     if due_dt is not None:
                    #         if isinstance(due_dt, (int, float)):
                    #             try:
                    #                 dt_obj = datetime.fromtimestamp(due_dt)
                    #                 item["isoformat"] = dt_obj.isoformat()
                    #             except Exception as e:
                    #                 _LOGGER.warning("Failed to parse due_datetime timestamp %s: %s", due_dt, e)

                    self._todo_items = [TodoItem.from_dict(item) for item in items_list]
                    self._todo_items.sort(key=lambda item: float(item.due_datetime) if item.due_datetime is not None else float('inf'))
                    _LOGGER.debug("Loaded %d todo items for %s", len(self._todo_items), self._name)

            except Exception as e:
                _LOGGER.error("Failed to load items for %s: %s", self._name, e)
        else:
            self._todo_items = []


    async def async_create_todo_item(self, item: TodoItem) -> None:
        # Check if an item with the same summary already exists
        for idx, existing_item in enumerate(self._todo_items):
            if existing_item.summary == item.summary:
                # Update the existing item with new data (but keep its UID)
                _LOGGER.info("Item with summary '%s' already exists. Updating existing item.", item.summary)
                updated_uid = existing_item.uid  # preserve original UID
                item.uid = updated_uid
                self._todo_items[idx] = item
                await self._save_and_refresh()
                return

        # If no match is found, create a new item
        if not item.uid:
            item.uid = str(uuid.uuid4())

        _LOGGER.info("Creating new todo item with summary '%s'", item.summary)
        self._todo_items.append(item)
        await self._save_and_refresh()

    async def async_update_todo_item(self, updated_item: TodoItem) -> None:
        for idx, item in enumerate(self._todo_items):
            if updated_item.uid and item.uid == updated_item.uid:
                self._todo_items[idx] = updated_item
                break
            elif not updated_item.uid and item.summary == updated_item.summary:
                self._todo_items[idx] = updated_item
                break
        else:
            _LOGGER.warning("Item to update not found: %s", updated_item)
            return
        await self._save_and_refresh()

    async def async_delete_todo_items(self, uids: List[str]) -> None:
        self._todo_items = [item for item in self._todo_items if item.uid not in uids]
        await self._save_and_refresh()

    async def async_move_todo_item(self, uid: str, previous_uid: str | None = None) -> None:
        index_map = {item.uid: idx for idx, item in enumerate(self._todo_items)}
        if uid not in index_map:
            raise ValueError(f"UID {uid} not found")
        item = self._todo_items.pop(index_map[uid])

        if previous_uid:
            if previous_uid not in index_map:
                raise ValueError(f"Previous UID {previous_uid} not found")
            prev_index = index_map[previous_uid]
            # Adjust index if necessary due to pop
            if prev_index > index_map[uid]:
                prev_index -= 1
            self._todo_items.insert(prev_index + 1, item)
        else:
            # Insert at start
            self._todo_items.insert(0, item)

        await self._save_and_refresh()

    def async_subscribe_updates(self, listener: Callable[[list[TodoItem] | None], None]) -> CALLBACK_TYPE:
        self._listeners.append(listener)

        # Immediately notify the new listener with current items
        listener(self._todo_items)

        def remove_listener():
            self._listeners.remove(listener)

        return remove_listener

    @callback
    def async_update_listeners(self) -> None:
        for listener in self._listeners:
            listener(self._todo_items)


    async def _save_and_refresh(self) -> None:
        self._todo_items.sort(key=lambda item: float(item.due_datetime) if item.due_datetime is not None else float('inf'))

        os.makedirs(os.path.dirname(self._storage_path), exist_ok=True)

        # Prepare data for JSON serialization
        data = {
            "display_name": self._display_name,
            "todo_items": [item.to_dict() for item in self._todo_items],
        }

        # Debug log for full JSON content
        _LOGGER.debug("Saving JSON: %s", json.dumps(data, ensure_ascii=False, indent=2))

        text = json.dumps(data, ensure_ascii=False, indent=2)
        tmp = f"{self._storage_path}.tmp"

        # Write to temporary file
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)

        # Replace the old file only if write succeeded
        os.replace(tmp, self._storage_path)

        # Now update the Home Assistant state and listeners
        self._attr_extra_state_attributes["todo_items"] = [
            item.to_dict() for item in self._todo_items
        ]

        self.async_write_ha_state()
        self.async_update_listeners()

    async def async_update_requiring_items(self) -> None:
        now = datetime.now()
        updated = False

        for item in self._todo_items:
            if not item.requiring or not item.period:
                continue

            period_delta = self._parse_period(item.period)
            if not period_delta:
                _LOGGER.info("Skipping '%s': invalid period %s", item.summary, item.period)
                continue

            old_due = self._parse_datetime(item.due_datetime)

            if item.status == TodoItemStatus.COMPLETED:
                _LOGGER.info("Rescheduling '%s' (was completed).", item.summary)
                item.status = TodoItemStatus.NEEDS_ACTION
                _LOGGER.info("Rescheduling '%s'", item.due_datetime)
                if item.due_datetime:
                    old_due = datetime.fromtimestamp(item.due_datetime)
                    new_due = old_due + period_delta
                    _LOGGER.info("Rescheduling1 '%s'", new_due)
                else:
                    _LOGGER.info("Rescheduling2 '%s'",now + period_delta)
                    new_due = now + period_delta

                _LOGGER.info("Rescheduling '%s'",  new_due.isoformat())
                _LOGGER.info("Rescheduling '%s'",  new_due.timestamp())
                item.due_datetime = new_due.timestamp()
                updated = True

        if updated:
            _LOGGER.info("Detected updates, saving rescheduled items.")
            await self._save_and_refresh()
        else:
            _LOGGER.debug("No requiring/completed items to reschedule.")



    def _parse_period(self, period_str: Optional[str]) -> Optional[timedelta]:
        if not period_str:
            return None

        match = re.fullmatch(r"(\d+)(minute|hour|day|week|month|year)", period_str)
        if not match:
            return None

        num, unit = match.groups()
        num = int(num)
        if unit == "minute":
            return timedelta(minutes=num)
        elif unit == "hour":
            return timedelta(hours=num)
        elif unit == "day":
            return timedelta(days=num)
        elif unit == "week":
            return timedelta(weeks=num)
        elif unit == "month":
            return relativedelta(months=num)
        elif unit == "year":
            return relativedelta(years=num)
        return None

    def _parse_datetime(self, value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            # Assume value is a timestamp string or number (int/float)
            timestamp = float(value)  # convert string to float if needed
            return datetime.fromtimestamp(timestamp)
        except (ValueError, TypeError) as e:
            _LOGGER.error(f"Failed to parse timestamp '{value}': {e}")
            return None

    def validate_period(value):
        if value is None:
            return None
        if not isinstance(value, str):
            return None
        if re.fullmatch(r"^\d+(minute|hour|day|week|month|year)$", value):
            return value
        return None  # Treat invalid as None