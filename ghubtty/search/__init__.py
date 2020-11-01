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

import sqlalchemy.sql.expression
from sqlalchemy.sql.expression import and_, select, func

from ghubtty.search import tokenizer, parser
import ghubtty.db


class SearchSyntaxError(Exception):
    def __init__(self, message):
        self.message = message


class SearchCompiler(object):
    def __init__(self, get_account_id):
        self.get_account_id = get_account_id
        self.lexer = tokenizer.SearchTokenizer()
        self.parser = parser.SearchParser()
        self.parser.account_id = None

    def findTables(self, expression):
        tables = set()
        stack = [expression]
        while stack:
            x = stack.pop()
            if hasattr(x, 'table'):
                if (x.table != ghubtty.db.change_table
                    and hasattr(x.table, 'name')):
                    tables.add(x.table)
            for child in x.get_children():
                if not isinstance(child, sqlalchemy.sql.selectable.Select):
                    stack.append(child)
        return tables

    def parse(self, data):
        if self.parser.account_id is None:
            self.parser.account_id = self.get_account_id()
        if self.parser.account_id is None:
            raise Exception("Own account is unknown")
        result = self.parser.parse(data, lexer=self.lexer)
        tables = self.findTables(result)
        if ghubtty.db.project_table in tables:
            result = and_(ghubtty.db.change_table.c.project_key == ghubtty.db.project_table.c.key,
                          result)
            tables.remove(ghubtty.db.project_table)
        if ghubtty.db.account_table in tables:
            result = and_(ghubtty.db.change_table.c.account_key == ghubtty.db.account_table.c.key,
                          result)
            tables.remove(ghubtty.db.account_table)
        if ghubtty.db.file_table in tables:
            # We only want to look at files for the most recent
            # revision.
            s = select([func.max(ghubtty.db.revision_table.c.number)], correlate=False).where(
                ghubtty.db.revision_table.c.change_key==ghubtty.db.change_table.c.key).correlate(ghubtty.db.change_table)
            result = and_(ghubtty.db.file_table.c.revision_key == ghubtty.db.revision_table.c.key,
                          ghubtty.db.revision_table.c.change_key == ghubtty.db.change_table.c.key,
                          ghubtty.db.revision_table.c.number == s,
                          result)
            tables.remove(ghubtty.db.file_table)
        if tables:
            raise Exception("Unknown table in search: %s" % tables)
        return result

if __name__ == '__main__':
    class Dummy(object):
        pass
    query = 'recentlyseen:24 hours'
    lexer = tokenizer.SearchTokenizer()
    lexer.input(query)
    while True:
        token = lexer.token()
        if not token:
            break
        print(token)

    app = Dummy()
    app.config = Dummy()
    app.config.username = 'bob'
    search = SearchCompiler(app.config.username)
    x = search.parse(query)
    print(x)
