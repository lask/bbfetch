import io
import os
import json
import pprint
import html5lib

from requests.compat import urljoin

import blackboard
from blackboard import logger, ParserError, BlackBoardSession
from blackboard.datatable import fetch_datatable
from blackboard.elementtext import (
    element_to_markdown, element_text_content, form_field_value)


NS = {'h': 'http://www.w3.org/1999/xhtml'}


def fetch_overview(session):
    """Fetch gradebook information. Returns (assignments, students)."""
    assert isinstance(session, BlackBoardSession)
    url = (
        'https://bb.au.dk/webapps/gradebook/do/instructor/getJSONData' +
        '?course_id=%s' % session.course_id)
    response = session.get(url)
    try:
        o = response.json()
    except json.decoder.JSONDecodeError:
        raise ParserError("Couldn't decode JSON", response)

    columns = o['colDefs']
    assignments = {}
    for c in columns:
        if c.get('src') != 'resource/x-bb-assignment':
            continue
        assignments[c['id']] = c

    users = {}
    for row in o['rows']:
        user_id = row[0]['uid']
        user_available = row[0]['avail']

        user_cells = {cell['c']: cell for cell in row if 'c' in cell}
        user_data = {cell['c']: cell['v'] for cell in row if 'v' in cell}

        user_assignments = {}

        for a in assignments.keys():
            try:
                cell = user_cells[a]
            except KeyError:
                continue
            needs_grading = bool(cell.get('ng'))
            user_assignments[a] = {
                'score': cell['v'],
                'needs_grading': needs_grading,
                'attempts': None,
            }

        users[user_id] = dict(
            first_name=user_data['FN'],
            last_name=user_data['LN'],
            username=user_data['UN'],
            student_number=user_data['SI'],
            last_access=user_data['LA'],
            id=user_id,
            available=user_available,
            assignments=user_assignments,
        )

    return assignments, users


def fetch_attempt(session, attempt_id, is_group_assignment):
    assert isinstance(session, BlackBoardSession)
    if is_group_assignment:
        url = ('https://bb.au.dk/webapps/assignment/' +
               'gradeAssignmentRedirector' +
               '?course_id=%s' % session.course_id +
               '&groupAttemptId=%s' % attempt_id)
    else:
        url = ('https://bb.au.dk/webapps/assignment/' +
               'gradeAssignmentRedirector' +
               '?course_id=%s' % session.course_id +
               '&attempt_id=%s' % attempt_id)
    response = session.get(url)
    document = html5lib.parse(response.content, encoding=response.encoding)

    submission_text = document.find(
        './/h:div[@id="submissionTextView"]', NS)
    if submission_text is not None:
        submission_text = element_to_markdown(submission_text)

    comments = document.find(
        './/h:div[@id="currentAttempt_comments"]', NS)
    if comments is not None:
        xpath = './/h:div[@class="vtbegenerated"]'
        comments = [
            element_to_markdown(e)
            for e in comments.findall(xpath, NS)
        ]
        if not comments:
            raise blackboard.ParserError(
                "Page contains currentAttempt_comments, " +
                "but it contains no comments",
                response)
        comments = '\n\n'.join(comments)

    files = []
    submission_list = document.find(
        './/h:ul[@id="currentAttempt_submissionList"]', NS)
    if submission_list is None:
        raise ParserError("No currentAttempt_submissionList",
                          response)
    for submission in submission_list:
        filename = element_text_content(submission)
        download_button = submission.find(
            './/h:a[@class="dwnldBtn"]', NS)
        if download_button is not None:
            download_link = urljoin(
                response.url, download_button.get('href'))
            files.append(
                dict(filename=filename, download_link=download_link))
        else:
            s = 'currentAttempt_attemptFilesubmissionText'
            a = submission.find(
                './/h:a[@id="' + s + '"]', NS)
            if a is not None:
                # This <li> is for the submission_text
                if not submission_text:
                    raise blackboard.ParserError(
                        "%r in file list, but no " % (filename,) +
                        "accompanying submission text contents",
                        response)
            else:
                raise blackboard.ParserError(
                    "No download link for file %r" % (filename,),
                    response)

    score_input = document.find(
        './/h:input[@id="currentAttempt_grade"]', NS)
    if score_input is None:
        score = None
    else:
        score = form_field_value(score_input)
        try:
            score = float(score)
        except ValueError:
            if score:
                raise blackboard.ParserError(
                    "Couldn't parse currentAttempt_grade: %r" % (score,),
                    response)
            score = None

    feedbacktext_input = document.find(
        './/*[@id="feedbacktext"]', NS)
    if feedbacktext_input is None:
        feedback = ''
    else:
        feedback = form_field_value(feedbacktext_input)

    feedbackfiles_rows = document.find(
        './/h:tbody[@id="feedbackFiles_table_body"]', NS)
    feedbackfiles = []
    for i, row in enumerate(feedbackfiles_rows or []):
        try:
            link = row.findall('.//h:a', NS)[0]
        except IndexError:
            raise blackboard.ParserError(
                "feedbackFiles_table_body row %s: no link" % i,
                response)
        download_link = urljoin(
            response.url, link.get('href'))
        filename = element_text_content(link)
        feedbackfiles.append(
            dict(filename=filename, download_link=download_link))

    return dict(
        submission=submission_text,
        comments=comments,
        files=files,
        feedback=feedback,
        feedbackfiles=feedbackfiles,
        score=score,
    )


def submit_grade(session, attempt_id, is_group_assignment,
                 grade, text, filenames):
    assert isinstance(session, BlackBoardSession)
    if is_group_assignment:
        url = ('https://bb.au.dk/webapps/assignment/' +
               'gradeAssignmentRedirector' +
               '?course_id=%s' % session.course_id +
               '&groupAttemptId=%s' % attempt_id)
    else:
        url = ('https://bb.au.dk/webapps/assignment/' +
               'gradeAssignmentRedirector' +
               '?course_id=%s' % session.course_id +
               '&attempt_id=%s' % attempt_id)
    # We need to fetch the page to get the nonce
    response = session.get(url)
    document = html5lib.parse(response.content, encoding=response.encoding)
    form = document.find('.//h:form[@id="currentAttempt_form"]', NS)
    if form is None:
        raise ParserError("No <form id=currentAttempt_form>", response)
    fields = (form.findall('.//h:input', NS) +
              form.findall('.//h:textarea', NS))
    data = [
        (field.get('name'), field.get('value') or '')
        for field in fields
        if field.get('name')
    ]
    data_lookup = {k: i for i, (k, v) in enumerate(data)}

    def data_get(k, *args):
        if args:
            d, = args
        try:
            return data[data_lookup[k]][1]
        except KeyError:
            if args:
                return d
            raise

    def data_set(k, v):
        try:
            data[data_lookup[k]] = k, v
        except KeyError:
            data_lookup[k] = len(data)
            data.append((k, v))

    def data_extend(kvs):
        for k, v in kvs:
            data_lookup[k] = len(data)
            data.append((k, v))

    data_set('grade', str(grade))
    data_set('feedbacktext', text)

    files = []

    for i, filename in enumerate(filenames):
        base = os.path.basename(filename)
        data_extend([
            ('feedbackFiles_attachmentType', 'L'),
            ('feedbackFiles_fileId', 'new'),
            ('feedbackFiles_artifactFileId', 'undefined'),
            ('feedbackFiles_artifactType', 'undefined'),
            ('feedbackFiles_artifactTypeResourceKey', 'undefined'),
            ('feedbackFiles_linkTitle', base),
        ])
        with open(filename, 'rb') as fp:
            fdata = fp.read()
        files.append(('feedbackFiles_LocalFile%d' % i, (base, fdata)))
    post_url = (
        'https://bb.au.dk/webapps/assignment//gradeGroupAssignment/submit')
    if not files:
        # BlackBoard requires the POST to be
        # Content-Type: multipart/form-data.
        # Unfortunately, requests can only make a form-data POST
        # if it has file-like input in the files list.
        files = [('dummy', io.StringIO(''))]
    try:
        response = session.post(post_url, data=data, files=files)
    except:
        logger.exception("data=%r files=%r", data, files)
        raise
    document = html5lib.parse(response.content, encoding=response.encoding)
    badmsg = document.find('.//h:span[@id="badMsg1"]', NS)
    if badmsg is not None:
        raise ParserError(
            "badMsg1: %s" % element_text_content(badmsg), response,
            'Post data:\n%s' % pprint.pformat(data),
            'Files:\n%s' % pprint.pformat(files))
    msg = document.find('.//h:span[@id="goodMsg1"]', NS)
    if msg is None:
        raise ParserError(
            "No goodMsg1 in POST response", response,
            'Post data:\n%s' % pprint.pformat(data),
            'Files:\n%s' % pprint.pformat(files))
    logger.debug("goodMsg1: %s", element_text_content(msg))


def fetch_groups(session):
    def strip_prefix(s, prefix):
        if s.startswith(prefix):
            return s[len(prefix):]
        else:
            raise ValueError("%r does not start with %r" % (s, prefix))

    def extract(key, cell, d):
        if key != 'Groups':
            return d
        groups = cell.findall(
            './/h:a[@class="userGroupNameListItemRemove"]', NS)
        res = []
        for g in groups:
            name = ' '.join(''.join(g.itertext()).split())
            i = g.get('id')
            res.append((name, strip_prefix(i, 'rmv_')))
        return res

    url = ('https://bb.au.dk/webapps/bb-group-mgmt-LEARN/execute/' +
           'groupInventoryList?course_id=%s' % session.course_id +
           '&toggleType=users&chkAllRoles=on')

    response, keys, rows = fetch_datatable(
        session, url, extract=extract, table_id='userGroupList_datatable')
    username = keys.index('userorgroupname')
    first_name = keys.index('firstname')
    last_name = keys.index('lastname')
    role = keys.index('Role')
    groups = keys.index('Groups')
    users = {}
    for row in rows:
        users[row[username]] = dict(
            username=row[username],
            first_name=row[first_name],
            last_name=row[last_name],
            role=row[role],
            groups=row[groups],
        )
    return users
