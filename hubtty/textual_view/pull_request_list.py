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

import datetime
import logging

from rich.text import Text

from textual.widget import Widget
from textual.widgets import DataTable, Input

from hubtty import keymap
from hubtty import sync


# Style names matching the urwid palette entries
STYLE_UNREVIEWED = "unreviewed-pr"
STYLE_REVIEWED = "reviewed-pr"
STYLE_STARRED = "starred-pr"
STYLE_HELD = "held-pr"
STYLE_MARKED = "marked-pr"

# Map column keys to db sort-by values (only sortable columns)
_COLUMN_SORT_MAP = {
    "number": "number",
    "repository": "repository",
    "updated": "updated",
}

# Base column labels (without sort indicators)
_COLUMN_LABELS = {
    "number": " #",
    "title": " Title",
    "repository": "Repository",
    "branch": "Branch",
    "author": "Author",
    "updated": "Updated",
    "review": "CR",
}


def _pr_style(pr, mark=False):
    """Determine the display style for a PR based on state."""
    if pr.reviewed or pr.hidden:
        style = STYLE_REVIEWED
    else:
        style = STYLE_UNREVIEWED
    if pr.starred:
        style = STYLE_STARRED
    if pr.held:
        style = STYLE_HELD
    if mark:
        style = STYLE_MARKED
    return style


def _pr_flag(pr, mark=False):
    """Return the flag character for a PR."""
    flag = " "
    if pr.starred:
        flag = "*"
    if pr.held:
        flag = "!"
    if mark:
        flag = "%"
    return flag


def _format_updated(app, updated):
    """Format an updated timestamp for display."""
    today = app.time(datetime.datetime.utcnow()).date()
    updated_time = app.time(updated)
    if today == updated_time.date():
        return updated_time.strftime("%I:%M %p").upper()
    return updated_time.strftime("%Y-%m-%d")


def _review_state_cell(pr):
    """Return a Rich Text object for the Code-Review column."""
    state = pr.getReviewState()
    if state == "APPROVED":
        t = Text(" ✓")
        t.stylize("positive-label")
        return t
    elif state == "CHANGES_REQUESTED":
        t = Text(" ✗")
        t.stylize("negative-label")
        return t
    elif state == "COMMENTED":
        return Text(" •")
    return Text("")


class PullRequestListView(Widget):
    """Widget showing the list of pull requests for a repository or query."""

    DEFAULT_CSS = """
    PullRequestListView {
        layout: vertical;
        height: 1fr;
    }
    PullRequestListView DataTable {
        height: 1fr;
    }
    #pr-search-bar {
        dock: bottom;
        height: 1;
        border: none;
        padding: 0;
        display: none;
    }
    #pr-search-bar.visible {
        display: block;
    }
    """

    def __init__(
        self,
        query,
        title=None,
        query_desc=None,
        repository_key=None,
        unreviewed=False,
        sort_by=None,
        reverse=None,
    ):
        super().__init__()
        self.logger = logging.getLogger("hubtty.textual_view.pull_request_list")
        self.query_string = query
        self.query_desc = query_desc or title or query
        self.title = title or "Pull requests"
        self.repository_key = repository_key
        self.unreviewed = unreviewed
        # Maps row_key_str -> {pr_key, style, mark, title, number, ...}
        self._row_meta = {}
        # Sort settings (initialized from config in on_mount)
        self._sort_by = sort_by
        self._reverse = reverse
        # Search state
        self._search_active = False
        self._search_results = []
        self._search_result_index = 0
        # Columns to hide
        self._hide_repository = repository_key is not None
        self._hide_author = "author:" in query

    def compose(self):
        table = DataTable(id="pr-list")
        table.cursor_type = "row"
        table.zebra_stripes = False
        table.show_row_labels = False
        yield table
        yield Input(placeholder="Search...", id="pr-search-bar")

    def on_mount(self):
        # Resolve config defaults now that self.app is available
        if self._sort_by is None:
            self._sort_by = self.app.config.pr_list_options["sort-by"]
        if self._reverse is None:
            self._reverse = self.app.config.pr_list_options["reverse"]

        table = self.query_one("#pr-list", DataTable)
        table.add_column(" #", key="number", width=6)
        table.add_column(" Title", key="title")
        if not self._hide_repository:
            table.add_column("Repository", key="repository")
        table.add_column("Branch", key="branch")
        if not self._hide_author:
            table.add_column("Author", key="author")
        table.add_column("Updated", key="updated", width=10)
        table.add_column("CR", key="review", width=2)
        self._update_column_labels()
        self.refresh_data()

    # ---- Column sorting via header click ----

    def _update_column_labels(self):
        """Update column header labels with sort indicators."""
        table = self.query_one("#pr-list", DataTable)
        for col_key, column in table.columns.items():
            key_str = col_key.value
            base_label = _COLUMN_LABELS.get(key_str, key_str)
            sort_field = _COLUMN_SORT_MAP.get(key_str)
            if sort_field and sort_field == self._sort_by:
                indicator = " ▼" if self._reverse else " ▲"
                column.label = Text(base_label + indicator)
            else:
                column.label = Text(base_label)

    def on_data_table_header_selected(self, event):
        """Sort by the clicked column, or reverse if already sorted."""
        col_key = event.column_key.value
        sort_field = _COLUMN_SORT_MAP.get(col_key)
        if sort_field is None:
            return
        if self._sort_by == sort_field:
            self._reverse = not self._reverse
        else:
            self._sort_by = sort_field
            self._reverse = False
        self._update_column_labels()
        self.refresh_data()

    # ---- Event interest and data refresh ----

    def interested(self, event):
        """Check if a sync event should trigger a refresh."""
        if isinstance(event, sync.PullRequestAddedEvent):
            if self.repository_key is not None:
                return event.repository_key == self.repository_key
            return True
        if isinstance(event, sync.PullRequestUpdatedEvent):
            row_key = "pr:%s" % event.pr_key
            return row_key in self._row_meta
        return False

    def refresh_data(self):
        """Rebuild the pull request list from the database."""
        table = self.query_one("#pr-list", DataTable)

        # Guard: columns not yet configured
        if not table.columns:
            return

        # Remember cursor position for restoration
        old_cursor_row = table.cursor_row

        table.clear()
        self._row_meta = {}

        with self.app.db.getSession() as session:
            pr_list = session.getPullRequests(
                self.query_string, self.unreviewed, sort_by=self._sort_by
            )

            if self.unreviewed:
                self.title = "Unreviewed %d pull requests in %s" % (
                    len(pr_list),
                    self.query_desc,
                )
            else:
                self.title = "All %d pull requests in %s" % (
                    len(pr_list),
                    self.query_desc,
                )

            # Update header title
            if hasattr(self.app, "hubtty_header"):
                self.app.hubtty_header.set_title(self.title)

            if self._reverse:
                pr_list.reverse()

            for pr in pr_list:
                self._add_pr_row(table, pr)

        # Restore cursor position
        if table.row_count > 0:
            if old_cursor_row < table.row_count:
                table.move_cursor(row=old_cursor_row, animate=False)
            else:
                table.move_cursor(row=table.row_count - 1, animate=False)

    def _add_pr_row(self, table, pr):
        """Add a pull request row to the DataTable."""
        row_key_str = "pr:%s" % pr.key
        style = _pr_style(pr)
        flag = _pr_flag(pr)

        number_text = Text("%s " % pr.number, justify="right")
        number_text.stylize(style)

        title_text = Text("%s%s" % (flag, pr.title))
        title_text.stylize(style)

        updated_text = Text(_format_updated(self.app, pr.updated))
        updated_text.stylize(style)

        review_cell = _review_state_cell(pr)

        cells = [number_text, title_text]
        if not self._hide_repository:
            repo_text = Text(pr.repository.name.split("/")[-1])
            repo_text.stylize(style)
            cells.append(repo_text)
        cells.append(Text(pr.branch or ""))
        if not self._hide_author:
            author_text = Text(pr.author_name)
            author_text.stylize(style)
            cells.append(author_text)
        cells.append(updated_text)
        cells.append(review_cell)

        table.add_row(*cells, key=row_key_str)

        self._row_meta[row_key_str] = {
            "pr_key": pr.key,
            "style": style,
            "mark": False,
            "title": pr.title,
            "number": pr.number,
            "repository": pr.repository.name,
            "author": pr.author_name,
            "branch": pr.branch or "",
        }

    # ---- Row selection / activation ----

    def _get_focused_row_key(self):
        """Get the row key string of the currently focused row."""
        table = self.query_one("#pr-list", DataTable)
        if table.row_count == 0:
            return None
        try:
            row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
            return row_key.value
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
        row_key_str = event.row_key.value
        meta = self._row_meta.get(row_key_str)
        if meta is None:
            return
        # TODO: navigate to PR detail view (Phase 3)
        self.app.notify(
            "PR #%s detail view not yet implemented" % meta["number"],
            title=meta["title"],
        )

    def _advance_cursor(self):
        """Move cursor down one row."""
        table = self.query_one("#pr-list", DataTable)
        if table.cursor_row < table.row_count - 1:
            table.move_cursor(row=table.cursor_row + 1, animate=False)

    # ---- Mark operations ----

    def _get_marked_or_focused(self):
        """Get marked rows, or the focused row if none are marked.

        Returns a list of (row_key_str, meta) tuples.
        """
        marked = [(k, m) for k, m in self._row_meta.items() if m["mark"]]
        if marked:
            return marked
        meta = self._get_focused_meta()
        if meta:
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
        self._update_row_display(row_key, meta)
        self._advance_cursor()

    def _update_row_display(self, row_key_str, meta):
        """Update the visual display of a single row."""
        table = self.query_one("#pr-list", DataTable)
        pr_key = meta["pr_key"]
        with self.app.db.getSession() as session:
            pr = session.getPullRequest(pr_key)
            if pr is None:
                return
            style = _pr_style(pr, meta["mark"])
            flag = _pr_flag(pr, meta["mark"])
            meta["style"] = style

            number_text = Text("%s " % pr.number, justify="right")
            number_text.stylize(style)

            title_text = Text("%s%s" % (flag, pr.title))
            title_text.stylize(style)

            updated_text = Text(_format_updated(self.app, pr.updated))
            updated_text.stylize(style)

            review_cell = _review_state_cell(pr)

            try:
                table.update_cell(row_key_str, "number", number_text)
                table.update_cell(row_key_str, "title", title_text)
                if not self._hide_repository:
                    repo_text = Text(pr.repository.name.split("/")[-1])
                    repo_text.stylize(style)
                    table.update_cell(row_key_str, "repository", repo_text)
                branch_text = Text(pr.branch or "")
                branch_text.stylize(style)
                table.update_cell(row_key_str, "branch", branch_text)
                if not self._hide_author:
                    author_text = Text(pr.author_name)
                    author_text.stylize(style)
                    table.update_cell(row_key_str, "author", author_text)
                table.update_cell(row_key_str, "updated", updated_text)
                table.update_cell(row_key_str, "review", review_cell)
            except Exception:
                pass

    # ---- Toggle operations ----

    def toggleReviewed(self):
        """Toggle the reviewed flag on the focused PR."""
        meta = self._get_focused_meta()
        if meta is None:
            return
        pr_key = meta["pr_key"]
        with self.app.db.getSession() as session:
            pr = session.getPullRequest(pr_key)
            pr.reviewed = not pr.reviewed
            self.app.repository_cache.clear(pr.repository)
            reviewed = pr.reviewed
        if self.unreviewed and reviewed:
            # Remove the row directly instead of full refresh
            row_key = self._get_focused_row_key()
            table = self.query_one("#pr-list", DataTable)
            table.remove_row(row_key)
            del self._row_meta[row_key]
        else:
            self.refresh_data()

    def toggleHidden(self):
        """Toggle the hidden flag on the focused PR."""
        meta = self._get_focused_meta()
        if meta is None:
            return
        pr_key = meta["pr_key"]
        with self.app.db.getSession() as session:
            pr = session.getPullRequest(pr_key)
            pr.hidden = not pr.hidden
            hidden = pr.hidden
        if hidden:
            row_key = self._get_focused_row_key()
            table = self.query_one("#pr-list", DataTable)
            table.remove_row(row_key)
            del self._row_meta[row_key]
        else:
            self.refresh_data()

    def toggleStarred(self):
        """Toggle the starred flag on the focused PR."""
        meta = self._get_focused_meta()
        if meta is None:
            return
        pr_key = meta["pr_key"]
        with self.app.db.getSession() as session:
            pr = session.getPullRequest(pr_key)
            pr.starred = not pr.starred
        row_key = self._get_focused_row_key()
        self._update_row_display(row_key, meta)
        self._advance_cursor()

    def toggleHeld(self):
        """Toggle the held flag on the focused PR."""
        meta = self._get_focused_meta()
        if meta is None:
            return
        self.app.toggleHeldPullRequest(meta["pr_key"])
        row_key = self._get_focused_row_key()
        self._update_row_display(row_key, meta)
        self._advance_cursor()

    # ---- Interactive search ----

    def searchStart(self):
        """Activate interactive search mode."""
        if self._search_active:
            self._nextSearchResult()
            return
        self._search_active = True
        self._search_results = []
        self._search_result_index = 0
        search_bar = self.query_one("#pr-search-bar", Input)
        search_bar.value = ""
        search_bar.add_class("visible")
        self.screen.set_focus(search_bar)
        if hasattr(self.app, "hubtty_header"):
            self.app.hubtty_header.set_message("Search: ")

    def _searchStop(self):
        """Deactivate interactive search mode."""
        self._search_active = False
        self._search_results = []
        self._search_result_index = 0
        search_bar = self.query_one("#pr-search-bar", Input)
        search_bar.remove_class("visible")
        table = self.query_one("#pr-list", DataTable)
        self.screen.set_focus(table)
        if hasattr(self.app, "hubtty_header"):
            self.app.hubtty_header.set_message(None)

    def on_input_changed(self, event):
        """Handle search text changes."""
        if not self._search_active:
            return
        if event.input.id != "pr-search-bar":
            return
        search = event.value
        if hasattr(self.app, "hubtty_header"):
            self.app.hubtty_header.set_message("Search: %s" % search)
        self._performSearch(search)

    def on_input_submitted(self, event):
        """Handle Enter in the search bar."""
        if event.input.id != "pr-search-bar":
            return
        self._searchStop()

    def _performSearch(self, search):
        """Search PR titles, numbers, repos, authors and navigate."""
        self._search_results = []
        self._search_result_index = 0
        if not search:
            return
        search_lower = search.lower()
        table = self.query_one("#pr-list", DataTable)
        for i, (row_key_str, meta) in enumerate(self._ordered_row_meta(table)):
            searchable = "%s %s %s %s %s" % (
                meta["number"],
                meta["title"],
                meta["repository"],
                meta["author"],
                meta["branch"],
            )
            if search_lower in searchable.lower():
                self._search_results.append(i)
        if self._search_results:
            table.move_cursor(row=self._search_results[0], animate=False)

    def _nextSearchResult(self):
        """Cycle to the next search result."""
        if not self._search_results:
            return
        self._search_result_index += 1
        if self._search_result_index >= len(self._search_results):
            self._search_result_index = 0
        table = self.query_one("#pr-list", DataTable)
        table.move_cursor(
            row=self._search_results[self._search_result_index], animate=False
        )

    def _ordered_row_meta(self, table):
        """Yield (row_key_str, meta) in display order."""
        for row in table.ordered_rows:
            key_str = row.key.value
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
        if command == keymap.TOGGLE_REVIEWED:
            self.toggleReviewed()
            return True
        if command == keymap.TOGGLE_HIDDEN:
            self.toggleHidden()
            return True
        if command == keymap.TOGGLE_STARRED:
            self.toggleStarred()
            return True
        if command == keymap.TOGGLE_HELD:
            self.toggleHeld()
            return True
        if command == keymap.TOGGLE_MARK:
            self.toggleMark()
            return True
        if command == keymap.SORT_BY_NUMBER:
            self._sort_by = "number"
            self._update_column_labels()
            self.refresh_data()
            return True
        if command == keymap.SORT_BY_UPDATED:
            self._sort_by = "updated"
            self._update_column_labels()
            self.refresh_data()
            return True
        if command == keymap.SORT_BY_LAST_SEEN:
            self._sort_by = "last-seen"
            self._update_column_labels()
            self.refresh_data()
            return True
        if command == keymap.SORT_BY_REVERSE:
            self._reverse = not self._reverse
            self._update_column_labels()
            self.refresh_data()
            return True
        if command == keymap.REFRESH:
            if self.repository_key:
                self.app.sync.submitTask(
                    sync.SyncRepositoryTask(self.repository_key, sync.HIGH_PRIORITY)
                )
            else:
                self.app.sync.submitTask(
                    sync.SyncSubscribedRepositoriesTask(sync.HIGH_PRIORITY)
                )
            self.refresh_data()
            return True
        if command == keymap.LOCAL_CHECKOUT:
            self._localCheckout()
            return True
        return False

    def _localCheckout(self):
        """Checkout the focused PR's latest commit locally."""
        meta = self._get_focused_meta()
        if meta is None:
            return
        pr_key = meta["pr_key"]
        with self.app.db.getSession() as session:
            pr = session.getPullRequest(pr_key)
            if pr and pr.commits:
                self.app.localCheckoutCommit(pr.repository.name, pr.commits[-1].sha)
