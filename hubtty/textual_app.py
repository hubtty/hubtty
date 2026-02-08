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

import os
import threading
import warnings
import webbrowser

from textual.app import App, ComposeResult
from textual.widgets import Footer, Static
from textual.binding import Binding

from hubtty.base_app import BaseApp
import hubtty.version


class HubttyHeader(Static):
    """Status header showing title, sync status, and indicators."""

    def __init__(self):
        super().__init__("")
        self._title = "Hubtty"
        self._offline = False
        self._error = False
        self._sync = 0
        self._held = 0
        self._update_display()

    def _update_display(self):
        parts = [self._title]
        if self._held:
            parts.append(f"  Held: {self._held}")
        if self._error:
            parts.append("  Error")
        if self._offline:
            parts.append("  Offline")
        parts.append(f"  Sync: {self._sync}")
        self.update(" | ".join(parts))

    def set_title(self, title):
        self._title = title
        self._update_display()

    def set_error(self, error):
        self._error = error
        self._update_display()

    def set_offline(self, offline):
        self._offline = offline
        self._update_display()

    def set_held(self, held):
        self._held = held
        self._update_display()

    def set_sync(self, sync_count):
        self._sync = sync_count
        self._update_display()


class TextualApp(App, BaseApp):
    """Hubtty Textual UI application."""

    CSS = """
    HubttyHeader {
        dock: top;
        height: 1;
        background: $accent;
        color: $text;
        text-style: bold;
    }
    #main-content {
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        server=None,
        palette="default",
        keymap="default",
        debug=False,
        verbose=False,
        disable_sync=False,
        disable_background_sync=False,
        fetch_missing_refs=False,
        path=None,
    ):
        # Initialize Textual App first
        App.__init__(self)
        # Initialize BaseApp (config, db, sync, etc.)
        BaseApp.__init__(
            self,
            server=server,
            palette=palette,
            keymap=keymap,
            debug=debug,
            verbose=verbose,
            disable_sync=disable_sync,
            disable_background_sync=disable_background_sync,
            fetch_missing_refs=fetch_missing_refs,
            path=path,
        )

        self._disable_sync = disable_sync

    @property
    def title(self):
        return "Hubtty %s" % hubtty.version.version_info.release_string()

    @title.setter
    def title(self, value):
        # Textual App has a title property; we override it
        pass

    def compose(self) -> ComposeResult:
        yield HubttyHeader()
        yield Static("Hubtty - Textual UI (under construction)", id="main-content")
        yield Footer()

    def on_mount(self) -> None:
        """Called when the app is mounted and ready."""
        self.hubtty_header = self.query_one(HubttyHeader)

        warnings.showwarning = self._showWarning

        # Register label palette entries
        with self.db.getSession() as session:
            for label in session.getLabels():
                self.registerPaletteEntry(label.id, label.color)

        self.startSocketListener()

        # Start sync thread
        if not self._disable_sync:
            self.sync_pipe_r, self.sync_pipe_w = os.pipe()
            self.sync_thread = threading.Thread(
                target=self.sync.run, args=(self.sync_pipe_w,)
            )
            self.sync_thread.daemon = True
            self.sync_thread.start()
            # Poll for sync results periodically
            self.set_interval(1.0, self._poll_sync_results)
        else:
            self.sync_thread = None
            self.sync.offline = True
            self.hubtty_header.set_offline(True)

    def _poll_sync_results(self) -> None:
        """Periodically check for sync results and update UI."""
        import queue

        try:
            while True:
                self.sync.result_queue.get(0)
                # TODO: dispatch events to screens
        except queue.Empty:
            pass
        # Update sync queue count
        self.hubtty_header.set_sync(self.sync.queue.qsize())

    # ---- BaseApp abstract method implementations ----

    def run(self):
        """Start the Textual event loop."""
        App.run(self)

    def error(self, message, title="Error"):
        """Display an error notification."""
        self.notify(message, title=title, severity="error", timeout=10)
        return None

    def doSearch(self, query):
        """Execute a search query."""
        # TODO: implement when PR list screen is ready
        self.notify(f"Search: {query}", title="Search")

    def changeScreen(self, widget, push=True):
        """Navigate to a new screen."""
        # TODO: implement with push_screen when screens are ready
        pass

    def backScreen(self, target_widget=None):
        """Navigate back."""
        # TODO: implement with pop_screen when screens are ready
        pass

    def registerPaletteEntry(self, label_id, label_color):
        """Register a label color. In Textual, handled via CSS."""
        # Label colors will be handled via inline styles when needed
        pass

    def openURL(self, url):
        """Open a URL in the browser."""
        self.log.debug("Open URL %s", url)
        webbrowser.open_new_tab(url)

    def updateStatusQueries(self):
        """Update held PR count in header."""
        with self.db.getSession() as session:
            held = len(session.getHeld())
            if hasattr(self, "hubtty_header"):
                self.call_from_thread(self.hubtty_header.set_held, held)

    def handleSocketCommand(self, command, data):
        """Handle a command from the Unix socket."""
        if command == "open":
            url = data[0]
            self.log.debug("Opening URL %s", url)
            result = self.parseInternalURL(url)
            if result is not None:
                self.call_from_thread(self.openInternalURL, result)
        else:
            self.log.error("Unable to parse command %s with data %s", command, data)

    def showWarning(self, message):
        """Show a warning notification."""
        if hasattr(self, "_app_ready"):
            self.call_from_thread(
                self.notify, message, title="Warning", severity="warning"
            )

    def set_status(self, **kwargs):
        """Update status display from sync thread."""
        if not hasattr(self, "hubtty_header"):
            return
        if "offline" in kwargs:
            self.call_from_thread(self.hubtty_header.set_offline, kwargs["offline"])
        if "error" in kwargs:
            self.call_from_thread(self.hubtty_header.set_error, kwargs["error"])
