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

import ply.lex as lex
import six

operators = {
    'age': 'OP_AGE', # Hubtty extension
    'recentlyseen': 'OP_RECENTLYSEEN', # Hubtty extension
    'change': 'OP_CHANGE',
    'author': 'OP_AUTHOR',
    'reviewed-by': 'OP_REVIEWEDBY',
    'commenter': 'OP_COMMENTER',
    'mentions': 'OP_MENTIONS',
    'involves': 'OP_INVOLVES',
    'review': 'OP_REVIEW',
    'created': 'OP_CREATED',
    'updated': 'OP_UPDATED',
    'user': 'OP_USER',
    'org': 'OP_ORG',
    'repo': 'OP_REPO',
    'commit': 'OP_COMMIT',
    '_project_key': 'OP_PROJECT_KEY',  # internal hubtty use only
    'branch': 'OP_BRANCH',
    'base': 'OP_BASE',
    #'tr': 'OP_TR', # needs trackingids
    #'bug': 'OP_BUG', # needs trackingids
    'file': 'OP_FILE',
    'path': 'OP_PATH',
    'has': 'OP_HAS',
    'in': 'OP_IN',
    'is': 'OP_IS',
    'state': 'OP_STATE',
    'limit': 'OP_LIMIT',
    'label': 'OP_LABEL',
    }

reserved = {
    'or|OR': 'OR',
    'not|NOT': 'NOT',
    }

tokens = [
    'OP',
    'AND',
    'OR',
    'NOT',
    'NEG',
    'LPAREN',
    'RPAREN',
    'NUMBER',
    'CHANGE_ID',
    'SSTRING',
    'DSTRING',
    'USTRING',
    'DATE',
    'DATECOMP',
    #'REGEX',
    #'SHA',
    ] + list(operators.values())

def SearchTokenizer():
    t_LPAREN = r'\('   # NOQA
    t_RPAREN = r'\)'   # NOQA
    t_NEG    = r'[-!]' # NOQA
    t_ignore = ' \t'   # NOQA (and intentionally not using r'' due to tab char)

    def t_OP(t):
        r'[a-zA-Z_][a-zA-Z_-]*:'
        t.type = operators.get(t.value[:-1], 'OP')
        return t

    def t_CHANGE_ID(t):
        r'([a-zA-Z_]+/)+\d+'
        return t

    def t_SSTRING(t):
        r"'([^\\']+|\\'|\\\\)*'"
        t.value = t.value[1:-1]
        if not isinstance(t.value, six.text_type):
            t.value = t.value.decode('string-escape')
        return t

    def t_DSTRING(t):
        r'"([^\\"]+|\\"|\\\\)*"'
        t.value = t.value[1:-1]
        if not isinstance(t.value, six.text_type):
            t.value = t.value.decode('string-escape')
        return t

    def t_DATE(t):
        r'\d{4}(-\d\d(-\d\d(T\d\d:\d\d(:\d\d)?(\.\d+)?(([+-]\d\d:\d\d)|Z)?)?)?)?'
        return t

    def t_DATECOMP(t):
        r'[<>]=?\d{4}(-\d\d(-\d\d(T\d\d:\d\d(:\d\d)?(\.\d+)?(([+-]\d\d:\d\d)|Z)?)?)?)?'
        return t

    def t_AND(t):
        r'and|AND'
        return t

    def t_OR(t):
        r'or|OR'
        return t

    def t_NOT(t):
        r'not|NOT'
        return t

    def t_INTEGER(t):
        r'[+-]\d+\b'
        t.value = int(t.value)
        return t

    def t_NUMBER(t):
        r'\d+\b'
        t.value = int(t.value)
        return t

    def t_USTRING(t):
        r'([^\s\(\)!-][^\s\(\)!]*)'
        t.value = six.b(t.value).decode("unicode_escape")
        return t

    def t_newline(t):
        r'\n+'
        t.lexer.lineno += len(t.value)

    def t_error(t):
        print("Illegal character '%s'" % t.value[0])
        t.lexer.skip(1)

    return lex.lex()
