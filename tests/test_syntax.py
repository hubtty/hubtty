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

"""Tests for hubtty.syntax module."""

from pygments.token import Token

from hubtty.syntax import (
    DIFF_LINE_STYLES,
    LIGHT_DIFF_LINE_STYLES,
    LIGHT_SYNTAX_PALETTE,
    SYNTAX_PALETTE,
    _chars_to_markup,
    _flatten_to_chars,
    _simplify_markup,
    _token_to_attr,
    build_light_syntax_palette,
    build_syntax_focus_map,
    build_syntax_palette,
    highlight_file,
    merge_syntax_with_diff,
)


# ------------------------------------------------------------------
# _token_to_attr
# ------------------------------------------------------------------

class TestTokenToAttr:

    def test_direct_match(self):
        assert _token_to_attr(Token.Keyword) == 'syn-keyword'

    def test_direct_match_subtype(self):
        assert _token_to_attr(Token.Keyword.Type) == 'syn-type'

    def test_ancestor_fallback(self):
        """Token.Keyword.Reserved isn't mapped directly; falls back to
        Token.Keyword."""
        assert _token_to_attr(Token.Keyword.Reserved) == 'syn-keyword'

    def test_no_match(self):
        assert _token_to_attr(Token.Text) is None

    def test_whitespace_no_match(self):
        assert _token_to_attr(Token.Text.Whitespace) is None

    def test_comment_match(self):
        assert _token_to_attr(Token.Comment) == 'syn-comment'

    def test_comment_single_falls_back(self):
        """Token.Comment.Single isn't mapped; should fall back to
        Token.Comment."""
        assert _token_to_attr(Token.Comment.Single) == 'syn-comment'

    def test_string_doc(self):
        assert _token_to_attr(Token.Literal.String.Doc) == 'syn-string'

    def test_name_namespace(self):
        assert _token_to_attr(Token.Name.Namespace) == 'syn-type'

    def test_name_variable(self):
        assert _token_to_attr(Token.Name.Variable) == 'syn-name-function'

    def test_name_constant(self):
        assert _token_to_attr(Token.Name.Constant) == 'syn-number'


# ------------------------------------------------------------------
# highlight_file
# ------------------------------------------------------------------

class TestHighlightFile:

    def test_python_snippet(self):
        code = 'def foo():\n    return 42\n'
        result = highlight_file('example.py', code)
        assert isinstance(result, dict)
        # Line 1 should contain a keyword for 'def'
        line1 = result.get(1)
        assert line1 is not None
        flat = _flatten_to_chars(line1)
        attrs = {a for a, _ in flat if a is not None}
        assert 'syn-keyword' in attrs

    def test_python_string_token(self):
        code = 'x = "hello"\n'
        result = highlight_file('example.py', code)
        line1 = result.get(1)
        assert line1 is not None
        flat = _flatten_to_chars(line1)
        attrs = {a for a, _ in flat if a is not None}
        assert 'syn-string' in attrs

    def test_python_comment(self):
        code = '# a comment\n'
        result = highlight_file('example.py', code)
        line1 = result.get(1)
        assert line1 is not None
        flat = _flatten_to_chars(line1)
        attrs = {a for a, _ in flat if a is not None}
        assert 'syn-comment' in attrs

    def test_empty_content(self):
        assert highlight_file('example.py', '') == {}

    def test_none_content(self):
        assert highlight_file('example.py', None) == {}

    def test_too_large(self):
        big = 'x' * (512 * 1024 + 1)
        assert highlight_file('example.py', big) == {}

    def test_custom_max_file_size(self):
        content = 'x = 1\n'
        # Content fits in default but exceeds our tiny limit.
        assert highlight_file('example.py', content, max_file_size=2) == {}
        # And works with a large enough limit.
        assert highlight_file('example.py', content, max_file_size=1024) != {}

    def test_max_file_size_uses_char_count(self):
        """Size check uses character count as a fast heuristic.

        Callers (gitrepo._highlight, gitrepo.getFile) pre-check raw
        byte size before calling highlight_file, so the function
        itself only needs a cheap character-length guard.
        """
        # U+00E9 is 2 bytes in UTF-8.  10 chars = 20 bytes.
        content = '\u00e9' * 10
        # Character count (10) is below limit 15, so highlight_file
        # accepts it even though byte count (20) exceeds 15.
        result = highlight_file('example.py', content, max_file_size=15)
        assert result != {}, 'should not be rejected by char-count check'
        # When limit is below character count, it is rejected.
        assert highlight_file('example.py', content, max_file_size=5) == {}

    def test_unknown_extension(self):
        """Unknown extensions fall back to TextLexer → empty result."""
        assert highlight_file('data.zzzzz', 'hello') == {}

    def test_plain_text_file(self):
        assert highlight_file('readme.txt', 'just text') == {}

    def test_multiline(self):
        code = 'if True:\n    pass\n'
        result = highlight_file('example.py', code)
        assert 1 in result  # 'if' keyword on line 1
        assert 2 in result  # 'pass' keyword on line 2

    def test_crlf_line_endings(self):
        """CRLF line endings should not break highlighting."""
        code = 'def foo():\r\n    return 42\r\n'
        result = highlight_file('example.py', code)
        assert isinstance(result, dict)
        line1 = result.get(1)
        assert line1 is not None
        flat = _flatten_to_chars(line1)
        # Text should not contain \r
        text = ''.join(c for _, c in flat)
        assert '\r' not in text
        assert text == 'def foo():'

    def test_preserves_text_content(self):
        """The text content embedded in the markup should match the
        original source line (minus the newline)."""
        code = 'def foo():\n'
        result = highlight_file('example.py', code)
        line1 = result.get(1)
        flat = _flatten_to_chars(line1)
        text = ''.join(c for _, c in flat)
        assert text == 'def foo():'


# ------------------------------------------------------------------
# _simplify_markup
# ------------------------------------------------------------------

class TestSimplifyMarkup:

    def test_empty(self):
        assert _simplify_markup([]) == ''

    def test_single_string(self):
        assert _simplify_markup(['hello']) == 'hello'

    def test_single_tuple(self):
        assert _simplify_markup([('a', 'x')]) == ('a', 'x')

    def test_adjacent_same_attr(self):
        result = _simplify_markup([('a', 'he'), ('a', 'llo')])
        assert result == ('a', 'hello')

    def test_adjacent_strings(self):
        result = _simplify_markup(['he', 'llo'])
        assert result == 'hello'

    def test_mixed_preserved(self):
        result = _simplify_markup([('a', 'x'), ('b', 'y')])
        assert result == [('a', 'x'), ('b', 'y')]

    def test_mixed_with_strings(self):
        result = _simplify_markup([('a', 'x'), 'y', ('b', 'z')])
        assert result == [('a', 'x'), 'y', ('b', 'z')]


# ------------------------------------------------------------------
# _flatten_to_chars
# ------------------------------------------------------------------

class TestFlattenToChars:

    def test_plain_string(self):
        result = _flatten_to_chars('abc')
        assert result == [(None, 'a'), (None, 'b'), (None, 'c')]

    def test_attr_tuple(self):
        result = _flatten_to_chars(('bold', 'hi'))
        assert result == [('bold', 'h'), ('bold', 'i')]

    def test_list_of_mixed(self):
        result = _flatten_to_chars([('a', 'x'), 'y'])
        assert result == [('a', 'x'), (None, 'y')]

    def test_nested_list(self):
        result = _flatten_to_chars([('a', 'x'), [('b', 'y'), 'z']])
        assert result == [('a', 'x'), ('b', 'y'), (None, 'z')]

    def test_empty_string(self):
        assert _flatten_to_chars('') == []

    def test_empty_list(self):
        assert _flatten_to_chars([]) == []

    def test_non_markup_type(self):
        """Non-markup types (e.g. int) return empty list."""
        assert _flatten_to_chars(42) == []


# ------------------------------------------------------------------
# _chars_to_markup
# ------------------------------------------------------------------

class TestCharsToMarkup:

    def test_empty(self):
        assert _chars_to_markup([]) == ''

    def test_single_char_with_attr(self):
        assert _chars_to_markup([('a', 'x')]) == ('a', 'x')

    def test_single_char_no_attr(self):
        assert _chars_to_markup([(None, 'x')]) == 'x'

    def test_merge_same_attr(self):
        chars = [('a', 'h'), ('a', 'i')]
        assert _chars_to_markup(chars) == ('a', 'hi')

    def test_merge_no_attr(self):
        chars = [(None, 'h'), (None, 'i')]
        assert _chars_to_markup(chars) == 'hi'

    def test_different_attrs(self):
        chars = [('a', 'x'), ('b', 'y')]
        assert _chars_to_markup(chars) == [('a', 'x'), ('b', 'y')]

    def test_roundtrip_simple(self):
        markup = [('syn-keyword', 'def'), ' ', ('syn-name-function', 'foo')]
        chars = _flatten_to_chars(markup)
        result = _chars_to_markup(chars)
        # Flatten both and compare text + attrs.
        assert _flatten_to_chars(result) == chars

    def test_roundtrip_single_attr(self):
        markup = ('bold', 'hello')
        chars = _flatten_to_chars(markup)
        assert _chars_to_markup(chars) == markup


# ------------------------------------------------------------------
# merge_syntax_with_diff
# ------------------------------------------------------------------

class TestMergeSyntaxWithDiff:

    def test_preserves_word_emphasis(self):
        """*-word attrs must be kept as-is regardless of syntax."""
        syn = [('syn-keyword', 'def'), ' ', ('syn-name-function', 'foo')]
        diff = [('added-line', 'de'), ('added-word', 'f'), ('added-line', ' foo')]
        result = merge_syntax_with_diff(syn, diff)
        flat = _flatten_to_chars(result)
        # The 'f' at index 2 should keep added-word.
        assert flat[2] == ('added-word', 'f')

    def test_preserves_trailing_ws(self):
        syn = [('syn-keyword', 'if'), ' ']
        diff = [('added-line', 'if'), ('trailing-ws', ' ')]
        result = merge_syntax_with_diff(syn, diff)
        flat = _flatten_to_chars(result)
        assert flat[2] == ('trailing-ws', ' ')

    def test_combines_syntax_on_diff_line(self):
        """syn-keyword on added-line → syn-keyword-on-added-line."""
        syn = ('syn-keyword', 'if')
        diff = ('added-line', 'if')
        result = merge_syntax_with_diff(syn, diff)
        flat = _flatten_to_chars(result)
        assert all(a == 'syn-keyword-on-added-line' for a, _ in flat)

    def test_combines_syntax_on_removed_line(self):
        syn = ('syn-string', 'hi')
        diff = ('removed-line', 'hi')
        result = merge_syntax_with_diff(syn, diff)
        flat = _flatten_to_chars(result)
        assert all(a == 'syn-string-on-removed-line' for a, _ in flat)

    def test_unstyled_syntax_keeps_diff_attr(self):
        """Chars with no syntax attr should keep the diff attr."""
        syn = 'xy'  # no syntax attrs
        diff = ('added-line', 'xy')
        result = merge_syntax_with_diff(syn, diff)
        flat = _flatten_to_chars(result)
        assert all(a == 'added-line' for a, _ in flat)

    def test_no_diff_attr_uses_syntax(self):
        """Context lines with no diff attr get the syntax attr directly."""
        syn = ('syn-comment', 'xy')
        diff = 'xy'
        result = merge_syntax_with_diff(syn, diff)
        flat = _flatten_to_chars(result)
        assert all(a == 'syn-comment' for a, _ in flat)

    def test_both_empty_attrs(self):
        """No syntax and no diff attr → None attr."""
        syn = 'xy'
        diff = 'xy'
        result = merge_syntax_with_diff(syn, diff)
        flat = _flatten_to_chars(result)
        assert all(a is None for a, _ in flat)

    def test_empty_syntax_returns_diff(self):
        diff = ('added-line', 'hello')
        result = merge_syntax_with_diff('', diff)
        assert result == diff

    def test_empty_diff_returns_diff(self):
        syn = ('syn-keyword', 'def')
        result = merge_syntax_with_diff(syn, '')
        assert result == ''

    def test_mismatched_text_returns_diff_markup(self):
        """When syntax and diff text differ, fall back to plain diff."""
        syn = ('syn-keyword', 'def')
        diff = ('added-line', 'xyz')
        result = merge_syntax_with_diff(syn, diff)
        assert result == diff

    def test_mismatched_length_returns_diff_markup(self):
        syn = ('syn-keyword', 'if')
        diff = ('added-line', 'iff')
        result = merge_syntax_with_diff(syn, diff)
        assert result == diff


# ------------------------------------------------------------------
# build_syntax_palette
# ------------------------------------------------------------------

class TestBuildSyntaxPalette:

    def test_base_attrs_present(self):
        palette = build_syntax_palette()
        for attr in SYNTAX_PALETTE:
            assert attr in palette, f'Missing base attr: {attr}'

    def test_focused_attrs_present(self):
        palette = build_syntax_palette()
        for attr in SYNTAX_PALETTE:
            key = 'focused-' + attr
            assert key in palette, f'Missing focused attr: {key}'

    def test_combined_attrs_present(self):
        palette = build_syntax_palette()
        for syn_attr in SYNTAX_PALETTE:
            for diff_style in DIFF_LINE_STYLES:
                combined = f'{syn_attr}-on-{diff_style}'
                assert combined in palette, f'Missing combined: {combined}'
                focused = 'focused-' + combined
                assert focused in palette, f'Missing focused combined: {focused}'

    def test_base_attr_has_fg_and_bg(self):
        palette = build_syntax_palette()
        entry = palette['syn-keyword']
        assert len(entry) >= 2
        assert entry[0]  # foreground should be non-empty

    def test_combined_attr_has_highcolor(self):
        """Combined attrs should have 5 entries (16-color fg, bg, mono,
        highcolor fg, highcolor bg)."""
        palette = build_syntax_palette()
        entry = palette['syn-keyword-on-added-line']
        assert len(entry) == 5

    def test_focused_has_standout(self):
        palette = build_syntax_palette()
        entry = palette['focused-syn-keyword']
        assert 'standout' in entry[0]

    def test_fg_adjustment_applied(self):
        """syn-comment (dark gray) on removed-line (dark red) should be
        adjusted to light gray."""
        palette = build_syntax_palette()
        entry = palette['syn-comment-on-removed-line']
        assert entry[0] == 'light gray'


# ------------------------------------------------------------------
# build_light_syntax_palette
# ------------------------------------------------------------------

class TestBuildLightSyntaxPalette:

    def test_base_attrs_present(self):
        palette = build_light_syntax_palette()
        for attr in LIGHT_SYNTAX_PALETTE:
            assert attr in palette, f'Missing base attr: {attr}'

    def test_combined_attrs_present(self):
        """Light palette must include syn-*-on-{added,removed}-line."""
        palette = build_light_syntax_palette()
        for syn_attr in LIGHT_SYNTAX_PALETTE:
            for diff_style in LIGHT_DIFF_LINE_STYLES:
                combined = f'{syn_attr}-on-{diff_style}'
                assert combined in palette, f'Missing combined: {combined}'
                focused = 'focused-' + combined
                assert focused in palette, f'Missing focused: {focused}'

    def test_combined_uses_light_backgrounds(self):
        """Combined attrs should use light-theme diff backgrounds."""
        palette = build_light_syntax_palette()
        entry = palette['syn-keyword-on-added-line']
        # 16-color bg should be the light-theme value
        assert entry[1] == LIGHT_DIFF_LINE_STYLES['added-line'][0]
        # highcolor bg should be the light-theme value
        assert entry[4] == LIGHT_DIFF_LINE_STYLES['added-line'][1]

    def test_combined_attr_has_highcolor(self):
        palette = build_light_syntax_palette()
        entry = palette['syn-keyword-on-removed-line']
        assert len(entry) == 5


# ------------------------------------------------------------------
# build_syntax_focus_map
# ------------------------------------------------------------------

class TestBuildSyntaxFocusMap:

    def test_base_attrs_mapped(self):
        fm = build_syntax_focus_map()
        for attr in SYNTAX_PALETTE:
            assert fm[attr] == 'focused-' + attr

    def test_combined_attrs_mapped(self):
        fm = build_syntax_focus_map()
        for syn_attr in SYNTAX_PALETTE:
            for diff_style in DIFF_LINE_STYLES:
                combined = f'{syn_attr}-on-{diff_style}'
                assert fm[combined] == 'focused-' + combined

    def test_count(self):
        """Total entries = base attrs + combined attrs."""
        fm = build_syntax_focus_map()
        expected = len(SYNTAX_PALETTE) * (1 + len(DIFF_LINE_STYLES))
        assert len(fm) == expected
