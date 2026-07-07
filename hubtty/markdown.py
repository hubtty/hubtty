# Copyright 2022 Martin André
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
import re

import mistune
import urwid
from urwid.str_util import calc_width

from hubtty import mywid


class Renderer:
    def __init__(self, app):
        self.log = logging.getLogger('hubtty.markdown')
        self.app = app
        self._parser = mistune.create_markdown(
            renderer='ast', plugins=['strikethrough', 'table'])

    @staticmethod
    def _extract_summary(raw_html):
        """Extract <summary> text from a <details> opening block_html."""
        match = re.search(r'<summary[^>]*>(.*?)</summary>',
                          raw_html, re.DOTALL | re.IGNORECASE)
        if match:
            # Strip any remaining HTML tags from the summary text.
            summary = re.sub(r'<[^>]+>', '', match.group(1)).strip()
            return summary or 'Details'
        return 'Details'

    @staticmethod
    def _plain_text_len(markup):
        """Calculate the display width of urwid text markup.

        Uses terminal-aware column widths so that CJK characters and
        emoji (which occupy two cells) are measured correctly.
        """
        if isinstance(markup, str):
            return calc_width(markup, 0, len(markup))
        if isinstance(markup, list):
            return sum(Renderer._plain_text_len(item) for item in markup)
        if isinstance(markup, tuple):
            return Renderer._plain_text_len(markup[1])
        if isinstance(markup, mywid.Link):
            return calc_width(markup.text, 0, len(markup.text))
        return 0

    def _render_table(self, element):
        """Render a markdown table element as formatted urwid text markup."""
        header_cells = []
        body_rows = []

        for child in element.get('children', []):
            if child['type'] == 'table_head':
                header_cells = [
                    self.toUrwidMarkup(cell.get('children', []))
                    for cell in child.get('children', [])
                ]
            elif child['type'] == 'table_body':
                for row in child.get('children', []):
                    body_rows.append([
                        self.toUrwidMarkup(cell.get('children', []))
                        for cell in row.get('children', [])
                    ])

        all_rows = ([header_cells] if header_cells else []) + body_rows
        if not all_rows or not all_rows[0]:
            return []

        num_cols = max(len(row) for row in all_rows)
        col_widths = [0] * num_cols
        for row in all_rows:
            for i, cell in enumerate(row):
                w = self._plain_text_len(cell)
                if w > col_widths[i]:
                    col_widths[i] = w

        text = []
        for row_idx, row in enumerate(all_rows):
            for i in range(num_cols):
                cell = row[i] if i < len(row) else ''
                width = self._plain_text_len(cell)
                padding = ' ' * max(0, col_widths[i] - width)
                if header_cells and row_idx == 0:
                    # Include padding inside the styled tuple so the
                    # full column width renders with the header style.
                    if isinstance(cell, list):
                        text.append(('md-strong', cell + [padding]))
                    else:
                        text.append(('md-strong', cell + padding))
                else:
                    if isinstance(cell, list):
                        text.extend(cell)
                    else:
                        text.append(cell)
                    text.append(padding)
                if i < num_cols - 1:
                    text.append('  ')
            text.append('\n')
            if header_cells and row_idx == 0:
                sep = '  '.join('\u2500' * w for w in col_widths)
                text.append(('md-thematicbreak', sep))
                text.append('\n')

        return text

    @staticmethod
    def _ends_with_newline(item):
        """Check if a markup item ends with a newline character."""
        while True:
            if isinstance(item, str):
                return item.endswith('\n')
            elif isinstance(item, tuple):
                item = item[-1]
            elif isinstance(item, list):
                if not item:
                    return False
                item = item[-1]
            else:
                return False

    def _insert_line_prefix(self, markup, prefix):
        """Insert *prefix* at the start of each line in *markup*.

        Walks the top-level items in the markup list and inserts
        *prefix* at the beginning and after every item that ends
        with a newline (when followed by more content).

        This handles the ``| `` prefix for blockquotes so that
        every visual line gets the prefix, not just the first.
        Newlines from terminal line-wrapping are not handled
        (that would require widget-level changes).
        """
        if not markup:
            return []

        result = [prefix]
        for i, item in enumerate(markup):
            result.append(item)
            if (i < len(markup) - 1
                    and self._ends_with_newline(item)):
                result.append(prefix)

        return result

    def _group_details(self, nodes):
        """Group AST *nodes* by extracting ``<details>`` blocks.

        Returns a list of segment tuples whose payloads are raw AST
        node lists (not yet rendered to urwid markup):

        * ``('text', node_list)`` — regular AST nodes
        * ``('details', summary_str, node_list)`` — ``<details>``
          section
        """
        segments = []
        current_nodes = []
        details_stack = []  # list of (summary, node_list)

        for node in nodes:
            if node['type'] == 'block_html':
                raw = node.get('raw', '').strip()
                raw_lower = raw.lower()
                if raw_lower.startswith('<details'):
                    # Flush accumulated nodes.
                    if details_stack:
                        details_stack[-1][1].extend(current_nodes)
                    elif current_nodes:
                        segments.append(('text', current_nodes))
                    current_nodes = []
                    summary = self._extract_summary(raw)
                    details_stack.append((summary, []))
                    continue
                elif raw_lower.startswith('</details'):
                    if details_stack:
                        details_stack[-1][1].extend(current_nodes)
                        current_nodes = []
                        summary, detail_nodes = details_stack.pop()
                        if details_stack:
                            # Nested — fold into parent as plain
                            # content (no nested collapsibles).
                            details_stack[-1][1].extend(
                                detail_nodes)
                        else:
                            segments.append(
                                ('details', summary,
                                 detail_nodes))
                    continue
                # Other block HTML — fall through.

            # Regular AST node.
            if details_stack:
                details_stack[-1][1].append(node)
            else:
                current_nodes.append(node)

        # Flush remaining accumulated nodes.
        if current_nodes:
            if details_stack:
                details_stack[-1][1].extend(current_nodes)
                current_nodes = []

        # Handle any unclosed <details> blocks.
        while details_stack:
            summary, detail_nodes = details_stack.pop()
            segments.append(('details', summary, detail_nodes))

        if current_nodes:
            segments.append(('text', current_nodes))

        return segments

    def toUrwidMarkup(self, ast):
        text = []
        for element in ast:
            match element['type']:
                case 'text':
                    text.append(element.get('raw', ''))
                case 'strong':
                    text.append(('md-strong', self.toUrwidMarkup(element['children'])))
                case 'emphasis':
                    text.append(('md-emphasis', self.toUrwidMarkup(element['children'])))
                case 'strikethrough':
                    text.append(('md-strikethrough', self.toUrwidMarkup(element['children'])))
                case 'heading':
                    level = element.get('attrs', {}).get('level', 1)
                    text.append(('md-heading', ["#" * level, " ", self.toUrwidMarkup(element['children']), "\n"]))
                case 'paragraph':
                    # Add newline before paragraphs if needed
                    if self.needsNewLine(text):
                        text.append("\n")
                    text.extend(self.toUrwidMarkup(element['children']))
                    text.append("\n")
                case 'newline' | 'blank_line' | 'softbreak' | 'linebreak':
                    text.append("\n")
                case 'thematic_break':
                    text.append(('md-thematicbreak', "\n———————————————\n\n"))
                case 'block_quote':
                    inner = self.toUrwidMarkup(
                        element['children'])
                    prefixed = self._insert_line_prefix(
                        inner, '| ')
                    text.append(('md-blockquote', prefixed))
                case 'block_code':
                    info = element.get('attrs', {}).get('info', '')
                    if info is None:
                        info = ""
                    raw_code = element.get('raw', '')
                    text.append(('md-blockcode', ["```%s\n" % info, raw_code, "```\n"]))
                case 'table':
                    if self.needsNewLine(text):
                        text.append("\n")
                    text.extend(self._render_table(element))
                case 'table_head' | 'table_body' | 'table_row' | 'table_cell':
                    # Handled by _render_table; fallback if reached directly.
                    if 'children' in element:
                        text.extend(self.toUrwidMarkup(element['children']))
                case 'inline_html':
                    raw = element.get('raw', '')
                    if raw.lower().startswith(('<br', '<br/')):
                        text.append("\n")
                    # else: silently drop other inline HTML
                case 'image' | 'block_html' | 'blank_line':
                    # image, HTML comments, and blank lines - do nothing
                    pass
                case 'codespan':
                    text.append(('md-codespan', element.get('raw', '')))
                case 'list':
                    attrs = element.get('attrs', {})
                    ordered = attrs.get('ordered', False)
                    depth = attrs.get('depth', 0)
                    if ordered:
                        idx = 1
                        for li in element['children']:
                            text.append("  " * depth + "%s. " % idx)
                            text.extend(self.toUrwidMarkup([li]))
                            idx += 1
                    else:
                        for li in element['children']:
                            text.append("  " * depth + "- ")
                            text.extend(self.toUrwidMarkup([li]))
                case 'list_item':
                    text.extend(self.toUrwidMarkup(element['children']))
                case 'block_text':
                    text.extend(self.toUrwidMarkup(element['children']))
                    text.append("\n")
                case 'link':
                    url = element.get('attrs', {}).get('url', '')
                    link_text = ""
                    for child in element['children']:
                        if child.get('raw'):
                            link_text += child['raw']
                        elif child.get('alt'):
                            link_text += child['alt']
                    link = mywid.Link(link_text, 'link', 'focused-link')
                    urwid.connect_signal(link, 'selected',
                        lambda link:self.app.openURL(url))
                    text.append(link)
                case _:
                    self.log.warning("unknown element type: %s", element['type'])
                    if 'children' in element:
                        text.extend(self.toUrwidMarkup(element['children']))
        return text

    def needsNewLine(self, text):
        if len(text) == 0 or text == ["\n"]:
            return False

        last_element = text[-1]
        second_to_last_element = ""
        if len(text) > 1:
            second_to_last_element = text[-2]

        while not isinstance(last_element, str):
            while isinstance(last_element, list):
                if len(last_element) > 1:
                    second_to_last_element = last_element[-2]
                if len(last_element) > 0:
                    last_element = last_element[-1]
                else:
                    # Should not get empty list
                    return False
            while isinstance(last_element, tuple):
                last_element = last_element[-1]
            # Just to make sure we don't enter an infinite loop
            if not (isinstance(last_element, list) or isinstance(last_element, str)):
                return False

        if last_element.endswith("\n\n"):
            return False

        if last_element == "\n":
            # Need to look in second to last element
            while not isinstance(second_to_last_element, str):
                while isinstance(second_to_last_element, list):
                    if len(second_to_last_element) > 0:
                        second_to_last_element = second_to_last_element[-1]
                    else:
                        # Should not get empty list
                        return False
                while isinstance(second_to_last_element, tuple):
                    second_to_last_element = second_to_last_element[-1]
                # Just to make sure we don't enter an infinite loop
                if not (isinstance(second_to_last_element, list) or isinstance(second_to_last_element, str)):
                    return False

            if second_to_last_element.endswith("\n"):
                return False

        return True
        

    def render(self, text):
        """Render markdown *text* into a flat urwid markup list."""
        if not text:
            return []
        ast = self._parser(text)
        return self.toUrwidMarkup(ast)

    def _expand_blockquote_details(self, ast):
        """Lift ``<details>`` blocks out of block-quotes.

        When a ``block_quote`` node's children contain ``<details>``
        sections, the quote is split so that each details section
        becomes a top-level segment (processable by
        ``_group_details`` / ``render_structured``) while the
        surrounding text stays in separate ``block_quote`` nodes.
        """
        result = []
        for node in ast:
            if node['type'] != 'block_quote':
                result.append(node)
                continue

            sub = self._group_details(node['children'])
            if not any(s[0] == 'details' for s in sub):
                result.append(node)
                continue

            # Split the blockquote.
            for seg in sub:
                if seg[0] == 'text':
                    if seg[1]:
                        result.append({
                            'type': 'block_quote',
                            'children': seg[1],
                        })
                else:
                    _, summary, detail_nodes = seg
                    result.append({
                        'type': 'block_html',
                        'raw': '<details><summary>%s</summary>'
                               % summary,
                    })
                    result.extend(detail_nodes)
                    result.append({
                        'type': 'block_html',
                        'raw': '</details>',
                    })

        return result

    def render_structured(self, text):
        """Render markdown into structured segments.

        Returns a list of segment tuples:

        * ``('text', urwid_markup_list)`` — plain content
        * ``('details', summary_str, urwid_markup_list)`` —
          collapsible ``<details>`` section
        """
        if not text:
            return [('text', [])]

        ast = self._parser(text)
        ast = self._expand_blockquote_details(ast)
        grouped = self._group_details(ast)

        segments = []
        for seg in grouped:
            if seg[0] == 'text':
                markup = self.toUrwidMarkup(seg[1])
                if markup:
                    segments.append(('text', markup))
            else:  # 'details'
                _, summary, detail_nodes = seg
                body_markup = self.toUrwidMarkup(detail_nodes)
                segments.append(('details', summary, body_markup))

        if not segments:
            segments = [('text', [])]

        return segments
