# Copyright The Hubtty Authors.
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

"""Tests for hubtty.mywid.GrowingEditBox and hubtty.mywid.FixedOverlay."""

import urwid

from hubtty import markdown
from hubtty import mywid


class FakeRing:
    def kill(self, text):
        pass

    def yank(self, repeat=False):
        return None


class FakeScreen:
    def __init__(self, cols=100, rows=40):
        self.cols = cols
        self.rows = rows

    def get_cols_rows(self):
        return (self.cols, self.rows)


class FakeApp:
    def __init__(self, cols=100, rows=40):
        self.loop = type('Loop', (), {'screen': FakeScreen(cols, rows)})()

    def openURL(self, url):
        pass


class StubRenderer:
    """A minimal stand-in for markdown.Renderer with a render(text)
    method, so GrowingEditBox doesn't need the real mistune-based
    parser for pure sizing/focus-switching tests."""

    def __init__(self, prefix='PREVIEW: '):
        self.prefix = prefix
        self.calls = 0

    def render(self, text):
        self.calls += 1
        return [(self.prefix + text)]


def make_edit(text=''):
    return mywid.MyEdit('Message: \n', edit_text=text, multiline=True,
                        ring=FakeRing())


class TestGrowingEditBoxSizing:
    def test_min_height_floor(self):
        app = FakeApp(cols=100, rows=40)
        edit = make_edit('')
        box = mywid.GrowingEditBox(app, edit, min_height=5)
        assert box.rows((60,), focus=True) == 5

    def test_grows_with_content_up_to_cap(self):
        app = FakeApp(cols=100, rows=40)
        edit = make_edit('\n'.join('line %d' % i for i in range(50)))
        box = mywid.GrowingEditBox(app, edit, min_height=5)
        # Capped at screen_rows - GROWING_EDIT_RESERVED_ROWS.
        expected_max = max(5, 40 - mywid.GROWING_EDIT_RESERVED_ROWS)
        assert box.rows((60,), focus=True) == expected_max

    def test_floors_to_min_height_on_tiny_screen(self):
        app = FakeApp(cols=100, rows=10)
        edit = make_edit('\n'.join('line %d' % i for i in range(50)))
        box = mywid.GrowingEditBox(app, edit, min_height=5)
        assert box.rows((60,), focus=True) == 5


class TestGrowingEditBoxPreview:
    def test_no_md_always_shows_edit_widget(self):
        app = FakeApp()
        edit = make_edit('hello')
        box = mywid.GrowingEditBox(app, edit)
        box.rows((60,), focus=False)
        assert box._w is box._edit_attrmap

    def test_unfocused_shows_rendered_preview(self):
        app = FakeApp()
        edit = make_edit('hello world')
        stub = StubRenderer()
        box = mywid.GrowingEditBox(app, edit, md=stub)

        box.rows((60,), focus=False)
        assert box._w is box._preview_attrmap
        assert stub.calls == 1

        box.rows((60,), focus=True)
        assert box._w is box._edit_attrmap

        box.rows((60,), focus=False)
        assert box._w is box._preview_attrmap

    def test_attr_and_focus_attr_override(self):
        app = FakeApp()
        edit = make_edit('hello')
        box = mywid.GrowingEditBox(app, edit, attr='draft-comment',
                                   focus_attr='draft-comment')
        assert box._edit_attrmap.get_attr_map() == {None: 'draft-comment'}


class TestGrowingEditBoxMarkdownLinks:
    """Regression test: the preview widget must be able to display
    markdown links (rendered as mywid.Link objects) without raising.
    A plain urwid.Text cannot hold a Link object in its markup."""

    def test_markdown_link_in_preview_does_not_raise(self):
        app = FakeApp()
        renderer = markdown.Renderer(app)
        edit = make_edit('See [the docs](https://example.com) for details')
        box = mywid.GrowingEditBox(app, edit, md=renderer)

        box.rows((60,), focus=False)

        flattened = box.preview_widget.get_text()[0]
        assert 'the docs' in flattened
        assert isinstance(box.preview_widget, mywid.HyperText)


class FakeRowsWidget(urwid.Text):
    """A minimal flow widget whose row count depends on width, like a
    wrapping text box: narrower widths need more rows."""

    def __init__(self, base_cols, base_rows):
        super().__init__('x')
        self.base_cols = base_cols
        self.base_rows = base_rows

    def rows(self, size, focus=False):
        (maxcol,) = size
        return max(1, (self.base_cols * self.base_rows + maxcol - 1) // maxcol)

    def render(self, size, focus=False):
        (maxcol,) = size
        return urwid.SolidCanvas(' ', maxcol, self.rows(size, focus))


class TestOverlayPackHeightSizing:
    """Regression coverage for a crash ('top canvas of overlay not the
    size expected') seen when opening the review dialog with a long
    draft message: urwid.Overlay used to measure a 'pack' height-type
    widget's needed rows using the full screen width, not the
    narrower width a relative (or min_width-clamped) overlay actually
    renders at, so width-sensitive content (e.g. a wrapping/growing
    text box) could be measured and rendered at different heights.

    This was urwid issue #471, fixed upstream in urwid 4.0.13 (PR
    #1250). hubtty requires urwid>=4.0.13 (see pyproject.toml) rather
    than working around it, but these tests guard against that
    minimum version silently regressing (e.g. an out-of-date lockfile
    or environment).
    """

    def test_does_not_crash(self):
        for screen_cols, screen_rows in (
            (160, 45), (180, 48), (199, 50), (220, 55),
        ):
            widget = FakeRowsWidget(base_cols=158, base_rows=20)
            pile = urwid.Pile([widget])
            dialog = urwid.LineBox(pile, 'Review')
            width = ('relative', 60)
            background = urwid.SolidFill(' ')
            overlay = urwid.Overlay(dialog, background, 'center', width,
                                    'middle', 'pack', min_width=60)

            size = (screen_cols, screen_rows)
            # Render twice, as urwid's main loop may redraw an
            # unchanged screen more than once (e.g. from its idle
            # callback).
            canvas1 = overlay.render(size, focus=True)
            canvas2 = overlay.render(size, focus=True)
            assert canvas1.rows() == screen_rows
            assert canvas2.rows() == screen_rows

    def test_adapts_to_growing_content(self):
        """'pack' height is re-measured on every render, so it must
        keep working as content grows interactively (not just at the
        moment the dialog is first shown)."""
        widget = FakeRowsWidget(base_cols=50, base_rows=3)
        pile = urwid.Pile([widget])
        dialog = urwid.LineBox(pile, 'Review')
        width = ('relative', 60)
        background = urwid.SolidFill(' ')
        overlay = urwid.Overlay(dialog, background, 'center', width,
                                'middle', 'pack', min_width=60)
        size = (160, 45)

        canvas1 = overlay.render(size, focus=True)
        assert canvas1.rows() == 45

        # Simulate the content growing substantially (e.g. a user
        # pasting a long comment into a GrowingEditBox).
        widget.base_rows = 20
        canvas2 = overlay.render(size, focus=True)
        assert canvas2.rows() == 45
