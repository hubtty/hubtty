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

"""Tests for the markdown renderer and related helpers."""

from unittest.mock import Mock

import urwid

from hubtty.markdown import Renderer
from hubtty import mywid
from hubtty.view.pull_request import PullRequestMessageBox


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_app():
    app = Mock()
    app.openURL = Mock()
    app.config.syntax_highlighting = True
    app.config.max_highlight_size = 512 * 1024
    return app


def _flatten(markup):
    """Recursively flatten urwid markup into a plain string."""
    if isinstance(markup, str):
        return markup
    if isinstance(markup, mywid.Link):
        return markup.text
    if isinstance(markup, tuple):
        return _flatten(markup[1])
    if isinstance(markup, list):
        return ''.join(_flatten(item) for item in markup)
    return ''


def _find_attr(markup, attr):
    """Return all plain-text fragments wrapped with *attr*."""
    results = []
    if isinstance(markup, tuple):
        if markup[0] == attr:
            results.append(_flatten(markup[1]))
        else:
            results.extend(_find_attr(markup[1], attr))
    elif isinstance(markup, list):
        for item in markup:
            results.extend(_find_attr(item, attr))
    return results


# ---------------------------------------------------------------------------
# _extract_summary
# ---------------------------------------------------------------------------

class TestExtractSummary:
    def test_basic(self):
        html = '<details>\n<summary>Walkthrough</summary>\n'
        assert Renderer._extract_summary(html) == 'Walkthrough'

    def test_with_emoji(self):
        html = '<details>\n<summary>📝 Walkthrough</summary>\n'
        assert Renderer._extract_summary(html) == '📝 Walkthrough'

    def test_strips_inner_html(self):
        html = '<details>\n<summary><b>Bold Title</b></summary>\n'
        assert Renderer._extract_summary(html) == 'Bold Title'

    def test_no_summary_tag(self):
        html = '<details>\n'
        assert Renderer._extract_summary(html) == 'Details'

    def test_empty_summary(self):
        html = '<details>\n<summary></summary>\n'
        assert Renderer._extract_summary(html) == 'Details'

    def test_case_insensitive(self):
        html = '<DETAILS>\n<SUMMARY>Title</SUMMARY>\n'
        assert Renderer._extract_summary(html) == 'Title'

    def test_multiline_summary(self):
        html = '<details>\n<summary>\n  Multiline\n</summary>\n'
        assert Renderer._extract_summary(html) == 'Multiline'


# ---------------------------------------------------------------------------
# _plain_text_len
# ---------------------------------------------------------------------------

class TestPlainTextLen:
    def test_string(self):
        assert Renderer._plain_text_len('hello') == 5

    def test_empty(self):
        assert Renderer._plain_text_len('') == 0

    def test_tuple(self):
        assert Renderer._plain_text_len(('attr', 'hello')) == 5

    def test_list(self):
        assert Renderer._plain_text_len(['ab', 'cd']) == 4

    def test_nested(self):
        markup = ('bold', [('inner', 'abc'), 'de'])
        assert Renderer._plain_text_len(markup) == 5

    def test_link(self):
        link = mywid.Link('click me', 'link', 'focused-link')
        assert Renderer._plain_text_len(link) == 8


# ---------------------------------------------------------------------------
# render — basic markdown
# ---------------------------------------------------------------------------

class TestRenderBasic:
    def setup_method(self):
        self.r = Renderer(_mock_app())

    def test_empty(self):
        assert self.r.render('') == []
        assert self.r.render(None) == []

    def test_plain_text(self):
        result = self.r.render('Hello world')
        flat = _flatten(result)
        assert 'Hello world' in flat

    def test_heading(self):
        result = self.r.render('## Heading')
        attrs = _find_attr(result, 'md-heading')
        assert any('Heading' in a for a in attrs)

    def test_bold(self):
        result = self.r.render('Some **bold** text')
        attrs = _find_attr(result, 'md-strong')
        assert any('bold' in a for a in attrs)

    def test_emphasis(self):
        result = self.r.render('Some *italic* text')
        attrs = _find_attr(result, 'md-emphasis')
        assert any('italic' in a for a in attrs)

    def test_code_block(self):
        result = self.r.render('```\ncode here\n```')
        attrs = _find_attr(result, 'md-blockcode')
        assert any('code here' in a for a in attrs)

    def test_code_block_with_lang(self):
        result = self.r.render('```python\nprint(1)\n```')
        # Fence markers stay in the plain 'md-blockcode' style.
        attrs = _find_attr(result, 'md-blockcode')
        joined = ''.join(attrs)
        assert 'python' in joined
        # The code itself is syntax-highlighted rather than wrapped
        # in 'md-blockcode', but the text is still present.
        assert 'print(1)' in _flatten(result)
        assert any('print' in a for a in _find_attr(result, 'syn-builtin'))
        assert any('1' in a for a in _find_attr(result, 'syn-number'))

    def test_code_block_with_unknown_lang(self):
        result = self.r.render('```not-a-real-language\nsome text\n```')
        # Falls back to the plain, fully-highlighted block.
        attrs = _find_attr(result, 'md-blockcode')
        joined = ''.join(attrs)
        assert 'not-a-real-language' in joined
        assert 'some text' in joined

    def test_code_block_highlighting_disabled(self):
        self.r.app.config.syntax_highlighting = False
        result = self.r.render('```python\nprint(1)\n```')
        attrs = _find_attr(result, 'md-blockcode')
        joined = ''.join(attrs)
        assert 'python' in joined
        assert 'print(1)' in joined
        assert _find_attr(result, 'syn-builtin') == []

    def test_inline_code(self):
        result = self.r.render('Use `foo()` here')
        attrs = _find_attr(result, 'md-codespan')
        assert any('foo()' in a for a in attrs)

    def test_unordered_list(self):
        result = self.r.render('- item1\n- item2')
        flat = _flatten(result)
        assert 'item1' in flat
        assert 'item2' in flat
        # Styled bullet character
        bullets = _find_attr(result, 'md-list-bullet')
        assert any('\u2022' in b for b in bullets)

    def test_unordered_list_nested(self):
        result = self.r.render('- outer\n  - inner')
        flat = _flatten(result)
        assert 'outer' in flat
        assert 'inner' in flat
        bullets = _find_attr(result, 'md-list-bullet')
        assert any('\u2022' in b for b in bullets)  # outer
        assert any('\u25e6' in b for b in bullets)  # inner

    def test_ordered_list(self):
        result = self.r.render('1. first\n2. second')
        flat = _flatten(result)
        assert 'first' in flat
        assert 'second' in flat
        nums = _find_attr(result, 'md-list-bullet')
        assert any('1.' in n for n in nums)
        assert any('2.' in n for n in nums)

    def test_task_list_unchecked(self):
        result = self.r.render('- [ ] todo')
        flat = _flatten(result)
        assert 'todo' in flat
        cb = _find_attr(result, 'md-checkbox')
        assert any('\u2610' in c for c in cb)

    def test_task_list_checked(self):
        result = self.r.render('- [x] done')
        flat = _flatten(result)
        assert 'done' in flat
        cb = _find_attr(result, 'md-checkbox')
        assert any('\u2611' in c for c in cb)

    def test_link(self):
        result = self.r.render('[click](https://example.com)')
        links = [item for item in result if isinstance(item, mywid.Link)]
        assert len(links) == 1
        assert links[0].text == 'click'

    def test_blockquote(self):
        result = self.r.render('> quoted text')
        attrs = _find_attr(result, 'md-blockquote')
        assert any('quoted' in a for a in attrs)

    def test_blockquote_multiline_prefix(self):
        """Each line in a multi-paragraph blockquote gets '│ ' prefix."""
        md = '> para one\n>\n> para two\n'
        result = self.r.render(md)
        flat = _flatten(result)
        # Count '│ ' occurrences — at least one per paragraph.
        assert flat.count('│ ') >= 2
        assert 'para one' in flat
        assert 'para two' in flat

    def test_blockquote_heading_then_paragraph(self):
        md = '> ## Title\n>\n> Body text\n'
        result = self.r.render(md)
        flat = _flatten(result)
        assert flat.count('│ ') >= 2
        assert 'Title' in flat
        assert 'Body text' in flat

    def test_blockquote_nested(self):
        """Nested blockquotes get '| | ' on each line."""
        md = '> > inner quote\n'
        result = self.r.render(md)
        flat = _flatten(result)
        assert '│ │ ' in flat
        assert 'inner quote' in flat

    def test_blockquote_with_list(self):
        md = '> - item1\n> - item2\n'
        result = self.r.render(md)
        flat = _flatten(result)
        assert 'item1' in flat
        assert 'item2' in flat
        assert flat.startswith('│ ')

    def test_strikethrough(self):
        result = self.r.render('~~removed~~')
        attrs = _find_attr(result, 'md-strikethrough')
        assert any('removed' in a for a in attrs)

    def test_br_tag(self):
        result = self.r.render('line1<br>line2')
        flat = _flatten(result)
        assert 'line1' in flat
        assert 'line2' in flat
        assert '\n' in flat

    def test_html_comment_dropped(self):
        result = self.r.render('before\n\n<!-- comment -->\n\nafter')
        flat = _flatten(result)
        assert 'before' in flat
        assert 'after' in flat
        assert 'comment' not in flat


# ---------------------------------------------------------------------------
# render — tables
# ---------------------------------------------------------------------------

class TestRenderTable:
    def setup_method(self):
        self.r = Renderer(_mock_app())

    def test_simple_table(self):
        md = '| A | B |\n|---|---|\n| 1 | 2 |'
        result = self.r.render(md)
        flat = _flatten(result)
        assert 'A' in flat
        assert 'B' in flat
        assert '1' in flat
        assert '2' in flat

    def test_table_header_bold(self):
        md = '| Name | Value |\n|------|-------|\n| x | 1 |'
        result = self.r.render(md)
        bold = _find_attr(result, 'md-strong')
        joined = ''.join(bold)
        assert 'Name' in joined
        assert 'Value' in joined

    def test_table_separator_line(self):
        md = '| H |\n|---|\n| d |'
        result = self.r.render(md)
        sep = _find_attr(result, 'md-thematicbreak')
        assert len(sep) > 0
        assert '─' in sep[0]

    def test_table_column_alignment(self):
        md = '| Short | LongerHeader |\n|---|---|\n| x | y |'
        result = self.r.render(md)
        flat = _flatten(result)
        # Headers and data are present
        assert 'Short' in flat
        assert 'LongerHeader' in flat

    def test_table_with_inline_markup(self):
        md = '| Col |\n|---|\n| **bold** |'
        result = self.r.render(md)
        bold = _find_attr(result, 'md-strong')
        assert any('bold' in b for b in bold)


# ---------------------------------------------------------------------------
# render_structured — <details>/<summary>
# ---------------------------------------------------------------------------

class TestRenderStructured:
    def setup_method(self):
        self.r = Renderer(_mock_app())

    def test_no_details(self):
        segments = self.r.render_structured('Hello world')
        assert len(segments) == 1
        assert segments[0][0] == 'text'
        assert 'Hello world' in _flatten(segments[0][1])

    def test_empty_text(self):
        segments = self.r.render_structured('')
        assert segments == [('text', [])]

    def test_none_text(self):
        segments = self.r.render_structured(None)
        assert segments == [('text', [])]

    def test_single_details_block(self):
        md = (
            'Intro text.\n\n'
            '<details>\n<summary>Walkthrough</summary>\n\n'
            'Hidden content here.\n\n'
            '</details>\n\n'
            'After text.'
        )
        segments = self.r.render_structured(md)
        types = [s[0] for s in segments]
        assert 'text' in types
        assert 'details' in types

        # Find the details segment.
        details = [s for s in segments if s[0] == 'details']
        assert len(details) == 1
        assert details[0][1] == 'Walkthrough'
        assert 'Hidden content' in _flatten(details[0][2])

        # Intro text should be in a text segment.
        texts = [s for s in segments if s[0] == 'text']
        all_text = ''.join(_flatten(s[1]) for s in texts)
        assert 'Intro text' in all_text

    def test_multiple_details_blocks(self):
        md = (
            '<details>\n<summary>First</summary>\n\n'
            'Body 1.\n\n'
            '</details>\n\n'
            '<details>\n<summary>Second</summary>\n\n'
            'Body 2.\n\n'
            '</details>\n'
        )
        segments = self.r.render_structured(md)
        details = [s for s in segments if s[0] == 'details']
        assert len(details) == 2
        assert details[0][1] == 'First'
        assert details[1][1] == 'Second'
        assert 'Body 1' in _flatten(details[0][2])
        assert 'Body 2' in _flatten(details[1][2])

    def test_details_without_summary(self):
        md = (
            '<details>\n\n'
            'No summary here.\n\n'
            '</details>\n'
        )
        segments = self.r.render_structured(md)
        details = [s for s in segments if s[0] == 'details']
        assert len(details) == 1
        assert details[0][1] == 'Details'  # fallback title

    def test_text_between_details(self):
        md = (
            '<details>\n<summary>A</summary>\n\n'
            'Body A.\n\n'
            '</details>\n\n'
            'Middle text.\n\n'
            '<details>\n<summary>B</summary>\n\n'
            'Body B.\n\n'
            '</details>\n'
        )
        segments = self.r.render_structured(md)
        types = [s[0] for s in segments]
        assert types == ['details', 'text', 'details']

    def test_nested_details_flattened(self):
        md = (
            '<details>\n<summary>Outer</summary>\n\n'
            'Outer body.\n\n'
            '<details>\n<summary>Inner</summary>\n\n'
            'Inner body.\n\n'
            '</details>\n\n'
            '</details>\n'
        )
        segments = self.r.render_structured(md)
        # Nested details are folded into the parent.
        details = [s for s in segments if s[0] == 'details']
        assert len(details) == 1
        assert details[0][1] == 'Outer'
        flat = _flatten(details[0][2])
        assert 'Outer body' in flat
        assert 'Inner body' in flat

    def test_unclosed_details(self):
        md = (
            '<details>\n<summary>Oops</summary>\n\n'
            'Never closed.\n'
        )
        segments = self.r.render_structured(md)
        details = [s for s in segments if s[0] == 'details']
        assert len(details) == 1
        assert details[0][1] == 'Oops'
        assert 'Never closed' in _flatten(details[0][2])

    def test_html_comments_dropped(self):
        md = (
            'Before.\n\n'
            '<!-- This is a comment -->\n\n'
            'After.\n'
        )
        segments = self.r.render_structured(md)
        all_text = ''.join(_flatten(s[1]) for s in segments
                           if s[0] == 'text')
        assert 'Before' in all_text
        assert 'After' in all_text
        assert 'comment' not in all_text.lower()

    def test_details_with_markdown_body(self):
        md = (
            '<details>\n<summary>Code</summary>\n\n'
            '```python\nprint("hi")\n```\n\n'
            '- list item\n\n'
            '</details>\n'
        )
        segments = self.r.render_structured(md)
        details = [s for s in segments if s[0] == 'details']
        assert len(details) == 1
        flat = _flatten(details[0][2])
        assert 'print' in flat
        assert 'list item' in flat

    def test_details_with_table_body(self):
        md = (
            '<details>\n<summary>Changes</summary>\n\n'
            '| File | Status |\n'
            '|------|--------|\n'
            '| a.py | Added  |\n\n'
            '</details>\n'
        )
        segments = self.r.render_structured(md)
        details = [s for s in segments if s[0] == 'details']
        assert len(details) == 1
        flat = _flatten(details[0][2])
        assert 'a.py' in flat
        assert 'Added' in flat

    def test_coderabbit_style_comment(self):
        """Simulate a typical CodeRabbit comment structure."""
        md = (
            '## Summary\n\n'
            'Some review summary.\n\n'
            '<details>\n<summary>Walkthrough</summary>\n\n'
            'The changes modify validation logic.\n\n'
            '</details>\n\n'
            '<details>\n<summary>Changes</summary>\n\n'
            '| File | Summary |\n'
            '|------|--------|\n'
            '| foo.go | Modified validation |\n\n'
            '</details>\n\n'
            '<details>\n<summary>Tips</summary>\n\n'
            '### Chat with CodeRabbit\n\n'
            'You can interact with the bot.\n\n'
            '</details>\n'
        )
        segments = self.r.render_structured(md)

        # First segment is text with heading + summary.
        assert segments[0][0] == 'text'
        flat_intro = _flatten(segments[0][1])
        assert 'Summary' in flat_intro
        assert 'review summary' in flat_intro

        # Three collapsible sections.
        details = [s for s in segments if s[0] == 'details']
        assert len(details) == 3
        summaries = [d[1] for d in details]
        assert summaries == ['Walkthrough', 'Changes', 'Tips']

    def test_coderabbit_inline_comment(self):
        """Inline comment body with <details> wrapping a suggestion."""
        md = (
            '**`logrus.Fatal` skips the deferred `cleanup()`.**\n\n'
            'Description of the problem.\n\n'
            '<details>\n<summary>Suggested fix</summary>\n\n'
            '```diff\n'
            '-logrus.Fatal(err)\n'
            '+return err\n'
            '```\n\n'
            '> **IMPORTANT**\n'
            '> Review the code before committing.\n\n'
            '```suggestion\n'
            'return err\n'
            '```\n\n'
            '</details>\n\n'
            'Verify each finding.\n'
        )
        segments = self.r.render_structured(md)

        # Text before the details block.
        assert segments[0][0] == 'text'
        intro = _flatten(segments[0][1])
        assert 'logrus.Fatal' in intro
        assert 'Description' in intro

        # The suggestion is wrapped in a collapsible section.
        details = [s for s in segments if s[0] == 'details']
        assert len(details) == 1
        assert details[0][1] == 'Suggested fix'
        body = _flatten(details[0][2])
        assert 'return err' in body
        assert 'IMPORTANT' in body

        # Text after the details block.
        texts = [s for s in segments if s[0] == 'text']
        after = _flatten(texts[-1][1])
        assert 'Verify' in after


    def test_block_html_not_dropped(self):
        """Non-<details> block HTML should pass through to toUrwidMarkup,
        not be silently discarded by render_structured()."""
        md = (
            'Before\n\n'
            '<!-- html comment -->\n\n'
            'After\n'
        )
        segments = self.r.render_structured(md)
        # All content lands in text segments (the HTML comment is
        # ignored by toUrwidMarkup, but 'Before' and 'After' must
        # both survive).
        texts = [s for s in segments if s[0] == 'text']
        flat = _flatten([s[1] for s in texts])
        assert 'Before' in flat
        assert 'After' in flat

    def test_details_inside_blockquote_collapsible(self):
        """<details> inside a blockquote should become a proper
        collapsible details segment, not inline text."""
        md = (
            '> Some intro\n'
            '>\n'
            '> <details>\n'
            '> <summary>Run configuration</summary>\n'
            '>\n'
            '> **Profile**: CHILL\n'
            '>\n'
            '> </details>\n'
            '>\n'
            '> After text.\n'
        )
        segments = self.r.render_structured(md)
        types = [s[0] for s in segments]
        assert 'details' in types

        details = [s for s in segments if s[0] == 'details']
        assert len(details) == 1
        assert details[0][1] == 'Run configuration'
        assert 'CHILL' in _flatten(details[0][2])

        # Surrounding text should be in text segments.
        texts = [s for s in segments if s[0] == 'text']
        all_text = ''.join(_flatten(s[1]) for s in texts)
        assert 'Some intro' in all_text
        assert 'After text' in all_text

    def test_details_inside_blockquote_with_emoji(self):
        md = (
            '> <details>\n'
            '> <summary>\u2699\ufe0f Run configuration</summary>\n'
            '>\n'
            '> **Plan**: Enterprise\n'
            '>\n'
            '> </details>\n'
        )
        segments = self.r.render_structured(md)
        details = [s for s in segments if s[0] == 'details']
        assert len(details) == 1
        assert 'Run configuration' in details[0][1]
        assert 'Enterprise' in _flatten(details[0][2])

    def test_coderabbit_blockquoted_details(self):
        """Simulate the CodeRabbit comment with blockquoted <details>."""
        md = (
            '> [!IMPORTANT]\n'
            '> ## Review skipped\n'
            '>\n'
            '> Auto reviews are disabled.\n'
            '>\n'
            '> <details>\n'
            '> <summary>\u2699\ufe0f Run configuration</summary>\n'
            '>\n'
            '> **Configuration used**: Repo config\n'
            '>\n'
            '> **Review profile**: CHILL\n'
            '>\n'
            '> </details>\n'
            '>\n'
            '> You can disable this status message.\n'
        )
        segments = self.r.render_structured(md)

        # The details section should be a collapsible segment.
        details = [s for s in segments if s[0] == 'details']
        assert len(details) == 1
        assert 'Run configuration' in details[0][1]
        body = _flatten(details[0][2])
        assert 'Configuration used' in body
        assert 'CHILL' in body

        # Text before and after should be in text segments.
        texts = [s for s in segments if s[0] == 'text']
        all_text = ''.join(_flatten(s[1]) for s in texts)
        assert 'Review skipped' in all_text
        assert 'disable this status' in all_text

    def test_blockquote_without_details_unchanged(self):
        """A plain blockquote without <details> renders normally."""
        md = '> Just a quote\n'
        result = self.r.render(md)
        bq = _find_attr(result, 'md-blockquote')
        assert any('Just a quote' in b for b in bq)

    def test_block_html_inside_details_not_dropped(self):
        """Non-<details> block HTML inside a <details> section should
        pass through to toUrwidMarkup for the details body."""
        md = (
            '<details><summary>Info</summary>\n\n'
            'Start\n\n'
            '<div class="note">note</div>\n\n'
            'End\n\n'
            '</details>\n'
        )
        segments = self.r.render_structured(md)
        details = [s for s in segments if s[0] == 'details']
        assert len(details) == 1
        body = _flatten(details[0][2])
        assert 'Start' in body
        assert 'End' in body


# ---------------------------------------------------------------------------
# CollapsibleSection widget
# ---------------------------------------------------------------------------

class TestCollapsibleSection:
    def test_starts_collapsed(self):
        body = urwid.Text('body content')
        cs = mywid.CollapsibleSection('Title', body)
        assert not cs.expanded
        assert len(cs.pile.contents) == 1

    def test_toggle_expands(self):
        body = urwid.Text('body content')
        cs = mywid.CollapsibleSection('Title', body)
        cs.toggle(None)
        assert cs.expanded
        assert len(cs.pile.contents) == 2

    def test_toggle_collapses(self):
        body = urwid.Text('body content')
        cs = mywid.CollapsibleSection('Title', body)
        cs.toggle(None)
        cs.toggle(None)
        assert not cs.expanded
        assert len(cs.pile.contents) == 1

    def test_starts_expanded(self):
        body = urwid.Text('body content')
        cs = mywid.CollapsibleSection('Title', body, expanded=True)
        assert cs.expanded
        assert len(cs.pile.contents) == 2

    def test_title_indicator_collapsed(self):
        body = urwid.Text('body content')
        cs = mywid.CollapsibleSection('MyTitle', body)
        label = cs._title_widget.text.get_text()[0]
        assert '▶' in label
        assert 'MyTitle' in label

    def test_title_indicator_expanded(self):
        body = urwid.Text('body content')
        cs = mywid.CollapsibleSection('MyTitle', body)
        cs.toggle(None)
        label = cs._title_widget.text.get_text()[0]
        assert '▼' in label
        assert 'MyTitle' in label


# ---------------------------------------------------------------------------
# _merge_header_body
# ---------------------------------------------------------------------------

class TestMergeHeaderBody:
    def test_body_starts_with_string(self):
        header = ['Author ', ('bold', 'name')]
        body = ['hello', ' world']
        result = PullRequestMessageBox._merge_header_body(header, body)
        assert result == ['Author ', ('bold', 'name'), '\nhello', ' world']

    def test_body_starts_with_tuple(self):
        header = ['Author']
        body = [('md-strong', 'bold text'), ' rest']
        result = PullRequestMessageBox._merge_header_body(header, body)
        assert result == ['Author', '\n', ('md-strong', 'bold text'), ' rest']

    def test_body_starts_with_link(self):
        header = ['Author']
        link = mywid.Link('click here', 'link-attr', None)
        body = [link, ' some text']
        result = PullRequestMessageBox._merge_header_body(header, body)
        # Must not crash; newline is prepended as a separate element.
        assert result == ['Author', '\n', link, ' some text']

    def test_empty_body(self):
        header = ['Author']
        result = PullRequestMessageBox._merge_header_body(header, [])
        assert result == ['Author']
