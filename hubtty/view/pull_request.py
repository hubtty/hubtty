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

import collections
import datetime
import logging
try:
    import ordereddict
except:
    pass
import textwrap

import urwid

from hubtty import gitrepo
from hubtty import keymap
from hubtty import mywid
from hubtty import sync
from hubtty.view import side_diff as view_side_diff
from hubtty.view import unified_diff as view_unified_diff
from hubtty.view import mouse_scroll_decorator
import hubtty.view

try:
    OrderedDict = collections.OrderedDict
except AttributeError:
    OrderedDict = ordereddict.OrderedDict

class EditLabelsDialog(urwid.WidgetWrap, mywid.LineBoxTitlePropertyMixin):
    signals = ['save', 'cancel']
    def __init__(self, app, pr):
        self.app = app
        save_button = mywid.FixedButton('Save')
        cancel_button = mywid.FixedButton('Cancel')
        urwid.connect_signal(save_button, 'click',
                             lambda button:self._emit('save'))
        urwid.connect_signal(cancel_button, 'click',
                             lambda button:self._emit('cancel'))

        button_widgets = [('pack', save_button),
                          ('pack', cancel_button)]
        button_columns = urwid.Columns(button_widgets, dividechars=2)
        rows = []
        self.labels_checkboxes = []

        rows.append(urwid.Text(u"Labels:"))
        for label in pr.repository.labels:
            b = mywid.FixedCheckBox(label.name, state=(label in pr.labels))
            rows.append(b)
            self.labels_checkboxes.append(b)
        rows.append(urwid.Divider())
        rows.append(button_columns)
        pile = urwid.Pile(rows)
        fill = urwid.Filler(pile, valign='top')
        super(EditLabelsDialog, self).__init__(urwid.LineBox(fill,
                                                             'Set pull request labels'))

class ReviewDialog(urwid.WidgetWrap, mywid.LineBoxTitlePropertyMixin):
    signals = ['merge', 'save', 'cancel']
    def __init__(self, app, commit_key, message=''):
        self.commit_key = commit_key
        self.app = app
        save_button = mywid.FixedButton(u'Save')
        merge_button = mywid.FixedButton(u'Save and Merge')
        cancel_button = mywid.FixedButton(u'Cancel')
        urwid.connect_signal(save_button, 'click',
            lambda button:self._emit('save'))
        urwid.connect_signal(merge_button, 'click',
            lambda button:self._emit('merge'))
        urwid.connect_signal(cancel_button, 'click',
            lambda button:self._emit('cancel'))

        rows = []
        review_states = {
            'REQUEST_CHANGES': 'Request Changes',
            'COMMENT': 'Comment',
            'APPROVE': 'Approve'
        }
        self.button_group = []
        with self.app.db.getSession() as session:
            commit = session.getCommit(self.commit_key)
            pr = commit.pull_request
            buttons = [('pack', save_button)]
            if commit.pull_request.canMerge():
                buttons.append(('pack', merge_button))
            buttons.append(('pack', cancel_button))
            buttons = urwid.Columns(buttons, dividechars=2)
            if commit == pr.commits[-1]:
                current = None
                for approval in pr.approvals:
                    if approval.sha != commit.sha:
                        continue
                    if self.app.isOwnAccount(approval.reviewer):
                        current = approval.state
                        if current == 'APPROVED':
                            current = 'APPROVE'
                        elif current == 'CHANGES_REQUESTED':
                            current = 'REQUEST_CHANGES'
                        elif current == 'COMMENTED':
                            current = 'COMMENT'
                        break
                if current is None or current == '':
                    current = 'COMMENT'

                rows.append(urwid.Text('Review changes:'))
                for state in review_states:
                    b = urwid.RadioButton(self.button_group, review_states[state], state=(state == current))
                    b._value = state
                    if state == 'APPROVE':
                        b = urwid.AttrMap(b, 'positive-label')
                    elif state == 'REQUEST_CHANGES':
                        b = urwid.AttrMap(b, 'negative-label')
                    rows.append(b)
                rows.append(urwid.Divider())
            m = commit.getDraftMessage()
            if m:
                if message:
                    message = message + "\n" + m.message
                else:
                    message = m.message
        self.message = mywid.MyEdit(u"Message: \n", edit_text=message,
                                    multiline=True, ring=app.ring)
        rows.append(self.message)
        rows.append(urwid.Divider())
        rows.append(buttons)
        pile = urwid.Pile(rows)
        fill = urwid.Filler(pile, valign='top')
        super(ReviewDialog, self).__init__(urwid.LineBox(fill, 'Review'))

    def getValues(self):
        approval = ''
        for button in self.button_group:
            if button.state:
                approval = button._value
        message = self.message.edit_text.strip()
        return (approval, message)

    def keypress(self, size, key):
        if not self.app.input_buffer:
            key = super(ReviewDialog, self).keypress(size, key)
        keys = self.app.input_buffer + [key]
        commands = self.app.config.keymap.getCommands(keys)
        if keymap.PREV_SCREEN in commands:
            self._emit('cancel')
            return None
        return key

class MergeDialog(urwid.WidgetWrap, mywid.LineBoxTitlePropertyMixin):
    signals = ['merge', 'cancel']
    def __init__(self, app, pr, title='', message=''):
        self.app = app
        merge_button = mywid.FixedButton(u'Merge')
        cancel_button = mywid.FixedButton(u'Cancel')
        urwid.connect_signal(merge_button, 'click',
            lambda button:self._emit('merge'))
        urwid.connect_signal(cancel_button, 'click',
            lambda button:self._emit('cancel'))

        rows = []
        merge_method = {
            'merge': 'Create a merge commit',
            'squash': 'Squash and merge',
            'rebase': 'Rebase and merge'
        }
        self.button_group = []
        buttons = []
        if pr.canMerge():
            buttons.append(('pack', merge_button))
        buttons.append(('pack', cancel_button))
        buttons = urwid.Columns(buttons, dividechars=2)
        default = 'merge'
        rows.append(urwid.Text('Merge method:'))
        for method in merge_method:
            b = urwid.RadioButton(self.button_group, merge_method[method], state=(method == default))
            b._value = method
            rows.append(b)
        rows.append(urwid.Divider())
        self.commit_title = mywid.MyEdit(u"Commit title (Optional): \n", edit_text=title,
                                    multiline=False, ring=app.ring)
        rows.append(self.commit_title)
        self.commit_message = mywid.MyEdit(u"Commit message (Optional): \n", edit_text=message,
                                    multiline=True, ring=app.ring)
        rows.append(self.commit_message)
        rows.append(urwid.Divider())
        rows.append(buttons)
        pile = urwid.Pile(rows)
        fill = urwid.Filler(pile, valign='top')
        super(MergeDialog, self).__init__(urwid.LineBox(fill, 'Merge pull request'))

    def getValues(self):
        strategy = ''
        for button in self.button_group:
            if button.state:
                strategy = button._value
        title = self.commit_title.edit_text.strip()
        if title == '':
            title = None
        message = self.commit_message.edit_text.strip()
        if message == '':
            message = None
        return (strategy, title, message)

    def keypress(self, size, key):
        if not self.app.input_buffer:
            key = super(MergeDialog, self).keypress(size, key)
        keys = self.app.input_buffer + [key]
        commands = self.app.config.keymap.getCommands(keys)
        if keymap.PREV_SCREEN in commands:
            self._emit('cancel')
            return None
        return key

class EditPullRequestDialog(urwid.WidgetWrap, mywid.LineBoxTitlePropertyMixin):
    signals = ['save', 'cancel']
    def __init__(self, app, pr):
        self.app = app
        save_button = mywid.FixedButton(u'Save')
        cancel_button = mywid.FixedButton(u'Cancel')
        urwid.connect_signal(save_button, 'click',
            lambda button:self._emit('save'))
        urwid.connect_signal(cancel_button, 'click',
            lambda button:self._emit('cancel'))

        button_widgets = [('pack', save_button),
                          ('pack', cancel_button)]
        button_columns = urwid.Columns(button_widgets, dividechars=2)
        rows = []

        self.pr_title = mywid.MyEdit(edit_text=pr.title, multiline=False,
                ring=app.ring)
        rows.append(urwid.Text(u"Title:"))
        rows.append(self.pr_title)
        rows.append(urwid.Divider())
        self.pr_description = mywid.MyEdit(edit_text=pr.body,
                multiline=True, ring=app.ring)
        rows.append(urwid.Text(u"Description:"))
        rows.append(self.pr_description)
        rows.append(urwid.Divider())
        rows.append(button_columns)
        pile = urwid.Pile(rows)
        fill = urwid.Filler(pile, valign='top')
        super(EditPullRequestDialog, self).__init__(urwid.LineBox(fill, 'Edit Pull Request'))

class ReviewButton(mywid.FixedButton):
    def __init__(self, commit_row):
        super(ReviewButton, self).__init__(('commit-button', u'Review'))
        self.commit_row = commit_row
        self.pr_view = commit_row.pr_view
        urwid.connect_signal(self, 'click',
            lambda button: self.openReview())

    def openReview(self, message=''):
        self.dialog = ReviewDialog(self.pr_view.app,
                                   self.commit_row.commit_key,
                                   message=message)
        urwid.connect_signal(self.dialog, 'save',
            lambda button: self.closeReview(upload=True, merge=False))
        urwid.connect_signal(self.dialog, 'merge',
            lambda button: self.closeReview(upload=True, merge=True))
        urwid.connect_signal(self.dialog, 'cancel',
            lambda button: self.closeReview(upload=False, merge=False))
        self.pr_view.app.popup(self.dialog,
                               relative_width=50, relative_height=75,
                               min_width=60, min_height=20)

    def closeReview(self, upload=False, merge=False):
        approval, message = self.dialog.getValues()
        self.pr_view.saveReview(self.commit_row.commit_key, approval,
                                    message, upload, False)
        self.pr_view.app.backScreen()
        if merge:
            self.pr_view.mergePullRequest()

class CommitRow(urwid.WidgetWrap):
    commit_focus_map = {
                          'commit-name': 'focused-commit-name',
                          'commit-sha': 'focused-commit-sha',
                          'commit-comments': 'focused-commit-comments',
                          'commit-drafts': 'focused-commit-drafts',
                          }

    def __init__(self, app, pr_view, repo, commit, expanded=False):
        super(CommitRow, self).__init__(urwid.Pile([]))
        self.app = app
        self.pr_view = pr_view
        self.commit_key = commit.key
        self.repository_name = commit.pull_request.repository.name
        self.commit_sha = commit.sha
        self.can_merge = commit.pull_request.canMerge()
        self.title = mywid.TextButton(u'', on_press = self.expandContract)
        table = mywid.Table(columns=3)
        total_added = 0
        total_removed = 0
        for rfile in commit.files:
            if rfile.status is None:
                continue
            added = rfile.inserted or 0
            removed = rfile.deleted or 0
            total_added += added
            total_removed += removed
            table.addRow([urwid.Text(('filename', rfile.display_path), wrap='clip'),
                          urwid.Text([('lines-added', '+%i' % (added,)), ', '],
                                     align=urwid.RIGHT),
                          urwid.Text(('lines-removed', '-%i' % (removed,)))])
        table.addRow([urwid.Text(''),
                      urwid.Text([('lines-added', '+%i' % (total_added,)), ', '],
                                 align=urwid.RIGHT),
                      urwid.Text(('lines-removed', '-%i' % (total_removed,)))])
        table = urwid.Padding(table, width='pack')

        focus_map={'commit-button': 'focused-commit-button'}
        self.review_button = ReviewButton(self)
        buttons = [mywid.FixedButton(('commit-button', "Diff"),
                                     on_press=self.diff),
                   mywid.FixedButton(('commit-button', "Local Checkout"),
                                     on_press=self.checkout),
                   mywid.FixedButton(('commit-button', "Local Cherry-Pick"),
                                     on_press=self.cherryPick)]

        buttons = [('pack', urwid.AttrMap(b, None, focus_map=focus_map)) for b in buttons]
        buttons = urwid.Columns(buttons + [urwid.Text('')], dividechars=2)
        buttons = urwid.AttrMap(buttons, 'commit-button')
        self.more = urwid.Pile([table, buttons])
        padded_title = urwid.Padding(self.title, width='pack')
        self.pile = urwid.Pile([padded_title])
        self._w = urwid.AttrMap(self.pile, None, focus_map=self.commit_focus_map)
        self.expanded = False
        self.update(commit)
        if expanded:
            self.expandContract(None)

    def update(self, commit):
        line = [('commit-sha', commit.sha[0:7]),
                ('commit-name', ' %s' % commit.message.split('\n')[0])]
        num_drafts = sum([len(f.draft_comments) for f in commit.files])
        if num_drafts:
            if not commit.pull_request.hasPendingMessage():
                line.append(('commit-drafts', ' (%s draft%s)' % (
                            num_drafts, num_drafts>1 and 's' or '')))
        num_comments = sum([len(f.current_comments) for f in commit.files]) - num_drafts
        if num_comments:
            line.append(('commit-comments', ' (%s inline comment%s)' % (
                        num_comments, num_comments>1 and 's' or '')))
        self.title.text.set_text(line)

    def expandContract(self, button):
        if self.expanded:
            self.pile.contents.pop()
            self.expanded = False
        else:
            self.pile.contents.append((self.more, ('pack', None)))
            self.expanded = True

    def diff(self, button):
        self.pr_view.diff(self.commit_key)

    def checkout(self, button):
        self.app.localCheckoutCommit(self.repository_name, self.commit_sha)

    def cherryPick(self, button):
        self.app.localCherryPickCommit(self.repository_name, self.commit_sha)

class PullRequestButton(urwid.Button):
    button_left = urwid.Text(u' ')
    button_right = urwid.Text(u' ')

    def __init__(self, pr_view, pr_key, text):
        super(PullRequestButton, self).__init__('')
        self.set_label(text)
        self.pr_view = pr_view
        self.pr_key = pr_key
        urwid.connect_signal(self, 'click',
            lambda button: self.openPullRequest())

    def set_label(self, text):
        super(PullRequestButton, self).set_label(text)

    def openPullRequest(self):
        try:
            self.pr_view.app.changeScreen(PullRequestView(self.pr_view.app, self.pr_key))
        except hubtty.view.DisplayError as e:
            self.pr_view.app.error(e.message)

class PullRequestMessageBox(mywid.HyperText):
    def __init__(self, pr_view, pr, message):
        super(PullRequestMessageBox, self).__init__(u'')
        self.pr_view = pr_view
        self.app = pr_view.app
        self.refresh(pr, message)

    def formatReply(self):
        text = self.message_text
        pgraphs = []
        pgraph_accumulator = []
        wrap = True
        for line in text.split('\n'):
            if line.startswith('> '):
                wrap = False
                line = '> ' + line
            if not line:
                if pgraph_accumulator:
                    pgraphs.append((wrap, '\n'.join(pgraph_accumulator)))
                    pgraph_accumulator = []
                    wrap = True
                continue
            pgraph_accumulator.append(line)
        if pgraph_accumulator:
            pgraphs.append((wrap, '\n'.join(pgraph_accumulator)))
            pgraph_accumulator = []
            wrap = True
        wrapper = textwrap.TextWrapper(initial_indent='> ',
                                       subsequent_indent='> ')
        wrapped_pgraphs = []
        for wrap, pgraph in pgraphs:
            if wrap:
                wrapped_pgraphs.append('\n'.join(wrapper.wrap(pgraph)))
            else:
                wrapped_pgraphs.append(pgraph)
        return '\n>\n'.join(wrapped_pgraphs)

    def reply(self):
        reply_text = self.formatReply()
        if reply_text:
            reply_text = self.message_author + ' wrote:\n\n' + reply_text + '\n'
        row = self.pr_view.commit_rows[self.commit_key]
        row.review_button.openReview(reply_text)

    def refresh(self, pr, message):
        self.commit_key = self.pr_view.last_commit_key
        self.message_created = message.created
        self.message_author = message.author_name
        self.message_text = message.message
        created = self.app.time(message.created)
        lines = message.message.split('\n')
        if self.app.isOwnAccount(message.author):
            name_style = 'pr-message-own-name'
            header_style = 'pr-message-own-header'
            reviewer_string = message.author_name
        else:
            name_style = 'pr-message-name'
            header_style = 'pr-message-header'
            if message.author.email:
                reviewer_string = "%s <%s>" % (
                    message.author_name,
                    message.author.email)
            else:
                reviewer_string = message.author_name

        text = [(name_style, reviewer_string),
                (header_style,
                 created.strftime(' (%Y-%m-%d %H:%M:%S%z)'))]
        if message.draft and not message.pending:
            text.append(('pr-message-draft', ' (draft)'))
        else:
            link = mywid.Link('< Reply >',
                              'commit-button',
                              'focused-commit-button')
            urwid.connect_signal(link, 'selected',
                                 lambda link:self.reply())
            text.append(' ')
            text.append(link)

        if lines and lines[-1]:
            lines.insert(0, '')
            lines.append('')
        comment_text = ['\n'.join(lines)]
        for commentlink in self.app.config.commentlinks:
            comment_text = commentlink.run(self.app, comment_text)

        inline_comments = {}
        for comment in message.comments:
            path = comment.file.path
            inline_comments.setdefault(path, [])
            inline_comments[path].append((comment.original_commit_id[0:7], comment.original_line or 0, comment.message))
        for v in inline_comments.values():
            v.sort()

        if inline_comments:
            comment_text.append(u'\n')
        for key, value in inline_comments.items():
            comment_text.append(('filename-inline-comment', u'%s' % key))
            for sha, line, comment in value:
                location_str = ''
                if sha:
                    location_str += sha
                    if line: location_str += ", "
                if line:
                    location_str += str(line)
                if location_str:
                    location_str += ": "
                comment_text.append(u'\n  %s%s\n' % (location_str, comment))

        self.set_text(text+comment_text)

class PrDescriptionBox(mywid.HyperText):
    def __init__(self, app, message):
        self.app = app
        super(PrDescriptionBox, self).__init__(message)

    def set_text(self, text):
        text = [text]
        for commentlink in self.app.config.commentlinks:
            text = commentlink.run(self.app, text)
        super(PrDescriptionBox, self).set_text(text)

@mouse_scroll_decorator.ScrollByWheel
class PullRequestView(urwid.WidgetWrap):
    def getCommands(self):
        return [
            (keymap.LOCAL_CHECKOUT,
             "Checkout the pull request into the local repo"),
            (keymap.DIFF,
             "Show the diff of the first commit"),
            (keymap.TOGGLE_HIDDEN,
             "Toggle the hidden flag for the current pull request"),
            (keymap.NEXT_PR,
             "Go to the next pull request in the list"),
            (keymap.PREV_PR,
             "Go to the previous pull request in the list"),
            (keymap.REVIEW,
             "Leave a review for the pull request"),
            (keymap.TOGGLE_HELD,
             "Toggle the held flag for the current pull request"),
            (keymap.TOGGLE_HIDDEN_COMMENTS,
             "Toggle display of hidden comments"),
            (keymap.SEARCH_RESULTS,
             "Back to the list of pull requests"),
            (keymap.TOGGLE_REVIEWED,
             "Toggle the reviewed flag for the current pull request"),
            (keymap.TOGGLE_STARRED,
             "Toggle the starred flag for the current pull request"),
            (keymap.LOCAL_CHERRY_PICK,
             "Cherry-pick the most recent commit onto the local repo"),
            (keymap.CLOSE_PR,
             "Close this pull request"),
            (keymap.EDIT_PULL_REQUEST,
             "Edit the commit message of this pull request"),
            (keymap.REBASE_PR,
             "Rebase this pull request (remotely)"),
            (keymap.REOPEN_PR,
             "Reopen pull request"),
            (keymap.REFRESH,
             "Refresh this pull request"),
            (keymap.EDIT_LABELS,
             "Edit the labels of this pull request"),
            (keymap.MERGE_PR,
             "Merge this pull request"),
            ]

    def help(self):
        key = self.app.config.keymap.formatKeys
        commands = self.getCommands()
        ret = [(c[0], key(c[0]), c[1]) for c in commands]
        for k in self.app.config.reviewkeys.values():
            if k.get('description'):
                action = k['description']
            else:
                action = k['approval']
                if k.get('message'):
                    action = action + ": " + k.get('message')
            ret.append(('', keymap.formatKey(k['key']), action))
        return ret

    def __init__(self, app, pr_key):
        super(PullRequestView, self).__init__(urwid.Pile([]))
        self.log = logging.getLogger('hubtty.view.pull_request')
        self.app = app
        self.pr_key = pr_key
        self.commit_rows = {}
        self.message_rows = {}
        self.first_commit_key = None
        self.last_commit_key = None
        self.hide_comments = True
        self.marked_seen = False
        self.author_label = mywid.TextButton(u'', on_press=self.searchAuthor)
        self.repository_label = mywid.TextButton(u'', on_press=self.searchRepository)
        self.branch_label = urwid.Text(u'', wrap='clip')
        self.labels_label = mywid.HyperText(u'')
        self.created_label = urwid.Text(u'', wrap='clip')
        self.updated_label = urwid.Text(u'', wrap='clip')
        self.status_label = urwid.Text(u'', wrap='clip')
        self.permalink_label = mywid.TextButton(u'', on_press=self.openPermalink)
        pr_info = []
        pr_info_map={'pr-data': 'focused-pr-data'}
        for l, v in [("Author", urwid.Padding(urwid.AttrMap(self.author_label, None,
                                                           focus_map=pr_info_map),
                                             width='pack')),
                     ("Repository", urwid.Padding(urwid.AttrMap(self.repository_label, None,
                                                           focus_map=pr_info_map),
                                             width='pack')),
                     ("Branch", self.branch_label),
                     ("Labels", self.labels_label),
                     ("Created", self.created_label),
                     ("Updated", self.updated_label),
                     ("Status", self.status_label),
                     ("Permalink", urwid.Padding(urwid.AttrMap(self.permalink_label, None,
                                                               focus_map=pr_info_map),
                                                 width='pack')),
                     ]:
            row = urwid.Columns([(12, urwid.Text(('pr-header', l), wrap='clip')), v])
            pr_info.append(row)
        pr_info = urwid.Pile(pr_info)
        self.pr_description = PrDescriptionBox(app, u'')
        votes = mywid.Table([])
        self.depends_on = urwid.Pile([])
        self.depends_on_rows = {}
        self.needed_by = urwid.Pile([])
        self.needed_by_rows = {}
        self.related_prs = urwid.Pile([self.depends_on, self.needed_by])
        self.results = mywid.HyperText(u'') # because it scrolls better than a table
        self.grid = mywid.MyGridFlow([pr_info, self.pr_description, votes, self.results],
                                     cell_width=80, h_sep=2, v_sep=1, align='left')
        self.listbox = urwid.ListBox(urwid.SimpleFocusListWalker([]))
        self._w.contents.append((self.app.header, ('pack', 1)))
        self._w.contents.append((urwid.Divider(), ('pack', 1)))
        self._w.contents.append((self.listbox, ('weight', 1)))
        self._w.set_focus(2)

        self.listbox.body.append(self.grid)
        self.listbox.body.append(urwid.Divider())
        self.listbox.body.append(self.related_prs)
        self.listbox.body.append(urwid.Divider())
        self.listbox_patchset_start = len(self.listbox.body)

        self.checkGitRepo()
        self.refresh()
        self.listbox.set_focus(0)
        self.grid.set_focus(1)

    def checkGitRepo(self):
        missing_commits = set()
        pr_number = None
        pr_id = None
        shas = set()
        with self.app.db.getSession() as session:
            pr = session.getPullRequest(self.pr_key)
            pr_repository_name = pr.repository.name
            pr_number = pr.number
            pr_id = pr.pr_id
            for commit in pr.commits:
                shas.add(commit.parent)
                shas.add(commit.sha)
        repo = gitrepo.get_repo(pr_repository_name, self.app.config)
        missing_commits = repo.checkCommits(shas)
        if missing_commits:
            if self.app.sync.offline:
                raise hubtty.view.DisplayError("Git commits not present in local repository")
            self.app.log.warning("Missing some commits for pull request %s %s",
                pr_number, missing_commits)
            task = sync.SyncPullRequestTask(pr_id, force_fetch=True,
                                       priority=sync.HIGH_PRIORITY)
            self.app.sync.submitTask(task)
            succeeded = task.wait(300)
            if not succeeded:
                raise hubtty.view.DisplayError("Git commits not present in local repository")

    def interested(self, event):
        if not ((isinstance(event, sync.PullRequestAddedEvent) and
                 self.pr_key in event.related_pr_keys)
                or
                (isinstance(event, sync.PullRequestUpdatedEvent) and
                 self.pr_key in event.related_pr_keys)):
            self.log.debug("Ignoring refresh pull request due to event %s" % (event,))
            return False
        self.log.debug("Refreshing pull request due to event %s" % (event,))
        return True

    def refresh(self):
        with self.app.db.getSession() as session:
            pr = session.getPullRequest(self.pr_key, lazy=False)
            # When we first open the pr, update its last_seen time.
            if not self.marked_seen:
                pr.last_seen = datetime.datetime.utcnow()
                self.marked_seen = True
            self.pending_edit_message = pr.pending_edit_message or ''
            reviewed = hidden = starred = held = ''
            if pr.reviewed:
                reviewed = ' (reviewed)'
            if pr.hidden:
                hidden = ' (hidden)'
            if pr.starred:
                starred = '* '
            if pr.held:
                held = ' (held)'
            self.title = '%sPull request %s%s%s%s' % (starred, pr.number, reviewed,
                                                hidden, held)
            self.app.status.update(title=self.title)
            self.repository_key = pr.repository.key
            self.repository_name = pr.repository.name
            self.pr_rest_id = pr.pr_id
            if pr.author:
                self.author_login = pr.author.username
            else:
                self.author_login = None

            if pr.author.email:
                author_string = '%s <%s>' % (pr.author_name,
                                             pr.author.email)
            else:
                author_string = pr.author_name
            self.author_label.text.set_text(('pr-data', author_string))
            self.repository_label.text.set_text(('pr-data', pr.repository.name))
            self.branch_label.set_text(('pr-data', pr.branch))
            label_buttons = []
            for x in pr.labels:
                if label_buttons:
                    label_buttons.append(', ')
                link = mywid.Link(x.name, 'pr-data', 'focused-pr-data')
                urwid.connect_signal(
                    link, 'selected',
                    lambda link, x=x: self.searchLabel(x.name))
                label_buttons.append(link)
            self.labels_label.set_text(('pr-data', label_buttons or u''))
            self.created_label.set_text(('pr-data', str(self.app.time(pr.created))))
            self.updated_label.set_text(('pr-data', str(self.app.time(pr.updated))))
            self.status_label.set_text(('pr-data', pr.state))
            self.permalink_url = str(pr.html_url)
            self.permalink_label.text.set_text(('pr-data', self.permalink_url))
            self.pr_description.set_text('\n'.join([pr.title, '', pr.body]))

            review_states = ['Changes Requested', 'Comment', 'Approved']
            approval_headers = [urwid.Text(('table-header', 'Name'))]
            for state in review_states:
                approval_headers.append(urwid.Text(('table-header', state)))
            votes = mywid.Table(approval_headers)
            approvals_for_account = {}
            pending_message = pr.hasPendingMessage()
            for approval in pr.approvals:
                approvals = approvals_for_account.get(approval.reviewer.id)
                if not approvals:
                    approvals = {}
                    row = []
                    if self.app.isOwnAccount(approval.reviewer):
                        style = 'reviewer-own-name'
                    else:
                        style = 'reviewer-name'
                    row.append(urwid.Text((style, approval.reviewer_name)))
                    for i, state in enumerate(review_states):
                        w = urwid.Text(u'', align=urwid.CENTER)
                        approvals[state] = w
                        row.append(w)
                    approvals_for_account[approval.reviewer.id] = approvals
                    votes.addRow(row)
                # Only set approval status if the review is for the current commit
                if approval.sha == pr.commits[-1].sha:
                    if approval.state in ['APPROVED', 'APPROVE']:
                        text = '✓'
                        if approval.state == 'APPROVE' and not pending_message:
                            text = '(' + text + ')'
                        approvals['Approved'].set_text(('positive-label', text))
                    elif approval.state in ['CHANGES_REQUESTED', 'REQUEST_CHANGES']:
                        text = '✗'
                        if approval.state == 'REQUEST_CHANGES' and not pending_message:
                            text = '(' + text + ')'
                        approvals['Changes Requested'].set_text(('negative-label', text))
                    else:
                        text = '•'
                        if approval.state == 'COMMENT' and not pending_message:
                            text = '(' + text + ')'
                        approvals['Comment'].set_text(text)
            votes = urwid.Padding(votes, width='pack')

            # TODO: update the existing table rather than replacing it
            # wholesale.  It will become more important if the table
            # gets selectable items (like clickable names).
            self.grid.contents[2] = (votes, ('given', 80))

            # self.refreshDependencies(session, pr)

            repo = gitrepo.get_repo(pr.repository.name, self.app.config)
            # The listbox has both commits and messages in it (and
            # may later contain the vote table and pull request header), so
            # keep track of the index separate from the loop.
            listbox_index = self.listbox_patchset_start
            self.first_commit_key = pr.commits[0].key
            for commit in pr.commits:
                self.last_commit_key = commit.key
                row = self.commit_rows.get(commit.key)
                if not row:
                    row = CommitRow(self.app, self, repo, commit)
                    self.listbox.body.insert(listbox_index, row)
                    self.commit_rows[commit.key] = row
                row.update(commit)
                # Revisions are extremely unlikely to be deleted, skip
                # that case.
                listbox_index += 1
            if len(self.listbox.body) == listbox_index:
                self.listbox.body.insert(listbox_index, urwid.Divider())
            listbox_index += 1
            # Get the set of messages that should be displayed
            display_messages = []
            result_systems = {}
            for message in pr.messages:
                if (message.commit == pr.commits[-1] and
                    message.author and message.author.name):
                    for commentlink in self.app.config.commentlinks:
                        results = commentlink.getTestResults(self.app, message.message)
                        if results:
                            result_system = result_systems.get(message.author.name,
                                                               OrderedDict())
                            result_systems[message.author.name] = result_system
                            result_system.update(results)
                skip = False
                if self.hide_comments and message.author and message.author.username:
                    for regex in self.app.config.hide_comments:
                        if regex.match(message.author.username):
                            skip = True
                            break
                if not skip:
                    display_messages.append(message)
            # The set of message keys currently displayed
            unseen_keys = set(self.message_rows.keys())
            # Make sure all of the messages that should be displayed are
            for message in display_messages:
                row = self.message_rows.get(message.key)
                if not row:
                    box = PullRequestMessageBox(self, pr, message)
                    row = urwid.Padding(box, width=80)
                    self.listbox.body.insert(listbox_index, row)
                    self.message_rows[message.key] = row
                else:
                    unseen_keys.remove(message.key)
                    if message.draft or message.created != row.original_widget.message_created:
                        row.original_widget.refresh(pr, message)
                listbox_index += 1
            # Remove any messages that should not be displayed
            for key in unseen_keys:
                row = self.message_rows.get(key)
                self.listbox.body.remove(row)
                del self.message_rows[key]
                listbox_index -= 1
            self._updateTestResults(pr, result_systems)

    def _add_link(self, name, url):
        link = mywid.Link('{:<40}'.format(name[:38] + (name[38:] and '…')), 'link', 'focused-link')
        if url:
            urwid.connect_signal(link, 'selected', lambda link:self.app.openURL(url))
        return link

    def _updateTestResults(self, pr, result_systems):
        text = []
        for system, results in result_systems.items():
            for job, result in results.items():
                text.append(result)

        # Add check results
        commit = pr.commits[-1]
        for check in commit.checks:
            if not (check.url or check.message):
                continue
            # link check name/url, color result, in time
            color = 'check-%s' % check.state
            result = (color, check.message[:39] + (check.message[39:] and '…'))
            line = [self._add_link(check.name, check.url), result]
            if check.finished and check.started:
                line.append(' in %s' % (check.finished-check.started))
            line.append('\n')
            text.append(line)

        if text:
            self.results.set_text(text)
        else:
            self.results.set_text('')

    def _updateDependenciesWidget(self, prs, widget, widget_rows, header):
        if not prs:
            if len(widget.contents) > 0:
                widget.contents[:] = []
            return

        if len(widget.contents) == 0:
            widget.contents.append((urwid.Text(('table-header', header)),
                                    widget.options()))

        unseen_keys = set(widget_rows.keys())
        i = 1
        for key, title in prs.items():
            row = widget_rows.get(key)
            if not row:
                row = urwid.AttrMap(urwid.Padding(PullRequestButton(self, key, title), width='pack'),
                                    'link', focus_map={None: 'focused-link'})
                row = (row, widget.options('pack'))
                widget.contents.insert(i, row)
                if not widget.selectable():
                    widget.set_focus(i)
                if not self.related_prs.selectable():
                    self.related_prs.set_focus(widget)
                widget_rows[key] = row
            else:
                row[0].original_widget.original_widget.set_label(title)
                unseen_keys.remove(key)
            i += 1
        for key in unseen_keys:
            row = widget_rows[key]
            widget.contents.remove(row)
            del widget_rows[key]

    def refreshDependencies(self, session, pr):
        commit = pr.commits[-1]

        # Handle depends-on
        parents = {}
        parent = pr.getCommitBySha(commit.parent)
        if parent:
            title = parent.pull_request.title
            show_merged = False
            if parent != parent.pull_request.commits[-1]:
                title += ' [OUTDATED]'
                show_merged = True
            if parent.pull_request.state == 'closed' and not parent.pull_request.merged:
                title += ' [CLOSED]'
            if show_merged or parent.pull_request.merged:
                parents[parent.pull_request.key] = title
        self._updateDependenciesWidget(parents,
                                       self.depends_on, self.depends_on_rows,
                                       header='Depends on:')

        # Handle needed-by
        children = {}
        children.update((r.pull_request.key, r.pull_request.title)
                        for r in session.getCommitsByParent([commit.sha for commit in pr.commits])
                        if (r.pull_request.state == 'open' and r == r.pull_request.commits[-1]))
        self._updateDependenciesWidget(children,
                                       self.needed_by, self.needed_by_rows,
                                       header='Needed by:')


    def toggleReviewed(self):
        with self.app.db.getSession() as session:
            pr = session.getPullRequest(self.pr_key)
            pr.reviewed = not pr.reviewed
            self.app.repository_cache.clear(pr.repository)

    def toggleHidden(self):
        with self.app.db.getSession() as session:
            pr = session.getPullRequest(self.pr_key)
            pr.hidden = not pr.hidden
            self.app.repository_cache.clear(pr.repository)

    def toggleStarred(self):
        with self.app.db.getSession() as session:
            pr = session.getPullRequest(self.pr_key)
            pr.starred = not pr.starred
            self.app.repository_cache.clear(pr.repository)

    def toggleHeld(self):
        return self.app.toggleHeldPullRequest(self.pr_key)

    def keypress(self, size, key):
        if not self.app.input_buffer:
            key = super(PullRequestView, self).keypress(size, key)
        keys = self.app.input_buffer + [key]
        commands = self.app.config.keymap.getCommands(keys)
        if keymap.TOGGLE_REVIEWED in commands:
            self.toggleReviewed()
            self.refresh()
            return None
        if keymap.TOGGLE_HIDDEN in commands:
            self.toggleHidden()
            self.refresh()
            return None
        if keymap.TOGGLE_STARRED in commands:
            self.toggleStarred()
            self.refresh()
            return None
        if keymap.TOGGLE_HELD in commands:
            self.toggleHeld()
            self.refresh()
            return None
        if keymap.REVIEW in commands:
            row = self.commit_rows[self.last_commit_key]
            row.review_button.openReview()
            return None
        if keymap.DIFF in commands:
            row = self.commit_rows[self.first_commit_key]
            row.diff(None)
            return None
        if keymap.LOCAL_CHECKOUT in commands:
            row = self.commit_rows[self.last_commit_key]
            row.checkout(None)
            return None
        if keymap.LOCAL_CHERRY_PICK in commands:
            row = self.commit_rows[self.last_commit_key]
            row.cherryPick(None)
            return None
        if keymap.SEARCH_RESULTS in commands:
            widget = self.app.findPullRequestList()
            if widget:
                self.app.backScreen(widget)
            return None
        if ((keymap.NEXT_PR in commands) or
            (keymap.PREV_PR in commands)):
            widget = self.app.findPullRequestList()
            if widget:
                if keymap.NEXT_PR in commands:
                    new_pr_key = widget.getNextPullRequestKey(self.pr_key)
                else:
                    new_pr_key = widget.getPrevPullRequestKey(self.pr_key)
                if new_pr_key:
                    try:
                        view = PullRequestView(self.app, new_pr_key)
                        self.app.changeScreen(view, push=False)
                    except hubtty.view.DisplayError as e:
                        self.app.error(e.message)
            return None
        if keymap.TOGGLE_HIDDEN_COMMENTS in commands:
            self.hide_comments = not self.hide_comments
            self.refresh()
            return None
        if keymap.CLOSE_PR in commands:
            self.closePullRequest()
            return None
        if keymap.EDIT_PULL_REQUEST in commands:
            self.editPullRequest()
            return None
        if keymap.REBASE_PR in commands:
            self.rebasePullRequest()
            return None
        if keymap.REOPEN_PR in commands:
            self.reopenPullRequest()
            return None
        if keymap.REFRESH in commands:
            self.app.sync.submitTask(
                sync.SyncPullRequestTask(self.pr_rest_id, priority=sync.HIGH_PRIORITY))
            self.app.status.update()
            return None
        if keymap.MERGE_PR in commands:
            self.mergePullRequest()
            return None
        if keymap.EDIT_LABELS in commands:
            self.editLabels()
            return None
        if key in self.app.config.reviewkeys:
            self.reviewKey(self.app.config.reviewkeys[key])
            return None
        return key

    def diff(self, commit_key):
        if self.app.config.diff_view == 'unified':
            screen = view_unified_diff.UnifiedDiffView(self.app, commit_key)
        else:
            screen = view_side_diff.SideDiffView(self.app, commit_key)
        self.app.changeScreen(screen)

    def closePullRequest(self):
        dialog = mywid.TextEditDialog(u'Close pull request', u'Message:',
                                      u'Close pull request',
                                      self.pending_edit_message)
        urwid.connect_signal(dialog, 'cancel', lambda button: self.app.backScreen())
        urwid.connect_signal(dialog, 'save', lambda button:
                                 self.doCloseReopenPullRequest(dialog, 'closed'))
        self.app.popup(dialog)

    def reopenPullRequest(self):
        dialog = mywid.TextEditDialog(u'Reopen pull request', u'Message:',
                                      u'Reopen pull request',
                                      self.pending_edit_message)
        urwid.connect_signal(dialog, 'cancel', lambda button: self.app.backScreen())
        urwid.connect_signal(dialog, 'save', lambda button:
                                 self.doCloseReopenPullRequest(dialog, 'open'))
        self.app.popup(dialog)

    def doCloseReopenPullRequest(self, dialog, state):
        pr_key = None
        with self.app.db.getSession() as session:
            pr = session.getPullRequest(self.pr_key)
            pr.state = state
            pr.pending_edit = True
            pr.pending_edit_message = dialog.entry.edit_text
            pr_key = pr.key
        self.app.sync.submitTask(
            sync.EditPullRequestTask(pr_key, sync.HIGH_PRIORITY))
        self.app.backScreen()
        self.refresh()

    def editPullRequest(self):
        with self.app.db.getSession() as session:
            pr = session.getPullRequest(self.pr_key)
            dialog = EditPullRequestDialog(self.app, pr)
        urwid.connect_signal(dialog, 'cancel',
                    lambda button: self.app.backScreen())
        urwid.connect_signal(dialog, 'save', lambda button:
                                 self.doEditPullRequest(dialog))
        self.app.popup(dialog,
                       relative_width=50, relative_height=75,
                       min_width=60, min_height=20)

    def doEditPullRequest(self, dialog):
        pr_key = None
        with self.app.db.getSession() as session:
            pr = session.getPullRequest(self.pr_key)
            pr.title = dialog.pr_title.edit_text
            pr.body = dialog.pr_description.edit_text
            pr.pending_edit = True
            pr_key = pr.key
        self.app.sync.submitTask(
            sync.EditPullRequestTask(pr_key, sync.HIGH_PRIORITY))
        self.app.backScreen()
        self.refresh()

    def rebasePullRequest(self):
        dialog = mywid.YesNoDialog(u'Rebase pull request',
                                   u'Perform a remote rebase of this pull request?')
        urwid.connect_signal(dialog, 'no', self.app.backScreen)
        urwid.connect_signal(dialog, 'yes', self.doRebasePullRequest)
        self.app.popup(dialog)

    def doRebasePullRequest(self, button=None):
        pr_key = None
        with self.app.db.getSession() as session:
            pr = session.getPullRequest(self.pr_key)
            pr.pending_rebase = True
            pr_key = pr.key
        self.app.sync.submitTask(
            sync.RebasePullRequestTask(pr_key, sync.HIGH_PRIORITY))
        self.app.backScreen()
        self.refresh()

    def mergePullRequest(self):
        with self.app.db.getSession() as session:
            pr = session.getPullRequest(self.pr_key)
            dialog = MergeDialog(self.app, pr)
        urwid.connect_signal(dialog, 'cancel',
                    lambda button: self.app.backScreen())
        urwid.connect_signal(dialog, 'merge', lambda button:
                                 self.doMergePullRequest(dialog))
        self.app.popup(dialog,
                       relative_width=50, relative_height=75,
                       min_width=60, min_height=20)

    def doMergePullRequest(self, dialog):
        pending_merge = None

        strategy, title, message = dialog.getValues()

        with self.app.db.getSession() as session:
            pr = session.getPullRequest(self.pr_key)

            if not pr.canMerge():
                error_dialog = mywid.MessageDialog('Error', 'You cannot merge this pull request.')
                urwid.connect_signal(error_dialog, 'close',
                    lambda button: self.app.backScreen())
                self.app.popup(error_dialog)
                return

            sha = pr.commits[-1].sha
            pending_merge = pr.createPendingMerge(sha, strategy,
                    commit_title=title, commit_message=message)

        if pending_merge:
            self.app.sync.submitTask(
                    sync.SendMergeTask(pending_merge.key, sync.HIGH_PRIORITY))

        self.app.backScreen()
        self.refresh()

    def editLabels(self):
        with self.app.db.getSession() as session:
            pr = session.getPullRequest(self.pr_key)
            dialog = EditLabelsDialog(self.app, pr)
        urwid.connect_signal(dialog, 'save',
            lambda button: self.closeEditLabels(dialog, True))
        urwid.connect_signal(dialog, 'cancel',
            lambda button: self.closeEditLabels(dialog, False))
        self.app.popup(dialog)

    def closeEditLabels(self, dialog, save):
        if save:
            pr_key = None
            labels_to_set = [ cb.label for cb in dialog.labels_checkboxes if cb.state ]
            with self.app.db.getSession() as session:
                pr = session.getPullRequest(self.pr_key)
                for label in pr.repository.labels:
                    if label.name in labels_to_set and label not in pr.labels:
                        pr.addLabel(label)
                    if label.name not in labels_to_set and label in pr.labels:
                        pr.removeLabel(label)
                pr.pending_labels = True
                pr_key = pr.key
            self.app.sync.submitTask(
                sync.SetLabelsTask(pr_key, sync.HIGH_PRIORITY))
        self.app.backScreen()
        self.refresh()

    def openPermalink(self, widget):
        self.app.openURL(self.permalink_url)

    def searchAuthor(self, widget):
        if self.author_login:
            self.app.doSearch("state:open author:%s" % (self.author_login,))

    def searchRepository(self, widget):
        self.app.doSearch("state:open repo:%s" % (self.repository_name,))

    def searchLabel(self, name):
        self.app.doSearch("state:open repo:%s label:%s" % (self.repository_name, name,))

    def reviewKey(self, reviewkey):
        approval = reviewkey.get('approval', 'COMMENT')
        self.app.log.debug("Reviewkey %s with approval %s" %
                           (reviewkey['key'], approval))
        row = self.commit_rows[self.last_commit_key]
        message = reviewkey.get('message', '')
        merge = reviewkey.get('merge', False)
        upload = not reviewkey.get('draft', False)
        self.saveReview(row.commit_key, approval, message, upload, merge)

    def saveReview(self, commit_key, approval, message, upload, merge):
        message_keys = self.app.saveReviews([commit_key], approval,
                                            message, upload, merge)
        if upload:
            for message_key in message_keys:
                self.app.sync.submitTask(
                    sync.UploadReviewTask(message_key, sync.HIGH_PRIORITY))
        self.refresh()
        if self.app.config.close_pr_on_review:
            self.app.backScreen()
