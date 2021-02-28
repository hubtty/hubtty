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

import datetime
import re

import ply.yacc as yacc
from sqlalchemy.sql.expression import and_, or_, not_, select, func

import hubtty.db
import hubtty.search
from hubtty.search.tokenizer import tokens  # NOQA

def age_to_delta(delta, unit):
    if unit in ['seconds', 'second', 'sec', 's']:
        pass
    elif unit in ['minutes', 'minute', 'min', 'm']:
        delta = delta * 60
    elif unit in ['hours', 'hour', 'hr', 'h']:
        delta = delta * 60 * 60
    elif unit in ['days', 'day', 'd']:
        delta = delta * 60 * 60 * 24
    elif unit in ['weeks', 'week', 'w']:
        delta = delta * 60 * 60 * 24 * 7
    elif unit in ['months', 'month', 'mon']:
        delta = delta * 60 * 60 * 24 * 30
    elif unit in ['years', 'year', 'y']:
        delta = delta * 60 * 60 * 24 * 365
    return delta

def SearchParser():
    precedence = (  # NOQA
        ('left', 'NOT', 'NEG'),
    )

    def p_terms(p):
        '''expression : list_expr
                      | paren_expr
                      | boolean_expr
                      | negative_expr
                      | term'''
        p[0] = p[1]

    def p_list_expr(p):
        '''list_expr : expression expression'''
        p[0] = and_(p[1], p[2])

    def p_paren_expr(p):
        '''paren_expr : LPAREN expression RPAREN'''
        p[0] = p[2]

    def p_boolean_expr(p):
        '''boolean_expr : expression AND expression
                        | expression OR expression'''
        if p[2].lower() == 'and':
            p[0] = and_(p[1], p[3])
        elif p[2].lower() == 'or':
            p[0] = or_(p[1], p[3])
        else:
            raise hubtty.search.SearchSyntaxError("Boolean %s not recognized" % p[2])

    def p_negative_expr(p):
        '''negative_expr : NOT expression
                         | NEG expression'''
        p[0] = not_(p[2])

    def p_term(p):
        '''term : age_term
                | recentlyseen_term
                | change_term
                | author_term
                | reviewed-by_term
                | commenter_term
                | mentions_term
                | involves_term
                | commit_term
                | project_term
                | projects_term
                | project_key_term
                | branch_term
                | ref_term
                | label_term
                | message_term
                | comment_term
                | has_term
                | is_term
                | status_term
                | file_term
                | path_term
                | limit_term
                | op_term'''
        p[0] = p[1]

    def p_string(p):
        '''string : SSTRING
                  | DSTRING
                  | USTRING'''
        p[0] = p[1]

    def p_age_term(p):
        '''age_term : OP_AGE NUMBER string'''
        now = datetime.datetime.utcnow()
        delta = p[2]
        unit = p[3]
        delta = age_to_delta(delta, unit)
        p[0] = hubtty.db.change_table.c.updated < (now-datetime.timedelta(seconds=delta))

    def p_recentlyseen_term(p):
        '''recentlyseen_term : OP_RECENTLYSEEN NUMBER string'''
        # A hubtty extension
        delta = p[2]
        unit = p[3]
        delta = age_to_delta(delta, unit)
        s = select([func.datetime(func.max(hubtty.db.change_table.c.last_seen), '-%s seconds' % delta)],
                   correlate=False)
        p[0] = hubtty.db.change_table.c.last_seen >= s

    def p_change_term(p):
        '''change_term : OP_CHANGE CHANGE_ID
                       | OP_CHANGE NUMBER'''
        if type(p[2]) == int:
            p[0] = hubtty.db.change_table.c.number == p[2]
        else:
            p[0] = hubtty.db.change_table.c.change_id == p[2]

    def p_author_term(p):
        '''author_term : OP_AUTHOR string'''
        if p[2] == 'self':
            account_id = p.parser.account_id
            p[0] = hubtty.db.account_table.c.id == account_id
        else:
            p[0] = or_(hubtty.db.account_table.c.username == p[2],
                       hubtty.db.account_table.c.email == p[2],
                       hubtty.db.account_table.c.name == p[2])

    def p_reviewed_by_term(p):
        '''reviewed-by_term : OP_REVIEWEDBY string
                            | OP_REVIEWEDBY NUMBER'''
        filters = []
        filters.append(hubtty.db.approval_table.c.change_key == hubtty.db.change_table.c.key)
        filters.append(hubtty.db.approval_table.c.account_key == hubtty.db.account_table.c.key)
        try:
            number = int(p[2])
        except:
            number = None
        if number is not None:
            filters.append(hubtty.db.account_table.c.id == number)
        elif p[2] == 'self':
            account_id = p.parser.account_id
            filters.append(hubtty.db.account_table.c.id == account_id)
        else:
            filters.append(or_(hubtty.db.account_table.c.username == p[2],
                               hubtty.db.account_table.c.email == p[2],
                               hubtty.db.account_table.c.name == p[2]))
        s = select([hubtty.db.change_table.c.key], correlate=False).where(and_(*filters))
        p[0] = hubtty.db.change_table.c.key.in_(s)

    def p_commenter_term(p):
        '''commenter_term : OP_COMMENTER string
                          | OP_COMMENTER NUMBER'''
        filters = []
        filters.append(and_(hubtty.db.message_table.c.change_key == hubtty.db.change_table.c.key,
                            hubtty.db.message_table.c.commit_key == None))
        filters.append(hubtty.db.message_table.c.account_key == hubtty.db.account_table.c.key)
        try:
            number = int(p[2])
        except:
            number = None
        if number is not None:
            filters.append(hubtty.db.account_table.c.id == number)
        elif p[2] == 'self':
            account_id = p.parser.account_id
            filters.append(hubtty.db.account_table.c.id == account_id)
        else:
            filters.append(or_(hubtty.db.account_table.c.username == p[2],
                               hubtty.db.account_table.c.email == p[2],
                               hubtty.db.account_table.c.name == p[2]))
        s = select([hubtty.db.change_table.c.key], correlate=False).where(and_(*filters))
        p[0] = hubtty.db.change_table.c.key.in_(s)

    def p_mentions_term(p):
        '''mentions_term : OP_MENTIONS string'''
        # Currently search for mentions in PR messages and comments
        # TODO(mandre) might want to extend to commit messages and PR bodies as well
        filters = []
        filters.append(hubtty.db.message_table.c.change_key == hubtty.db.change_table.c.key)
        filters.append(hubtty.db.message_table.c.message.like('%%@%s%%' % p[2]))
        message_select = select([hubtty.db.change_table.c.key], correlate=False).where(and_(*filters))

        filters = []
        filters.append(hubtty.db.message_table.c.change_key == hubtty.db.change_table.c.key)
        filters.append(hubtty.db.comment_table.c.message_key == hubtty.db.message_table.c.key)
        filters.append(hubtty.db.comment_table.c.message.like('%%@%s%%' % p[2]))
        comment_select = select([hubtty.db.change_table.c.key], correlate=False).where(and_(*filters))

        p[0] = or_(hubtty.db.change_table.c.key.in_(message_select),
                   hubtty.db.change_table.c.key.in_(comment_select))

    def p_involves_term(p):
        '''involves_term : OP_INVOLVES string'''
        # According to github, involves is the union of: author, assignee,
        # mentions, and commenter.  We're however not yet syncing assignee so
        # we're using reviewed-by that has the same effect.

        filters = []
        filters.append(hubtty.db.approval_table.c.change_key == hubtty.db.change_table.c.key)
        filters.append(hubtty.db.approval_table.c.account_key == hubtty.db.account_table.c.key)
        filters.append(hubtty.db.account_table.c.username == p[2])
        reviewer_select = select([hubtty.db.change_table.c.key], correlate=False).where(and_(*filters))

        # TODO(mandre) might want to extend to commit messages and PR bodies as well
        filters = []
        filters.append(hubtty.db.message_table.c.change_key == hubtty.db.change_table.c.key)
        filters.append(hubtty.db.message_table.c.message.like('%%@%s%%' % p[2]))
        mentions_message_select = select([hubtty.db.change_table.c.key], correlate=False).where(and_(*filters))

        filters = []
        filters.append(hubtty.db.message_table.c.change_key == hubtty.db.change_table.c.key)
        filters.append(hubtty.db.comment_table.c.message_key == hubtty.db.message_table.c.key)
        filters.append(hubtty.db.comment_table.c.message.like('%%@%s%%' % p[2]))
        mentions_comment_select = select([hubtty.db.change_table.c.key], correlate=False).where(and_(*filters))

        filters = []
        filters.append(and_(hubtty.db.message_table.c.change_key == hubtty.db.change_table.c.key,
                            hubtty.db.message_table.c.commit_key == None))
        filters.append(hubtty.db.message_table.c.account_key == hubtty.db.account_table.c.key)
        filters.append(hubtty.db.account_table.c.username == p[2])
        commenter_select = select([hubtty.db.change_table.c.key], correlate=False).where(and_(*filters))

        p[0] = or_(hubtty.db.account_table.c.username == p[2],
                   hubtty.db.change_table.c.key.in_(reviewer_select),
                   hubtty.db.change_table.c.key.in_(mentions_message_select),
                   hubtty.db.change_table.c.key.in_(mentions_comment_select),
                   hubtty.db.change_table.c.key.in_(commenter_select))

    def p_commit_term(p):
        '''commit_term : OP_COMMIT string'''
        filters = []
        filters.append(hubtty.db.commit_table.c.change_key == hubtty.db.change_table.c.key)
        filters.append(hubtty.db.commit_table.c.commit == p[2])
        s = select([hubtty.db.change_table.c.key], correlate=False).where(and_(*filters))
        p[0] = hubtty.db.change_table.c.key.in_(s)

    def p_project_term(p):
        '''project_term : OP_PROJECT string'''
        if p[2].startswith('^'):
            p[0] = func.matches(p[2], hubtty.db.project_table.c.name)
        else:
            p[0] = hubtty.db.project_table.c.name == p[2]

    def p_projects_term(p):
        '''projects_term : OP_PROJECTS string'''
        p[0] = hubtty.db.project_table.c.name.like('%s%%' % p[2])

    def p_project_key_term(p):
        '''project_key_term : OP_PROJECT_KEY NUMBER'''
        p[0] = hubtty.db.change_table.c.project_key == p[2]

    def p_branch_term(p):
        '''branch_term : OP_BRANCH string'''
        if p[2].startswith('^'):
            p[0] = func.matches(p[2], hubtty.db.change_table.c.branch)
        else:
            p[0] = hubtty.db.change_table.c.branch == p[2]

    def p_ref_term(p):
        '''ref_term : OP_REF string'''
        if p[2].startswith('^'):
            p[0] = func.matches(p[2], 'refs/heads/'+hubtty.db.change_table.c.branch)
        else:
            p[0] = hubtty.db.change_table.c.branch == p[2][len('refs/heads/'):]

    label_re = re.compile(r'(?P<label>[a-zA-Z0-9_-]+([a-zA-Z]|((?<![-+])[0-9])))'
                          r'(?P<operator>[<>]?=?)(?P<value>[-+]?[0-9]+)'
                          r'($|,(user=)?(?P<user>\S+))')

    def p_label_term(p):
        '''label_term : OP_LABEL string'''
        args = label_re.match(p[2])
        label = args.group('label')
        op = args.group('operator') or '='
        value = int(args.group('value'))
        user = args.group('user')

        filters = []
        filters.append(hubtty.db.approval_table.c.change_key == hubtty.db.change_table.c.key)
        filters.append(hubtty.db.approval_table.c.category == label)
        if op == '=':
            filters.append(hubtty.db.approval_table.c.value == value)
        elif op == '>=':
            filters.append(hubtty.db.approval_table.c.value >= value)
        elif op == '<=':
            filters.append(hubtty.db.approval_table.c.value <= value)
        if user is not None:
            filters.append(hubtty.db.approval_table.c.account_key == hubtty.db.account_table.c.key)
            if user == 'self':
                filters.append(hubtty.db.account_table.c.id == p.parser.account_id)
            else:
                filters.append(
                    or_(hubtty.db.account_table.c.username == user,
                        hubtty.db.account_table.c.email == user,
                        hubtty.db.account_table.c.name == user))
        s = select([hubtty.db.change_table.c.key], correlate=False).where(and_(*filters))
        p[0] = hubtty.db.change_table.c.key.in_(s)

    def p_message_term(p):
        '''message_term : OP_MESSAGE string'''
        filters = []
        filters.append(hubtty.db.commit_table.c.change_key == hubtty.db.change_table.c.key)
        filters.append(hubtty.db.commit_table.c.message.like('%%%s%%' % p[2]))
        s = select([hubtty.db.change_table.c.key], correlate=False).where(and_(*filters))
        p[0] = hubtty.db.change_table.c.key.in_(s)

    def p_comment_term(p):
        '''comment_term : OP_COMMENT string'''
        filters = []
        filters.append(hubtty.db.commit_table.c.change_key == hubtty.db.change_table.c.key)
        filters.append(hubtty.db.commit_table.c.message == p[2])
        commit_select = select([hubtty.db.change_table.c.key], correlate=False).where(and_(*filters))
        filters = []
        filters.append(hubtty.db.commit_table.c.change_key == hubtty.db.change_table.c.key)
        filters.append(hubtty.db.comment_table.c.commit_key == hubtty.db.commit_table.c.key)
        filters.append(hubtty.db.comment_table.c.message == p[2])
        comment_select = select([hubtty.db.change_table.c.key], correlate=False).where(and_(*filters))
        p[0] = or_(hubtty.db.change_table.c.key.in_(comment_select),
                   hubtty.db.change_table.c.key.in_(commit_select))

    def p_has_term(p):
        '''has_term : OP_HAS string'''
        #TODO: implement star
        if p[2] == 'draft':
            filters = []
            filters.append(hubtty.db.commit_table.c.change_key == hubtty.db.change_table.c.key)
            filters.append(hubtty.db.message_table.c.commit_key == hubtty.db.commit_table.c.key)
            filters.append(hubtty.db.message_table.c.draft == True)
            s = select([hubtty.db.change_table.c.key], correlate=False).where(and_(*filters))
            p[0] = hubtty.db.change_table.c.key.in_(s)
        else:
            raise hubtty.search.SearchSyntaxError('Syntax error: has:%s is not supported' % p[2])

    def p_is_term(p):
        '''is_term : OP_IS string'''
        #TODO: implement draft
        account_id = p.parser.account_id
        if p[2] == 'reviewed':
            filters = []
            filters.append(hubtty.db.approval_table.c.change_key == hubtty.db.change_table.c.key)
            filters.append(hubtty.db.approval_table.c.value != 0)
            s = select([hubtty.db.change_table.c.key], correlate=False).where(and_(*filters))
            p[0] = hubtty.db.change_table.c.key.in_(s)
        elif p[2] == 'open':
            p[0] = hubtty.db.change_table.c.state == 'open'
        elif p[2] == 'closed':
            p[0] = hubtty.db.change_table.c.state == 'closed'
        elif p[2] == 'merged':
            p[0] = hubtty.db.change_table.c.merged == True
        elif p[2] == 'unmerged' or p[2] == 'abandoned':
            p[0] = and_(hubtty.db.change_table.c.state == 'closed',
                        hubtty.db.change_table.c.merged == False)
        elif p[2] == 'author':
            p[0] = hubtty.db.account_table.c.id == account_id
        elif p[2] == 'starred':
            p[0] = hubtty.db.change_table.c.starred == True
        elif p[2] == 'held':
            # A hubtty extension
            p[0] = hubtty.db.change_table.c.held == True
        elif p[2] == 'reviewer':
            # A hubtty extension: synonym of reviewed-by:self
            filters = []
            filters.append(hubtty.db.approval_table.c.change_key == hubtty.db.change_table.c.key)
            filters.append(hubtty.db.approval_table.c.account_key == hubtty.db.account_table.c.key)
            filters.append(hubtty.db.account_table.c.id == account_id)
            s = select([hubtty.db.change_table.c.key], correlate=False).where(and_(*filters))
            p[0] = hubtty.db.change_table.c.key.in_(s)
        elif p[2] == 'watched':
            p[0] = hubtty.db.project_table.c.subscribed == True
        else:
            raise hubtty.search.SearchSyntaxError('Syntax error: is:%s is not supported' % p[2])

    def p_file_term(p):
        '''file_term : OP_FILE string'''
        if p[2].startswith('^'):
            p[0] = and_(or_(func.matches(p[2], hubtty.db.file_table.c.path),
                            func.matches(p[2], hubtty.db.file_table.c.old_path)),
                        hubtty.db.file_table.c.status is not None)
        else:
            file_re = '(^|.*/)%s(/.*|$)' % re.escape(p[2])
            p[0] = and_(or_(func.matches(file_re, hubtty.db.file_table.c.path),
                            func.matches(file_re, hubtty.db.file_table.c.old_path)),
                        hubtty.db.file_table.c.status is not None)

    def p_path_term(p):
        '''path_term : OP_PATH string'''
        if p[2].startswith('^'):
            p[0] = and_(or_(func.matches(p[2], hubtty.db.file_table.c.path),
                            func.matches(p[2], hubtty.db.file_table.c.old_path)),
                        hubtty.db.file_table.c.status is not None)
        else:
            p[0] = and_(or_(hubtty.db.file_table.c.path == p[2],
                            hubtty.db.file_table.c.old_path == p[2]),
                        hubtty.db.file_table.c.status is not None)

    def p_status_term(p):
        '''status_term : OP_STATUS string'''
        if p[2] == 'merged':
            p[0] = hubtty.db.change_table.c.merged == True
        elif p[2] == 'unmerged' or p[2] == 'abandoned':
            p[0] = and_(hubtty.db.change_table.c.state == 'closed',
                        hubtty.db.change_table.c.merged == False)
        else:
            p[0] = hubtty.db.change_table.c.state == p[2]

    def p_limit_term(p):
        '''limit_term : OP_LIMIT NUMBER'''
        # TODO: Implement this.  The sqlalchemy limit call needs to be
        # applied to the query operation and so can not be returned as
        # part of the production here.  The information would need to
        # be returned out-of-band.  In the mean time, since limits are
        # not as important in hubtty, make this a no-op for now so
        # that it does not produce a syntax error.
        p[0] = (True == True)

    def p_op_term(p):
        'op_term : OP'
        raise SyntaxError()

    def p_error(p):
        if p:
            raise hubtty.search.SearchSyntaxError('Syntax error at "%s" in search string "%s" (col %s)' % (
                    p.lexer.lexdata[p.lexpos:], p.lexer.lexdata, p.lexpos))
        else:
            raise hubtty.search.SearchSyntaxError('Syntax error: EOF in search string')

    return yacc.yacc(debug=0, write_tables=0)
