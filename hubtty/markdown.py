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
import mistune
import urwid

from hubtty import mywid

class Renderer:
    def __init__(self, app):
        self.log = logging.getLogger('hubtty.markdown')
        self.app = app

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
                case 'newline' | 'blank_line' | 'softbreak' | 'linebeak':
                    text.append("\n")
                case 'thematic_break':
                    text.append(('md-thematicbreak', "\n———————————————\n\n"))
                case 'block_quote':
                    text.append(('md-blockquote', ["| ", self.toUrwidMarkup(element['children'])]))
                case 'block_code':
                    info = element.get('attrs', {}).get('info', '')
                    if info is None:
                        info = ""
                    raw_code = element.get('raw', '')
                    text.append(('md-blockcode', ["```%s\n" % info, raw_code, "```\n"]))
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
        md = mistune.create_markdown(renderer='ast', plugins=['strikethrough'])
        # Misture returns newline for empty text, we don't want that
        if not text:
            return []
        ast = md(text)
        return self.toUrwidMarkup(ast)
