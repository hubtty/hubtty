# Copyright 2014 OpenStack Foundation
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

DEFAULT_PALETTE={
    'focused': ['default,standout', ''],
    'header': ['white,bold', 'dark blue'],
    'error': ['light red', 'dark blue'],
    'table-header': ['white,bold', ''],
    'filename': ['light cyan', ''],
    'filename-inline-comment': ['dark cyan', ''],
    'focused-filename': ['light cyan,standout', ''],
    'positive-label': ['dark green', ''],
    'negative-label': ['dark red', ''],
    'max-label': ['light green', ''],
    'min-label': ['light red', ''],
    'focused-positive-label': ['dark green,standout', ''],
    'focused-negative-label': ['dark red,standout', ''],
    'focused-max-label': ['light green,standout', ''],
    'focused-min-label': ['light red,standout', ''],
    'link': ['dark blue', ''],
    'focused-link': ['light blue', ''],
    'footer': ['light gray', 'dark gray'],
    # Diff
    'context-button': ['dark magenta', ''],
    'focused-context-button': ['light magenta', ''],
    'removed-line': ['default', 'dark red', '', 'default', '#402020'],
    'removed-word': ['white,bold', 'dark red', '', 'white,bold', '#742a2a'],
    'added-line': ['default', 'dark green', '', 'default', '#204020'],
    'added-word': ['white,bold', 'dark green', '', 'white,bold', '#2a742a'],
    'nonexistent': ['default', ''],
    'focused-removed-line': ['default,standout', 'dark red', '', 'default,standout', '#402020'],
    'focused-removed-word': ['white,bold,standout', 'dark red', '', 'white,bold,standout', '#742a2a'],
    'focused-added-line': ['default,standout', 'dark green', '', 'default,standout', '#204020'],
    'focused-added-word': ['white,bold,standout', 'dark green', '', 'white,bold,standout', '#2a742a'],
    'focused-nonexistent': ['default,standout', ''],
    'draft-comment': ['default', 'dark gray'],
    'comment': ['light gray', 'dark gray'],
    'comment-name': ['white', 'dark gray'],
    'line-number': ['dark gray', ''],
    'focused-line-number': ['dark gray,standout', ''],
    'search-result': ['default,standout', ''],
    'trailing-ws': ['light red,standout', ''],
    # Pull request view
    'pr-data': ['dark cyan', ''],
    'focused-pr-data': ['light cyan', ''],
    'pr-header': ['light blue', ''],
    'commit-name': ['light blue', ''],
    'commit-sha': ['dark blue', ''],
    'commit-comments': ['default', ''],
    'commit-drafts': ['dark red', ''],
    'focused-commit-name': ['light blue,standout', ''],
    'focused-commit-sha': ['dark blue,standout', ''],
    'focused-commit-comments': ['default,standout', ''],
    'focused-commit-drafts': ['dark red,standout', ''],
    'commit-button': ['dark magenta', ''],
    'focused-commit-button': ['light magenta', ''],
    'pr-message-name': ['yellow', ''],
    'pr-message-own-name': ['light cyan', ''],
    'pr-message-header': ['brown', ''],
    'pr-message-own-header': ['dark cyan', ''],
    'pr-message-draft': ['dark red', ''],
    'lines-added': ['light green', ''],
    'lines-removed': ['light red', ''],
    'reviewer-name': ['yellow', ''],
    'reviewer-own-name': ['light cyan', ''],
    'check-success': ['light green', ''],
    'check-failure': ['light red', ''],
    'check-pending': ['dark magenta', ''],
    'check-skipped': ['dark gray', ''],
    'check-cancelled': ['dark gray', ''],
    'state-draft': ['yellow', ''],
    # repository list
    'unreviewed-repository': ['white', ''],
    'subscribed-repository': ['default', ''],
    'unsubscribed-repository': ['dark gray', ''],
    'marked-repository': ['light cyan', ''],
    'focused-unreviewed-repository': ['white,standout', ''],
    'focused-subscribed-repository': ['default,standout', ''],
    'focused-unsubscribed-repository': ['dark gray,standout', ''],
    'focused-marked-repository': ['light cyan,standout', ''],
    # Pull request list
    'unreviewed-pr': ['default', ''],
    'reviewed-pr': ['dark gray', ''],
    'focused-unreviewed-pr': ['default,standout', ''],
    'focused-reviewed-pr': ['dark gray,standout', ''],
    'starred-pr': ['light cyan', ''],
    'focused-starred-pr': ['light cyan,standout', ''],
    'held-pr': ['light red', ''],
    'focused-held-pr': ['light red,standout', ''],
    'marked-pr': ['dark cyan', ''],
    'focused-marked-pr': ['dark cyan,standout', ''],
    'added-graph': ['dark green', ''],
    'removed-graph': ['dark red', ''],
    'added-removed-graph': ['dark green', 'dark red'],
    'focused-added-graph': ['default,standout', 'dark green'],
    'focused-removed-graph': ['default,standout', 'dark red'],
    'line-count-threshold-1': ['light green', ''],
    'focused-line-count-threshold-1': ['light green,standout', ''],
    'line-count-threshold-2': ['light cyan', ''],
    'focused-line-count-threshold-2': ['light cyan,standout', ''],
    'line-count-threshold-3': ['light blue', ''],
    'focused-line-count-threshold-3': ['light blue,standout', ''],
    'line-count-threshold-4': ['yellow', ''],
    'focused-line-count-threshold-4': ['yellow,standout', ''],
    'line-count-threshold-5': ['dark magenta', ''],
    'focused-line-count-threshold-5': ['dark magenta,standout', ''],
    'line-count-threshold-6': ['light magenta', ''],
    'focused-line-count-threshold-6': ['light magenta,standout', ''],
    'line-count-threshold-7': ['dark red', ''],
    'focused-line-count-threshold-7': ['dark red,standout', ''],
    'line-count-threshold-8': ['light red', ''],
    'focused-line-count-threshold-8': ['light red,standout', ''],
    # Markdown
    'md-strong': ['bold', ''],
    'md-emphasis': ['italics', ''],
    'md-heading': ['underline,bold', ''],
    'md-blockquote': ['light gray', ''],
    'md-blockcode': ['', 'dark gray'],
    'md-codespan': ['', 'dark gray'],
    'md-strikethrough': ['strikethrough', ''],
    'md-thematicbreak': ['light gray', ''],
    }

# A delta from the default palette
LIGHT_PALETTE = {
    'table-header': ['black,bold', ''],
    # Diff
    'removed-line': ['default', 'light red', '', 'default', '#e6c8c8'],
    'removed-word': ['black,bold', 'light red', '', 'black,bold', '#d0a0a0'],
    'added-line': ['default', 'light green', '', 'default', '#c8e6c8'],
    'added-word': ['black,bold', 'light green', '', 'black,bold', '#a0d0a0'],
    'focused-removed-line': ['default,standout', 'light red', '', 'default,standout', '#e6c8c8'],
    'focused-removed-word': ['black,bold,standout', 'light red', '', 'black,bold,standout', '#d0a0a0'],
    'focused-added-line': ['default,standout', 'light green', '', 'default,standout', '#c8e6c8'],
    'focused-added-word': ['black,bold,standout', 'light green', '', 'black,bold,standout', '#a0d0a0'],
    'unreviewed-repository': ['black', ''],
    'subscribed-repository': ['dark gray', ''],
    'unsubscribed-repository': ['dark gray', ''],
    'focused-unreviewed-repository': ['black,standout', ''],
    'focused-subscribed-repository': ['dark gray,standout', ''],
    'focused-unsubscribed-repository': ['dark gray,standout', ''],
    'pr-data': ['dark blue,bold', ''],
    'focused-pr-data': ['dark blue,standout', ''],
    'reviewer-name': ['brown', ''],
    'reviewer-own-name': ['dark blue,bold', ''],
    'pr-message-name': ['brown', ''],
    'pr-message-own-name': ['dark blue,bold', ''],
    'pr-message-header': ['black', ''],
    'pr-message-own-header': ['black,bold', ''],
    'focused-link': ['dark blue,bold', ''],
    'filename': ['dark cyan', ''],
    # Markdown
    'md-blockquote': ['dark gray', ''],
    'md-blockcode': ['', 'light gray'],
    'md-codespan': ['', 'light gray'],
    'md-thematicbreak': ['dark gray', ''],
    }

class Palette:
    def __init__(self, config, light=False):
        self.palette = {}
        self.palette.update(DEFAULT_PALETTE)
        # Syntax highlighting palette entries are generated from
        # hubtty.syntax so that colour definitions live in one place.
        # Imported here (rather than at module level) to avoid a
        # circular import and to ensure every Palette instance —
        # including light and custom palettes — gets the entries.
        from hubtty.syntax import build_syntax_palette, build_light_syntax_palette
        if light:
            self.palette.update(build_light_syntax_palette())
        else:
            self.palette.update(build_syntax_palette())
        self.update(config)

    def update(self, config):
        d = config.copy()
        if 'name' in d:
            del d['name']
        self.palette.update(d)

    def getPalette(self):
        ret = []
        for k,v in self.palette.items():
            ret.append(tuple([k]+v))
        return ret

    def getPaletteItem(self, name):
        return self.palette.get(name, ['',''])
