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

from pygments.lexers import get_lexer_for_filename
from pygments.util import ClassNotFound

from rich.style import Style
from rich.syntax import ANSISyntaxTheme, ANSI_DARK
from rich.table import Table
from rich.text import Text

from textual.widget import Widget
from textual.widgets import Static, Rule
from textual.containers import Vertical, VerticalScroll

from hubtty import gitrepo
from hubtty import keymap
from hubtty import sync

LN_COL_WIDTH = 5

# Syntax highlighting theme (foreground-only, no bgcolor baked in)
_SYNTAX_THEME = ANSISyntaxTheme(ANSI_DARK)

# Diff background styles (subtle tints)
_ADDED_BG = Style(bgcolor="#0d2816")
_REMOVED_BG = Style(bgcolor="#3b1113")
_ADDED_WORD_BG = Style(bgcolor="#174525")
_REMOVED_WORD_BG = Style(bgcolor="#5c2425")


class DiffView(Widget):
    """Side-by-side diff view for a single commit."""

    DEFAULT_CSS = """
    DiffView {
        layout: vertical;
        height: 1fr;
    }
    DiffView VerticalScroll {
        height: 1fr;
    }
    #diff-file-reminder {
        height: auto;
        max-height: 1;
        dock: top;
    }
    #diff-content {
        height: auto;
    }
    .diff-file-header {
        height: auto;
    }
    .diff-line {
        height: auto;
    }
    .diff-comment {
        padding: 0 0 0 0;
    }
    .diff-context-btn {
        height: 1;
    }
    """

    def __init__(self, pr_key, commit_key):
        super().__init__()
        self.logger = logging.getLogger("hubtty.textual_view.diff")
        self.pr_key = pr_key
        self.commit_key = commit_key
        self.title = "Diff"
        self._file_header_indices = []
        self._lexer_cache = {}

    def _style(self, name):
        """Look up a palette entry name and return a Rich style string."""
        return self.app.rich_palette.get(name, "")

    def _get_lexer(self, filename):
        """Get a Pygments lexer for a filename, cached. Returns None on failure."""
        if filename in self._lexer_cache:
            return self._lexer_cache[filename]
        lexer = None
        if filename:
            try:
                lexer = get_lexer_for_filename(filename, stripnl=False, ensurenl=False)
            except ClassNotFound:
                pass
        self._lexer_cache[filename] = lexer
        return lexer

    @staticmethod
    def _extract_raw_text(content):
        """Extract plain text from diff content (str, tuple, or list).

        Also replaces the » tab indicator with a plain space (the
        tab-stop padding spaces from gitrepo.expand_tabs are preserved).
        """
        if isinstance(content, str):
            return content.replace("»", " ")
        if isinstance(content, tuple):
            return content[1].replace("»", " ")
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, tuple):
                    parts.append(item[1])
                elif isinstance(item, list):
                    for sub in item:
                        if isinstance(sub, tuple):
                            parts.append(sub[1])
            return "".join(parts).replace("»", " ")
        return str(content)

    def _syntax_highlight(self, raw_text, lexer):
        """Tokenize raw_text with Pygments and return a Rich Text with
        syntax foreground colors (no background)."""
        text = Text()
        text.append_tokens(
            (token_text, _SYNTAX_THEME.get_style_for_token(token_type))
            for token_type, token_text in lexer.get_tokens(raw_text)
        )
        # Strip trailing newline that Pygments may add
        if text.plain.endswith("\n") and not raw_text.endswith("\n"):
            text.right_crop(1)
        return text

    def _make_table(self, old_col_style="", new_col_style=""):
        """Create a 4-column Rich Table for side-by-side layout.

        Columns: old_ln (fixed) | old_content (1fr) |
                 new_ln (fixed) | new_content (1fr)

        Line number columns act as natural visual separators.
        """
        table = Table(
            show_header=False,
            box=None,
            padding=(0, 0),
            expand=True,
            show_edge=False,
        )
        table.add_column(width=LN_COL_WIDTH, no_wrap=True)
        table.add_column(ratio=1, style=old_col_style)
        table.add_column(width=LN_COL_WIDTH, no_wrap=True)
        table.add_column(ratio=1, style=new_col_style)
        return table

    def compose(self):
        yield Static(id="diff-file-reminder")
        with VerticalScroll(id="diff-scroll"):
            yield Vertical(id="diff-content")

    def on_mount(self):
        scroll = self.query_one("#diff-scroll", VerticalScroll)
        self.watch(scroll, "scroll_y", self._on_scroll_changed)
        self.refresh_data()

    def _on_scroll_changed(self, scroll_y):
        self._update_file_reminder_from_scroll()

    # ---- Event interest ----

    def interested(self, event):
        if isinstance(event, sync.PullRequestAddedEvent):
            return self.pr_key == event.pr_key
        if isinstance(event, sync.PullRequestUpdatedEvent):
            return self.pr_key == event.pr_key
        return False

    # ---- Data loading and rendering ----

    def refresh_data(self):
        """Load diff data and build the view."""
        with self.app.db.getSession() as session:
            new_commit = session.getCommit(self.commit_key)
            if new_commit is None:
                return

            pr = new_commit.pull_request
            self.pr_key = pr.key
            repository_name = pr.repository.name
            base_sha = new_commit.parent
            sha = new_commit.sha

            self.title = "Diff of %s from %s to %s" % (
                repository_name,
                base_sha[:7],
                sha[:7],
            )
            if hasattr(self.app, "hubtty_header"):
                self.app.hubtty_header.set_title(self.title)

            # Build file key mappings
            old_file_keys = {}
            new_file_keys = {}
            for f in new_commit.files:
                if f.old_path:
                    old_file_keys[f.old_path] = f.key
                else:
                    old_file_keys[f.path] = f.key
                new_file_keys[f.path] = f.key

            # Collect comments
            comment_lists = {}
            comment_filenames = set()
            for f in new_commit.files:
                for comment in f.current_comments:
                    path = comment.file.path
                    if comment.parent:
                        key = "old"
                        if comment.file.old_path:
                            path = comment.file.old_path
                    else:
                        key = "new"
                    if comment.draft:
                        key += "draft"
                    key += "-" + str(comment.line)
                    key += "-" + path
                    comment_list = comment_lists.get(key, [])
                    if comment.draft:
                        message = comment.message
                    else:
                        author = (
                            comment.author.name or comment.author.username or "Unknown"
                        )
                        message = (author, comment.message)
                    comment_list.append((comment.key, message))
                    comment_lists[key] = comment_list
                    comment_filenames.add(path)

        # Get diff from git repo (outside DB session)
        try:
            repo = gitrepo.get_repo(repository_name, self.app.config)
            diffs = repo.diff(base_sha, sha)
        except Exception as e:
            self.logger.error("Error loading diff: %s", e)
            self._show_error("Error loading diff: %s" % e)
            return

        # Remove files that are already in the diff from comment_filenames
        for diff in diffs:
            comment_filenames.discard(diff.oldname)
            comment_filenames.discard(diff.newname)

        # Create fake diffs for files with comments but no diff
        for filename in comment_filenames:
            try:
                diff = repo.getFile(base_sha, sha, filename)
                if diff:
                    diffs.append(diff)
            except Exception:
                self.logger.debug("Unable to find file %s in commit %s", filename, sha)

        # Build widgets
        self._build_diff_widgets(diffs, comment_lists, old_file_keys, new_file_keys)

    def _show_error(self, message):
        """Display an error in the diff content area."""
        container = self.query_one("#diff-content", Vertical)
        container.remove_children()
        container.mount(Static(message))

    def _build_diff_widgets(self, diffs, comment_lists, old_file_keys, new_file_keys):
        """Build all diff widgets and mount them."""
        container = self.query_one("#diff-content", Vertical)
        container.remove_children()

        widgets = []
        self._file_header_indices = []

        for i, diff in enumerate(diffs):
            if i > 0:
                widgets.append(Rule())

            # Track file header position
            self._file_header_indices.append((len(widgets), diff.oldname, diff.newname))

            # Determine file keys for this diff
            old_key = None
            new_key = None
            if not diff.old_empty:
                old_key = old_file_keys.get(diff.oldname) or old_file_keys.get(
                    diff.newname
                )
            if not diff.new_empty:
                new_key = new_file_keys.get(diff.newname)

            # Resolve syntax highlighting lexer for this file
            lexer = self._get_lexer(diff.newname or diff.oldname)

            # File header
            widgets.append(self._build_file_header(diff))

            # File-level comments
            widgets.extend(self._pop_comments(comment_lists, diff, None, None))

            # Chunks
            for chunk in diff.chunks:
                if chunk.context:
                    # Show first 10 and last 10 context lines
                    # with an expand indicator in between
                    first_lines = chunk.lines[:10]
                    last_lines = chunk.lines[-10:]
                    middle_count = len(chunk.lines) - len(first_lines)
                    if len(chunk.lines) <= 20:
                        # Small enough to show all
                        for line in chunk.lines:
                            widgets.append(
                                self._build_diff_line(
                                    diff, line, old_key, new_key, lexer
                                )
                            )
                            widgets.extend(
                                self._pop_comments(
                                    comment_lists,
                                    diff,
                                    line[gitrepo.OLD][gitrepo.LINENO],
                                    line[gitrepo.NEW][gitrepo.LINENO],
                                )
                            )
                    else:
                        if not chunk.first:
                            for line in first_lines:
                                widgets.append(
                                    self._build_diff_line(
                                        diff, line, old_key, new_key, lexer
                                    )
                                )
                                widgets.extend(
                                    self._pop_comments(
                                        comment_lists,
                                        diff,
                                        line[gitrepo.OLD][gitrepo.LINENO],
                                        line[gitrepo.NEW][gitrepo.LINENO],
                                    )
                                )
                        # Context collapse indicator
                        if middle_count > 0:
                            widgets.append(self._build_context_indicator(middle_count))
                        if not chunk.last:
                            for line in last_lines:
                                widgets.append(
                                    self._build_diff_line(
                                        diff, line, old_key, new_key, lexer
                                    )
                                )
                                widgets.extend(
                                    self._pop_comments(
                                        comment_lists,
                                        diff,
                                        line[gitrepo.OLD][gitrepo.LINENO],
                                        line[gitrepo.NEW][gitrepo.LINENO],
                                    )
                                )
                else:
                    # Changed chunk -- show all lines
                    for line in chunk.lines:
                        widgets.append(
                            self._build_diff_line(diff, line, old_key, new_key, lexer)
                        )
                        widgets.extend(
                            self._pop_comments(
                                comment_lists,
                                diff,
                                line[gitrepo.OLD][gitrepo.LINENO],
                                line[gitrepo.NEW][gitrepo.LINENO],
                            )
                        )

        if widgets:
            container.mount_all(widgets)
        else:
            container.mount(Static("No diff available"))

        # Clear the file reminder initially -- the in-content file
        # header is visible at the top, so no need to duplicate it.
        reminder = self.query_one("#diff-file-reminder", Static)
        reminder.update("")

    def _build_file_header(self, diff):
        """Build a file header widget with side-by-side table layout."""
        old = diff.oldname or ""
        new = diff.newname or ""

        table = self._make_table()
        table.add_row(
            Text(""),
            Text(old, style=self._style("filename"), no_wrap=True),
            Text(""),
            Text(new, style=self._style("filename"), no_wrap=True),
        )
        return Static(table, classes="diff-file-header")

    @staticmethod
    def _diff_bg(action):
        """Return the background Style for a diff action."""
        if action == "+":
            return _ADDED_BG
        if action == "-":
            return _REMOVED_BG
        return None

    def _build_diff_line(self, diff, line, old_key, new_key, lexer):
        """Build a single side-by-side diff line widget using Rich Table."""
        old_side = line[gitrepo.OLD]
        new_side = line[gitrepo.NEW]
        old_ln, old_action, old_content = old_side
        new_ln, new_action, new_content = new_side

        # Column styles for nonexistent sides
        old_col_style = self._style("nonexistent") if old_action == "" else ""
        new_col_style = self._style("nonexistent") if new_action == "" else ""
        table = self._make_table(old_col_style, new_col_style)

        old_bg = self._diff_bg(old_action)
        new_bg = self._diff_bg(new_action)

        # Old line number
        ln_fg = self._style("line-number")
        if old_ln is not None:
            old_ln_text = Text("%*i " % (LN_COL_WIDTH - 1, old_ln), style=ln_fg)
        else:
            old_ln_text = Text(" " * LN_COL_WIDTH, style=ln_fg)
        if old_bg:
            old_ln_text.stylize(old_bg)

        # Old content
        if old_action != "":
            old_content_text = self._build_line_content(old_action, old_content, lexer)
        else:
            old_content_text = Text()

        # New line number
        if new_ln is not None:
            new_ln_text = Text("%*i " % (LN_COL_WIDTH - 1, new_ln), style=ln_fg)
        else:
            new_ln_text = Text(" " * LN_COL_WIDTH, style=ln_fg)
        if new_bg:
            new_ln_text.stylize(new_bg)

        # New content
        if new_action != "":
            new_content_text = self._build_line_content(new_action, new_content, lexer)
        else:
            new_content_text = Text()

        table.add_row(
            old_ln_text,
            old_content_text,
            new_ln_text,
            new_content_text,
        )
        return Static(table, classes="diff-line")

    def _build_line_content(self, action, content, lexer):
        """Build a Rich Text for one side of a diff line.

        Combines syntax highlighting (foreground) with diff background
        tinting, plus intraline word-emphasis overlays.
        """
        raw = self._extract_raw_text(content)
        bg = self._diff_bg(action)

        # Build base text: syntax highlighted or plain
        if lexer:
            text = self._syntax_highlight(raw, lexer)
        else:
            text = Text(raw)

        # Apply diff background tint
        if bg:
            text.style = bg

        # Overlay intraline word emphasis backgrounds
        if isinstance(content, (list, tuple)) and not isinstance(content, str):
            self._apply_word_emphasis(text, action, content)

        return text

    def _apply_word_emphasis(self, text, action, content):
        """Overlay brighter backgrounds on word-emphasis segments."""
        if action == "+":
            word_bg = _ADDED_WORD_BG
            word_suffix = "-word"
        elif action == "-":
            word_bg = _REMOVED_WORD_BG
            word_suffix = "-word"
        else:
            return

        # Flatten content into (style_name, text) pairs with offsets
        segments = []
        if isinstance(content, tuple):
            segments.append((content[0], content[1]))
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, tuple):
                    segments.append((item[0], item[1]))
                elif isinstance(item, list):
                    for sub in item:
                        if isinstance(sub, tuple):
                            segments.append((sub[0], sub[1]))

        offset = 0
        for style_name, seg_text in segments:
            seg_len = len(seg_text)
            if style_name.endswith(word_suffix) or style_name == "trailing-ws":
                text.stylize(word_bg, offset, offset + seg_len)
            offset += seg_len

    def _build_context_indicator(self, count):
        """Build a context collapse indicator."""
        text = Text()
        text.append(
            "  ... %d lines of context ..." % count, style=self._style("context-button")
        )
        return Static(text, classes="diff-context-btn")

    def _pop_comments(self, comment_lists, diff, old_ln, new_ln):
        """Pop and build comment widgets for a given line."""
        widgets = []

        # Non-draft comments
        for side, ln, name in (
            ("old", old_ln, diff.oldname),
            ("new", new_ln, diff.newname),
        ):
            key = "%s-%s-%s" % (side, ln, name)
            comments = comment_lists.pop(key, [])
            for comment_key, message in comments:
                widgets.append(self._build_comment(side, message))

        # Draft comments (read-only for now)
        for side, ln, name in (
            ("old", old_ln, diff.oldname),
            ("new", new_ln, diff.newname),
        ):
            key = "%sdraft-%s-%s" % (side, ln, name)
            comments = comment_lists.pop(key, [])
            for comment_key, message in comments:
                widgets.append(self._build_draft_comment(side, message))

        return widgets

    def _build_comment(self, side, message):
        """Build a read-only inline comment widget."""
        text = Text()
        if isinstance(message, tuple):
            author, body = message
            text.append(author, style=self._style("comment-name"))
            text.append(": ", style=self._style("comment"))
            text.append(body, style=self._style("comment"))
        else:
            text.append(str(message), style=self._style("comment"))
        prefix = "  < " if side == "old" else "  > "
        result = Text()
        result.append(prefix, style="dim")
        result.append_text(text)
        return Static(result, classes="diff-comment")

    def _build_draft_comment(self, side, message):
        """Build a read-only draft comment widget."""
        text = Text()
        text.append("  (draft) ", style=self._style("pr-message-draft"))
        text.append(str(message), style=self._style("draft-comment"))
        return Static(text, classes="diff-comment")

    def _update_file_reminder(self, old_name, new_name):
        """Update the sticky file reminder header with side-by-side layout."""
        reminder = self.query_one("#diff-file-reminder", Static)
        table = self._make_table()
        table.add_row(
            Text(""),
            Text(old_name or "", style=self._style("filename"), no_wrap=True),
            Text(""),
            Text(new_name or "", style=self._style("filename"), no_wrap=True),
        )
        reminder.update(table)

    # ---- Scroll tracking for file reminder ----

    def _update_file_reminder_from_scroll(self):
        """Determine which file is at the top of the visible area.

        Only show the docked file reminder for a file whose in-content
        header has scrolled above the viewport (strict < check).
        This avoids duplicating the filename when the header is visible.
        """
        if not self._file_header_indices:
            return
        scroll = self.query_one("#diff-scroll", VerticalScroll)
        scroll_y = scroll.scroll_y

        container = self.query_one("#diff-content", Vertical)
        children = list(container.children)
        if not children:
            return

        best_old = None
        best_new = None
        for idx, old_name, new_name in self._file_header_indices:
            if idx < len(children):
                child = children[idx]
                # virtual_region is in content-space coordinates
                # (same as scroll_y), unlike region which is screen coords
                vr = child.virtual_region
                if vr.height > 0 and vr.y + vr.height <= scroll_y:
                    best_old = old_name
                    best_new = new_name

        reminder = self.query_one("#diff-file-reminder", Static)
        if best_old is not None:
            self._update_file_reminder(best_old, best_new)
        else:
            # No file header has scrolled past -- clear the reminder
            reminder.update("")

    # ---- Commit navigation ----

    def _move_commit(self, direction):
        """Navigate to the next (direction=1) or previous (direction=-1)
        commit in the PR."""
        with self.app.db.getSession() as session:
            commit = session.getCommit(self.commit_key)
            if commit is None:
                return
            pr = commit.pull_request
            commits = list(pr.commits)
            current_idx = None
            for i, c in enumerate(commits):
                if c.key == self.commit_key:
                    current_idx = i
                    break
            if current_idx is None:
                return
            new_idx = current_idx + direction
            if new_idx < 0 or new_idx >= len(commits):
                return
            self.commit_key = commits[new_idx].key
        self.refresh_data()

    # ---- Command dispatch ----

    def handleCommand(self, command):
        if command == keymap.NEXT_COMMIT:
            self._move_commit(1)
            return True
        if command == keymap.PREV_COMMIT:
            self._move_commit(-1)
            return True
        if command == keymap.REFRESH:
            self.app.sync.submitTask(
                sync.SyncPullRequestTask(self._pr_id(), priority=sync.HIGH_PRIORITY)
            )
            self.refresh_data()
            return True
        if command == keymap.SEARCH_RESULTS:
            self.app.backScreen()
            return True
        if command == keymap.PREV_SCREEN:
            self.app.backScreen()
            return True
        return False

    def _pr_id(self):
        """Get the pr_id string for sync tasks."""
        with self.app.db.getSession() as session:
            pr = session.getPullRequest(self.pr_key)
            if pr:
                return pr.pr_id
        return None
