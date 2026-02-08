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

from textual.screen import Screen
from textual.widgets import DataTable

from hubtty import sync


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


class RepositoryListScreen(Screen):
    """Screen showing the list of repositories."""

    title = "Repository list"

    BINDINGS = []

    DEFAULT_CSS = """
    RepositoryListScreen {
        layout: vertical;
    }
    RepositoryListScreen DataTable {
        height: 1fr;
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

    def compose(self):
        table = DataTable(id="repo-list")
        table.cursor_type = "row"
        table.zebra_stripes = False
        table.show_row_labels = False
        yield table

    def on_mount(self):
        table = self.query_one("#repo-list", DataTable)
        table.add_column(" Repository", key="name")
        table.add_column("Unreviewed", key="unreviewed")
        table.add_column("Open", key="open")
        self.refresh_data()

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

    def handleCommand(self, command):
        """Handle a command dispatched from the app's keymap.

        Returns True if the command was handled, False otherwise."""
        return False
