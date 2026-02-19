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

from textual import work
from textual.widget import Widget
from textual.widgets import Markdown, Static, Rule
from textual.containers import Horizontal, Vertical, VerticalScroll

from hubtty import gitrepo
from hubtty import keymap
from hubtty import sync
from hubtty.perf import perf_log, PerfCounters, LOG as PERF_LOG

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
    .diff-comment-row {
        height: auto;
    }
    .diff-comment-pad {
        width: 1fr;
    }
    .diff-comment {
        background: #1a2332;
        border-left: thick #4a9eff;
        padding: 0 1 0 1;
        margin: 1 0;
        height: auto;
        width: 1fr;
    }
    .diff-comment Static {
        margin: 0;
        padding: 0;
    }
    .diff-comment Markdown {
        margin: 0;
        padding: 0;
    }
    .diff-draft-comment {
        background: #2a1a1a;
        border-left: thick #e05050;
        padding: 0 1 0 1;
        margin: 1 0;
        height: auto;
        width: 1fr;
    }
    .diff-draft-comment Static {
        margin: 0;
        padding: 0;
    }
    .diff-draft-comment Markdown {
        margin: 0;
        padding: 0;
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
        self._perf_counters = PerfCounters()
        self._scroll_perf_counters = PerfCounters()

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
        with self._perf_counters.count("_syntax_highlight"):
            text = Text()
            text.append_tokens(
                (token_text, _SYNTAX_THEME.get_style_for_token(token_type))
                for token_type, token_text in lexer.get_tokens(raw_text)
            )
            # Strip trailing newline that Pygments may add
            if text.plain.endswith("\n") and not raw_text.endswith("\n"):
                text.right_crop(1)
            return text

    def _make_table(self):
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
        table.add_column(ratio=1)
        table.add_column(width=LN_COL_WIDTH, no_wrap=True)
        table.add_column(ratio=1)
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
        """Kick off background diff loading.

        The heavy work (DB queries, git diff, row data building) runs
        in a thread worker so the UI stays responsive.  When the worker
        finishes it hands the prepared data to _mount_diff() on the
        main thread for widget construction and mounting.
        """
        self.loading = True
        self._load_diff_data()

    @work(thread=True, exclusive=True, group="diff-load")
    def _load_diff_data(self):
        """Worker: load diff data and build row tuples (background thread).

        Produces an instruction list of plain Python / Rich objects
        that _mount_diff() converts into Textual widgets on the main
        thread.
        """
        with perf_log("DiffView._load_diff_data"):
            with perf_log("DiffView._load_diff_data.db_session"):
                with self.app.db.getSession() as session:
                    new_commit = session.getCommit(self.commit_key)
                    if new_commit is None:
                        self.app.call_from_thread(self._mount_diff, None)
                        return

                    pr = new_commit.pull_request
                    self.pr_key = pr.key
                    repository_name = pr.repository.name
                    base_sha = new_commit.parent
                    sha = new_commit.sha

                    title = "Diff of %s from %s to %s" % (
                        repository_name,
                        base_sha[:7],
                        sha[:7],
                    )

                    # Collect comments into plain dicts
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
                                    comment.author.name
                                    or comment.author.username
                                    or "Unknown"
                                )
                                message = (author, comment.message)
                            comment_list.append((comment.key, message))
                            comment_lists[key] = comment_list
                            comment_filenames.add(path)

            # Get diff from git repo (outside DB session)
            try:
                repo = gitrepo.get_repo(repository_name, self.app.config)
                with perf_log("DiffView._load_diff_data.repo_diff"):
                    diffs = repo.diff(base_sha, sha)
            except Exception as e:
                self.logger.error("Error loading diff: %s", e)
                self.app.call_from_thread(
                    self._mount_diff_error, "Error loading diff: %s" % e
                )
                return

            # Add files that have comments but no diff
            for diff in diffs:
                comment_filenames.discard(diff.oldname)
                comment_filenames.discard(diff.newname)
            for filename in comment_filenames:
                try:
                    diff = repo.getFile(base_sha, sha, filename)
                    if diff:
                        diffs.append(diff)
                except Exception:
                    self.logger.debug(
                        "Unable to find file %s in commit %s", filename, sha
                    )

            # Build instruction list (plain Python / Rich objects only)
            with perf_log("DiffView._load_diff_data.build_instructions"):
                instructions = self._build_instructions(diffs, comment_lists)

        self.app.call_from_thread(self._mount_diff, instructions, title)

    # ---- Instruction types used between worker and main thread ----
    # Each instruction is a tuple whose first element identifies its type.
    _INST_RULE = "rule"
    _INST_FILE_HEADER = "file_header"
    _INST_BATCH = "batch"  # (type, [row_data, ...])
    _INST_CONTEXT_IND = "context"  # (type, count)
    _INST_COMMENT = "comment"  # (type, side, message)
    _INST_DRAFT = "draft"  # (type, side, message)

    def _build_instructions(self, diffs, comment_lists):
        """Build an instruction list from diffs (runs in worker thread).

        Returns a list of tuples describing what widgets to create.
        All heavy work (syntax highlighting, row data building) happens
        here.  The instructions contain only plain Python objects and
        Rich renderables (Text, Table) -- no Textual widgets.
        """
        self._perf_counters.reset()
        instructions = []
        file_headers = []
        line_count = 0

        for i, diff in enumerate(diffs):
            if i > 0:
                instructions.append((self._INST_RULE,))

            # Track file header position (index into instructions)
            file_headers.append((len(instructions), diff.oldname, diff.newname))

            # File header data
            instructions.append(
                (self._INST_FILE_HEADER, diff.oldname or "", diff.newname or "")
            )

            # File-level comment data
            self._collect_comment_instructions(
                instructions, comment_lists, diff, None, None
            )

            # Chunks -- one batch spans across chunk boundaries
            batch = []
            lexer = self._get_lexer(diff.newname or diff.oldname)

            for chunk in diff.chunks:
                if chunk.context and len(chunk.lines) > 20:
                    if not chunk.first:
                        for line in chunk.lines[:10]:
                            with self._perf_counters.count("_build_diff_line"):
                                batch.append(
                                    self._build_diff_line_data(diff, line, lexer)
                                )
                                line_count += 1
                            batch, line_count = self._maybe_flush_for_comments(
                                batch,
                                instructions,
                                comment_lists,
                                diff,
                                line,
                                line_count,
                            )
                    # Flush before context indicator
                    if batch:
                        instructions.append((self._INST_BATCH, batch))
                        batch = []
                    middle_count = len(chunk.lines) - 10
                    if chunk.first:
                        middle_count = len(chunk.lines)
                    if not chunk.last:
                        middle_count -= 10
                    if middle_count > 0:
                        instructions.append((self._INST_CONTEXT_IND, middle_count))
                    if not chunk.last:
                        for line in chunk.lines[-10:]:
                            with self._perf_counters.count("_build_diff_line"):
                                batch.append(
                                    self._build_diff_line_data(diff, line, lexer)
                                )
                                line_count += 1
                            batch, line_count = self._maybe_flush_for_comments(
                                batch,
                                instructions,
                                comment_lists,
                                diff,
                                line,
                                line_count,
                            )
                else:
                    for line in chunk.lines:
                        with self._perf_counters.count("_build_diff_line"):
                            batch.append(self._build_diff_line_data(diff, line, lexer))
                            line_count += 1
                        batch, line_count = self._maybe_flush_for_comments(
                            batch,
                            instructions,
                            comment_lists,
                            diff,
                            line,
                            line_count,
                        )
            # Flush remaining rows for this file
            if batch:
                instructions.append((self._INST_BATCH, batch))

        PERF_LOG.info(
            "[perf] DiffView._build_instructions: %d instructions (%d diff lines)",
            len(instructions),
            line_count,
        )
        self._perf_counters.log_summary("DiffView._build_instructions")
        return (instructions, file_headers)

    def _maybe_flush_for_comments(
        self, batch, instructions, comment_lists, diff, line, line_count
    ):
        """Check for comments at this line; if any, flush the batch and
        append comment instructions.  Returns the (possibly reset) batch
        and unchanged line_count."""
        comment_data = self._pop_comment_data(
            comment_lists,
            diff,
            line[gitrepo.OLD][gitrepo.LINENO],
            line[gitrepo.NEW][gitrepo.LINENO],
        )
        if comment_data:
            if batch:
                instructions.append((self._INST_BATCH, batch))
                batch = []
            instructions.extend(comment_data)
        return batch, line_count

    def _collect_comment_instructions(
        self, instructions, comment_lists, diff, old_ln, new_ln
    ):
        """Append comment instructions for a given line position."""
        instructions.extend(self._pop_comment_data(comment_lists, diff, old_ln, new_ln))

    def _pop_comment_data(self, comment_lists, diff, old_ln, new_ln):
        """Pop comment data for a given line and return instruction tuples.

        Returns lightweight instruction tuples (not Textual widgets)
        that _mount_diff() converts into widgets on the main thread.
        """
        result = []
        for side, ln, name in (
            ("old", old_ln, diff.oldname),
            ("new", new_ln, diff.newname),
        ):
            key = "%s-%s-%s" % (side, ln, name)
            for _ck, message in comment_lists.pop(key, []):
                result.append((self._INST_COMMENT, side, message))
        for side, ln, name in (
            ("old", old_ln, diff.oldname),
            ("new", new_ln, diff.newname),
        ):
            key = "%sdraft-%s-%s" % (side, ln, name)
            for _ck, message in comment_lists.pop(key, []):
                result.append((self._INST_DRAFT, side, message))
        return result

    # ---- Main-thread widget construction and mounting ----

    def _mount_diff_error(self, message):
        """Show an error message (called on main thread)."""
        self.loading = False
        container = self.query_one("#diff-content", Vertical)
        container.remove_children()
        container.mount(Static(message))

    def _mount_diff(self, data, title=None):
        """Convert instructions into Textual widgets and mount them.

        Called on the main thread by the worker via call_from_thread.
        """
        with perf_log("DiffView._mount_diff"):
            self.loading = False
            container = self.query_one("#diff-content", Vertical)
            container.remove_children()

            if data is None:
                return

            instructions, file_headers = data

            if title:
                self.title = title
                if hasattr(self.app, "hubtty_header"):
                    self.app.hubtty_header.set_title(title)

            self._file_header_indices = []
            widgets = []

            for inst in instructions:
                itype = inst[0]
                if itype == self._INST_RULE:
                    widgets.append(Rule())
                elif itype == self._INST_FILE_HEADER:
                    _, old_name, new_name = inst
                    table = self._make_table()
                    table.add_row(
                        Text(""),
                        Text(old_name, style=self._style("filename"), no_wrap=True),
                        Text(""),
                        Text(new_name, style=self._style("filename"), no_wrap=True),
                    )
                    widgets.append(Static(table, classes="diff-file-header"))
                elif itype == self._INST_BATCH:
                    _, batch = inst
                    table = self._make_table()
                    for old_ln, old_ct, new_ln, new_ct in batch:
                        table.add_row(old_ln, old_ct, new_ln, new_ct)
                    widgets.append(Static(table, classes="diff-line"))
                elif itype == self._INST_CONTEXT_IND:
                    _, count = inst
                    text = Text()
                    text.append(
                        "  ... %d lines of context ..." % count,
                        style=self._style("context-button"),
                    )
                    widgets.append(Static(text, classes="diff-context-btn"))
                elif itype == self._INST_COMMENT:
                    _, side, message = inst
                    widgets.append(self._build_comment(side, message))
                elif itype == self._INST_DRAFT:
                    _, side, message = inst
                    widgets.append(self._build_draft_comment(side, message))

            # Rebuild file header indices from the instruction positions
            # mapped to widget positions
            inst_to_widget = {}
            widget_idx = 0
            for inst_idx, inst in enumerate(instructions):
                inst_to_widget[inst_idx] = widget_idx
                widget_idx += 1
            for inst_idx, old_name, new_name in file_headers:
                w_idx = inst_to_widget.get(inst_idx, 0)
                self._file_header_indices.append((w_idx, old_name, new_name))

            if widgets:
                with perf_log("DiffView._mount_diff.mount_all"):
                    container.mount_all(widgets)
            else:
                container.mount(Static("No diff available"))

            # Clear the file reminder initially
            reminder = self.query_one("#diff-file-reminder", Static)
            reminder.update("")

            # Scroll to top
            scroll = self.query_one("#diff-scroll", VerticalScroll)
            scroll.scroll_home(animate=False)

    @staticmethod
    def _diff_bg(action):
        """Return the background Style for a diff action."""
        if action == "+":
            return _ADDED_BG
        if action == "-":
            return _REMOVED_BG
        return None

    def _build_diff_line_data(self, diff, line, lexer):
        """Build row data for a single side-by-side diff line.

        Returns a tuple of (old_ln_text, old_content_text,
        new_ln_text, new_content_text) suitable for batching into a
        Rich Table.

        The "nonexistent" palette style (for sides that don't exist
        in the diff) is applied directly to the cell Text objects
        so that lines with different actions can share one Table.
        """
        old_side = line[gitrepo.OLD]
        new_side = line[gitrepo.NEW]
        old_ln, old_action, old_content = old_side
        new_ln, new_action, new_content = new_side

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
            old_content_text = Text(style=self._style("nonexistent"))

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
            new_content_text = Text(style=self._style("nonexistent"))

        return (old_ln_text, old_content_text, new_ln_text, new_content_text)

    def _build_line_content(self, action, content, lexer):
        """Build a Rich Text for one side of a diff line.

        Combines syntax highlighting (foreground) with diff background
        tinting, plus intraline word-emphasis overlays.
        """
        raw = self._extract_raw_text(content)
        bg = self._diff_bg(action)

        # Build base text: syntax highlighted for changed lines, plain
        # for context lines (where highlighting adds little value)
        if lexer and action != " ":
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
        elif action == "-":
            word_bg = _REMOVED_WORD_BG
        else:
            return
        word_suffix = "-word"

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

    def _build_comment(self, side, message):
        """Build a read-only inline comment widget."""
        if isinstance(message, tuple):
            author, body = message
        else:
            author = None
            body = str(message)
        prefix = "<" if side == "old" else ">"
        header = Text()
        header.append(prefix + " ", style="dim")
        if author:
            header.append(author, style=self._style("comment-name"))
        comment = Vertical(
            Static(header),
            Markdown(body),
            classes="diff-comment",
        )
        pad = Static("", classes="diff-comment-pad")
        if side == "old":
            return Horizontal(comment, pad, classes="diff-comment-row")
        else:
            return Horizontal(pad, comment, classes="diff-comment-row")

    def _build_draft_comment(self, side, message):
        """Build a read-only draft comment widget."""
        prefix = "<" if side == "old" else ">"
        header = Text()
        header.append(prefix + " ", style="dim")
        header.append("(draft)", style=self._style("pr-message-draft"))
        comment = Vertical(
            Static(header),
            Markdown(str(message)),
            classes="diff-draft-comment",
        )
        pad = Static("", classes="diff-comment-pad")
        if side == "old":
            return Horizontal(comment, pad, classes="diff-comment-row")
        else:
            return Horizontal(pad, comment, classes="diff-comment-row")

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
        with self._scroll_perf_counters.count("_update_file_reminder_from_scroll"):
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
            self._log_scroll_perf()
            self.app.backScreen()
            return True
        if command == keymap.PREV_SCREEN:
            self._log_scroll_perf()
            self.app.backScreen()
            return True
        return False

    def _log_scroll_perf(self):
        """Log accumulated scroll performance counters before leaving."""
        self._scroll_perf_counters.log_summary("DiffView.scroll")

    def _pr_id(self):
        """Get the pr_id string for sync tasks."""
        with self.app.db.getSession() as session:
            pr = session.getPullRequest(self.pr_key)
            if pr:
                return pr.pr_id
        return None
