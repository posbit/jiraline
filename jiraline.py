#!/usr/bin/python

import datetime
import getpass
import json
import re
import subprocess
import sys
import os
import textwrap

import clap
import requests
import unidecode

try:
    import colored
except ImportError:
    colored = None


# Jiraline version
__version__ = '0.1.2'


filename_ui = os.path.expanduser('~/.local/share/jiraline/ui.json')

model = {}
with open(filename_ui, 'r') as ifstream: model = json.loads(ifstream.read())
args = list(clap.formatter.Formatter(sys.argv[1:]).format())
command = clap.builder.Builder(model).insertHelpCommand().build().get()
parser = clap.parser.Parser(command).feed(args)
checker = clap.checker.RedChecker(parser)

try:
    fail = True
    checker.check()
    fail = False
except clap.errors.UnrecognizedOptionError as e:
    print('unrecognized option found: {0}'.format(e))
except clap.errors.UIDesignError as e:
    print('misdesigned interface: {0}'.format(e))
except clap.errors.MissingArgumentError as e:
    print('missing argument for option: {0}'.format(e))
    fail = True
except clap.errors.ConflictingOptionsError as e:
    print('conflicting options found: {0}'.format(e))
    fail = True
except clap.errors.RequiredOptionNotFoundError as e:
    fail = True
    print('required option not found: {0}'.format(e))
except clap.errors.InvalidOperandRangeError as e:
    print('invalid number of operands: {0}'.format(e))
    fail = True
except clap.errors.UIDesignError as e:
    print('UI has design error: {0}'.format(e))
    fail = True
except clap.errors.AmbiguousCommandError as e:
    name, candidates = str(e).split(': ')
    print("ambiguous shortened command name: '{0}', candidates are: {1}".format(name, candidates))
    print("note: if this is a false positive use '--' operand separator")
    fail = True
except Exception as e:
    print('error: unhandled exception: {0}: {1}'.format(str(type(e))[8:-2], e))
    fail = True
finally:
    if fail: exit(1)
    ui = parser.parse().ui().finalise()

if clap.helper.HelpRunner(ui=ui, program=sys.argv[0]).adjust(options=['-h', '--help']).run().displayed(): exit(0)
if '--version' in ui:
    print(('jiraline version {}' if '--verbose' in ui else '{}').format(__version__))
    exit(0)


ui = ui.down()

def obtain(dictionary, *path, error=False, default=None):
    found = False
    value = dictionary
    path_length = len(path)-1
    for i, key in enumerate(path):
        if key not in value:
            if error:
                raise KeyError('.'.join(path))
            break
        value = value[key]
        if type(value) is not dict and i < path_length:
            if error:
                raise KeyError('.'.join(path))
            break
        if type(value) is not dict and i == path_length:
            found = True
        if i == path_length:
            found = True
    return (value if found else default)

class Cache:
    def __init__(self, issue_key, lazy=False):
        self._issue_key = issue_key
        self._data = {}
        if not lazy:
            self.load()

    @staticmethod
    def dir():
        return os.path.join(os.path.expanduser('~'), '.cache', 'jiraline')

    def path(self):
        return os.path.join(os.path.expanduser('~'), '.cache', 'jiraline', '{}.json'.format(self._issue_key))

    def raw(self):
        return self._data.copy()

    def response(self):
        raw_data = self.raw()
        offset_start = len('fields.')
        fields = dict([(key[offset_start:], value) for key, value in raw_data.items() if key.startswith('fields.')])
        return {
            'fields': fields,
            'key': raw_data.get('key'),
        }

    def is_cached(self):
        return os.path.isfile(self.path())

    def load(self):
        cached_path = self.path()
        if not os.path.isfile(cached_path):
            return self
        with open(cached_path) as ifstream:
            self._data = json.loads(ifstream.read())
        return self

    def store(self):
        cached_path = self.path()
        if not os.path.isdir(Cache.dir()):
            os.makedirs(Cache.dir(), exist_ok=True)
        with open(cached_path, 'w') as ofstream:
            ofstream.write(json.dumps(self._data))
        return self

    def get(self, *path, default=None):
        return self._data.get('.'.join(path), default)

    def set(self, *path, value):
        self._data['.'.join(path)] = value
        return self

class Settings:
    def __init__(self):
        self._settings = {}
        self._username = None
        self._password = None

    # Operator overloads suitable for settings objects.
    def __getitem__(self, key):
        return self._settings[key]

    def __contains__(self, key):
        return (key in self._settings)

    @staticmethod
    def get_settings_path():
        return os.path.expanduser(os.path.join('~', '.config', 'jiraline', 'config.json'))

    # Maintenance API.
    def load(self):
        self._settings = {}
        if not os.path.isfile(Settings.get_settings_path()):
            return self
        try:
            with open(Settings.get_settings_path()) as ifstream:
                self._settings = json.loads(ifstream.read())
        except json.decoder.JSONDecodeError as e:
            print('error: invalid settings format: {}'.format(e))
            exit(1)
        except Exception as e:
            print('error: failed loading settings: {}'.format(e))
            exit(1)
        return self

    # Low-level access API.
    def data(self):
        return self._settings

    def keys(self):
        return self._settings.keys()

    def items(self):
        return self._settings.items()

    def get(self, key, default=None):
        return self._settings.get(key, default)

    # High-level access API.
    def username(self):
        if self._username is not None: return self._username
        username = str(self._settings.get('credentials', {}).get('user', '')).strip()
        if not username:
            try:
                username = input('username: ')
            except (EOFError, KeyboardInterrupt) as e:
                print()
                exit(1)
        self._username = username
        return username

    def password(self):
        if self._password is not None: return self._password
        password = str(self._settings.get('credentials', {}).get('password', '')).strip()
        if not password:
            try:
                password = getpass.getpass('password: ')
            except (EOFError, KeyboardInterrupt) as e:
                print()
                exit(1)
        self._password = password
        return password

    def credentials(self):
        """Suitable for passing as 'auth' parameter to requests functions.
        """
        return (self.username(), self.password(),)

settings = Settings().load()

class Connection:
    """Class representing connection to Jira cloud instance.
    Used to simplify queries.
    """
    def __init__(self, settings):
        self._settings = settings

    # Private helper methods.
    def _server(self):
        return 'https://{}.atlassian.net'.format(self._settings.get('domain'))

    def _auth(self):
        return self._settings.credentials()

    # Public helper methods.
    def url(self, url):
        return '{server}{url}'.format(server=self._server(), url=url)

    # Public request methods.
    def get(self, url, **kwargs):
        return requests.get(self.url(url), auth=self._auth(), **kwargs)

    def put(self, url, **kwargs):
        return requests.put(self.url(url), auth=self._auth(), **kwargs)
    def post(self, url, **kwargs):
        return requests.post(self.url(url), auth=self._auth(), **kwargs)

connection = Connection(settings)


class JIRALineException(Exception):
    pass

class IssueException(JIRALineException):
    pass

class IssueNotFoundException(IssueException):
    pass


COLOR_LABEL = 'white'
COLOR_ISSUE_KEY = 'yellow'
COLOR_ASSIGNEE = 'light_blue'
COLOR_PRIORITY = 'green'
COLOR_STATUS = 'light_green'
COLOR_SHOW_SECTION = 'white'

COLOR_NOTE = 'light_cyan'
COLOR_ERROR = 'red'
COLOR_WARNING = 'red_1'

FORCE_COLOURS = False


################################################################################
# Helper functions.
#
def get_last_active_issue_marker_path():
    return os.path.expanduser(os.path.join('~', '.cache', 'jiraline', 'last_active_issue_marker'))

def store_last_active_issue_marker(issue_name):
    with open(get_last_active_issue_marker_path(), 'w') as ofstream:
        ofstream.write(issue_name)

def load_last_active_issue_marker():
    pth = get_last_active_issue_marker_path()
    if os.path.isfile(pth):
        with open(pth) as ifstream:
            return ifstream.read().strip()
    print('error: no last active issue')
    exit(1)

def get_known_labels_path():
    return os.path.expanduser(os.path.join('~', '.config', 'jiraline', 'labels.json'))

def load_known_labels_list():
    labels = []
    pth = get_known_labels_path()
    if os.path.isfile(pth):
        with open(pth) as ifstream:
            labels = json.loads(ifstream.read())
    return labels

def store_known_labels_list(labels):
    with open(get_known_labels_path(), 'w') as ofstream:
        ofstream.write(json.dumps(labels))

def stringifyAssignee(assignee):
    return '{} <{}>'.format(
        assignee.get('displayName', ''),
        assignee.get('emailAddress', ''),
    ).strip()

def stringify_reporter(person):
    display_name = person.get('displayName', '').strip()
    user_name = person.get('key', '').strip()
    email_address = person.get('emailAddress', '').strip()
    fmt = '(unknown)'
    if (not display_name) and (not user_name) and (not email_address):
        pass
    elif display_name and user_name and email_address:
        fmt = '{0} @{1} <{2}>'
    elif display_name and user_name and (not email_address):
        fmt = '{0} @{1}'
    elif display_name and (not user_name) and email_address:
        fmt = '{0} <{2}>'
    elif (not display_name) and user_name and email_address:
        fmt = '@{1} <{2}>'
    elif display_name and (not user_name) and (not email_address):
        fmt = '{0}'
    elif (not display_name) and (not user_name) and email_address:
        fmt = '<{2}>'
    elif (not display_name) and user_name and (not email_address):
        fmt = '@{1}'
    else:
        pass
    return fmt.format(display_name, user_name, email_address)

def transition_to(issue_name, to_id):
    transition = {
        "transition": {
            "id": to_id,
        }
    }
    r = requests.post('https://{}.atlassian.net/rest/api/2/issue/{}/transitions'.format(settings.get('domain'), issue_name),
                      json=transition,
                      auth=settings.credentials())
    if r.status_code == 404:
        print("error: the issue does not exist or the user does not have permission to view it")
        exit(1)
    elif r.status_code == 400:
        print("error: there is no transition specified")
        exit(1)
    elif r.status_code == 500:
        print("error: 500 Internal server error")
        exit(1)

def add_label(issue_name, label):
    payload = {
        "update": {
            "labels":[
                {
                    "add": label
                }
            ]
        }
    }

    r = connection.put('/rest/api/2/issue/{}'.format(issue_name), json=payload)
    if r.status_code == 404:
        print("error: the issue does not exist or the user does not have permission to view it")
        exit(1)
    elif r.status_code == 400:
        print("error: the requested issue update failed")
        exit(1)
    elif r.status_code == 403:
        print("error: the user tries to disable users notification or override screen security but doesn't have permission to do that")
        exit(1)
    elif r.status_code == 500:
        print("error: 500 Internal server error")
        exit(1)

def set_priority(issue_name, id):
    payload = {
        "fields": {
            "priority": {
                "id": id
            }
        }
    }

    r = connection.put('/rest/api/2/issue/{}'.format(issue_name), json=payload)
    if r.status_code == 404:
        print("error: the issue does not exist or the user does not have permission to view it")
        exit(1)
    elif r.status_code == 400:
        print("error: the requested issue update failed")
        exit(1)
    elif r.status_code == 403:
        print("error: the user tries to disable users notification or override screen security but doesn't have permission to do that")
        exit(1)
    elif r.status_code == 500:
        print("error: 500 Internal server error")
        exit(1)

def set_type(issue_name, type_name):
    payload = {
        "fields": {
            "issuetype": {
                "name": type_name
            }
        }
    }

    r = connection.put('/rest/api/2/issue/{}'.format(issue_name), json=payload)
    if r.status_code == 404:
        print("error: the issue does not exist or the user does not have permission to view it")
        exit(1)
    elif r.status_code == 400:
        print("error: the requested issue update failed")
        exit(1)
    elif r.status_code == 403:
        print("error: the user tries to disable users notification or override screen security but doesn't have permission to do that")
        exit(1)
    elif r.status_code == 500:
        print("error: 500 Internal server error")
        exit(1)

def set_customfield_executor(issue_name, message):
    payload = {
        "fields": {
            "customfield_10101": message
        }
    }

    r = connection.put('/rest/api/2/issue/{}'.format(issue_name), json=payload)
    print(r.status_code)
    if r.status_code == 404:
        print("error: the issue does not exist or the user does not have permission to view it")
        exit(1)
    elif r.status_code == 400:
        print("error: the requested issue update failed")
        exit(1)
    elif r.status_code == 403:
        print("error: the user tries to disable users notification or override screen security but doesn't have permission to do that")
        exit(1)
    elif r.status_code == 500:
        print("error: 500 Internal server error")
        exit(1)

def colorise(color, string):
    colour_settings = settings.get('ui', {}).get('colours') or 'default'
    if colored and (colour_settings != 'never') and (sys.stdout.isatty() or FORCE_COLOURS or (colour_settings == 'always')):
        string = (colored.fg(color) + str(string) + colored.attr('reset'))
    return string

def colorise_repr(color, string):
    return "'{}'".format(colorise(color, repr(string)[1:-1]))

def sluggify(issue_message):
    return '-'.join(re.compile('[^ a-zA-Z0-9_]').sub(' ', unidecode.unidecode(issue_message).lower()).split())

def get_issue_name_cache_pair(ui):
    issue_name = expand_issue_name(ui.operands()[0])
    store_last_active_issue_marker(issue_name)
    cached = Cache(issue_name)
    return (issue_name, cached)

def get_nice_wall_of_text(s, indent='    '):
    return textwrap.indent('\n'.join(textwrap.wrap(s)), indent)

def displayBasicInformation(data):
    print(colorise(COLOR_ISSUE_KEY, 'issue {}'.format(data.get('key'))))

    fields = lambda *path, default=None: (data.get('fields', *path, default=default) or default)

    reporter = fields('reporter')
    if reporter:
        print('Reporter: {}'.format(stringify_reporter(reporter)))

    assignee = fields('assignee')
    if assignee:
        print('Assignee: {}'.format(stringify_reporter(assignee)))

    created = fields('created')
    if created:
        print('Created:  {}'.format(created.replace('T', ' ').replace('+', ' +')))

    labels = fields('labels')
    if labels:
        print('Labels:   {}'.format(', '.join(map(lambda s: colorise(COLOR_LABEL, s), labels))))

    project = fields('project', default={}).get('name')
    if project:
        print('Project:  {}'.format(colorise(COLOR_LABEL, project)))

    issue_type = fields('issuetype', default={}).get('name')
    if issue_type:
        issue_status_name = fields('status', default={}).get('name', 'Unknown')
        issue_status_category_name = fields('status', default={}).get('statusCategory', {}).get('name', 'Unknown')
        issue_status_category_key = fields('status', default={}).get('statusCategory', {}).get('key', 'unknown')
        print('Issue:    {} in {} (category {}, key {})'.format(
            colorise(COLOR_LABEL, issue_type),
            colorise(COLOR_STATUS, issue_status_name),
            colorise_repr(COLOR_STATUS, issue_status_category_name),
            colorise_repr(COLOR_STATUS, issue_status_category_key),
        ))

    summary = fields('summary')
    if summary:
        print()
        print(get_nice_wall_of_text(summary))

    description = fields('description', default='').strip()
    if description:
        print('\n{}\n'.format(colorise(COLOR_SHOW_SECTION, 'Description')))
        print(get_nice_wall_of_text(description))

def displayComments(comments):
    if comments:
        print('\n{}'.format(colorise(COLOR_SHOW_SECTION, 'Comments')))
        for c in comments:
            print()
            print('Author: {}'.format(stringify_reporter(c.get('updateAuthor', {}))))
            print('Date:   {}'.format(c.get('created', '').replace('T', ' ').replace('+', ' +')))
            print()
            print(get_nice_wall_of_text(c.get('body', '')))

def print_abbrev_issue_summary(issue, ui):
    key = issue.get('key', '<undefined>')
    fields = issue.get('fields', {})
    summary = fields.get('summary', '')
    if colored:
        key = colorise(COLOR_ISSUE_KEY, key)

    formatted_line = '{} {}'.format(key, summary)
    if '--verbose' in ui:
        assignee_string = 'unassigned'
        assignee = fields.get('assignee', {})
        if assignee:
            assignee = colorise(COLOR_ASSIGNEE, '{}'.format(stringifyAssignee(assignee)))
        assignee_string = colorise(COLOR_ASSIGNEE, 'assignee: {}'.format(assignee))
        priority_data = (fields.get('priority', {}) or {})
        priority = priority_data.get('name')
        priority_string = colorise(COLOR_PRIORITY, priority)
        formatted_line = '{}'
        formats = [key]
        if '--status' not in ui:
            formatted_line +=  ' [{}/{}]'
            formats.append(colorise(COLOR_STATUS, '{}:{}'.format(fields.get('status', {}).get('id', 0), fields.get('status', {}).get('name', ''))))
            formats.append(priority_string)
        formatted_line += ' {}'
        formats.append(summary)
        formatted_line += ' ({})'
        formats.append(assignee_string)
        formatted_line = formatted_line.format(*formats)
    print(formatted_line)

def fetch_summary(issue_name):
    r = connection.get('/rest/api/2/issue/{}'.format(issue_name), params={
        'fields': 'summary',
    })
    if r.status_code == 200:
        response = json.loads(r.text)
        return response.get('fields', {}).get('summary', None)
    elif r.status_code == 404:
        print("error: the requested issue is not found or the user does not have permission to view it.")
        exit(1)
    else:
        print('error: HTTP {}'.format(r.status_code))
        exit(1)

def fetch_issue(issue_name, fatal=True):
    request_content = {}
    r = connection.get('/rest/api/2/issue/{}'.format(issue_name), params=request_content)
    if r.status_code == 200:
        response = json.loads(r.text)
        cached = Cache(issue_name)
        cached.set('key', value=issue_name)
        for k, v in response.get('fields', {}).items():
            cached.set('fields', k, value=v)
        cached.store()
    elif r.status_code == 404:
        msg = 'the requested issue is not found or the user does not have permission to view it.'
        if fatal:
            print('error: {}'.format(msg))
            exit(1)
        else:
            raise IssueNotFoundException(issue_name, msg)
    else:
        if fatal:
            print('error: HTTP {}'.format(r.status_code))
            exit(1)
        else:
            raise IssueException(issue_name, r.status_code)
    return cached

def dump_issue(cached, ui):
    data = cached.response().get('fields', {})
    if '--field' in ui:
        filtered_data = {}
        for k in ui.get('-f'):
            k = k[0]
            filtered_data[k] = data.get(k)
        data = filtered_data
    return json.dumps(data, indent=ui.get('--pretty'))

def show_issue(issue_name, ui, cached=None):
    if cached is None:
        cached = Cache(issue_name)
    if '--field' not in ui:
        displayBasicInformation(cached)
        displayComments(cached.get('fields', 'comment', default={}).get('comments', []))
    elif '--pretty' in ui:
        print(dump_issue(cached, ui))
    elif '--raw' in ui:
        print(dump_issue(cached, ui))
    else:
        for i, key in enumerate(map(lambda _: _[0], ui.get('-f'))):
            if key == 'comment': continue
            value = cached.get('fields', key)
            if key == 'assignee':
                value = stringifyAssignee(value)
            if value is None:
                print('{} (undefined)'.format(key))
            else:
                print('{} = {}'.format(key, str(value).strip()))
        displayComments(cached.response().get('fields', {}).get('comment', {}).get('comments', []))

def expand_issue_name(issue_name, project=None):
    if issue_name == '-':
        issue_name = load_last_active_issue_marker()
    if issue_name.isdigit():
        issue_name = '{}-{}'.format((project if project is not None else settings.get('default_project')), issue_name)
    return issue_name

def get_message_from_editor(template='', fmt={}, join_lines=''):
    editor = os.getenv('EDITOR', 'vi')
    message_path = os.path.expanduser(os.path.join('~', '.local', 'share', 'jiraline', 'tmp_message'))
    if template and format:
        with open(os.path.expanduser('~/.local/share/jiraline/messages/{0}'.format(template))) as ifstream:
            default_message_text = ifstream.read()
        with open(message_path, 'w') as ofstream:
            ofstream.write(default_message_text.format(**fmt))
    elif template and not format:
        shutil.copy(os.path.expanduser('~/.local/share/jiraline/messages/{0}'.format(template)), message_path)
    os.system('{0} {1}'.format(editor, message_path))
    message = ''
    with open(message_path) as ifstream:
        message_lines = ifstream.readlines()
        message = [l for l in message_lines if not l.lstrip().startswith('#')]
        if join_lines is not None:
            message = join_lines.join(message).strip()
    return message

def get_shortlog_path():
    return os.path.expanduser(os.path.join('~', '.local', 'log', 'jiraline'))

def timestamp(dt=None):
    return (dt or datetime.datetime.now()).timestamp()

def read_shortlog():
    pth = get_shortlog_path()
    if not os.path.isdir(pth):
        os.makedirs(pth)
    shortlog = []
    shortlog_path = os.path.join(pth, 'shortlog.json')
    if os.path.isfile(shortlog_path):
        with open(shortlog_path) as ifstream:
            shortlog = json.loads(ifstream.read())
    return shortlog

def write_shortlog(shortlog):
    pth = get_shortlog_path()
    if not os.path.isdir(pth):
        os.makedirs(pth)
    with open(os.path.join(pth, 'shortlog.json'), 'w') as ofstream:
        ofstream.write(json.dumps(shortlog[-settings.get('shortlog_size', default=80):]))

def append_shortlog_event(issue_name, log_content):
    issue_log_name = '{}.{}.json'.format(timestamp(), issue_name)
    pth = get_shortlog_path()
    if not os.path.isdir(pth):
        os.makedirs(pth)
    shortlog = read_shortlog()
    log_content['issue'] = issue_name
    log_content['timestamp'] = timestamp()
    shortlog.append(log_content)
    write_shortlog(shortlog)

def add_shortlog_event_transition(issue_name, to):
    append_shortlog_event(issue_name, log_content = {
        'event': 'transition',
        'parameters': {
            'to': to,
        },
    })

def add_shortlog_event_fetch(issue_name):
    append_shortlog_event(issue_name, log_content = {
        'event': 'fetch',
        'parameters': {},
    })

def add_shortlog_event_show(issue_name):
    append_shortlog_event(issue_name, log_content = {
        'event': 'show',
        'parameters': {},
    })

def add_shortlog_event_slug(issue_name, slug):
    append_shortlog_event(issue_name, log_content = {
        'event': 'slug',
        'parameters': {
            'slug': slug,
        },
    })

def add_shortlog_event_label(issue_name, labels):
    append_shortlog_event(issue_name, log_content = {
        'event': 'label-add',
        'parameters': {
            'labels': labels,
        },
    })

def add_shortlog_event_comment(issue_name, comment):
    append_shortlog_event(issue_name, log_content = {
        'event': 'comment',
        'parameters': {
            'comment': comment,
        },
    })

def add_shortlog_event_open_issue(issue_name, issue_summary):
    append_shortlog_event(issue_name, log_content = {
        'event': 'open-issue',
        'parameters': {
            'summary': issue_summary,
            'key': issue_name,
        },
    })



################################################################################
# Commands.
#
def commandComment(ui):
    issue_name = expand_issue_name(ui.operands()[0])
    store_last_active_issue_marker(issue_name)
    message = ""
    if '-m' in ui:
        message = ui.get("-m")
    if not message.strip():
        cached = Cache(issue_name)
        summary_not_available = '<summary not available>'
        description_not_available = '<description not available>'
        initial_comment_text = ''
        if '--ref' in ui:
            p = subprocess.Popen(('git', 'show', ui.get('--ref')), stdout=subprocess.PIPE)
            output, error = p.communicate()
            output = output.decode('utf-8').strip()
            git_exit_code = p.wait()
            if git_exit_code != 0:
                print('error: Git error')
                exit(git_exit_code)
            initial_comment_text = output
        fmt = {
            'issue_name': issue_name,
            'issue_summary': summary_not_available,
            'issue_description': description_not_available,
            'text': initial_comment_text,
        }
        if cached.is_cached():
            fmt['issue_summary'] = get_nice_wall_of_text(cached.get('fields.summary', default=summary_not_available).strip(), indent='#   ')
            fmt['issue_description'] = get_nice_wall_of_text((cached.get('fields.description', default=description_not_available) or description_not_available).strip(), indent='#   ')
        if '--reply' in ui and cached.is_cached():
            comments = cached.get('fields', 'comment', default={}).get('comments', [])
            if comments:
                fmt['text'] = '> {}'.format(comments[-1].get('body', ''))
        message = get_message_from_editor('issue_comment_message', fmt)
    if not message.strip():
        print('error: aborting due to empty message')
        exit(1)
    comment = {
        'body': message,
    }
    add_shortlog_event_comment(issue_name, message)
    r = requests.post('https://{}.atlassian.net/rest/api/2/issue/{}/comment'.format(settings.get('domain'), issue_name),
                      json=comment,
                      auth=settings.credentials())
    if r.status_code == 400:
        print('The input is invalid (e.g. missing required fields, invalid values, and so forth).')


def commandAssign(ui):
    issue_name = expand_issue_name(ui.operands()[0])
    store_last_active_issue_marker(issue_name)
    if '--ls' in ui:
        url = '/rest/api/2/user/assignable/search?issueKey={}'.format(issue_name)
        if '--user' in ui:
            url += '&username={}'.format(ui.get('--user'))
        r = connection.get(url)
        if r.status_code == 200:
            list_of_users = r.json()
            longest_username = 0
            try:
                longest_username = max(map(len, map(lambda each: each.get('key'), list_of_users)))
            except ValueError:
                # raised when there are no users matching
                pass
            for u in list_of_users:
                fmt = '{}: {}'
                args = (colorise(COLOR_LABEL, u.get('key')).ljust(longest_username), u.get('displayName'),)
                if '--verbose' in ui:
                    fmt += ' ({}), email: {}'
                    args += (u.get('name'), u.get('emailAddress'),)
                print(fmt.format(*args))
        else:
            print('{}: Request failed'.format(colorise(COLOR_ERROR, 'error')))
    else:
        user_name = ui.get('-u')
        assign = {'name': user_name}
        r = connection.put('/rest/api/2/issue/{}/assignee'.format(issue_name), json=assign)
        if r.status_code == 400:
            print('There is a problem with the received user representation.')
        elif r.status_code == 401:
            print("Calling user does not have permission to assign the issue.")
        elif r.status_code == 404:
            print("Either the issue or the user does not exist.")


def commandIssue(ui):
    ui = ui.down()
    issue_name, cached = None, None
    if str(ui) == 'issue':
        issue_name, cached = get_issue_name_cache_pair(ui)
    if str(ui) == 'transition':
        issue_name, cached = get_issue_name_cache_pair(ui)
        if '--to' in ui:
            for to_id in ui.get('-t'):
                transition_to(issue_name, *to_id)
                add_shortlog_event_transition(issue_name, *to_id)
        else:
            r = connection.get('/rest/api/2/issue/{}/transitions'.format(issue_name))
            if r.status_code == 200:
                response = json.loads(r.text)
                transitions = response.get('transitions', [])
                if '--ids' in ui:
                    for t in transitions:
                        print(t["id"])
                elif '--names' in ui:
                    for t in transitions:
                        print(t["name"])
                else:
                    for t in transitions:
                        print(t["id"], t["name"])
            elif r.status_code == 404:
                print("error: the requested issue is not found or the user does not have permission to view it")
                exit(1)
            else:
                print('error: HTTP {}'.format(r.status_code))
                exit(1)
    elif str(ui) == 'issue' and cached.is_cached():
        add_shortlog_event_show(issue_name)
        show_issue(issue_name, ui, cached)
    elif str(ui) == 'show' or str(ui) == 'issue':
        issue_name, cached = get_issue_name_cache_pair(ui)
        add_shortlog_event_show(issue_name)
        show_issue(issue_name, ui, fetch_issue(issue_name))
    elif str(ui) == 'label':
        ui = ui.down()
        if str(ui) == 'label':
            issue_name, *labels = ui.operands()
            issue_name = expand_issue_name(issue_name)
            known_labels = load_known_labels_list()
            if '--force' not in ui:
                for label in labels:
                    if label not in known_labels:
                        print('{}: unknown label: {}'.format(colorise(COLOR_ERROR, 'error'), colorise_repr(COLOR_LABEL, label)))
                        print('{}: to create this label run: "jiraline issue label new {}"'.format(colorise(COLOR_NOTE, 'note'), label))
                        exit(1)
            add_shortlog_event_label(issue_name, labels)
            for label in labels:
                if '--verbose' in ui or len(labels) > 1:
                    print('applying label {}'.format(colorise_repr(COLOR_LABEL, label)))
                add_label(issue_name, label)
        elif str(ui) == 'new':
            labels = ui.operands()
            known_labels = set(load_known_labels_list())
            for label in labels:
                known_labels.add(label)
            store_known_labels_list(list(known_labels))
        elif str(ui) == 'rm':
            labels = ui.operands()
            known_labels = set(load_known_labels_list())
            for label in labels:
                known_labels.remove(label)
            store_known_labels_list(list(known_labels))
        elif str(ui) == 'ls':
            known_labels = load_known_labels_list()
            for label in sorted(known_labels):
                print(label)
    elif str(ui) == 'priority':
        issue_name, id = ui.operands()
        store_last_active_issue_marker(issue_name)
        set_priority(issue_name, id)
    elif str(ui) == 'type':
        issue_name, type_name = ui.operands()
        store_last_active_issue_marker(issue_name)
        set_type(issue_name, type_name)
    elif str(ui) == 'customfield-executor':
        issue_name, message = ui.operands()
        store_last_active_issue_marker(issue_name)
        set_customfield_executor(issue_name, message)


def commandSearch(ui):
    request_content = {
        'jql': '',
        'startAt': 0,
        'maxResults': 15,
        'fields': [
            'summary',
            'status',
            'assignee',
            'reporter',
            'priority',
            'created',
        ],
        'fieldsByKeys': False,
    }
    conditions = []
    if "-p" in ui:
        conditions.append('project = {}'.format(ui.get("-p")))
    if "-a" in ui:
        conditions.append('assignee = {}'.format(ui.get("-a")))
    if '--reporter' in ui:
        conditions.append('reporter = {}'.format(ui.get('-r')))
    if '--key-lower' in ui:
        conditions.append('key >= {}'.format(expand_issue_name(ui.get('-L'), ui.get('-p'))))
    if '--key-upper' in ui:
        conditions.append('key <= {}'.format(expand_issue_name(ui.get('-U'), ui.get('-p'))))
    if "-s" in ui:
        conditions.append('status = {}'.format(ui.get("-s")))
    if "-j" in ui:
        conditions.append('{}'.format(ui.get("-j")))
    if "-n" in ui:
        request_content["maxResults"] = ui.get("-n")

    request_content["jql"] = " AND ".join(conditions)
    r = connection.get('/rest/api/2/search', params=request_content)
    if r.status_code == 200:
        response = json.loads(r.text)
        if '--table' not in ui:
            terms = [_.lower() for _ in ui.operands()]
            for i in response.get('issues', []):
                skip = bool(terms)
                if terms:
                    summary = i.get('fields', {}).get('summary', '').lower()
                    for term in terms:
                        if term in summary:
                            skip = False
                            break
                if skip:
                    continue
                print_abbrev_issue_summary(i, ui)
        else:
            print('{:<7} | {:<50} | {:<20} | {:<19} | {:<20}'.format('Key','Summary','Assignee','Created','Status'))
            print('-' * 130)
            for i in response['issues']:
                key = i['key']
                fields = i.get('fields', {})
                summary = fields.get('summary', '')
                assignee = fields.get('assignee', {})
                if assignee is None:
                    assignee = {}
                assignee_display_name = assignee.get('displayName', '')
                created = fields.get('created', '')
                status_name = fields.get('status', {}).get('name', '')
                message_line = '{:<.7} | {:<50.50} | {:<20.20} | {:<19.19} | {:<20.20}'.format(
                    key,
                    summary,
                    assignee_display_name,
                    created,
                    status_name,
                )
                print(message_line)
    else:
        print('error: HTTP {}'.format(r.status_code))


def get_current_git_branch():
    p = subprocess.Popen(('git', 'rev-parse', '--abbrev-ref', 'HEAD'), stdout=subprocess.PIPE)
    output, error = p.communicate()
    output = output.decode('utf-8').strip()
    git_exit_code = p.wait()
    if git_exit_code != 0:
        print('error: Git error')
        exit(git_exit_code)
    branch_name = output.strip()
    return branch_name

def commandSlug(ui):
    ui = ui.down()
    issue_name = expand_issue_name(ui.operands()[0])
    store_last_active_issue_marker(issue_name)

    cached = Cache(issue_name)
    issue_message = cached.get('fields', 'summary')
    if not issue_message:
        print('{}: message for issue {} not available, fetching'.format(colorise(COLOR_WARNING, 'warning'), colorise_repr(COLOR_ISSUE_KEY, issue_name)))
        issue_message = fetch_summary(issue_name)
        cached.set('fields', 'summary', value=issue_message)
        cached.store()

    issue_slug = sluggify(issue_message)

    default_slug_format = 'issue/{issue_key}/{slug}'
    slug_format = settings.get('slug', {}).get('format', {}).get('default', default_slug_format)
    if slug_format.startswith('@'):
        slug_format = settings.get('slug', {}).get('format', {}).get(slug_format[1:], default=default_slug_format)

    if '--git' in ui:
        slug_format = 'issue/{slug}'
    if '--format' in ui:
        slug_format = ui.get('--format')
    if '--use-format' in ui:
        slug_format = settings.get('slug', 'format', ui.get('--use-format'), default=False)
        if not slug_format:
            print('fatal: undefined slug format: {0}'.format(ui.get('--use-format')))
            exit(1)

    if slug_format:
        try:
            issue_slug = slug_format.format(slug=issue_slug, issue_key=issue_name)
        except KeyError as e:
            print('error: required parameter not found: {}'.format(str(e)))
            exit(1)

    add_shortlog_event_slug(issue_name, issue_slug)

    if '--git-branch' in ui:
        allow_branching_from = settings.data().get('base_branch')
        if '--allow-branch-from' in ui:
            allow_branching_from = ui.get('--allow-branch-from')
        current_git_branch = get_current_git_branch()
        if allow_branching_from != 'HEAD' and allow_branching_from != current_git_branch:
            print('{}: branching from {} is not allowed'.format(colorise(COLOR_ERROR, 'error'), colorise_repr(COLOR_LABEL, current_git_branch)))
            if allow_branching_from is not None:
                print('{}: only branching from {} is allowed'.format(colorise(COLOR_NOTE, 'note'), colorise_repr(COLOR_LABEL, allow_branching_from)))
            exit(1)
        r = os.system('git branch {0}'.format(issue_slug))
        r = (r >> 8)
        if r != 0:
            exit(r)
    if '--git-checkout' in ui:
        r = os.system('git checkout {0}'.format(issue_slug))
        r = (r >> 8)
        if r != 0:
            exit(r)
    if ('--git-branch' not in ui) and ('--git-checkout' not in ui):
        print(issue_slug)


def commandEstimate(ui):
    ui = ui.down()
    issue_name = expand_issue_name(ui.operands()[0])
    store_last_active_issue_marker(issue_name)
    estimation_time = ui.operands()[1]

    request_content = {
        "timeSpent":"1m"
    }
    request_params = {
        "adjustEstimate":"new",
        "newEstimate":estimation_time
    }
    r = connection.post('/rest/api/2/issue/{}/worklog'.format(issue_name),params=request_params,json=request_content)
    if r.status_code == 400:
        print('error: the input is invalid (e.g. missing required fields, invalid values, and so forth).')
        exit(1)
    elif r.status_code == 403:
        print('error: returned if the calling user does not have permission to add the worklog')
        exit(1)
    elif not (r.status_code >= 200 and r.status_code < 300):
        print('error: other error: {}'.format(r.status_code))
        exit(1)


def commandPin(ui):
    jiraline_config_directory = os.path.expanduser(os.path.join('~', '.config', 'jiraline'))
    if not os.path.isdir(jiraline_config_directory):
        os.makedirs(jiraline_config_directory, exist_ok=True)

    pins_path = os.path.join(jiraline_config_directory, 'pinned.json')
    pins = {}
    if os.path.isfile(pins_path):
        with open(pins_path) as ifstream:
            pins = json.loads(ifstream.read())

    if '--un' in ui:
        issue_name = expand_issue_name(ui.get('--un'))
        del pins[issue_name]
    elif ui.operands():
        pins[expand_issue_name(ui.operands()[0])] = (ui.get('-m') or '').strip()
    else:
        for k in sorted(pins.keys()):
            note = pins[k]
            print('{}{}'.format(colorise(COLOR_ISSUE_KEY, k), ((': ' + note) if note else '')))

    with open(pins_path, 'w') as ofstream:
        ofstream.write(json.dumps(pins))


def colorise_percentage(s, percentage):
    color = 'white'
    colors = (
        (98, 'dark_green'),
        (90, 'green'),
        (85, 'light_green'),
        (75, 'pale_green_1b'),
        (60, 'dark_olive_green_1a'),
        (50, 'light_yellow'),
        (40, 'green_yellow'),
        (30, 'yellow_4b'),
        (20, 'yellow'),
        (10, 'yellow_4a'),
        (2, 'red'),
        (0, 'dark_red_1'),
    )
    for pc, clr in colors:
        if percentage >= pc:
            color = clr
            break
    return colorise(color, str(s))

def commandFetch(ui):
    ui = ui.down()
    total_isues_to_fetch = len(ui.operands())
    for i, issue_name in enumerate(ui.operands()):
        issue_name = expand_issue_name(issue_name)
        if '--lazy' in ui and Cache(issue_name, lazy=True).is_cached():
            continue
        try:
            if '--verbose' in ui or total_isues_to_fetch > 1:
                percent_complete = round(((i+1)/total_isues_to_fetch*100), 2)
                print('fetching {} ({}/{} ~{}%)'.format(colorise(COLOR_ISSUE_KEY, issue_name), i+1, total_isues_to_fetch, colorise_percentage(percent_complete, percent_complete)))
            fetch_issue(issue_name, fatal=False)
        except IssueException:
            print('{}: failed to fetch issue {}'.format(colorise(COLOR_WARNING, 'warning'), colorise(COLOR_ISSUE_KEY, issue_name)))


def display_shortlog(shortlog, head=None, tail=None):
    if head is not None:
        shortlog = shortlog[:head]
    if tail is not None:
        shortlog = shortlog[tail:]
    for event in shortlog:
        event_name = event['event']
        event_description = event['parameters']
        if event_name == 'show':
            event_description = ''
        elif event_name == 'slug':
            event_description = 'sluggified to {}'.format(colorise_repr(COLOR_LABEL, event['parameters']['slug']))
        elif event_name == 'transition':
            event_description = 'to status {}'.format(colorise_repr(COLOR_STATUS, event['parameters']['to']))
        elif event_name == 'comment':
            comment_lines = event['parameters']['comment'].splitlines()
            event_description = '{}'.format(comment_lines[0].strip())
            if len(comment_lines) > 1:
                event_description += ' (...)'
        elif event_name == 'label-add':
            event_description = 'added labels {}'.format(', '.join(map(lambda l: colorise_repr(COLOR_LABEL, l), event['parameters']['labels'])))
        elif event_name == 'open-issue':
            event_description = 'opened issue: {}'.format(colorise(COLOR_NOTE, event_description.get('summary')))
        else:
            # if no special description formatting is provided, just display name of the event
            event_description = ''
        if event_description:
            event_description = ': {}'.format(event_description)
        print('{} {}{}'.format(colorise(COLOR_ISSUE_KEY, event['issue']), event_name, event_description))

def _bug_event_without_assigned_weight(event):
    print('{}: {}: event {} does not have a weight assigned'.format(colorise(COLOR_WARNING, 'warning'), colorise(COLOR_ERROR, 'bug'), colorise_repr(COLOR_LABEL, event['event'])))

SHORTLOG_EVENT_WEIGHTS = {
    'slug': 0,
    'transition': 0,
    'label-add': 5,
    'comment': 7,
    'show': 10,
}

def squash_shortlog_aggressive_1(shortlog):
    """Aggressive-squash-1 assumes that basic squashing has
    already been performed.
    """
    if len(shortlog) < 2:
        return shortlog
    squashed_shortlog = [shortlog[0]]
    for event in shortlog[1:]:
        if event['issue'] == squashed_shortlog[-1]['issue']:
            last_event_action = SHORTLOG_EVENT_WEIGHTS.get(squashed_shortlog[-1]['event'])
            this_event_action = SHORTLOG_EVENT_WEIGHTS.get(event['event'])

            if last_event_action is None:
                _bug_event_without_assigned_weight(squashed_shortlog[-1])
            if this_event_action is None:
                _bug_event_without_assigned_weight(event)
            if last_event_action is None or this_event_action is None:
                # zero out the comparison when an event does not have a weight assigned
                last_event_action, this_event_action = 0, 0

            if last_event_action > this_event_action:
                squashed_shortlog.pop()
            elif last_event_action < this_event_action:
                continue
            else:
                pass
        squashed_shortlog.append(event)
    return squashed_shortlog

def rfind_if(seq, pred):
    index = len(seq)-1
    while index > -1:
        if pred(seq[index]):
            break
        index -= 1
    return index

def squash_shortlog_aggressive_2(shortlog):
    """Aggressive-squash-2 assumes that basic squashing has
    already been performed.
    """
    if len(shortlog) < 2:
        return shortlog
    squashed_shortlog = [shortlog[0]]
    for event in shortlog[1:]:
        this_event_action = SHORTLOG_EVENT_WEIGHTS.get(event['event'])
        index_of_last_event_for_the_same_issue = rfind_if(squashed_shortlog, lambda e: e['issue'] == event['issue'])
        if index_of_last_event_for_the_same_issue > -1:
            last_event_action = SHORTLOG_EVENT_WEIGHTS.get(squashed_shortlog[index_of_last_event_for_the_same_issue]['event'])

            if last_event_action is None:
                _bug_event_without_assigned_weight(squashed_shortlog[-1])
            if this_event_action is None:
                _bug_event_without_assigned_weight(event)
            if last_event_action is None or this_event_action is None:
                # zero out the comparison when an event does not have a weight assigned
                last_event_action, this_event_action = 0, 0

            if last_event_action > this_event_action:
                squashed_shortlog.pop()
            elif last_event_action < this_event_action:
                continue
            else:
                pass
        squashed_shortlog.append(event)
    return squashed_shortlog

def squash_shortlog(shortlog, aggressive=0):
    if len(shortlog) < 2:
        return shortlog
    squashed_shortlog = [shortlog[0]]
    for event in shortlog[1:]:
        if event['issue'] == squashed_shortlog[-1]['issue'] and event['event'] == squashed_shortlog[-1]['event']:
            continue
        squashed_shortlog.append(event)
    if aggressive and aggressive == 1:
        squashed_shortlog = squash_shortlog_aggressive_1(squashed_shortlog)
    if aggressive and aggressive > 1:
        squashed_shortlog = squash_shortlog_aggressive_2(squashed_shortlog)
    return squashed_shortlog

def commandShortlog(ui):
    ui = ui.down()
    if '--colorise' in ui:
        global FORCE_COLOURS
        FORCE_COLOURS = True
    shortlog = read_shortlog()
    shortlog.reverse()
    if str(ui) == 'squash':
        initial_size = len(shortlog)
        if initial_size < 2:
            print('{}: shortlog too short to shorten'.format(colorise(COLOR_WARNING, 'warning')))
            return
        squashed_shortlog = squash_shortlog(shortlog, aggressive = ui.get('--aggressive'))
        final_size = len(squashed_shortlog)
        if final_size < initial_size:
            print('{}: shortened shortlog from {} to {} entries'.format(colorise(COLOR_NOTE, 'note'), initial_size, final_size))
        write_shortlog(squashed_shortlog)
        if '--verbose' in ui:
            display_shortlog(squashed_shortlog)
    else:
        head = None
        tail = None
        if '--head' in ui:
            head = ui.get('-H')
        if '--tail' in ui:
            tail = ui.get('-T')
        display_shortlog(shortlog, head=head, tail=tail)


def commandOpen(ui):
    ui = ui.down()
    if str(ui) == 'open':
        project, project_original = None, None
        if '-p' in ui:
            project = ui.get('-p').strip()
            project_original = project
        if not project:
            print('error: aborting: no project selected')
            exit(1)

        issuetype = str(settings.data().get('default_issue_type'))
        if '-i' in ui:
            issuetype = ui.get('-i')
        if not issuetype:
            print('error: aborting: no issue type selected')
            exit(1)

        create_issue_meta = {}
        if (not issuetype.isdigit()) or (not project.isdigit()):
            create_issue_meta_path = os.path.expanduser(os.path.join('~', '.config', 'jiraline', 'createissuemeta.json'))
            if not os.path.isfile(create_issue_meta_path):
                print('{}: no issue create metadata available'.format(colorise(COLOR_ERROR, 'error')))
                print('{}: use "{}" to store it'.format(colorise(COLOR_NOTE, 'note'), create_issue_meta_path))
                exit(1)
            with open(create_issue_meta_path, 'r') as ifstream:
                create_issue_meta = json.loads(ifstream.read())

        if not project.isdigit():
            available_projects = create_issue_meta.get('projects', [])
            matching = list(filter(lambda each: each.get('key') == project, available_projects))
            if not matching:
                print('{}: not a valid project: {}'.format(colorise(COLOR_ERROR, 'error'), colorise(COLOR_LABEL, project)))
                exit(1)
            project = matching[0].get('id')

        if not issuetype.isdigit():
            project_meta = list(filter(lambda each: each.get('id') == project, create_issue_meta.get('projects', [])))[0]
            available_issue_types = project_meta.get('issuetypes', [])
            matching = list(filter(lambda each: each.get('name') == issuetype, available_issue_types))
            if not matching:
                print('{}: not a valid issue type for project {}: {}'.format(colorise(COLOR_ERROR, 'error'), colorise(COLOR_LABEL, project_original), colorise(COLOR_LABEL, issuetype)))
                exit(1)
            issuetype = matching[0].get('id')

        summary = ''
        if '-s' in ui:
            summary = ui.get('-s')
        if not summary.strip():
            summary = get_message_from_editor('issue_open_message', {'what': 'summary'})
        if not summary.strip():
            print('error: aborting due to empty summary')
            exit(1)

        description = ''
        if '-d' in ui:
            description = ui.get('-d')
        if (not description.strip()) and '--allow-empty-message' not in ui:
            description = get_message_from_editor('issue_open_message_description', {
                'summary': get_nice_wall_of_text(summary, indent='#   '),
            }, join_lines='\n')
        if (not description.strip()) and '--allow-empty-message' not in ui:
            print('error: aborting due to empty description')
            exit(1)

        assignee_name = settings.username()
        if '--assignee' in ui:
            assignee_name = ui.get('-a')

        fields = {
            'project': {
                'id': project,
            },
            'summary': summary,
            'description': description,
            'issuetype': {
                'id': issuetype,
            },
            'labels': list(map(lambda each: each[0], ui.get('-l'))),
            'assignee': {
                'name': assignee_name,
            },
        }
        r = requests.post('https://{}.atlassian.net/rest/api/2/issue'.format(settings.get('domain')),
            json={'fields': fields,},
            auth=settings.credentials()
        )
        if r.status_code == 400:
            exit(1)
        else:
            data = json.loads(r.text)
            try:
                print(data.get('key', r.text))
            except Exception as e:
                print(r.text)
            add_shortlog_event_open_issue(data.get('key'), summary)
    elif str(ui) == 'what':
        r = requests.get('https://{}.atlassian.net/rest/api/2/issue/createmeta'.format(settings.get('domain')), auth=settings.credentials())
        text = r.text
        if '--pretty' in ui:
            print(json.dumps(json.loads(text), indent=2))
        else:
            print(text)


################################################################################
# Program's entry point.
#
def dispatch(ui, *commands, overrides = {}, default_command=''):
    """Semi-automatic command dispatcher.

    Functions passed to `*commands` parameter should be named like `commandFooBarBaz` because
    of command name mangling.
    Example: `foo-bar-baz` is transformed to `FooBarBaz` and handled with `commandFooBarBaz`.

    It is possible to override a command handler by passing it inside the `overrides` parameter.

    This scheme can be effectively used to support command auto-dispatch with minimal manual guidance by
    providing sane defaults and a way of overriding them when needed.
    """
    ui_command = (str(ui) or default_command)
    if not ui_command:
        return

    if ui_command in overrides:
        overrides[ui_command](ui)
    else:
        ui_command = ('command' + ''.join([(s[0].upper() + s[1:]) for s in ui_command.split('-')]))
        for cmd in commands:
            if cmd.__name__ == ui_command:
                cmd(ui)
                break

dispatch(ui,        # first: pass the UI object to dispatch
    commandComment,    # second: pass command handling functions
    commandAssign,
    commandIssue,
    commandSearch,
    commandSlug,
    commandEstimate,
    commandPin,
    commandFetch,
    commandShortlog,
    commandOpen,
)
