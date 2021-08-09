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

import six
import urwid

from hubtty import keymap
from hubtty import mywid
from hubtty import sync
from hubtty.view import change as view_change
from hubtty.view import mouse_scroll_decorator
import hubtty.view


class ColumnInfo(object):
    def __init__(self, name, packing, value):
        self.name = name
        self.packing = packing
        self.value = value
        self.options = (packing, value)
        if packing == 'given':
            self.spacing = value + 1
        else:
            self.spacing = (value * 8) + 1


COLUMNS = [
    ColumnInfo('Number',  'given',   6),
    ColumnInfo('Title',   'weight',  4),
    ColumnInfo('Project', 'weight',  1),
    ColumnInfo('Branch',  'weight',  1),
    ColumnInfo('Author',  'weight',  1),
    ColumnInfo('Updated', 'given',  10),
    ColumnInfo('Size',    'given',   4),
]


class ChangeListColumns(object):
    def updateColumns(self):
        del self.columns.contents[:]
        cols = self.columns.contents
        options = self.columns.options

        for colinfo in COLUMNS:
            if colinfo.name in self.enabled_columns:
                attr = colinfo.name.lower().replace(' ', '_')
                cols.append((getattr(self, attr),
                             options(*colinfo.options)))

        for c in self.category_columns:
            cols.append(c)


class ChangeRow(urwid.Button, ChangeListColumns):
    change_focus_map = {None: 'focused',
                        'unreviewed-change': 'focused-unreviewed-change',
                        'reviewed-change': 'focused-reviewed-change',
                        'starred-change': 'focused-starred-change',
                        'held-change': 'focused-held-change',
                        'marked-change': 'focused-marked-change',
                        'positive-label': 'focused-positive-label',
                        'negative-label': 'focused-negative-label',
                        'min-label': 'focused-min-label',
                        'max-label': 'focused-max-label',


                        'added-graph': 'focused-added-graph',
                        'removed-graph': 'focused-removed-graph',

                        'line-count-threshold-1': 'focused-line-count-threshold-1',
                        'line-count-threshold-2': 'focused-line-count-threshold-2',
                        'line-count-threshold-3': 'focused-line-count-threshold-3',
                        'line-count-threshold-4': 'focused-line-count-threshold-4',
                        'line-count-threshold-5': 'focused-line-count-threshold-5',
                        'line-count-threshold-6': 'focused-line-count-threshold-6',
                        'line-count-threshold-7': 'focused-line-count-threshold-7',
                        'line-count-threshold-8': 'focused-line-count-threshold-8',
                        }

    def selectable(self):
        return True

    def __init__(self, app, change, prefix, categories,
                 enabled_columns, callback=None):
        super(ChangeRow, self).__init__('', on_press=callback, user_data=change.key)
        self.app = app
        self.change_key = change.key
        self.prefix = prefix
        self.enabled_columns = enabled_columns
        self.title = mywid.SearchableText(u'', wrap='clip')
        self.number = mywid.SearchableText(u'')
        self.updated = mywid.SearchableText(u'')
        self.size = mywid.SearchableText(u'', align='right')
        self.project = mywid.SearchableText(u'', wrap='clip')
        self.author = mywid.SearchableText(u'', wrap='clip')
        self.branch = mywid.SearchableText(u'', wrap='clip')
        self.mark = False
        self.columns = urwid.Columns([], dividechars=1)
        self.row_style = urwid.AttrMap(self.columns, '')
        self._w = urwid.AttrMap(self.row_style, None, focus_map=self.change_focus_map)
        self.category_columns = []
        self.update(change, categories)

    def search(self, search, attribute):
        if self.title.search(search, attribute):
            return True
        if self.number.search(search, attribute):
            return True
        if self.project.search(search, attribute):
            return True
        if self.branch.search(search, attribute):
            return True
        if self.author.search(search, attribute):
            return True
        if self.updated.search(search, attribute):
            return True
        return False

    def _makeSizeGraph(self, added, removed):
        # Removed is a red graph on top, added is a green graph on bottom.
        #
        # The graph is 4 cells wide.  If both the red and green graphs
        # are in the cell, we set the bg to red, fg to green, and set
        # a box in the bottom half of the cell.
        #
        # If only one of the graphs is in the cell, we set a box in
        # either the top or bottom of the cell, and set the fg color
        # appropriately.  This is so that the reverse-video which
        # operates on the line when focused works as expected.

        lower_box = u'\u2584'
        upper_box = u'\u2580'
        ret = []
        # The graph is logarithmic -- one cell for each order of
        # magnitude.
        conf_thresholds = self.app.config.size_column['thresholds']
        # for threshold in [1, 10, 100, 1000]:
        for threshold in conf_thresholds:
            if (added > threshold and removed > threshold):
                ret.append(('added-removed-graph', lower_box))
            elif (added > threshold):
                ret.append(('added-graph', lower_box))
            elif (removed > threshold):
                ret.append(('removed-graph', upper_box))
            else:
                ret.append(' ')
        return ret

    def _makeSizeSplitGraph(self, added, removed):
        # Removed is a red graph on right, added is a green graph on left.
        # conf_thresholds[7]: Full block,
        # conf_thresholds[6]: Left seven eighths block,
        # ...., conf_thresholds[0]: Left one eighth block.
        # You can see the character table at the wikipedia[1] or somewhere.
        # [1] https://en.wikipedia.org/wiki/Block_Elements#Character_table
        conf_thresholds = self.app.config.size_column['thresholds']
        thresholds = [(conf_thresholds[7], u'\u2588'),
                      (conf_thresholds[6], u'\u2589'),
                      (conf_thresholds[5], u'\u258a'),
                      (conf_thresholds[4], u'\u258b'),
                      (conf_thresholds[3], u'\u258c'),
                      (conf_thresholds[2], u'\u258d'),
                      (conf_thresholds[1], u'\u258e'),
                      (conf_thresholds[0], u'\u258f')]
        ret = []
        # The graph is logarithmic -- one cell for each order of
        # magnitude.
        for diff in [[added, 'added-graph'], [removed, 'removed-graph']]:
            for threshold in thresholds:
                if (diff[0] == 0):
                    ret.append(' ')
                    break
                if (diff[0] >= threshold[0]):
                    ret.append((diff[1], threshold[1]))
                    break
            ret.append(' ')
        return ret

    def update(self, change, categories):
        if change.reviewed or change.hidden:
            style = 'reviewed-change'
        else:
            style = 'unreviewed-change'
        title = '%s%s' % (self.prefix, change.title)
        flag = ' '
        if change.starred:
            flag = '*'
            style = 'starred-change'
        if change.held:
            flag = '!'
            style = 'held-change'
        if self.mark:
            flag = '%'
            style = 'marked-change'
        title = flag + title
        self.row_style.set_attr_map({None: style})
        self.title.set_text(title)
        self.number.set_text(str(change.number))
        self.project.set_text(change.project.name.split('/')[-1])
        self.author.set_text(change.author_name)
        self.branch.set_text(change.branch or '')
        self.project_name = change.project.name
        self.commit_sha = change.commits[-1].sha
        self.current_commit_key = change.commits[-1].key
        today = self.app.time(datetime.datetime.utcnow()).date()
        updated_time = self.app.time(change.updated)
        if today == updated_time.date():
            self.updated.set_text(updated_time.strftime("%I:%M %p").upper())
        else:
            self.updated.set_text(updated_time.strftime("%Y-%m-%d"))
        total_added = change.additions
        total_removed = change.deletions
        if self.app.config.size_column['type'] == 'number':
            total_added_removed = total_added + total_removed
            thresholds = self.app.config.size_column['thresholds']
            size_style = 'line-count-threshold-1'
            if (total_added_removed >= thresholds[7]):
                size_style = 'line-count-threshold-8'
            elif (total_added_removed >= thresholds[6]):
                size_style = 'line-count-threshold-7'
            elif (total_added_removed >= thresholds[5]):
                size_style = 'line-count-threshold-6'
            elif (total_added_removed >= thresholds[4]):
                size_style = 'line-count-threshold-5'
            elif (total_added_removed >= thresholds[3]):
                size_style = 'line-count-threshold-4'
            elif (total_added_removed >= thresholds[2]):
                size_style = 'line-count-threshold-3'
            elif (total_added_removed >= thresholds[1]):
                size_style = 'line-count-threshold-2'
            elif (total_added_removed >= thresholds[0]):
                size_style = 'line-count-threshold-1'
            self.size.set_text((size_style, str(total_added_removed)))
        elif self.app.config.size_column['type'] == 'split-graph':
            self.size.set_text(self._makeSizeSplitGraph(total_added,
                                                          total_removed))
        else:
            self.size.set_text(self._makeSizeGraph(total_added, total_removed))

        self.category_columns = []
        for category in categories:
            v = ''
            val = ''
            if category == 'Code-Review':
                v = change.getReviewState()
            if v in ['APPROVED']:
                val = ('positive-label', ' ✓')
            elif v in ['CHANGES_REQUESTED']:
                val = ('negative-label', ' ✗')
            elif v in ['COMMENTED']:
                val = ' •'
            self.category_columns.append((urwid.Text(val),
                                          self.columns.options('given', 2)))
        self.updateColumns()

class ChangeListHeader(urwid.WidgetWrap, ChangeListColumns):
    def __init__(self, enabled_columns):
        self.enabled_columns = enabled_columns
        self.title = urwid.Text(u'Title', wrap='clip')
        self.number = urwid.Text(u'Number')
        self.updated = urwid.Text(u'Updated')
        self.size = urwid.Text(u'Size')
        self.project = urwid.Text(u'Project', wrap='clip')
        self.author = urwid.Text(u'Author', wrap='clip')
        self.branch = urwid.Text(u'Branch', wrap='clip')
        self.columns = urwid.Columns([], dividechars=1)
        self.category_columns = []
        super(ChangeListHeader, self).__init__(self.columns)

    def update(self, categories):
        self.category_columns = []
        for category in categories:
            self.category_columns.append((urwid.Text(' %s' % category[0]),
                                          self._w.options('given', 2)))
        self.updateColumns()


@mouse_scroll_decorator.ScrollByWheel
class ChangeListView(urwid.WidgetWrap, mywid.Searchable):
    required_columns = set(['Number', 'Title', 'Updated'])
    # FIXME(masayukig): Disable 'Size' column when configured
    optional_columns = set(['Branch', 'Size'])

    def getCommands(self):
        if self.project_key:
            refresh_help = "Sync current project"
        else:
            refresh_help = "Sync subscribed projects"
        return [
            (keymap.TOGGLE_HELD,
             "Toggle the held flag for the currently selected change"),
            (keymap.LOCAL_CHECKOUT,
             "Checkout the selected change into the local repo"),
            (keymap.TOGGLE_HIDDEN,
             "Toggle the hidden flag for the currently selected change"),
            (keymap.TOGGLE_LIST_REVIEWED,
             "Toggle whether only unreviewed or all changes are displayed"),
            (keymap.TOGGLE_REVIEWED,
             "Toggle the reviewed flag for the currently selected change"),
            (keymap.TOGGLE_STARRED,
             "Toggle the starred flag for the currently selected change"),
            (keymap.TOGGLE_MARK,
             "Toggle the process mark for the currently selected change"),
            (keymap.REFINE_CHANGE_SEARCH,
             "Refine the current search query"),
            (keymap.CLOSE_CHANGE,
             "Close the marked pull requests"),
            (keymap.REOPEN_CHANGE,
             "Reopen the marked pull requests"),
            (keymap.REFRESH,
             refresh_help),
            (keymap.REVIEW,
             "Leave reviews for the marked changes"),
            (keymap.SORT_BY_NUMBER,
             "Sort changes by number"),
            (keymap.SORT_BY_UPDATED,
             "Sort changes by how recently the change was updated"),
            (keymap.SORT_BY_REVERSE,
             "Reverse the sort"),
            (keymap.LOCAL_CHERRY_PICK,
             "Cherry-pick the most recent commit of the selected change onto the local repo"),
            (keymap.INTERACTIVE_SEARCH,
             "Interactive search"),
            ]

    def help(self):
        key = self.app.config.keymap.formatKeys
        commands = self.getCommands()
        return [(c[0], key(c[0]), c[1]) for c in commands]

    def __init__(self, app, query, query_desc=None, project_key=None,
                 unreviewed=False, sort_by=None, reverse=None):
        super(ChangeListView, self).__init__(urwid.Pile([]))
        self.log = logging.getLogger('hubtty.view.change_list')
        self.searchInit()
        self.app = app
        self.query = query
        self.query_desc = query_desc or query
        self.unreviewed = unreviewed
        self.change_rows = {}
        self.enabled_columns = set()
        for colinfo in COLUMNS:
            if (colinfo.name in self.required_columns or
                colinfo.name not in self.optional_columns):
                self.enabled_columns.add(colinfo.name)
        self.disabled_columns = set()
        self.listbox = urwid.ListBox(urwid.SimpleFocusListWalker([]))
        self.project_key = project_key
        if 'Project' not in self.required_columns and project_key is not None:
            self.enabled_columns.discard('Project')
            self.disabled_columns.add('Project')
        if 'Author' not in self.required_columns and 'author:' in query:
            # This could be or'd with something else, but probably
            # not.
            self.enabled_columns.discard('Author')
            self.disabled_columns.add('Author')
        if app.config.size_column['type'] == 'disabled':
            self.enabled_columns.discard('Size')
            self.disabled_columns.add('Size')
        self.sort_by = sort_by or app.config.change_list_options['sort-by']
        if reverse is not None:
            self.reverse = reverse
        else:
            self.reverse = app.config.change_list_options['reverse']
        self.header = ChangeListHeader(self.enabled_columns)
        self.categories = []
        self.refresh()
        self._w.contents.append((app.header, ('pack', 1)))
        self._w.contents.append((urwid.Divider(), ('pack', 1)))
        self._w.contents.append((urwid.AttrWrap(self.header, 'table-header'), ('pack', 1)))
        self._w.contents.append((self.listbox, ('weight', 1)))
        self._w.set_focus(3)

    def interested(self, event):
        if not ((self.project_key is not None and
                 isinstance(event, sync.ChangeAddedEvent) and
                 self.project_key == event.project_key)
                or
                (self.project_key is None and
                 isinstance(event, sync.ChangeAddedEvent))
                or
                (isinstance(event, sync.ChangeUpdatedEvent) and
                 event.change_key in self.change_rows.keys())):
            self.log.debug("Ignoring refresh change list due to event %s" % (event,))
            return False
        self.log.debug("Refreshing change list due to event %s" % (event,))
        return True

    def refresh(self):
        unseen_keys = set(self.change_rows.keys())
        with self.app.db.getSession() as session:
            change_list = session.getChanges(self.query, self.unreviewed,
                                             sort_by=self.sort_by)
            if self.unreviewed:
                self.title = (u'Unreviewed %d changes in %s' %
                    (len(change_list), self.query_desc))
            else:
                self.title = (u'All %d changes in %s' %
                    (len(change_list), self.query_desc))
            self.short_title = self.query_desc
            if '/' in self.short_title and ' ' not in self.short_title:
                i = self.short_title.rfind('/')
                self.short_title = self.short_title[i+1:]
            self.app.status.update(title=self.title)
            categories = ['Code-Review']
            self.categories = sorted(categories)
            self.chooseColumns()
            self.header.update(self.categories)
            i = 0
            if self.reverse:
                change_list.reverse()
            prefixes = {}
            new_rows = []
            if len(self.listbox.body):
                focus_pos = self.listbox.focus_position
                focus_row = self.listbox.body[focus_pos]
            else:
                focus_pos = 0
                focus_row = None
            for change in change_list:
                row = self.change_rows.get(change.key)
                if not row:
                    row = ChangeRow(self.app, change,
                                    prefixes.get(change.key, ''),
                                    self.categories,
                                    self.enabled_columns,
                                    callback=self.onSelect)
                    self.listbox.body.insert(i, row)
                    self.change_rows[change.key] = row
                else:
                    row.update(change, self.categories)
                    unseen_keys.remove(change.key)
                new_rows.append(row)
                i += 1
            self.listbox.body[:] = new_rows
            if focus_row in self.listbox.body:
                pos = self.listbox.body.index(focus_row)
            else:
                pos = min(focus_pos, len(self.listbox.body)-1)
            self.listbox.body.set_focus(pos)
        for key in unseen_keys:
            row = self.change_rows[key]
            del self.change_rows[key]

    def chooseColumns(self):
        currently_enabled_columns = self.enabled_columns.copy()
        size = self.app.loop.screen.get_cols_rows()
        cols = size[0]
        for colinfo in COLUMNS:
            if (colinfo.name not in self.disabled_columns):
                cols -= colinfo.spacing
        cols -= 3 * len(self.categories)

        for colinfo in COLUMNS:
            if colinfo.name in self.optional_columns:
                if cols >= colinfo.spacing:
                    self.enabled_columns.add(colinfo.name)
                    cols -= colinfo.spacing
                else:
                    self.enabled_columns.discard(colinfo.name)
        if currently_enabled_columns != self.enabled_columns:
            self.header.updateColumns()
            for key, value in six.iteritems(self.change_rows):
                value.updateColumns()

    def getQueryString(self):
        if self.project_key is not None:
            return "repo:%s %s" % (self.query_desc, self.app.config.project_change_list_query)
        return self.query

    def clearChangeList(self):
        for key, value in six.iteritems(self.change_rows):
            self.listbox.body.remove(value)
        self.change_rows = {}

    def getNextChangeKey(self, change_key):
        row = self.change_rows.get(change_key)
        try:
            i = self.listbox.body.index(row)
        except ValueError:
            return None
        if i+1 >= len(self.listbox.body):
            return None
        row = self.listbox.body[i+1]
        return row.change_key

    def getPrevChangeKey(self, change_key):
        row = self.change_rows.get(change_key)
        try:
            i = self.listbox.body.index(row)
        except ValueError:
            return None
        if i <= 0:
            return None
        row = self.listbox.body[i-1]
        return row.change_key

    def toggleReviewed(self, change_key):
        with self.app.db.getSession() as session:
            change = session.getChange(change_key)
            change.reviewed = not change.reviewed
            self.app.project_cache.clear(change.project)
            ret = change.reviewed
            reviewed_str = 'reviewed' if change.reviewed else 'unreviewed'
            self.log.debug("Set change %s to %s", change_key, reviewed_str)
        return ret

    def toggleStarred(self, change_key):
        with self.app.db.getSession() as session:
            change = session.getChange(change_key)
            change.starred = not change.starred
            ret = change.starred
            starred_str = 'starred' if change.starred else 'un-starred'
            self.log.debug("Set change %s to %s", change_key, starred_str)
        return ret

    def toggleHeld(self, change_key):
        return self.app.toggleHeldChange(change_key)

    def toggleHidden(self, change_key):
        with self.app.db.getSession() as session:
            change = session.getChange(change_key)
            change.hidden = not change.hidden
            ret = change.hidden
            hidden_str = 'hidden' if change.hidden else 'visible'
            self.log.debug("Set change %s to %s", change_key, hidden_str)
        return ret

    def advance(self):
        pos = self.listbox.focus_position
        if pos < len(self.listbox.body)-1:
            pos += 1
            self.listbox.focus_position = pos

    def keypress(self, size, key):
        if self.searchKeypress(size, key):
            return None

        if not self.app.input_buffer:
            key = super(ChangeListView, self).keypress(size, key)
        keys = self.app.input_buffer + [key]
        commands = self.app.config.keymap.getCommands(keys)
        ret = self.handleCommands(commands)
        if ret is True:
            if keymap.FURTHER_INPUT not in commands:
                self.app.clearInputBuffer()
            return None
        return key

    def onResize(self):
        self.chooseColumns()

    def handleCommands(self, commands):
        if keymap.TOGGLE_LIST_REVIEWED in commands:
            self.unreviewed = not self.unreviewed
            self.refresh()
            return True
        if keymap.TOGGLE_REVIEWED in commands:
            if not len(self.listbox.body):
                return True
            pos = self.listbox.focus_position
            change_key = self.listbox.body[pos].change_key
            reviewed = self.toggleReviewed(change_key)
            if self.unreviewed and reviewed:
                # Here we can avoid a full refresh by just removing the particular
                # row from the change list if the view is for the unreviewed changes
                # only.
                row = self.change_rows[change_key]
                self.listbox.body.remove(row)
                del self.change_rows[change_key]
            else:
                # Just fall back on doing a full refresh if we're in a situation
                # where we're not just popping a row from the list of unreviewed
                # changes.
                self.refresh()
                self.advance()
            return True
        if keymap.TOGGLE_HIDDEN in commands:
            if not len(self.listbox.body):
                return True
            pos = self.listbox.focus_position
            change_key = self.listbox.body[pos].change_key
            hidden = self.toggleHidden(change_key)
            if hidden:
                # Here we can avoid a full refresh by just removing the particular
                # row from the change list
                row = self.change_rows[change_key]
                self.listbox.body.remove(row)
                del self.change_rows[change_key]
            else:
                # Just fall back on doing a full refresh if we're in a situation
                # where we're not just popping a row from the list of changes.
                self.refresh()
                self.advance()
            return True
        if keymap.TOGGLE_HELD in commands:
            if not len(self.listbox.body):
                return True
            pos = self.listbox.focus_position
            change_key = self.listbox.body[pos].change_key
            self.toggleHeld(change_key)
            row = self.change_rows[change_key]
            with self.app.db.getSession() as session:
                change = session.getChange(change_key)
                row.update(change, self.categories)
            self.advance()
            return True
        if keymap.TOGGLE_STARRED in commands:
            if not len(self.listbox.body):
                return True
            pos = self.listbox.focus_position
            change_key = self.listbox.body[pos].change_key
            self.toggleStarred(change_key)
            row = self.change_rows[change_key]
            with self.app.db.getSession() as session:
                change = session.getChange(change_key)
                row.update(change, self.categories)
            self.advance()
            return True
        if keymap.TOGGLE_MARK in commands:
            if not len(self.listbox.body):
                return True
            pos = self.listbox.focus_position
            change_key = self.listbox.body[pos].change_key
            row = self.change_rows[change_key]
            row.mark = not row.mark
            with self.app.db.getSession() as session:
                change = session.getChange(change_key)
                row.update(change, self.categories)
            self.advance()
            return True
        if keymap.REFRESH in commands:
            if self.project_key:
                self.app.sync.submitTask(
                    sync.SyncProjectTask(self.project_key, sync.HIGH_PRIORITY))
            else:
                self.app.sync.submitTask(
                    sync.SyncSubscribedProjectsTask(sync.HIGH_PRIORITY))
            self.app.status.update()
            return True
        if keymap.REVIEW in commands:
            rows = [row for row in self.change_rows.values() if row.mark]
            if not rows:
                pos = self.listbox.focus_position
                rows = [self.listbox.body[pos]]
            self.openReview(rows)
            return True
        if keymap.SORT_BY_NUMBER in commands:
            if not len(self.listbox.body):
                return True
            self.sort_by = 'number'
            self.clearChangeList()
            self.refresh()
            return True
        if keymap.SORT_BY_UPDATED in commands:
            if not len(self.listbox.body):
                return True
            self.sort_by = 'updated'
            self.clearChangeList()
            self.refresh()
            return True
        if keymap.SORT_BY_REVERSE in commands:
            if not len(self.listbox.body):
                return True
            if self.reverse:
                self.reverse = False
            else:
                self.reverse = True
            self.clearChangeList()
            self.refresh()
            return True
        if keymap.LOCAL_CHECKOUT in commands:
            if not len(self.listbox.body):
                return True
            pos = self.listbox.focus_position
            row = self.listbox.body[pos]
            self.app.localCheckoutCommit(row.project_name, row.commit_sha)
            return True
        if keymap.LOCAL_CHERRY_PICK in commands:
            if not len(self.listbox.body):
                return True
            pos = self.listbox.focus_position
            row = self.listbox.body[pos]
            self.app.localCherryPickCommit(row.project_name, row.commit_sha)
            return True
        if keymap.REFINE_CHANGE_SEARCH in commands:
            default = self.getQueryString()
            self.app.searchDialog(default)
            return True
        if keymap.CLOSE_CHANGE in commands:
            self.closeChange()
            return True
        if keymap.REOPEN_CHANGE in commands:
            self.reopenChange()
            return True
        if keymap.INTERACTIVE_SEARCH in commands:
            self.searchStart()
            return True
        return False

    def onSelect(self, button, change_key):
        try:
            view = view_change.ChangeView(self.app, change_key)
            self.app.changeScreen(view)
        except hubtty.view.DisplayError as e:
            self.app.error(str(e))

    def openReview(self, rows):
        dialog = view_change.ReviewDialog(self.app, rows[0].current_commit_key)
        urwid.connect_signal(dialog, 'save',
            lambda button: self.closeReview(dialog, rows, True, False))
        urwid.connect_signal(dialog, 'merge',
            lambda button: self.closeReview(dialog, rows, True, True))
        urwid.connect_signal(dialog, 'cancel',
            lambda button: self.closeReview(dialog, rows, False, False))
        self.app.popup(dialog,
                       relative_width=50, relative_height=75,
                       min_width=60, min_height=20)

    def closeReview(self, dialog, rows, upload, merge):
        approval, message = dialog.getValues()
        # Ensure approval has the expected value for upload to github
        if approval == 'APPROVED':
            approval = 'APPROVE'
        elif approval == 'CHANGES_REQUESTED':
            approval = 'REQUEST_CHANGES'
        elif approval == 'COMMENTED':
            approval = 'COMMENT'
        commit_keys = [row.current_commit_key for row in rows]
        message_keys = self.app.saveReviews(commit_keys, approval,
                                            message, upload, merge)
        if upload:
            for message_key in message_keys:
                self.app.sync.submitTask(
                    sync.UploadReviewTask(message_key, sync.HIGH_PRIORITY))
        self.refresh()
        self.app.backScreen()

    def closeChange(self):
        dialog = mywid.TextEditDialog(u'Close pull request', u'Message:',
                                      u'Close pull request', u'')
        urwid.connect_signal(dialog, 'cancel', self.app.backScreen)
        urwid.connect_signal(dialog, 'save', lambda button:
                                 self.doCloseReopenChange(dialog, 'closed'))
        self.app.popup(dialog)

    def reopenChange(self):
        dialog = mywid.TextEditDialog(u'Reopen pull request', u'Message:',
                                      u'Reopen pull request', u'')
        urwid.connect_signal(dialog, 'cancel', self.app.backScreen)
        urwid.connect_signal(dialog, 'save', lambda button:
                             self.doCloseReopenChange(dialog, 'open'))
        self.app.popup(dialog)

    def doCloseReopenChange(self, dialog, state):
        rows = [row for row in self.change_rows.values() if row.mark]
        if not rows:
            pos = self.listbox.focus_position
            rows = [self.listbox.body[pos]]
        change_keys = [row.change_key for row in rows]
        with self.app.db.getSession() as session:
            for change_key in change_keys:
                change = session.getChange(change_key)
                change.state = state
                change.pending_edit = True
                change.pending_edit_message = dialog.entry.edit_text
                self.app.sync.submitTask(
                    sync.EditPullRequestTask(change_key, sync.HIGH_PRIORITY))
        self.app.backScreen()
        self.refresh()
