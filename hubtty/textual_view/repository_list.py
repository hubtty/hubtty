# Copyright 2014 OpenStack Foundation
# Copyright 2014 Hewlett-Packard Development Company, L.P.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import logging

from rich.text import Text

from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import (
    Button,
    DataTable,
    Input,
    Label,
    RadioButton,
    RadioSet,
)

from hubtty import keymap
from hubtty import sync
from hubtty.textual_view.pull_request_list import PullRequestListView


# Style names matching the urwid palette entries
STYLE_UNREVIEWED = "unreviewed-repository"
STYLE_SUBSCRIBED = "subscribed-repository"
STYLE_UNSUBSCRIBED = "unsubscribed-repository"
STYLE_MARKED = "marked-repository"
STYLE_TOPIC = "subscribed-repository"

# Row key prefixes to distinguish row types
ROW_TYPE_REPO = "repo"
ROW_TYPE_TOPIC = "topic"


def _make_repo_key(repository_key, topic_key=None):
    """Create a unique row key for a repository row."""
    if topic_key is not None:
        return "%s:%s:topic:%s" % (ROW_TYPE_REPO, repository_key, topic_key)
    return "%s:%s" % (ROW_TYPE_REPO, repository_key)


def _make_topic_key(topic_key):
    """Create a unique row key for a topic row."""
    return "%s:%s" % (ROW_TYPE_TOPIC, topic_key)


def _parse_row_key(row_key):
    """Parse a row key string into (type, db_key, topic_key_or_None).

    Returns:
        ('repo', repository_key, topic_key_or_None) for repository rows
        ('topic', topic_key, None) for topic rows
    """
    key_str = str(row_key)
    parts = key_str.split(":")
    if parts[0] == ROW_TYPE_TOPIC:
        return (ROW_TYPE_TOPIC, int(parts[1]), None)
    elif parts[0] == ROW_TYPE_REPO:
        topic_key = None
        if len(parts) >= 4 and parts[2] == "topic":
            topic_key = int(parts[3])
        return (ROW_TYPE_REPO, int(parts[1]), topic_key)
    return (None, None, None)


# ---- Modal dialog screens ----


class TextInputDialog(ModalScreen):
    """A modal dialog with a text input field."""

    DEFAULT_CSS = """
    TextInputDialog {
        align: center middle;
    }
    #dialog-container {
        width: 60;
        height: auto;
        max-height: 12;
        border: thick $background 80%;
        background: $surface;
        padding: 1 2;
    }
    #dialog-container Label {
        width: 100%;
        margin-bottom: 1;
    }
    #dialog-container Input {
        width: 100%;
        margin-bottom: 1;
    }
    #dialog-buttons {
        width: 100%;
        height: 3;
        align: right middle;
    }
    #dialog-buttons Button {
        margin-left: 1;
    }
    """

    def __init__(self, title, prompt, initial=""):
        super().__init__()
        self.dialog_title = title
        self.prompt = prompt
        self.initial = initial

    def compose(self):
        with Vertical(id="dialog-container"):
            yield Label(self.dialog_title)
            yield Input(value=self.initial, placeholder=self.prompt, id="dialog-input")
            with Horizontal(id="dialog-buttons"):
                yield Button("OK", variant="primary", id="ok-btn")
                yield Button("Cancel", id="cancel-btn")

    def on_mount(self):
        self.query_one("#dialog-input", Input).focus()

    def on_button_pressed(self, event):
        if event.button.id == "ok-btn":
            value = self.query_one("#dialog-input", Input).value
            self.dismiss(value)
        else:
            self.dismiss(None)

    def on_input_submitted(self, event):
        """Handle Enter in the input field."""
        self.dismiss(event.value)

    def key_escape(self):
        self.dismiss(None)


class TopicSelectDialog(ModalScreen):
    """A modal dialog for selecting a topic from a list."""

    DEFAULT_CSS = """
    TopicSelectDialog {
        align: center middle;
    }
    #topic-dialog-container {
        width: 60;
        height: auto;
        max-height: 20;
        border: thick $background 80%;
        background: $surface;
        padding: 1 2;
    }
    #topic-dialog-container Label {
        width: 100%;
        margin-bottom: 1;
    }
    #topic-radio-set {
        width: 100%;
        max-height: 12;
        margin-bottom: 1;
    }
    #topic-dialog-buttons {
        width: 100%;
        height: 3;
        align: right middle;
    }
    #topic-dialog-buttons Button {
        margin-left: 1;
    }
    """

    def __init__(self, title, topics):
        """topics is a list of (key, name) tuples."""
        super().__init__()
        self.dialog_title = title
        self.topics = topics

    def compose(self):
        with Vertical(id="topic-dialog-container"):
            yield Label(self.dialog_title)
            with RadioSet(id="topic-radio-set"):
                for key, name in self.topics:
                    yield RadioButton(name, id="topic-%s" % key)
            with Horizontal(id="topic-dialog-buttons"):
                yield Button("OK", variant="primary", id="ok-btn")
                yield Button("Cancel", id="cancel-btn")

    def on_button_pressed(self, event):
        if event.button.id == "ok-btn":
            selected = self._get_selected()
            self.dismiss(selected)
        else:
            self.dismiss(None)

    def _get_selected(self):
        """Return the topic key of the selected radio button, or None."""
        radio_set = self.query_one("#topic-radio-set", RadioSet)
        index = radio_set.pressed_index
        if index >= 0 and index < len(self.topics):
            return self.topics[index][0]
        return None

    def key_escape(self):
        self.dismiss(None)


# ---- Main view ----


class RepositoryListView(Widget):
    """Widget showing the list of repositories."""

    title = "Repository list"

    DEFAULT_CSS = """
    RepositoryListView {
        layout: vertical;
        height: 1fr;
    }
    RepositoryListView DataTable {
        height: 1fr;
    }
    #search-bar {
        dock: bottom;
        height: 1;
        display: none;
    }
    #search-bar.visible {
        display: block;
    }
    """

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger("hubtty.textual_view.repository_list")
        self.subscribed = True
        self.unreviewed = True
        self.open_topics = set()
        # Maps row_key_str -> {type, db_key, topic_key, style, mark, name}
        self._row_meta = {}
        # Search state
        self._search_active = False
        self._search_results = []
        self._search_result_index = 0

    def compose(self):
        table = DataTable(id="repo-list")
        table.cursor_type = "row"
        table.zebra_stripes = False
        table.show_row_labels = False
        yield table
        yield Input(placeholder="Search...", id="search-bar")

    def on_mount(self):
        table = self.query_one("#repo-list", DataTable)
        table.add_column(" Repository", key="name")
        table.add_column("Unreviewed", key="unreviewed")
        table.add_column("Open", key="open")
        self.refresh_data()

    # ---- Event interest and data refresh ----

    def interested(self, event):
        """Check if a sync event should trigger a refresh."""
        if isinstance(event, sync.RepositoryAddedEvent):
            return True
        if isinstance(event, sync.PullRequestAddedEvent):
            return True
        if isinstance(event, sync.PullRequestUpdatedEvent) and (
            event.state_changed or event.review_flag_changed
        ):
            return True
        return False

    def refresh_data(self):
        """Rebuild the repository list from the database."""
        # Update title based on filter state
        if self.subscribed:
            self.title = "Subscribed repositories"
            self.short_title = self.title[:]
            if self.unreviewed:
                self.title += " with unreviewed pull requests"
        else:
            self.title = "All repositories"
            self.short_title = self.title[:]

        # Update header title
        if hasattr(self.app, "hubtty_header"):
            self.app.hubtty_header.set_title(self.title)

        table = self.query_one("#repo-list", DataTable)

        # Remember cursor position for restoration
        old_cursor_row = table.cursor_row

        table.clear()
        self._row_meta = {}

        with self.app.db.getSession() as session:
            # Topicless repositories
            for repository in session.getRepositories(
                topicless=True, subscribed=self.subscribed, unreviewed=self.unreviewed
            ):
                self._add_repository_row(table, repository, None)

            # Repositories grouped by topic
            for topic in session.getTopics():
                self._add_topic_row(table, topic)
                topic_unreviewed = 0
                topic_open = 0
                for repository in topic.repositories:
                    cache = self.app.repository_cache.get(repository)
                    topic_unreviewed += cache["unreviewed_prs"]
                    topic_open += cache["open_prs"]
                    if self.subscribed:
                        if not repository.subscribed:
                            continue
                        if self.unreviewed and not cache["unreviewed_prs"]:
                            continue
                    if topic.key in self.open_topics:
                        self._add_repository_row(table, repository, topic)
                # Update topic row with aggregate counts
                self._update_topic_counts(
                    table, topic.key, topic_unreviewed, topic_open
                )

        # Restore cursor position
        if table.row_count > 0:
            if old_cursor_row < table.row_count:
                table.move_cursor(row=old_cursor_row, animate=False)
            else:
                table.move_cursor(row=table.row_count - 1, animate=False)

    # ---- Row building helpers ----

    def _get_repo_style(self, repository, cache):
        """Determine the display style for a repository based on state."""
        if repository.subscribed:
            if cache["unreviewed_prs"] > 0:
                return STYLE_UNREVIEWED
            else:
                return STYLE_SUBSCRIBED
        return STYLE_UNSUBSCRIBED

    def _add_repository_row(self, table, repository, topic):
        """Add a repository row to the DataTable."""
        cache = self.app.repository_cache.get(repository)
        style = self._get_repo_style(repository, cache)

        if topic:
            indent = "  "
            row_key_str = _make_repo_key(repository.key, topic.key)
        else:
            indent = ""
            row_key_str = _make_repo_key(repository.key)

        name_text = Text(" " + indent + repository.name)
        name_text.stylize(style)

        unreviewed_text = Text("%i " % cache["unreviewed_prs"], justify="right")
        unreviewed_text.stylize(style)

        open_text = Text("%i " % cache["open_prs"], justify="right")
        open_text.stylize(style)

        table.add_row(name_text, unreviewed_text, open_text, key=row_key_str)

        self._row_meta[row_key_str] = {
            "type": ROW_TYPE_REPO,
            "db_key": repository.key,
            "topic_key": topic.key if topic else None,
            "style": style,
            "mark": False,
            "name": repository.name,
        }

    def _add_topic_row(self, table, topic):
        """Add a topic header row to the DataTable."""
        row_key_str = _make_topic_key(topic.key)

        name_text = Text(" [[ %s ]]" % topic.name)
        name_text.stylize(STYLE_TOPIC)

        # Counts will be updated later via _update_topic_counts
        table.add_row(name_text, Text(""), Text(""), key=row_key_str)

        self._row_meta[row_key_str] = {
            "type": ROW_TYPE_TOPIC,
            "db_key": topic.key,
            "topic_key": None,
            "style": STYLE_TOPIC,
            "mark": False,
            "name": topic.name,
        }

    def _update_topic_counts(self, table, topic_key, unreviewed, open_prs):
        """Update a topic row's aggregate PR counts."""
        row_key_str = _make_topic_key(topic_key)
        try:
            unreviewed_text = Text("%i " % unreviewed, justify="right")
            unreviewed_text.stylize(STYLE_TOPIC)
            open_text = Text("%i " % open_prs, justify="right")
            open_text.stylize(STYLE_TOPIC)
            table.update_cell(row_key_str, "unreviewed", unreviewed_text)
            table.update_cell(row_key_str, "open", open_text)
        except Exception:
            pass

    # ---- Row selection / activation ----

    def _get_focused_row_key(self):
        """Get the row key string of the currently focused row."""
        table = self.query_one("#repo-list", DataTable)
        if table.row_count == 0:
            return None
        try:
            row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
            return str(row_key)
        except Exception:
            return None

    def _get_focused_meta(self):
        """Get the metadata dict for the currently focused row."""
        row_key = self._get_focused_row_key()
        if row_key is None:
            return None
        return self._row_meta.get(row_key)

    def on_data_table_row_selected(self, event):
        """Handle Enter/click on a row."""
        row_key_str = str(event.row_key)
        meta = self._row_meta.get(row_key_str)
        if meta is None:
            return
        if meta["type"] == ROW_TYPE_REPO:
            self._open_repository(meta)
        elif meta["type"] == ROW_TYPE_TOPIC:
            self._toggle_topic(meta)

    def _open_repository(self, meta):
        """Navigate to the pull request list for a repository."""
        repo_key = meta["db_key"]
        repo_name = meta["name"]
        query = "_repository_key:%s %s" % (
            repo_key,
            self.app.config.repository_pr_list_query,
        )
        self.app.changeScreen(PullRequestListView(query, title=repo_name))

    def _toggle_topic(self, meta):
        """Toggle topic fold/collapse state."""
        topic_key = meta["db_key"]
        self.open_topics ^= {topic_key}
        self.refresh_data()

    # ---- Mark operations ----

    def _get_selected_rows(self, row_type):
        """Get marked rows of a given type, or the focused row if none marked.

        Returns a list of (row_key_str, meta) tuples.
        """
        # First check for marked rows
        marked = [
            (k, m)
            for k, m in self._row_meta.items()
            if m["mark"] and m["type"] == row_type
        ]
        if marked:
            return marked
        # Fall back to focused row
        meta = self._get_focused_meta()
        if meta and meta["type"] == row_type:
            row_key = self._get_focused_row_key()
            return [(row_key, meta)]
        return []

    def toggleMark(self):
        """Toggle the mark on the focused row, then advance cursor."""
        row_key = self._get_focused_row_key()
        if row_key is None:
            return
        meta = self._row_meta.get(row_key)
        if meta is None:
            return

        meta["mark"] = not meta["mark"]

        # Update the visual display of the name column
        table = self.query_one("#repo-list", DataTable)
        if meta["type"] == ROW_TYPE_REPO:
            indent = "  " if meta["topic_key"] is not None else ""
            prefix = "%" if meta["mark"] else " "
            style = STYLE_MARKED if meta["mark"] else meta["style"]
            name_text = Text(prefix + indent + meta["name"])
            name_text.stylize(style)
        elif meta["type"] == ROW_TYPE_TOPIC:
            prefix = "%" if meta["mark"] else " "
            style = STYLE_MARKED if meta["mark"] else meta["style"]
            name_text = Text(prefix + "[[ %s ]]" % meta["name"])
            name_text.stylize(style)
        else:
            return

        try:
            table.update_cell(row_key, "name", name_text)
        except Exception:
            pass

        # Advance cursor
        if table.cursor_row < table.row_count - 1:
            table.move_cursor(row=table.cursor_row + 1, animate=False)

    # ---- Subscription toggle ----

    def toggleSubscribed(self):
        """Toggle subscription for selected/marked repository rows."""
        rows = self._get_selected_rows(ROW_TYPE_REPO)
        if not rows:
            return
        repo_keys = [meta["db_key"] for _, meta in rows]
        subscribed_keys = []
        with self.app.db.getSession() as session:
            for key in repo_keys:
                repository = session.getRepository(key)
                repository.subscribed = not repository.subscribed
                if repository.subscribed:
                    subscribed_keys.append(key)
        # Clear marks
        for _, meta in rows:
            meta["mark"] = False
        # Submit sync tasks for newly subscribed repos
        for key in subscribed_keys:
            self.app.sync.submitTask(sync.SyncRepositoryTask(key))
        self.refresh_data()

    # ---- Topic CRUD operations ----

    def createTopic(self):
        """Show a dialog to create a new topic."""
        dialog = TextInputDialog("Create a new topic", "Topic name")
        self.app.push_screen(dialog, self._on_create_topic)

    def _on_create_topic(self, result):
        """Callback when the create topic dialog is dismissed."""
        if result is None or not result.strip():
            return
        name = result.strip()
        with self.app.db.getSession() as session:
            topics = session.getTopics()
            if topics:
                seq = max(t.sequence for t in topics) + 1
            else:
                seq = 0
            session.createTopic(name, seq)
        self.refresh_data()

    def deleteTopic(self):
        """Delete selected/marked topic rows."""
        rows = self._get_selected_rows(ROW_TYPE_TOPIC)
        if not rows:
            return
        with self.app.db.getSession() as session:
            for _, meta in rows:
                topic = session.getTopic(meta["db_key"])
                if topic:
                    session.delete(topic)
        self.refresh_data()

    def renameTopic(self):
        """Show a dialog to rename the focused topic."""
        meta = self._get_focused_meta()
        if not meta or meta["type"] != ROW_TYPE_TOPIC:
            return
        topic_key = meta["db_key"]
        current_name = meta["name"]
        dialog = TextInputDialog("Rename topic", "Topic name", initial=current_name)
        self.app.push_screen(
            dialog, lambda result: self._on_rename_topic(result, topic_key)
        )

    def _on_rename_topic(self, result, topic_key):
        """Callback when the rename topic dialog is dismissed."""
        if result is None or not result.strip():
            return
        name = result.strip()
        with self.app.db.getSession() as session:
            topic = session.getTopic(topic_key)
            if topic:
                topic.name = name
        self.refresh_data()

    def copyMoveToTopic(self, move):
        """Show a dialog to copy or move repositories to a topic."""
        rows = self._get_selected_rows(ROW_TYPE_REPO)
        if not rows:
            return
        with self.app.db.getSession() as session:
            topics = [(t.key, t.name) for t in session.getTopics()]
        if not topics:
            self.app.error("No topics exist. Create a topic first.")
            return
        verb = "Move" if move else "Copy"
        dialog = TopicSelectDialog("%s to Topic" % verb, topics)
        self.app.push_screen(
            dialog, lambda result: self._on_copy_move_to_topic(result, rows, move)
        )

    def _on_copy_move_to_topic(self, selected_key, rows, move):
        """Callback when the topic selection dialog is dismissed."""
        if selected_key is None:
            return
        with self.app.db.getSession() as session:
            new_topic = session.getTopic(selected_key)
            if not new_topic:
                self.app.error("Unable to find topic %s" % selected_key)
                return
            for _, meta in rows:
                repository = session.getRepository(meta["db_key"])
                if move and meta["topic_key"]:
                    old_topic = session.getTopic(meta["topic_key"])
                    if old_topic:
                        self.logger.debug("Remove %s from %s", repository, old_topic)
                        old_topic.removeRepository(repository)
                self.logger.debug("Add %s to %s", repository, new_topic)
                new_topic.addRepository(repository)
        self.refresh_data()

    def moveToTopic(self):
        """Move selected repositories to a topic."""
        self.copyMoveToTopic(True)

    def copyToTopic(self):
        """Copy selected repositories to a topic."""
        self.copyMoveToTopic(False)

    def removeFromTopic(self):
        """Remove selected repositories from their topics."""
        rows = self._get_selected_rows(ROW_TYPE_REPO)
        rows = [(k, m) for k, m in rows if m["topic_key"]]
        if not rows:
            return
        with self.app.db.getSession() as session:
            for _, meta in rows:
                repository = session.getRepository(meta["db_key"])
                topic = session.getTopic(meta["topic_key"])
                if repository and topic:
                    self.logger.debug("Remove %s from %s", repository, topic)
                    topic.removeRepository(repository)
        self.refresh_data()

    # ---- Interactive search ----

    def searchStart(self):
        """Activate interactive search mode."""
        if self._search_active:
            # Already searching; cycle to next result
            self._nextSearchResult()
            return
        self._search_active = True
        self._search_results = []
        self._search_result_index = 0
        search_bar = self.query_one("#search-bar", Input)
        search_bar.value = ""
        search_bar.add_class("visible")
        search_bar.focus()
        # Update header to show search mode
        if hasattr(self.app, "hubtty_header"):
            self.app.hubtty_header.set_message("Search: ")

    def _searchStop(self):
        """Deactivate interactive search mode."""
        self._search_active = False
        self._search_results = []
        self._search_result_index = 0
        search_bar = self.query_one("#search-bar", Input)
        search_bar.remove_class("visible")
        # Restore focus to the data table
        table = self.query_one("#repo-list", DataTable)
        table.focus()
        # Restore header title
        if hasattr(self.app, "hubtty_header"):
            self.app.hubtty_header.set_message(None)

    def on_input_changed(self, event):
        """Handle search text changes."""
        if not self._search_active:
            return
        if event.input.id != "search-bar":
            return
        search = event.value
        if hasattr(self.app, "hubtty_header"):
            self.app.hubtty_header.set_message("Search: %s" % search)
        self._performSearch(search)

    def on_input_submitted(self, event):
        """Handle Enter in the search bar."""
        if event.input.id != "search-bar":
            return
        self._searchStop()

    def on_key(self, event):
        """Handle special keys during search mode."""
        if not self._search_active:
            return
        if event.key == "escape":
            self._searchStop()
            event.prevent_default()
            event.stop()
            return
        # Check if this key triggers INTERACTIVE_SEARCH to cycle results
        from hubtty.textual_app import textual_key_to_urwid

        urwid_key = textual_key_to_urwid(event)
        if urwid_key:
            commands = self.app.config.keymap.getCommands([urwid_key])
            if keymap.INTERACTIVE_SEARCH in commands:
                self._nextSearchResult()
                event.prevent_default()
                event.stop()
        elif event.key in ("ctrl+s", "slash"):
            # Cycle to next search result
            self._nextSearchResult()
            event.prevent_default()
            event.stop()

    def _performSearch(self, search):
        """Search repository names and highlight/navigate to matches."""
        self._search_results = []
        self._search_result_index = 0
        if not search:
            return
        search_lower = search.lower()
        table = self.query_one("#repo-list", DataTable)
        for i, (row_key_str, meta) in enumerate(self._ordered_row_meta(table)):
            if meta["type"] == ROW_TYPE_REPO:
                if search_lower in meta["name"].lower():
                    self._search_results.append(i)
        # Move cursor to first result
        if self._search_results:
            table.move_cursor(row=self._search_results[0], animate=False)

    def _nextSearchResult(self):
        """Cycle to the next search result."""
        if not self._search_results:
            return
        self._search_result_index += 1
        if self._search_result_index >= len(self._search_results):
            self._search_result_index = 0
        table = self.query_one("#repo-list", DataTable)
        table.move_cursor(
            row=self._search_results[self._search_result_index], animate=False
        )

    def _ordered_row_meta(self, table):
        """Yield (row_key_str, meta) in display order."""
        for row in table.ordered_rows:
            key_str = str(row.key)
            meta = self._row_meta.get(key_str)
            if meta:
                yield (key_str, meta)

    # ---- Command dispatch ----

    def handleCommand(self, command):
        """Handle a command dispatched from the app's keymap.

        Returns True if the command was handled, False otherwise.
        """
        if command == keymap.INTERACTIVE_SEARCH:
            self.searchStart()
            return True
        if command == keymap.TOGGLE_LIST_REVIEWED:
            self.unreviewed = not self.unreviewed
            self.refresh_data()
            return True
        if command == keymap.TOGGLE_LIST_SUBSCRIBED:
            self.subscribed = not self.subscribed
            self.refresh_data()
            return True
        if command == keymap.TOGGLE_SUBSCRIBED:
            self.toggleSubscribed()
            return True
        if command == keymap.TOGGLE_MARK:
            self.toggleMark()
            return True
        if command == keymap.REFRESH:
            self.app.sync.submitTask(
                sync.SyncSubscribedRepositoriesTask(sync.HIGH_PRIORITY)
            )
            self.refresh_data()
            return True
        if command == keymap.NEW_REPOSITORY_TOPIC:
            self.createTopic()
            return True
        if command == keymap.DELETE_REPOSITORY_TOPIC:
            self.deleteTopic()
            return True
        if command == keymap.RENAME_REPOSITORY_TOPIC:
            self.renameTopic()
            return True
        if command == keymap.MOVE_REPOSITORY_TOPIC:
            self.moveToTopic()
            return True
        if command == keymap.COPY_REPOSITORY_TOPIC:
            self.copyToTopic()
            return True
        if command == keymap.REMOVE_REPOSITORY_TOPIC:
            self.removeFromTopic()
            return True
        return False
