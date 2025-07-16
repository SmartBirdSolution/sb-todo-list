class SbTodoListCard extends HTMLElement {

    setConfig(config) {
        this.config = config;
        this.attachShadow({ mode: "open" });

        const style = document.createElement("style");
        style.textContent = `
          .sb-button {
            background: var(--primary-color);
            color: white;
            padding: 0.5em 1em;
            border: none;
            border-radius: 4px;
            cursor: pointer;
          }

          .sb-button:hover {
            opacity: 0.9;
          }

          .sb-button-danger {
            color: var(--error-color);
            background: none;
            border: none;
            cursor: pointer;
          }

          .sb-input {
            width: 100%;
            padding: 0.6em 0.8em;
            font-size: 1em;
            border: 1px solid var(--divider-color, #ccc);
            border-radius: 4px;
            background: var(--mdc-select-fill-color, #f5f5f5);
            color: var(--primary-text-color, #000);
            box-sizing: border-box;
            transition: border-color 0.2s ease;
          }

          .sb-input:focus {
            border-color: var(--mdc-theme-primary, var(--primary-color, #6200ee));
            outline: none;
          }

          .sb-row {
            display: flex;
            gap: 0.5em;
            margin-bottom: 1em;
          }

          .sb-row.vertical {
            flex-direction: column;
          }

          .sb-label {
            font-size: 0.9em;
            color: var(--secondary-text-color, #666);
            margin-bottom: 0.2em;
          }

          .sb-checkbox-row {
            display: flex;
            align-items: center;
            gap: 0.5em;
          }

          .sb-select {
            padding: 0.5em;
            border: 1px solid var(--divider-color, #ccc);
            border-radius: 4px;
            background: var(--divider-color, #ccc);
            font-size: 1em;
            color: var(--primary-text-color, #000); /* Ensures text is visible */
            transition: background 0.3s ease;
          }

          .sb-select:hover,
          .sb-select:focus {
            background: var(--divider-color, #ccc);
            outline: none;
            border-color: var(--mdc-theme-primary, #6200ee);
          }

          .sb-select option {
            background: #3b3b3b;
            color: var(--primary-text-color, #000); /* Explicit text color */
          }


          .sb-select:disabled,
          .sb-input:disabled {
            background: var(--input-disabled-fill-color, #3a3a3a);
            color: var(--disabled-text-color, #999);
            cursor: not-allowed;
          }

        `;
        this.shadowRoot.appendChild(style);
        this.selectedIndex = 0;

        this.card = document.createElement("ha-card");
        this.card.header = this.config.title || "Todo Lists";

        this.card.style.width = "50vw";
        this.card.style.maxWidth = "none";
        this.card.style.minWidth = "500px";

        this.card.style.height = "100vh";
        this.card.style.maxHeight = "none";
        this.card.style.minHeight = "500px";

        this.card.style.margin = "0 auto";

        this.tabContainer = document.createElement("div");
        this.tabContainer.style.display = "flex";
        this.tabContainer.style.gap = "1em";
        this.tabContainer.style.padding = "0.5em 1em";
        this.tabContainer.style.borderBottom = "1px solid #ccc";
        this.card.appendChild(this.tabContainer);

        this.content = document.createElement("div");
        this.content.style.display = "flex";
        this.content.style.justifyContent = "space-between";
        this.content.style.gap = "2em";
        this.content.style.padding = "1em";
        this.content.style.overflowY = "auto";   // enable vertical scroll if content overflows
        this.content.style.maxHeight = "50vh";
        this.card.appendChild(this.content);

        this.listContainer = document.createElement("div");
        this.listContainer.style.flex = "1";
        this.content.appendChild(this.listContainer);

        this.clearCompletedContainer = document.createElement("div");
        this.clearCompletedContainer.style.padding = "0.5em 1em";
        this.clearCompletedContainer.style.textAlign = "right";
        // this.clearCompletedContainer.style.borderBottom = "1px solid #ccc";
        this.card.appendChild(this.clearCompletedContainer);


        // Create the line element
        this.separatorLine = document.createElement("div");
        this.separatorLine.style.position = "absolute";
        this.separatorLine.style.bottom = "calc(10% + 30px)";
        this.separatorLine.style.left = "0";
        this.separatorLine.style.width = "100%";
        this.separatorLine.style.height = "1px";
        this.separatorLine.style.backgroundColor = "white";
        this.separatorLine.style.opacity = "0.6";

        // Add the line to the card (same container as actions)
        this.card.appendChild(this.separatorLine);


        this.actions = document.createElement("div");
        this.actions.style.position = "absolute";
        this.actions.style.bottom = "5%";
        this.actions.style.left = "0";
        this.actions.style.width = "100%";
        this.actions.style.display = "flex";
        this.actions.style.justifyContent = "center";
        this.actions.style.gap = "1em";
        // this.actions.style.borderTop = "1px solid #ccc";
        this.card.appendChild(this.actions);

        this.shadowRoot.appendChild(this.card);

        this._renderAddListButton?.();
    }

    set hass(hass) {
        this._hass = hass;

        const entityIds = this.config.entities && Array.isArray(this.config.entities)
            ? this.config.entities
            : Object.keys(hass.states)
                .filter(id =>
                    id.startsWith("sb_todo.") &&
                    hass.states[id].state !== "unavailable"
                );

        this.entities = entityIds
            .map(eid => hass.states[eid])
            .filter(Boolean);

        // Always show tabs & action area, even if no entities
        this._renderTabs();
        this._renderSelectedListTasks();
        this._renderAddButton();
    }


    _renderTabs() {
        this.tabContainer.innerHTML = "";

        this.entities.forEach((entity, index) => {
            const tab = document.createElement("button");
            tab.style.display = "flex";
            tab.style.alignItems = "center";
            tab.style.padding = "0.5em 1em";
            tab.style.border = "none";
            tab.style.color = "white";
            tab.style.borderBottom =
                index === this.selectedIndex ? "2px solid var(--primary-color)" : "2px solid transparent";
            tab.style.background = "none";
            tab.style.cursor = "pointer";
            tab.style.fontWeight = index === this.selectedIndex ? "bold" : "normal";

            // Use display name (friendly_name attribute) for label
            const labelSpan = document.createElement("span");
            labelSpan.textContent = entity.attributes.friendly_name || entity.entity_id;
            labelSpan.style.flex = "1";
            labelSpan.style.cursor = "pointer";

            labelSpan.addEventListener("dblclick", async (e) => {
                e.stopPropagation();
                // Use full entity_id for service call
                const entityId = entity.entity_id;
                const currentDisplayName = entity.attributes.friendly_name || entityId.split(".")[1];
                const newName = prompt(`Rename list "${currentDisplayName}" to:`);
                if (newName && newName !== currentDisplayName && confirm(`Rename list "${currentDisplayName}" to "${newName}"?`)) {
                    await this._hass.callService("sb_todo", "rename_list", {
                        entity_id: entityId,
                        new_name: newName.trim(),
                    });
                    setTimeout(() => this._refreshLists(), 500);
                }
            });

            tab.appendChild(labelSpan);

            tab.addEventListener("click", () => {
                this.selectedIndex = index;
                this._renderTabs();
                this._renderSelectedListTasks();
                this._renderAddButton();
            });

            // Delete button with confirmation
            const delBtn = document.createElement("button");
            delBtn.textContent = "✖";
            delBtn.title = `Delete list ${labelSpan.textContent}`;
            delBtn.className = 'sb-button-danger';
            // delBtn.style.marginLeft = "0.5em";
            // delBtn.style.color = "var(--error-color)";
            // delBtn.style.background = "none";
            // delBtn.style.border = "none";
            // delBtn.style.cursor = "pointer";

            delBtn.addEventListener("click", async (e) => {
                e.stopPropagation();
                const listId = entity.entity_id.split(".")[1];
                if (confirm(`Are you sure you want to delete list "${labelSpan.textContent}"?`)) {
                    await this._hass.callService("sb_todo", "delete_list", { name: listId });
                    setTimeout(() => this._refreshLists(), 500);
                }
            });

            tab.appendChild(delBtn);

            this.tabContainer.appendChild(tab);

        });
    }

    async _refreshLists() {
        this.entities = this.config.entities.map(eid => this._hass.states[eid]).filter(Boolean);
        if (this.selectedIndex >= this.entities.length) this.selectedIndex = 0;
        this._renderTabs();
        this._renderSelectedListTasks();
        this._renderAddButton();
    }

    _renderSelectedListTasks() {
        this.content.innerHTML = "";
        this.clearCompletedContainer.innerHTML = "";  // clear previous button

        if (!this.entities.length) {
            this.content.textContent = "No todo lists available.";
            return;
        }

        const entity = this.entities[this.selectedIndex];
        if (!entity) return;

        const items = entity.attributes.todo_items || [];
        const activeTasks = items.filter(item => item.status !== "completed");
        const completedTasks = items.filter(item => item.status === "completed");

        // Show clear completed button only if there are completed tasks
        if (completedTasks.length > 0) {
            const clearCompletedBtn = document.createElement("button");
            clearCompletedBtn.textContent = "🧹 Clear Completed";
            clearCompletedBtn.className = 'sb-button';
            // clearCompletedBtn.style.background = "var(--primary-color)";
            // clearCompletedBtn.style.color = "white";
            // clearCompletedBtn.style.padding = "0.5em 1em";
            // clearCompletedBtn.style.border = "none";
            // clearCompletedBtn.style.borderRadius = "4px";
            // clearCompletedBtn.style.cursor = "pointer";

            clearCompletedBtn.addEventListener("click", async () => {
                if (confirm("Remove all completed items?")) {
                    await this._hass.callService("sb_todo", "remove_completed_items", {
                        entity_id: entity.entity_id,
                    });
                    setTimeout(() => this._refreshLists(), 500);
                }
            });

            this.clearCompletedContainer.appendChild(clearCompletedBtn);
        }

        const section = (titleText, tasks) => {
            const section = document.createElement("div");
            section.style.flex = "1";
            const title = document.createElement("h3");
            title.textContent = titleText;
            section.appendChild(title);
            tasks.forEach(item => section.appendChild(this._renderTask(item, entity.entity_id)));
            return section;
        };

        this.content.appendChild(section("To Do", activeTasks));
        this.content.appendChild(section("Completed", completedTasks));
    }


    _renderTask(item, entityId) {
        const line = document.createElement("div");
        line.style.marginBottom = "0.5em";
        line.style.border = "1px solid #ccc";
        line.style.borderRadius = "4px";
        line.style.padding = "0.5em";
        line.style.display = "flex";
        line.style.flexDirection = "column";

        // 🔁 Background color based on due date
        if (item.due_datetime || item.due_date) {
            const due = new Date(item.due_datetime || item.due_date);
            const now = new Date();
            const diffMs = due.getTime() - now.getTime();
            const diffDays = diffMs / (1000 * 60 * 60 * 24);

            if (diffDays >= 3) {
                line.style.background = "#d4ffdd"; // green
                line.style.color = "#000"
            } else if (diffDays >= 0) {
                line.style.background = "#fff3cd"; // yellow
                line.style.color = "#000"
            } else {
                line.style.background = "#f8d7da"; // red
                line.style.color = "#000"
            }
        }

        // ===== TOP ROW: Delete - Name - Done Button =====
        const topRow = document.createElement("div");
        topRow.style.display = "flex";
        topRow.style.alignItems = "center";
        topRow.style.justifyContent = "space-between";

        // 🔴 Delete button
        const deleteButton = document.createElement("button");
        deleteButton.textContent = "✖";
        deleteButton.title = `Delete item "${item.summary}"`;
        deleteButton.style.color = "var(--error-color)";
        deleteButton.style.background = "none";
        deleteButton.style.border = "none";
        deleteButton.style.cursor = "pointer";
        deleteButton.style.marginRight = "0.5em";
        deleteButton.addEventListener("click", async () => {
            if (confirm(`Delete item "${item.summary}"?`)) {
                await this._hass.callService("sb_todo", "remove_item", {
                    entity_id: entityId,
                    item: item.uid || item.summary,
                });
                setTimeout(() => this._refreshLists(), 500);
            }
        });

        // 📝 Name text
        const name = document.createElement("div");
        name.style.flex = "1";
        name.style.textAlign = "center";
        name.style.wordBreak = "break-word";
        name.style.padding = "0 0.5em";
        name.style.cursor = "pointer";
        name.textContent = item.summary;
        if (item.status === "completed") {
            name.style.textDecoration = "line-through";
            name.style.opacity = "0.6";
        }
        name.addEventListener("dblclick", () => this._showEditDialog(item, entityId));

        // ✅ Done / Undo button
        const toggleBtn = document.createElement("button");
        toggleBtn.textContent = item.status === "completed" ? "Undo" : "Done";
        toggleBtn.className = "sb-button";
        toggleBtn.addEventListener("click", () => {
            this._hass.callService("sb_todo", "update_item", {
                entity_id: entityId,
                item: item.summary,
                status: item.status === "completed" ? "needs_action" : "completed",
            });
        });

        topRow.appendChild(deleteButton);
        topRow.appendChild(name);
        topRow.appendChild(toggleBtn);

        // ===== BOTTOM ROW: Parameters (bulleted, multiline) =====
        const details = document.createElement("ul");
        details.style.fontSize = "0.85em";
        details.style.color = "#555";
        details.style.margin = "0.5em 0 0 1em";
        details.style.padding = "0";
        details.style.listStyleType = "disc";

        if (item.due_datetime || item.due_date) {
            const due = new Date(item.due_datetime || item.due_date);
            const formatted = due.toLocaleString("en-US", {
                month: "2-digit",
                day: "2-digit",
                year: "numeric",
                hour: "2-digit",
                minute: "2-digit",
                hour12: true,
            });
            const li = document.createElement("li");
            li.textContent = `📅 Due: ${formatted}`;
            details.appendChild(li);
        }

        if (item.requiring) {
            const li = document.createElement("li");
            li.textContent = `🔁 Requiring`;
            details.appendChild(li);
        }

        if (item.period) {
            const li = document.createElement("li");
            li.textContent = `🕒 Repeats: every ${item.period}`;
            details.appendChild(li);
        }

        line.appendChild(topRow);
        line.appendChild(details);

        return line;
    }

    _renderAddListButton() {
        // Stub for add-list logic, populated in _renderAddButton
    }

    _renderAddButton() {
        this.actions.innerHTML = "";

        if (this.entities.length) {
            const addTaskBtn = document.createElement("button");
            addTaskBtn.textContent = "➕ Add Task";
            addTaskBtn.style.marginRight = "1em";
            addTaskBtn.className = 'sb-button';
            addTaskBtn.addEventListener("click", () => this._showAddDialog());
            this.actions.appendChild(addTaskBtn);
        }

        const addListBtn = document.createElement("button");
        addListBtn.textContent = "➕ Add New List";
        addListBtn.className = 'sb-button';
        addListBtn.addEventListener("click", () => this._showAddListDialog());
        this.actions.appendChild(addListBtn);
    }


    _showEditDialog(item, entityId) {
        if (!this._editDialog) this._editDialog = this._createDialog();
        this._populateDialog(this._editDialog, item, false, entityId);
        this._editDialog.showModal();
    }

    _showAddDialog() {
        if (!this._addDialog) this._addDialog = this._createDialog();
        this._populateDialog(this._addDialog, null, true, this.entities[this.selectedIndex].entity_id);
        this._addDialog.showModal();
    }

    _showAddListDialog() {
        if (!this._addListDialog) {
            this._addListDialog = document.createElement("dialog");
            this._addListDialog.style.padding = "1em";
            this._addListDialog.style.maxWidth = "400px";
            this._addListDialog.style.border = "1px solid #97989c"
            this._addListDialog.style.borderRadius = "6px";
            this._addListDialog.style.background = "var(--ha-card-background,var(--card-background-color,#fff))"

            const input = document.createElement("input");
            input.type = "text";
            input.placeholder = "New list name";
            input.className = "sb-input";
            input.style.marginBottom = "1em";
            this._addListDialog.appendChild(input);

            const buttonsContainer = document.createElement("div");
            buttonsContainer.style.display = "flex";
            buttonsContainer.style.justifyContent = "center";
            buttonsContainer.style.gap = "1em";

            const saveBtn = document.createElement("button");
            saveBtn.textContent = "Create";
            saveBtn.style.marginRight = "1em";
            saveBtn.className = 'sb-button';
            saveBtn.addEventListener("click", async () => {
                const name = input.value.trim();
                if (!name) {
                    alert("List name cannot be empty");
                    return;
                }

                if (this.entities.length >= 5) {
                    alert("You can only have up to 5 todo lists.");
                    return;
                }

                if (confirm(`Are you sure you want to create a new list "${name}"?`)) {
                    await this._hass.callService("sb_todo", "create_list", { name });
                    this._addListDialog.close();
                    setTimeout(() => this._refreshLists(), 500);
                }
            });

            const cancelBtn = document.createElement("button");
            cancelBtn.textContent = "Cancel";
            cancelBtn.className = 'sb-button';
            cancelBtn.addEventListener("click", () => this._addListDialog.close());

            buttonsContainer.appendChild(cancelBtn);
            buttonsContainer.appendChild(saveBtn);

            this._addListDialog.appendChild(buttonsContainer);
            this.shadowRoot.appendChild(this._addListDialog);
            this._addListInput = input;
        }

        this._addListInput.value = "";
        this._addListDialog.showModal();
    }

    _createDialog() {
        const dialog = document.createElement("dialog");
        dialog.style.padding = "1em";
        dialog.style.maxWidth = "400px";
        dialog.style.border = "1px solid #97989c"
        dialog.style.borderRadius = "6px";
        dialog.style.background = "var(--ha-card-background,var(--card-background-color,#fff))"


        // === Task Name
        const nameWrapper = document.createElement("div");
        nameWrapper.className = "sb-row vertical";

        const nameLabel = document.createElement("label");
        nameLabel.textContent = "Task Name";
        nameLabel.className = "sb-label";

        dialog.nameInput = document.createElement("input");
        dialog.nameInput.type = "text";
        dialog.nameInput.className = "sb-input";

        nameWrapper.appendChild(nameLabel);
        nameWrapper.appendChild(dialog.nameInput);

        // === Date + Time
        const datetimeRow = document.createElement("div");
        datetimeRow.className = "sb-row";

        dialog.dateInput = document.createElement("input");
        dialog.dateInput.type = "date";
        dialog.dateInput.className = "sb-input";
        dialog.dateInput.style.flex = "1";

        dialog.timeInput = document.createElement("input");
        dialog.timeInput.type = "time";
        dialog.timeInput.className = "sb-input";
        dialog.timeInput.style.flex = "1";

        datetimeRow.appendChild(dialog.dateInput);
        datetimeRow.appendChild(dialog.timeInput);

        // === Requiring + Period
        const recurringRow = document.createElement("div");
        recurringRow.className = "sb-row";

        const checkWrap = document.createElement("div");
        checkWrap.className = "sb-checkbox-row";
        dialog.requiringCheck = document.createElement("input");
        dialog.requiringCheck.type = "checkbox";
        const checkLabel = document.createElement("label");
        checkLabel.textContent = "Requiring";

        checkWrap.appendChild(dialog.requiringCheck);
        checkWrap.appendChild(checkLabel);

        dialog.periodAmount = document.createElement("input");
        dialog.periodAmount.type = "number";
        dialog.periodAmount.className = "sb-input";
        dialog.periodAmount.style.width = "60px";
        dialog.periodAmount.placeholder = "e.g. 2";
        dialog.periodAmount.disabled = true;

        dialog.periodUnit = document.createElement("select");
        dialog.periodUnit.className = "sb-select";
        dialog.periodUnit.disabled = true;

        ["minute", "hour", "day", "week", "month", "year"].forEach(unit => {
            const opt = document.createElement("option");
            opt.value = unit;
            opt.textContent = unit;
            dialog.periodUnit.appendChild(opt);
        });

        dialog.requiringCheck.addEventListener("change", () => {
            const enable = dialog.requiringCheck.checked;
            dialog.periodAmount.disabled = !enable;
            dialog.periodUnit.disabled = !enable;
        });

        recurringRow.appendChild(checkWrap);
        recurringRow.appendChild(dialog.periodAmount);
        recurringRow.appendChild(dialog.periodUnit);

        // === Buttons
        dialog.saveBtn = document.createElement("button");
        dialog.saveBtn.textContent = "Save";
        dialog.saveBtn.className = "sb-button";
        dialog.saveBtn.style.marginRight = "1em";

        dialog.cancelBtn = document.createElement("button");
        dialog.cancelBtn.textContent = "Cancel";
        dialog.cancelBtn.className = "sb-button";
        dialog.cancelBtn.addEventListener("click", () => dialog.close());

        dialog.appendChild(nameWrapper);
        dialog.appendChild(datetimeRow);
        dialog.appendChild(recurringRow);

        const buttonsContainer = document.createElement("div");
        buttonsContainer.style.display = "flex";
        buttonsContainer.style.justifyContent = "center";
        buttonsContainer.style.gap = "1em";

        buttonsContainer.appendChild(dialog.saveBtn);
        buttonsContainer.appendChild(dialog.cancelBtn);

        dialog.appendChild(buttonsContainer);
        this.shadowRoot.appendChild(dialog);
        return dialog;
    }



    _populateDialog(dialog, item, isNew, entityId) {
        if (item) {
            dialog.nameInput.value = item.summary;
            if (item.due_datetime) {
                const [date, time] = item.due_datetime.split("T");
                dialog.dateInput.value = date;
                dialog.timeInput.value = time?.slice(0, 5) ?? "";
            } else {
                dialog.dateInput.value = "";
                dialog.timeInput.value = "";
            }
            // Set checkbox
            dialog.requiringCheck.checked = !!item?.requiring;

            // Enable/disable period based on checkbox
            const togglePeriodInputs = () => {
                const enabled = dialog.requiringCheck.checked;
                dialog.periodAmount.disabled = !enabled;
                dialog.periodUnit.disabled = !enabled;
            };

            // Set period values if available
            if (item?.period) {
                dialog.periodAmount.value = item.period.match(/\d+/)?.[0] || "";
                dialog.periodUnit.value = item.period.match(/[a-zA-Z]+/)?.[0] || "d";
            } else {
                dialog.periodAmount.value = "";
                dialog.periodUnit.value = "d";
            }

            // Initial toggle
            togglePeriodInputs();

            // Listen for checkbox toggle
            dialog.requiringCheck.addEventListener("change", togglePeriodInputs);
        } else {
            dialog.nameInput.value = "";
            dialog.dateInput.value = "";
            dialog.timeInput.value = "";
            dialog.requiringCheck.checked = false;
            dialog.periodAmount.value = "";
            dialog.periodUnit.value = "d";
        }

        dialog.saveBtn.onclick = () => {
            const due_date = dialog.dateInput.value;
            const due_time = dialog.timeInput.value;
            const due_datetime = due_date && due_time ? `${due_date}T${due_time}` : due_date || null;

            const amount = dialog.periodAmount.value?.trim() ?? "";

            const periodStr = amount !== "" && Number.isInteger(Number(amount)) &&  Number(amount) > 0 ? `${amount}${dialog.periodUnit.value}` : null;

            if (isNew) {
                this._hass.callService("sb_todo", "add_item", {
                    entity_id: entityId,
                    item: dialog.nameInput.value.trim(),
                    due_datetime,
                    requiring: dialog.requiringCheck.checked,
                    period: periodStr,
                });
            } else {
                this._hass.callService("sb_todo", "update_item", {
                    entity_id: entityId,
                    item: item.summary,
                    rename: dialog.nameInput.value.trim(),
                    due_datetime,
                    requiring: dialog.requiringCheck.checked,
                    period: periodStr,
                });
            }
            dialog.close();
        };
    }

    getCardSize() {
        return 6;
    }
}

customElements.define("sb-todo-list", SbTodoListCard);
