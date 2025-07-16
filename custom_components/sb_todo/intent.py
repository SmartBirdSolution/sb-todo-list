"""Intents for the my_todo integration."""

from __future__ import annotations

import datetime
import re
import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent

from . import TodoItem, TodoItemStatus, TodoListEntity
from .const import DATA_COMPONENT, DOMAIN

INTENT_LIST_ADD_ITEM = "HassListAddItem"
INTENT_LIST_COMPLETE_ITEM = "HassListCompleteItem"

PERIOD_REGEX = re.compile(r"^(?P<num>\d+)(?P<unit>minute|hour|day|week|month|year)$")

async def async_setup_intents(hass: HomeAssistant) -> None:
    """Set up the my_todo intents."""
    intent.async_register(hass, ListAddItemIntent())
    intent.async_register(hass, ListCompleteItemIntent())

def parse_period(period_str: str) -> datetime.timedelta | None:
    """Parse a period string into a timedelta or None if unsupported."""
    match = PERIOD_REGEX.match(period_str)
    if not match:
        return None
    num = int(match.group("num"))
    unit = match.group("unit")

    if unit == "minute":
        return datetime.timedelta(minutes=num)
    if unit == "hour":
        return datetime.timedelta(hours=num)
    if unit == "day":
        return datetime.timedelta(days=num)
    if unit == "week":
        return datetime.timedelta(weeks=num)
    if unit == "month":
        # Approximate one month as 30 days
        return datetime.timedelta(days=30 * num)
    if unit == "year":
        # Approximate one year as 365 days
        return datetime.timedelta(days=365 * num)
    return None

class ListAddItemIntent(intent.IntentHandler):
    """Handle ListAddItem intents."""

    intent_type = INTENT_LIST_ADD_ITEM
    description = "Add item to a todo list"
    slot_schema = {
        vol.Required("item"): intent.non_empty_string,
        vol.Required("name"): intent.non_empty_string,
        vol.Optional("requiring"): vol.Boolean(),  # Optional slot for requiring
        vol.Optional("period"): intent.non_empty_string,  # Optional period string
    }
    platforms = {DOMAIN}

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        """Handle the intent."""
        hass = intent_obj.hass

        slots = self.async_validate_slots(intent_obj.slots)
        item = slots["item"]["value"].strip()
        list_name = slots["name"]["value"]
        requiring = slots.get("requiring", {}).get("value", False)
        period = slots.get("period", {}).get("value")

        target_list: TodoListEntity | None = None

        # Find matching list
        match_constraints = intent.MatchTargetsConstraints(
            name=list_name, domains=[DOMAIN], assistant=intent_obj.assistant
        )
        match_result = intent.async_match_targets(hass, match_constraints)
        if not match_result.is_match:
            raise intent.MatchFailedError(
                result=match_result, constraints=match_constraints
            )

        target_list = hass.data[DATA_COMPONENT].get_entity(
            match_result.states[0].entity_id
        )
        if target_list is None:
            raise intent.IntentHandleError(
                f"No to-do list: {list_name}", "list_not_found"
            )

        # Create todo item with optional requiring and period
        todo_item = TodoItem(
            summary=item,
            status=TodoItemStatus.NEEDS_ACTION,
        )
        if requiring is not None:
            todo_item.requiring = requiring
        if period:
            todo_item.period = period

        await target_list.async_create_todo_item(todo_item)

        response: intent.IntentResponse = intent_obj.create_response()
        response.response_type = intent.IntentResponseType.ACTION_DONE
        response.async_set_results(
            [
                intent.IntentResponseTarget(
                    type=intent.IntentResponseTargetType.ENTITY,
                    name=list_name,
                    id=match_result.states[0].entity_id,
                )
            ]
        )
        return response


class ListCompleteItemIntent(intent.IntentHandler):
    """Handle ListCompleteItem intents."""

    intent_type = INTENT_LIST_COMPLETE_ITEM
    description = "Complete item on a todo list"
    slot_schema = {
        vol.Required("item"): intent.non_empty_string,
        vol.Required("name"): intent.non_empty_string,
    }
    platforms = {DOMAIN}

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        """Handle the intent."""
        hass = intent_obj.hass

        slots = self.async_validate_slots(intent_obj.slots)
        item = slots["item"]["value"]
        list_name = slots["name"]["value"]

        target_list: TodoListEntity | None = None

        # Find matching list
        match_constraints = intent.MatchTargetsConstraints(
            name=list_name, domains=[DOMAIN], assistant=intent_obj.assistant
        )
        match_result = intent.async_match_targets(hass, match_constraints)
        if not match_result.is_match:
            raise intent.MatchFailedError(
                result=match_result, constraints=match_constraints
            )

        target_list = hass.data[DATA_COMPONENT].get_entity(
            match_result.states[0].entity_id
        )
        if target_list is None:
            raise intent.IntentHandleError(
                f"No to-do list: {list_name}", "list_not_found"
            )

        # Find item in list
        matching_item = None
        for todo_item in target_list.todo_items or ():
            if (
                item in (todo_item.uid, todo_item.summary)
                and todo_item.status == TodoItemStatus.NEEDS_ACTION
            ):
                matching_item = todo_item
                break
        if not matching_item or not matching_item.uid:
            raise intent.IntentHandleError(
                f"Item '{item}' not found on list", "item_not_found"
            )

        # Mark as completed
        await target_list.async_update_todo_item(
            TodoItem(
                uid=matching_item.uid,
                summary=matching_item.summary,
                status=TodoItemStatus.COMPLETED,
            )
        )

        # If requiring and period are set, create a new item with new due date
        requiring = getattr(matching_item, "requiring", False)
        period = getattr(matching_item, "period", None)
        if requiring and period:
            new_due = None
            now = datetime.datetime.now()
            delta = parse_period(period)
            if delta:
                # Calculate new due date/time (date or datetime depending on original)
                if isinstance(matching_item.due, datetime.datetime):
                    new_due = now + delta
                elif isinstance(matching_item.due, datetime.date):
                    new_due = (now + delta).date()
                else:
                    # fallback to datetime
                    new_due = now + delta

                # Create new todo item with same summary and new due
                new_item = TodoItem(
                    summary=matching_item.summary,
                    status=TodoItemStatus.NEEDS_ACTION,
                    due=new_due,
                    requiring=requiring,
                    period=period,
                )
                await target_list.async_create_todo_item(new_item)

        response: intent.IntentResponse = intent_obj.create_response()
        response.response_type = intent.IntentResponseType.ACTION_DONE
        response.async_set_results(
            [
                intent.IntentResponseTarget(
                    type=intent.IntentResponseTargetType.ENTITY,
                    name=list_name,
                    id=match_result.states[0].entity_id,
                )
            ]
        )
        return response
