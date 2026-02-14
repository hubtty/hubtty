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
import re

from rich.text import Text

from textual.widget import Widget
from textual.widgets import Static, Markdown, Rule
from textual.containers import Vertical, VerticalScroll

from hubtty import keymap
from hubtty import sync


class PullRequestView(Widget):
    """Widget showing the details of a single pull request."""

    DEFAULT_CSS = """
    PullRequestView {
        layout: vertical;
        height: 1fr;
    }
    PullRequestView VerticalScroll {
        height: 1fr;
    }
    .pr-metadata {
        padding: 1 2;
    }
    .pr-description {
        padding: 1 2;
    }
    .pr-approvals {
        padding: 1 2;
    }
    .pr-commits-section {
        padding: 0 2;
    }
    #pr-messages-container {
        padding: 0 2;
    }
    .pr-messages-header {
        padding: 0;
    }
    .pr-message-header {
        padding: 1 0 0 0;
    }
    .pr-message-body {
        padding: 0 0 0 2;
    }
    .pr-inline-file {
        padding: 0 0 0 2;
    }
    .pr-inline-comment {
        padding: 0 0 0 4;
    }
    .pr-commit-files {
        padding: 0 2;
    }
    """

    def __init__(self, pr_key):
        super().__init__()
        self.logger = logging.getLogger("hubtty.textual_view.pull_request")
        self.pr_key = pr_key
        self.title = "Pull request"

    def _style(self, name):
        """Look up a palette entry name and return a Rich style string."""
        return self.app.rich_palette.get(name, "")

    def compose(self):
        with VerticalScroll():
            yield Static(id="pr-metadata", classes="pr-metadata")
            yield Rule()
            yield Markdown(id="pr-description", classes="pr-description")
            yield Rule()
            yield Static(id="pr-approvals", classes="pr-approvals")
            yield Rule()
            yield Static(id="pr-commits-section", classes="pr-commits-section")
            yield Rule()
            yield Vertical(id="pr-messages-container")

    def on_mount(self):
        self.refresh_data()

    # ---- Event interest and data refresh ----

    def interested(self, event):
        """Check if a sync event should trigger a refresh."""
        if isinstance(event, sync.PullRequestAddedEvent):
            return event.pr_key == self.pr_key
        if isinstance(event, sync.PullRequestUpdatedEvent):
            return event.pr_key == self.pr_key
        return False

    def refresh_data(self):
        """Rebuild the PR detail view from the database."""
        with self.app.db.getSession() as session:
            pr = session.getPullRequest(self.pr_key, lazy=False)
            if pr is None:
                return

            # Update last_seen
            if pr.last_seen is None:
                pr.last_seen = datetime.datetime.utcnow()

            # Build the view title
            self._update_title(pr)

            # Metadata section
            self._update_metadata(pr)

            # PR description (markdown)
            self._update_description(pr)

            # Approvals table
            self._update_approvals(pr)

            # Commits section
            self._update_commits(pr)

            # Messages section
            self._update_messages(pr)

    def _update_title(self, pr):
        """Set the view title based on PR state."""
        parts = []
        if pr.starred:
            parts.append("* ")
        parts.append("Pull request %s" % pr.number)
        if pr.reviewed:
            parts.append(" (reviewed)")
        if pr.hidden:
            parts.append(" (hidden)")
        if pr.held:
            parts.append(" (held)")
        self.title = "".join(parts)
        if hasattr(self.app, "hubtty_header"):
            self.app.hubtty_header.set_title(self.title)

    def _update_metadata(self, pr):
        """Build the metadata section."""
        metadata = self.query_one("#pr-metadata", Static)

        text = Text()
        fields = [
            ("Author", pr.author_name),
            ("Repository", pr.repository.name),
            ("Branch", pr.branch or ""),
            ("Created", self._format_time(pr.created)),
            ("Updated", self._format_time(pr.updated)),
            ("Status", self._format_status(pr)),
            ("Permalink", pr.html_url),
        ]

        # Labels
        if pr.labels:
            label_names = ", ".join(l.name for l in pr.labels)
            fields.insert(3, ("Labels", label_names))

        for i, (label, value) in enumerate(fields):
            if i > 0:
                text.append("\n")
            label_text = "%-12s" % (label + ":")
            text.append(label_text, style=self._style("pr-header"))
            text.append(" ")
            text.append(str(value), style=self._style("pr-data"))

        metadata.update(text)

    def _format_time(self, dt):
        """Format a datetime for display."""
        if dt is None:
            return ""
        t = self.app.time(dt)
        return t.strftime("%Y-%m-%d %H:%M:%S")

    def _format_status(self, pr):
        """Format PR status string."""
        if pr.draft:
            return "Draft"
        if pr.merged:
            return "Merged"
        return pr.state.capitalize() if pr.state else ""

    def _update_description(self, pr):
        """Update the PR description markdown widget."""
        desc = self.query_one("#pr-description", Markdown)
        title_line = "## %s (#%s)\n\n" % (pr.title, pr.number)
        body = pr.body or ""
        desc.update(title_line + body)

    def _update_approvals(self, pr):
        """Build the approvals/review table."""
        approvals_widget = self.query_one("#pr-approvals", Static)

        if not pr.commits:
            approvals_widget.update("")
            return

        latest_sha = pr.commits[-1].sha

        # Collect approvals by reviewer
        reviewers = {}
        for approval in pr.approvals:
            reviewer_id = approval.reviewer.id
            if reviewer_id not in reviewers:
                is_own = self.app.isOwnAccount(approval.reviewer)
                name = (
                    approval.reviewer.name
                    or approval.reviewer.username
                    or approval.reviewer.email
                    or "Unknown"
                )
                reviewers[reviewer_id] = {
                    "name": name,
                    "is_own": is_own,
                    "state": "",
                    "sha": "",
                }
            reviewers[reviewer_id]["state"] = approval.state
            reviewers[reviewer_id]["sha"] = approval.sha

        if not reviewers:
            approvals_widget.update(Text("No reviews yet", style="dim"))
            return

        text = Text()
        # Header
        text.append(
            "%-20s  %s\n" % ("Reviewer", "Status"), style=self._style("table-header")
        )

        for reviewer in reviewers.values():
            name = reviewer["name"]
            name_style = self._style(
                "reviewer-own-name" if reviewer["is_own"] else "reviewer-name"
            )

            # Only show approval symbol for latest commit
            if reviewer["sha"] == latest_sha:
                state = reviewer["state"]
                symbol, style = self._approval_display(state)
            else:
                symbol = ""
                style = ""

            text.append("%-20s  " % name, style=name_style)
            if symbol:
                text.append(symbol, style=style)
            text.append("\n")

        approvals_widget.update(text)

    def _approval_display(self, state):
        """Return (symbol, rich_style) for an approval state."""
        if state in ("APPROVED", "APPROVE"):
            return ("✓ Approved", self._style("positive-label"))
        elif state in ("CHANGES_REQUESTED", "REQUEST_CHANGES"):
            return ("✗ Changes Requested", self._style("negative-label"))
        elif state in ("COMMENTED", "COMMENT"):
            return ("• Commented", "")
        elif state == "DISMISSED":
            return ("○ Dismissed", "dim")
        return ("", "")

    def _update_commits(self, pr):
        """Build the commits section."""
        commits_widget = self.query_one("#pr-commits-section", Static)

        if not pr.commits:
            commits_widget.update("No commits")
            return

        text = Text()
        text.append(
            "Commits (%d)\n" % len(pr.commits), style=self._style("table-header")
        )

        for commit in pr.commits:
            sha_short = commit.sha[:7]
            first_line = commit.message.split("\n")[0] if commit.message else ""

            text.append("\n")
            text.append(sha_short, style=self._style("commit-sha"))
            text.append(" ")
            text.append(first_line, style=self._style("commit-name"))

            # Show file summary if files are available
            if commit.files:
                total_added = sum(f.inserted or 0 for f in commit.files)
                total_removed = sum(f.deleted or 0 for f in commit.files)
                text.append("  ")
                text.append("+%d" % total_added, style=self._style("lines-added"))
                text.append(" ")
                text.append("-%d" % total_removed, style=self._style("lines-removed"))
                text.append(" (%d files)" % len(commit.files))

            # Show inline comment count
            total_comments = 0
            total_drafts = 0
            for f in commit.files:
                for c in f.comments:
                    if c.draft:
                        total_drafts += 1
                    else:
                        total_comments += 1
            if total_drafts:
                text.append(" ")
                text.append(
                    "(%d draft%s)" % (total_drafts, "s" if total_drafts != 1 else ""),
                    style=self._style("commit-drafts"),
                )
            if total_comments:
                text.append(" ")
                text.append(
                    "(%d comment%s)"
                    % (total_comments, "s" if total_comments != 1 else ""),
                    style=self._style("commit-comments"),
                )

        commits_widget.update(text)

    def _update_messages(self, pr):
        """Build the messages section with markdown-rendered bodies."""
        container = self.query_one("#pr-messages-container", Vertical)
        container.remove_children()

        if not pr.messages:
            container.mount(Static("No messages", classes="pr-messages-header"))
            return

        # Filter hidden comments if configured
        hide_comments = getattr(self.app.config, "hide_comments", [])

        widgets = []
        header = Text()
        header.append("Messages", style=self._style("table-header"))
        widgets.append(Static(header, classes="pr-messages-header"))

        first = True
        for message in pr.messages:
            # Skip hidden comments
            if hide_comments and message.author:
                username = message.author.username or ""
                skip = False
                for pattern in hide_comments:
                    if re.match(pattern, username):
                        skip = True
                        break
                if skip:
                    continue

            if not first:
                widgets.append(Rule())
            first = False

            # Author and timestamp header
            hdr = Text()
            author_name = "Unknown"
            is_own = False
            if message.author:
                author_name = (
                    message.author.name
                    or message.author.username
                    or message.author.email
                    or "Unknown"
                )
                is_own = self.app.isOwnAccount(message.author)

            name_style = self._style(
                "pr-message-own-name" if is_own else "pr-message-name"
            )
            header_style = self._style(
                "pr-message-own-header" if is_own else "pr-message-header"
            )

            hdr.append(author_name, style=name_style)
            if message.created:
                time_str = self._format_time(message.created)
                hdr.append(" (%s)" % time_str, style=header_style)
            if message.draft and not message.pending:
                hdr.append(" (draft)", style=self._style("pr-message-draft"))

            widgets.append(Static(hdr, classes="pr-message-header"))

            # Message body (rendered as markdown)
            if message.message:
                widgets.append(Markdown(message.message, classes="pr-message-body"))

            # Inline comments
            widgets.extend(self._build_inline_comment_widgets(message))

        container.mount_all(widgets)

    def _build_inline_comment_widgets(self, message):
        """Build widgets for inline comments on a message.

        Uses message.comments (the direct relationship) rather than
        walking message.commit.files, because inline comments may
        reference files from a different commit than the message's own.
        """
        if not message.comments:
            return []

        # Group comments by file path
        by_file = {}
        for comment in message.comments:
            f = comment.file
            path = f.display_path if hasattr(f, "display_path") else f.path
            path = path or "unknown"
            by_file.setdefault(path, []).append(comment)

        widgets = []
        for path, comments in by_file.items():
            file_label = Text()
            file_label.append(path, style=self._style("filename-inline-comment"))
            widgets.append(Static(file_label, classes="pr-inline-file"))

            for comment in sorted(comments, key=lambda c: c.line or 0):
                if not comment.message:
                    continue
                prefix = ""
                if comment.line:
                    prefix = "line %d" % comment.line
                # Render comment body as markdown; prepend line reference
                body = comment.message
                if prefix:
                    body = "**%s**\n%s" % (prefix, body)
                widgets.append(Markdown(body, classes="pr-inline-comment"))

        return widgets

    # ---- Command dispatch ----

    def handleCommand(self, command):
        """Handle a command dispatched from the app's keymap.

        Returns True if the command was handled, False otherwise.
        """
        if command == keymap.TOGGLE_REVIEWED:
            self._toggleReviewed()
            return True
        if command == keymap.TOGGLE_HIDDEN:
            self._toggleHidden()
            return True
        if command == keymap.TOGGLE_STARRED:
            self._toggleStarred()
            return True
        if command == keymap.TOGGLE_HELD:
            self._toggleHeld()
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
        return False

    def _pr_id(self):
        """Get the pr_id string for sync tasks."""
        with self.app.db.getSession() as session:
            pr = session.getPullRequest(self.pr_key)
            if pr:
                return pr.pr_id
        return None

    # ---- Toggle operations ----

    def _toggleReviewed(self):
        with self.app.db.getSession() as session:
            pr = session.getPullRequest(self.pr_key)
            if pr:
                pr.reviewed = not pr.reviewed
                self.app.repository_cache.clear(pr.repository)
        self.refresh_data()

    def _toggleHidden(self):
        with self.app.db.getSession() as session:
            pr = session.getPullRequest(self.pr_key)
            if pr:
                pr.hidden = not pr.hidden
        self.refresh_data()

    def _toggleStarred(self):
        with self.app.db.getSession() as session:
            pr = session.getPullRequest(self.pr_key)
            if pr:
                pr.starred = not pr.starred
        self.refresh_data()

    def _toggleHeld(self):
        self.app.toggleHeldPullRequest(self.pr_key)
        self.refresh_data()
