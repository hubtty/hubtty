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

from textual.widget import Widget
from textual.widgets import Static


class PullRequestListView(Widget):
    """Widget showing the list of pull requests for a repository.

    This is a stub placeholder that will be fully implemented later.
    """

    DEFAULT_CSS = """
    PullRequestListView {
        layout: vertical;
        height: 1fr;
    }
    #pr-list-placeholder {
        height: 1fr;
        content-align: center middle;
    }
    """

    def __init__(self, query, title=None):
        super().__init__()
        self.query_string = query
        self.title = title or "Pull requests"

    def compose(self):
        yield Static(
            "Pull request list (not yet implemented)\n\nQuery: %s" % self.query_string,
            id="pr-list-placeholder",
        )

    def handleCommand(self, command):
        """Handle a command dispatched from the app's keymap.

        Returns True if the command was handled, False otherwise."""
        return False
