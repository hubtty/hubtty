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

from textual.screen import Screen
from textual.widgets import DataTable


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

    def compose(self):
        table = DataTable(id="repo-list")
        table.cursor_type = "row"
        table.zebra_stripes = False
        table.show_row_labels = False
        yield table

    def on_mount(self):
        table = self.query_one("#repo-list", DataTable)
        table.add_columns("Repository", "Unreviewed", "Open")

    def handleCommand(self, command):
        """Handle a command dispatched from the app's keymap.

        Returns True if the command was handled, False otherwise."""
        return False
