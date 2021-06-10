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
from sqlalchemy.sql.expression import and_

from hubtty.search import tokenizer, parser
import hubtty.db


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
                if (x.table != hubtty.db.change_table
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
        if hubtty.db.project_table in tables:
            result = and_(hubtty.db.change_table.c.project_key == hubtty.db.project_table.c.key,
                          result)
            tables.remove(hubtty.db.project_table)
        if hubtty.db.account_table in tables:
            result = and_(hubtty.db.change_table.c.account_key == hubtty.db.account_table.c.key,
                          result)
            tables.remove(hubtty.db.account_table)
        if hubtty.db.file_table in tables:
            result = and_(hubtty.db.file_table.c.commit_key == hubtty.db.commit_table.c.key,
                          hubtty.db.commit_table.c.change_key == hubtty.db.change_table.c.key,
                          result)
            tables.remove(hubtty.db.file_table)
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
    def my_account():
      return 1
    search = SearchCompiler(my_account)
    x = search.parse(query)
    print(x)
