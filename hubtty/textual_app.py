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
from textual.containers import Vertical
from textual.widgets import Footer, Static

from hubtty.base_app import BaseApp
from hubtty import keymap
import hubtty.version


# ---- urwid color name mappings ----

# Mapping from urwid 16-color names to Rich style color names.
# Rich uses 'red', 'bright_red', etc. for standard terminal colors.
_URWID_TO_RICH_COLOR = {
    "default": "",
    "black": "black",
    "dark red": "red",
    "dark green": "green",
    "brown": "yellow",  # ANSI color 3
    "dark blue": "blue",
    "dark magenta": "magenta",
    "dark cyan": "cyan",
    "light gray": "white",  # ANSI color 7
    "dark gray": "bright_black",
    "light red": "bright_red",
    "light green": "bright_green",
    "yellow": "bright_yellow",
    "light blue": "bright_blue",
    "light magenta": "bright_magenta",
    "light cyan": "bright_cyan",
    "white": "bright_white",  # ANSI color 15
}

# urwid text attributes to Rich style keywords
_URWID_TO_RICH_STYLE = {
    "bold": "bold",
    "standout": "reverse",
    "underline": "underline",
    "italics": "italic",
    "italic": "italic",
    "strikethrough": "strike",
}


def _urwid_spec_to_rich_style(spec):
    """Convert an urwid foreground spec like 'light blue' or 'white,bold'
    to a Rich style string like 'bright_blue' or 'bright_white bold'."""
    if not spec:
        return ""
    parts = [p.strip() for p in spec.split(",")]
    color = ""
    styles = []
    for part in parts:
        if part in _URWID_TO_RICH_STYLE:
            styles.append(_URWID_TO_RICH_STYLE[part])
        elif part in _URWID_TO_RICH_COLOR:
            color = _URWID_TO_RICH_COLOR[part]
    tokens = []
    if color:
        tokens.append(color)
    tokens.extend(styles)
    return " ".join(tokens)


def palette_to_rich_styles(palette_dict):
    """Convert an urwid palette dict to a dict of {name: rich_style_string}.

    Only includes the foreground spec; background is ignored for Rich Text
    spans (use CSS classes for background colors).
    """
    result = {}
    for name, (fg_spec, bg_spec) in palette_dict.items():
        rich_style = _urwid_spec_to_rich_style(fg_spec)
        if rich_style:
            result[name] = rich_style
    return result


# ---- Palette to CSS conversion ----

# Mapping from urwid 16-color names to Textual CSS color names.
# Textual CSS uses 'ansi_X' for standard colors and 'ansi_bright_X'
# for bright colors, matching ANSI terminal color indices 0-15.
_URWID_COLOR_MAP = {
    "default": "",
    "black": "ansi_black",
    "dark red": "ansi_red",
    "dark green": "ansi_green",
    "brown": "ansi_yellow",  # ANSI color 3 = dark yellow / brown
    "dark blue": "ansi_blue",
    "dark magenta": "ansi_magenta",
    "dark cyan": "ansi_cyan",
    "light gray": "ansi_white",  # ANSI color 7
    "dark gray": "ansi_bright_black",  # ANSI color 8
    "light red": "ansi_bright_red",
    "light green": "ansi_bright_green",
    "yellow": "ansi_bright_yellow",
    "light blue": "ansi_bright_blue",
    "light magenta": "ansi_bright_magenta",
    "light cyan": "ansi_bright_cyan",
    "white": "ansi_bright_white",  # ANSI color 15
}

# urwid text attributes to Textual text-style values
_URWID_STYLE_MAP = {
    "bold": "bold",
    "standout": "reverse",
    "underline": "underline",
    "italics": "italic",
    "italic": "italic",
    "strikethrough": "strike",
}


def _parse_urwid_color_spec(spec):
    """Parse an urwid foreground/background spec into (color, [styles]).

    An urwid spec looks like 'dark cyan' or 'white,bold' or
    'default,standout' or 'underline,bold' or just ''.

    Returns (css_color_or_empty, list_of_css_styles).
    """
    if not spec:
        return "", []

    parts = [p.strip() for p in spec.split(",")]
    color = ""
    styles = []

    for part in parts:
        if part in _URWID_STYLE_MAP:
            styles.append(_URWID_STYLE_MAP[part])
        elif part in _URWID_COLOR_MAP:
            color = _URWID_COLOR_MAP[part]
        else:
            # Try two-word color: check if this plus next makes a known color
            # urwid colors like 'dark red' are already single entries in parts
            # since comma splits on commas, not spaces.
            color = _URWID_COLOR_MAP.get(part, "")

    return color, styles


def _palette_name_to_css_class(name):
    """Convert a palette entry name to a valid CSS class name."""
    return name  # Textual allows hyphens in class names


def palette_to_css(palette_dict):
    """Convert an urwid palette dict to a Textual CSS string.

    Each palette entry becomes a CSS class rule using the '.' prefix.
    """
    rules = []
    for name, (fg_spec, bg_spec) in palette_dict.items():
        css_class = _palette_name_to_css_class(name)
        fg_color, fg_styles = _parse_urwid_color_spec(fg_spec)
        bg_color, bg_styles = _parse_urwid_color_spec(bg_spec)

        props = []
        if fg_color:
            props.append(f"    color: {fg_color};")
        if bg_color:
            props.append(f"    background: {bg_color};")

        all_styles = fg_styles + bg_styles
        if all_styles:
            props.append(f"    text-style: {' '.join(all_styles)};")

        if props:
            rule = ".%s {\n%s\n}" % (css_class, "\n".join(props))
            rules.append(rule)

    return "\n".join(rules)


# ---- Key translation between urwid and Textual ----

# Mapping from urwid special key names to Textual key names.
# Printable characters (single chars like 'v', 'S', '?') pass through as-is.
_URWID_TO_TEXTUAL = {
    "esc": "escape",
    "enter": "enter",
    "tab": "tab",
    "shift tab": "shift+tab",
    "up": "up",
    "down": "down",
    "left": "left",
    "right": "right",
    "page up": "pageup",
    "page down": "pagedown",
    "home": "home",
    "end": "end",
    "delete": "delete",
    "backspace": "backspace",
    "insert": "insert",
    " ": "space",
}

# Mapping from Textual key names back to urwid key names.
_TEXTUAL_TO_URWID = {v: k for k, v in _URWID_TO_TEXTUAL.items()}


def urwid_key_to_textual(key):
    """Convert an urwid key name to a Textual key name."""
    # Direct lookup for special keys
    if key in _URWID_TO_TEXTUAL:
        return _URWID_TO_TEXTUAL[key]
    # 'ctrl x' -> 'ctrl+x'
    if key.startswith("ctrl "):
        return "ctrl+" + key[5:]
    # 'meta x' -> 'escape' (Textual doesn't have meta; terminals send ESC+key)
    if key.startswith("meta "):
        return None  # handled via escape sequence buffering
    # 'f1' through 'f24' are the same in both
    if key.startswith("f") and key[1:].isdigit():
        return key
    # Single printable characters pass through
    return key


def textual_key_to_urwid(event):
    """Convert a Textual Key event to an urwid-style key name.

    Returns the urwid key name string, or None if the key should be ignored.
    """
    key = event.key
    # Direct lookup for special keys
    if key in _TEXTUAL_TO_URWID:
        return _TEXTUAL_TO_URWID[key]
    # 'ctrl+x' -> 'ctrl x'
    if key.startswith("ctrl+"):
        return "ctrl " + key[5:]
    # Function keys pass through
    if key.startswith("f") and key[1:].isdigit():
        return key
    # Printable character: use the character value to preserve case
    if event.character and len(event.character) == 1:
        return event.character
    # Named keys that match directly
    return key


# ---- Cursor/navigation command handling ----

# Cursor commands that should be forwarded to the focused widget rather
# than handled by _handle_command.  In the urwid app these go through
# urwid's command_map; in Textual we either let the native key pass
# through or invoke the widget action programmatically (for vi keys).
_CURSOR_COMMANDS = frozenset(
    (
        keymap.CURSOR_UP,
        keymap.CURSOR_DOWN,
        keymap.CURSOR_LEFT,
        keymap.CURSOR_RIGHT,
        keymap.CURSOR_PAGE_UP,
        keymap.CURSOR_PAGE_DOWN,
        keymap.CURSOR_MAX_LEFT,
        keymap.CURSOR_MAX_RIGHT,
        keymap.ACTIVATE,
    )
)

# Map cursor commands to Textual widget action method names.
# Each value is a tuple of action names to try in order, so that
# widgets with different APIs (DataTable vs VerticalScroll) all work.
_CURSOR_ACTION_MAP = {
    keymap.CURSOR_UP: ("action_cursor_up", "action_scroll_up"),
    keymap.CURSOR_DOWN: ("action_cursor_down", "action_scroll_down"),
    keymap.CURSOR_PAGE_UP: ("action_page_up",),
    keymap.CURSOR_PAGE_DOWN: ("action_page_down",),
    keymap.CURSOR_MAX_LEFT: ("action_scroll_top", "action_scroll_home"),
    keymap.CURSOR_MAX_RIGHT: ("action_scroll_bottom", "action_scroll_end"),
    keymap.ACTIVATE: ("action_select_cursor",),
}

# urwid key names that Textual/DataTable already handle natively.
# When the resolved commands are all cursor commands AND the key is
# one of these, we let the event pass through untouched.
_NATIVE_NAV_KEYS = frozenset(
    (
        "up",
        "down",
        "left",
        "right",
        "page up",
        "page down",
        "enter",
    )
)


class HubttyHeader(Static):
    """Status header showing title, sync status, and indicators."""

    def __init__(self):
        super().__init__("")
        self._title = "Hubtty"
        self._offline = False
        self._error = False
        self._sync = 0
        self._held = 0
        self._message = None
        self._update_display()

    def _update_display(self):
        if self._message:
            parts = [self._message]
        else:
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

    def set_message(self, message):
        self._message = message
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
    #content {
        height: 1fr;
    }
    """

    BINDINGS = []

    def __init__(
        self,
        server=None,
        palette="default",
        keymap_name="default",
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
            keymap=keymap_name,
            debug=debug,
            verbose=verbose,
            disable_sync=disable_sync,
            disable_background_sync=disable_background_sync,
            fetch_missing_refs=fetch_missing_refs,
            path=path,
        )

        self._disable_sync = disable_sync
        self.input_buffer = []

        # Generate palette CSS from the hubtty palette config
        palette_css = palette_to_css(self.config.palette.palette)
        if palette_css:
            self.stylesheet.add_source(palette_css)

        # Build Rich style lookup for palette entry names
        self.rich_palette = palette_to_rich_styles(self.config.palette.palette)

    @property
    def title(self):
        return "Hubtty %s" % hubtty.version.version_info.release_string()

    @title.setter
    def title(self, value):
        # Textual App has a title reactive; we override to keep ours fixed
        pass

    def compose(self) -> ComposeResult:
        yield HubttyHeader()
        yield Vertical(id="content")
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

        # Mount the initial repository list view
        from hubtty.textual_view.repository_list import RepositoryListView

        self._view_stack = []
        self._current_view = RepositoryListView()
        content = self.query_one("#content")
        content.mount(self._current_view)

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

    def on_resize(self, event) -> None:
        """Refresh the current view when the terminal is resized."""
        view = getattr(self, "_current_view", None)
        if view and view.is_mounted and hasattr(view, "refresh_data"):
            view.refresh_data()

    # ---- Key handling ----

    async def on_event(self, event) -> None:
        """Intercept key events for keymap processing before Textual
        forwards them to the focused widget.

        This runs in the dispatch phase (before forwarding), not the
        bubble phase (after).  That way, commands like searchStart()
        can change focus synchronously and subsequent queued key events
        will be routed to the newly-focused widget (e.g. the search
        Input) instead of the previously-focused one (e.g. DataTable).
        """
        from textual import events

        if isinstance(event, events.Key):
            if self._process_keymap(event):
                return  # consumed by keymap; don't forward
        await super().on_event(event)

    def _process_keymap(self, event) -> bool:
        """Process a key event through the hubtty keymap system.

        Returns True if the key was consumed (should not be forwarded
        to the focused widget), False to let Textual handle it.
        """
        # When a text input widget has focus, let most keys pass through
        # so the user can type freely.  But intercept keys that should
        # control the search (INTERACTIVE_SEARCH to cycle results, and
        # Escape to close the search bar).
        from textual.widgets import Input, TextArea

        focused = self.focused
        if isinstance(focused, (Input, TextArea)):
            view = self._current_view
            if view and hasattr(view, "_search_active") and view._search_active:
                urwid_key = textual_key_to_urwid(event)
                if urwid_key:
                    cmds = self.config.keymap.getCommands([urwid_key])
                    if keymap.INTERACTIVE_SEARCH in cmds:
                        view._nextSearchResult()
                        return True
                if event.key == "escape":
                    view._searchStop()
                    return True
            return False

        urwid_key = textual_key_to_urwid(event)
        if urwid_key is None:
            return False

        keys = self.input_buffer + [urwid_key]
        commands = self.config.keymap.getCommands(keys)

        if not commands:
            # No match; clear buffer and let Textual handle it
            self._clearInputBuffer()
            return False

        if keymap.FURTHER_INPUT in commands:
            # Multi-key sequence in progress; buffer and wait
            self.input_buffer.append(urwid_key)
            # Show the buffered keys in the header
            msg = "".join(self.input_buffer)
            further = self.config.keymap.getFurtherCommands(keys)
            completions = " ".join(fkey for fkey, cmds in further if cmds)
            msg = "%s: %s" % (msg, completions)
            self.hubtty_header.set_message(msg)
            return True  # consumed

        # We have a complete command match
        self._clearInputBuffer()

        # Separate cursor commands from non-cursor commands
        real_commands = [c for c in commands if c != keymap.FURTHER_INPUT]
        cursor_cmds = [c for c in real_commands if c in _CURSOR_COMMANDS]
        other_cmds = [c for c in real_commands if c not in _CURSOR_COMMANDS]

        # Handle cursor/navigation commands
        if cursor_cmds and not other_cmds:
            # Only cursor commands resolved for this key
            if urwid_key in _NATIVE_NAV_KEYS:
                # Let Textual handle it natively (don't consume)
                return False
            # Vi-mode remapped key (j/k/g/G/etc): invoke the action
            # on the focused widget directly
            focused = self.focused
            if focused:
                for cmd in cursor_cmds:
                    self._invoke_cursor_action(focused, cmd)
            return True  # consumed

        # Non-cursor commands: dispatch
        for command in other_cmds:
            self._handle_command(command, urwid_key)

        # Also handle any cursor commands that came alongside
        if cursor_cmds:
            focused = self.focused
            if focused:
                for cmd in cursor_cmds:
                    self._invoke_cursor_action(focused, cmd)

        return True  # consumed

    def _clearInputBuffer(self):
        if self.input_buffer:
            self.input_buffer = []
            if hasattr(self, "hubtty_header"):
                self.hubtty_header.set_message(None)

    def _invoke_cursor_action(self, widget, cmd):
        """Invoke the first matching action for a cursor command on *widget*.

        _CURSOR_ACTION_MAP values are tuples of action names to try, so
        widgets with different APIs (DataTable vs VerticalScroll) all work.
        """
        actions = _CURSOR_ACTION_MAP.get(cmd, ())
        for action in actions:
            if hasattr(widget, action):
                getattr(widget, action)()
                return

    def _handle_command(self, command, key):
        """Dispatch a hubtty command. Global commands are handled here;
        screen-specific commands will be forwarded to the active screen."""
        if command == keymap.QUIT:
            self.exit()
        elif command == keymap.PREV_SCREEN:
            self.backScreen()
        elif command == keymap.TOP_SCREEN:
            # Pop all views back to the initial repository list
            while self._view_stack:
                old_view = self._current_view
                old_view.remove()
                self._current_view = self._view_stack.pop()
            self._current_view.display = True
            if hasattr(self._current_view, "refresh_data"):
                self._current_view.refresh_data()
        elif command == keymap.HELP:
            # TODO: show help
            self.notify("Help not yet implemented", title="Help")
        elif command == keymap.PR_SEARCH:
            # TODO: show search dialog
            self.notify("Search not yet implemented", title="Search")
        elif command == keymap.LIST_HELD:
            self.doSearch("is:held")
        else:
            # Forward to the active view's command handler
            view = self._current_view
            if view and hasattr(view, "handleCommand"):
                if view.handleCommand(command):
                    return
            self.logger.debug("Unhandled command: %s (key: %s)", command, key)

    # ---- Sync polling ----

    def _poll_sync_results(self) -> None:
        """Periodically check for sync results and update UI."""
        import queue

        needs_refresh = False
        invalidate = False
        try:
            while True:
                event = self.sync.result_queue.get(0)
                view = self._current_view
                if view and hasattr(view, "interested") and view.interested(event):
                    needs_refresh = True
                if hasattr(event, "held_changed") and event.held_changed:
                    invalidate = True
        except queue.Empty:
            pass
        if needs_refresh:
            view = self._current_view
            if view and hasattr(view, "refresh_data"):
                view.refresh_data()
        if invalidate:
            self.updateStatusQueries()
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

    def changeScreen(self, view, push=True):
        """Navigate to a new view widget."""
        self.logger.debug("Changing view to %s", view)
        self._clearInputBuffer()
        if push:
            self._view_stack.append(self._current_view)
        content = self.query_one("#content")
        self._current_view.display = False
        content.mount(view)
        self._current_view = view
        self.call_later(self.screen.focus_next)

    def backScreen(self, target_widget=None):
        """Navigate back to the previous view."""
        if not self._view_stack:
            return
        self._clearInputBuffer()
        self.logger.debug("Popping view")
        old_view = self._current_view
        old_view.remove()
        view = self._view_stack.pop()
        view.display = True
        self._current_view = view
        # Refresh the restored view so it picks up any changes
        if hasattr(view, "refresh_data"):
            view.refresh_data()
        self.screen.focus_next()

    def registerPaletteEntry(self, label_id, label_color):
        """Register a label color. In Textual, handled via CSS."""
        # Label colors will be handled via inline styles when needed
        pass

    def openURL(self, url):
        """Open a URL in the browser."""
        self.logger.debug("Open URL %s", url)
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
            self.logger.debug("Opening URL %s", url)
            result = self.parseInternalURL(url)
            if result is not None:
                self.call_from_thread(self.openInternalURL, result)
        else:
            self.logger.error("Unable to parse command %s with data %s", command, data)

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
