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
            if element['type'] == 'text':
                text.append(element['text'])
            elif element['type'] == 'strong':
                text.append(('md-strong', self.toUrwidMarkup(element['children'])))
            elif element['type'] == 'emphasis':
                text.append(('md-emphasis', self.toUrwidMarkup(element['children'])))
            elif element['type'] == 'strikethrough':
                text.append(('md-strikethrough', self.toUrwidMarkup(element['children'])))
            elif element['type'] == 'heading':
                text.append(('md-heading', ["#" * element['level'], " ", self.toUrwidMarkup(element['children']), "\n"]))
            elif element['type'] == 'paragraph':
                text.extend(self.toUrwidMarkup(element['children']))
                text.append("\n")
            elif element['type'] == 'newline':
                text.append("\n")
            elif element['type'] == 'block_quote':
                text.append(('md-blockquote', ["| ", self.toUrwidMarkup(element['children'])]))
            elif element['type'] == 'block_code':
                info = element['info']
                if info == None:
                    info = ""
                text.append(('md-blockcode', ["```%s\n" % info, element['text'], "```\n"]))
            elif element['type'] == 'block_html':
                # HTML comments - do nothing
                pass
            elif element['type'] == 'codespan':
                text.append(('md-codespan', element['text']))
            elif element['type'] == 'list':
                if element['ordered']:
                    idx = 1
                    for li in element['children']:
                        text.append("  " * element['level'] + "%s. " % idx)
                        text.extend(self.toUrwidMarkup([li]))
                        idx += 1
                else:
                    for li in element['children']:
                        text.append("  " * element['level'] + "- ")
                        text.extend(self.toUrwidMarkup([li]))
            elif element['type'] == 'list_item':
                text.extend(self.toUrwidMarkup(element['children']))
            elif element['type'] == 'block_text':
                text.extend(self.toUrwidMarkup(element['children']))
                text.append("\n")
            elif element['type'] == 'link':
                url = element['link']
                link_text = ""
                for child in element['children']:
                    if child.get('text'):
                        link_text += child['text']
                    elif child.get('alt'):
                        link_text += child['alt']
                link = mywid.Link(link_text, 'link', 'focused-link')
                urwid.connect_signal(link, 'selected',
                    lambda link:self.app.openURL(url))
                text.append(link)
            else:
                self.log.warning("unknown element type: %s" % element['type'])
                if 'children' in element:
                    text.extend(self.toUrwidMarkup(element['children']))
        return text
        

    def render(self, text):
        md = mistune.create_markdown(renderer=mistune.AstRenderer(), plugins=['strikethrough'])
        ast = md(text)
        return self.toUrwidMarkup(ast)
