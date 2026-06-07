# Copyright 2025 The hubtty developers
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

"""Syntax highlighting for diff views using Pygments."""

import functools
import logging

from pygments import lex
from pygments.lexers import get_lexer_for_filename, TextLexer
from pygments.token import Token

log = logging.getLogger('hubtty.syntax')

# Map Pygments token types to urwid palette attribute names.
# Only tokens listed here (or whose ancestors are listed) get styled;
# everything else keeps the default foreground colour.
TOKEN_MAP = {
    Token.Keyword: 'syn-keyword',
    Token.Keyword.Type: 'syn-type',
    Token.Name.Builtin: 'syn-builtin',
    Token.Name.Builtin.Pseudo: 'syn-builtin',
    Token.Name.Function: 'syn-name-function',
    Token.Name.Function.Magic: 'syn-name-function',
    Token.Name.Class: 'syn-type',
    Token.Name.Decorator: 'syn-decorator',
    Token.Name.Exception: 'syn-type',
    Token.Name.Namespace: 'syn-type',
    Token.Name.Tag: 'syn-keyword',
    Token.Name.Attribute: 'syn-name-function',
    Token.Name.Variable: 'syn-name-function',
    Token.Name.Variable.Instance: 'syn-name-function',
    Token.Name.Constant: 'syn-number',
    Token.Literal.String: 'syn-string',
    Token.Literal.String.Doc: 'syn-string',
    Token.Literal.String.Interpol: 'syn-string',
    Token.Literal.Number: 'syn-number',
    Token.Comment: 'syn-comment',
    Token.Comment.PreprocFile: 'syn-string',
    Token.Operator.Word: 'syn-keyword',
}

# Base syntax palette colours: (foreground, background).
SYNTAX_PALETTE = {
    'syn-keyword':       ['brown', ''],
    'syn-string':        ['dark green', ''],
    'syn-comment':       ['dark gray', ''],
    'syn-name-function': ['light blue', ''],
    'syn-type':          ['dark cyan', ''],
    'syn-number':        ['dark magenta', ''],
    'syn-builtin':       ['dark cyan', ''],
    'syn-decorator':     ['dark magenta', ''],
}

# Diff line styles that get background tinting.
# Values are (bg_16color, bg_highcolor).
DIFF_LINE_STYLES = {
    'added-line': ('dark green', '#204020'),
    'removed-line': ('dark red', '#402020'),
}

# Light-theme diff backgrounds (softer tints suitable for light terminals).
LIGHT_DIFF_LINE_STYLES = {
    'added-line': ('light green', '#c8e6c8'),
    'removed-line': ('light red', '#e6c8c8'),
}

# Foreground adjustments for readability on coloured backgrounds.
# (original_fg, bg) → adjusted_fg
_FG_ADJUST = {
    ('dark green', 'dark green'): 'light green',
    ('dark gray', 'dark red'): 'light gray',
    ('dark gray', 'dark green'): 'light gray',
    ('dark cyan', 'dark green'): 'light cyan',
}

# Light-theme foreground adjustments.
_LIGHT_FG_ADJUST = {
    ('dark green', 'light green'): 'dark green',
    ('dark magenta', 'light red'): 'dark magenta',
}

# Default maximum file size (bytes) to attempt highlighting.
DEFAULT_MAX_FILE_SIZE = 512 * 1024


def _token_to_attr(token_type):
    """Map a Pygments token type to a palette attribute name.

    Walks up the token hierarchy until a match is found.
    Returns *None* for tokens that should use the default style.
    """
    t = token_type
    while t:
        attr = TOKEN_MAP.get(t)
        if attr is not None:
            return attr
        t = t.parent
    return None


def highlight_file(filename, content, max_file_size=DEFAULT_MAX_FILE_SIZE):
    """Highlight *content* and return per-line urwid markup.

    Args:
        filename:      Used to select a Pygments lexer.
        content:       Full file text (``str``).
        max_file_size: Skip files larger than this (bytes).

    Returns:
        ``dict[int, markup]`` — 1-based line number → urwid text
        markup.  Lines that contain no styled tokens are omitted so
        the caller can fall back to the original plain string.
    """
    if not content or len(content) > max_file_size:
        return {}

    content = content.replace('\r\n', '\n').replace('\r', '\n')

    try:
        lexer = get_lexer_for_filename(filename, stripall=False)
    except Exception:
        return {}

    if isinstance(lexer, TextLexer):
        return {}

    lines = {}
    current_line = 1
    current_markup = []

    for token_type, value in lex(content, lexer):
        attr = _token_to_attr(token_type)
        parts = value.split('\n')
        for i, part in enumerate(parts):
            if i > 0:
                # newline → flush the current line
                markup = _simplify_markup(current_markup)
                if markup != '':
                    lines[current_line] = markup
                current_line += 1
                current_markup = []
            if part:
                if attr:
                    current_markup.append((attr, part))
                else:
                    current_markup.append(part)

    # last line (file may lack a trailing newline)
    if current_markup:
        markup = _simplify_markup(current_markup)
        if markup != '':
            lines[current_line] = markup

    return lines


def _simplify_markup(markup):
    """Merge adjacent segments that share the same attribute."""
    if not markup:
        return ''
    if len(markup) == 1:
        return markup[0]

    result = []
    for item in markup:
        if isinstance(item, str):
            if result and isinstance(result[-1], str):
                result[-1] += item
            else:
                result.append(item)
        else:
            attr, text = item
            if (result and isinstance(result[-1], tuple)
                    and result[-1][0] == attr):
                result[-1] = (attr, result[-1][1] + text)
            else:
                result.append(item)

    if len(result) == 1:
        return result[0]
    return result


# ------------------------------------------------------------------
# Merging syntax markup with diff markup for changed lines
# ------------------------------------------------------------------

def _flatten_to_chars(markup):
    """Convert urwid markup to a flat ``[(attr, char), …]`` list."""
    if isinstance(markup, str):
        return [(None, c) for c in markup]
    if isinstance(markup, tuple):
        attr, text = markup
        if isinstance(text, str):
            return [(attr, c) for c in text]
        return _flatten_to_chars(text)
    if isinstance(markup, list):
        result = []
        for item in markup:
            result.extend(_flatten_to_chars(item))
        return result
    return []


def _chars_to_markup(chars):
    """Re-assemble ``[(attr, char), …]`` into urwid markup."""
    if not chars:
        return ''
    result = []
    cur_attr, cur_text = chars[0]
    for attr, char in chars[1:]:
        if attr == cur_attr:
            cur_text += char
        else:
            result.append((cur_attr, cur_text) if cur_attr else cur_text)
            cur_attr, cur_text = attr, char
    result.append((cur_attr, cur_text) if cur_attr else cur_text)
    return result[0] if len(result) == 1 else result


def merge_syntax_with_diff(syntax_markup, diff_markup):
    """Overlay syntax colours onto diff markup for a changed line.

    * ``*-word`` and ``trailing-ws`` attributes are kept as-is (word
      emphasis is more important than syntax colour).
    * ``added-line`` / ``removed-line`` segments get a combined attr
      like ``syn-keyword-on-added-line`` so that the syntax foreground
      sits on the diff background.
    * Any other diff attr (e.g. ``context-line``) is replaced by the
      syntax attr directly.
    """
    syn_chars = _flatten_to_chars(syntax_markup)
    diff_chars = _flatten_to_chars(diff_markup)

    if not syn_chars or not diff_chars:
        return diff_markup

    # Guard: the character-level merge assumes both sides represent
    # the same text.  If they differ (encoding normalisation, "no
    # newline" workaround, etc.) fall back to plain diff markup
    # rather than silently mis-colouring characters.
    syn_text = ''.join(c for _, c in syn_chars)
    diff_text = ''.join(c for _, c in diff_chars)
    if syn_text != diff_text:
        log.warning('Syntax/diff text mismatch (len %d vs %d); '
                   'skipping syntax merge', len(syn_text), len(diff_text))
        return diff_markup

    merged = []
    for i, (diff_attr, char) in enumerate(diff_chars):
        # syn_chars and diff_chars have equal length (same text)
        syn_attr = syn_chars[i][0]

        if diff_attr and ('word' in diff_attr or diff_attr == 'trailing-ws'):
            merged.append((diff_attr, char))
        elif diff_attr in DIFF_LINE_STYLES and syn_attr:
            merged.append((f'{syn_attr}-on-{diff_attr}', char))
        elif diff_attr:
            merged.append((diff_attr, char))
        elif syn_attr:
            merged.append((syn_attr, char))
        else:
            merged.append((None, char))

    return _chars_to_markup(merged)


# ------------------------------------------------------------------
# Palette / focus-map helpers
# ------------------------------------------------------------------

def build_syntax_palette(syn_palette=None, diff_styles=None,
                         fg_adjust=None):
    """Return palette entries for syntax highlighting.

    Includes base ``syn-*`` attrs **and** combined
    ``syn-*-on-{added,removed}-line`` attrs with adjusted foreground
    colours for readability on coloured backgrounds.

    Pass *syn_palette*, *diff_styles* and *fg_adjust* to override the
    defaults (used by the light-theme builder).
    """
    if syn_palette is None:
        syn_palette = SYNTAX_PALETTE
    if diff_styles is None:
        diff_styles = DIFF_LINE_STYLES
    if fg_adjust is None:
        fg_adjust = _FG_ADJUST

    entries = {}

    # Base syntax attrs (context lines)
    for attr, (fg, bg) in syn_palette.items():
        entries[attr] = [fg, bg]
        sfg = (fg + ',standout' if fg and fg != 'default'
               else 'default,standout')
        entries['focused-' + attr] = [sfg, bg]

    # Combined syntax-on-diff attrs (changed lines)
    for syn_attr, (syn_fg, _) in syn_palette.items():
        for diff_style, (diff_bg, diff_bg_hi) in diff_styles.items():
            combined = f'{syn_attr}-on-{diff_style}'
            fg = fg_adjust.get((syn_fg, diff_bg), syn_fg)
            entries[combined] = [fg, diff_bg, '', fg, diff_bg_hi]
            sfg = (fg + ',standout' if fg and fg != 'default'
                   else 'default,standout')
            entries['focused-' + combined] = [
                sfg, diff_bg, '', sfg, diff_bg_hi]

    return entries


# Light-theme syntax palette: foreground colours adjusted for
# readability on light terminal backgrounds.
LIGHT_SYNTAX_PALETTE = {
    'syn-keyword':       ['dark magenta', ''],
    'syn-string':        ['dark green', ''],
    'syn-comment':       ['brown', ''],
    'syn-name-function': ['dark blue', ''],
    'syn-type':          ['dark cyan', ''],
    'syn-number':        ['dark magenta', ''],
    'syn-builtin':       ['dark cyan', ''],
    'syn-decorator':     ['dark magenta', ''],
}


def build_light_syntax_palette():
    """Return palette entries tuned for light terminal backgrounds."""
    return build_syntax_palette(
        syn_palette=LIGHT_SYNTAX_PALETTE,
        diff_styles=LIGHT_DIFF_LINE_STYLES,
        fg_adjust=_LIGHT_FG_ADJUST,
    )


@functools.lru_cache(maxsize=1)
def build_syntax_focus_map():
    """Return a *focus_map* dict for ``urwid.AttrMap``.

    Maps every ``syn-*`` and ``syn-*-on-*`` attr to its focused
    counterpart.
    """
    fm = {attr: 'focused-' + attr for attr in SYNTAX_PALETTE}
    for syn_attr in SYNTAX_PALETTE:
        for diff_style in DIFF_LINE_STYLES:
            combined = f'{syn_attr}-on-{diff_style}'
            fm[combined] = 'focused-' + combined
    return fm
