#!/usr/bin/python

import getpass
import json
import re
import subprocess
import sys
import os

import clap
import requests
import unidecode

try:
    import colored
except ImportError:
    colored = None


# Jiraline version
__version__ = '0.1.1'


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
    def __init__(self, issue_key):
        self._issue_key = issue_key
        self._data = {}
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

    # Maintenance API.
    def load(self):
        self._settings = {}
        if not os.path.isfile(os.path.expanduser("~/.jiraline")):
            return self
        try:
            with open(os.path.expanduser("~/.jiraline")) as ifstream:
                self._settings = json.loads(ifstream.read())
        except json.decoder.JSONDecodeError as e:
            print('error: invalid settings format: {}'.format(e))
            exit(1)
        except Exception as e:
            print('error: failed loading settings: {}'.format(e))
            exit(1)
        return self

    # Low-level access API.
    def get(self, *path, default=None):
        value = self._settings
        for key in path:
            if key not in value and default is None:
                print('error: key missing from configuration: {}'.format('.'.join(path)))
                exit(1)
            if key not in value and default is not None:
                return default
            value = value[key]
            if type(value) is not dict:
                break
        return value

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

def stringifyAssignee(assignee):
    return '{} <{}>'.format(
        assignee.get('displayName', ''),
        assignee.get('emailAddress', ''),
    ).strip()

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
    if colored:
        string = (colored.fg(color) + str(string) + colored.attr('reset'))
    return string

def sluggify(issue_message):
    return '-'.join(re.compile('[^ a-zA-Z0-9_]').sub(' ', unidecode.unidecode(issue_message).lower()).split())

def displayBasicInformation(data):
    print('issue {}'.format(data.get('key')))

    fields = lambda *path, default=None: data.get('fields', *path, default=default)

    created = fields('created')
    if created:
        print('Created {}'.format(created.replace('T', ' ').replace('+', ' +')))

    summary = fields('summary')
    if summary:
        print('\n    {}'.format(summary))

    description = fields('description', default='').strip()
    if description:
        print('\nDescription\n')
        print('\n'.join(['    {}'.format(_) for _ in description.splitlines()]))

def displayComments(comments):
    if comments:
        print("\nComments:")
        for c in comments:
            print('----------------------------------')
            print('Author: {} | Date: {}'.format(c["updateAuthor"]["displayName"],c["created"]))
            print('{}'.format(c["body"]))

def print_abbrev_issue_summary(issue, ui):
    key = issue.get('key', '<undefined>')
    fields = issue.get('fields', {})
    summary = fields.get('summary', '')
    if colored:
        key = colorise('yellow', key)

    formatted_line = '{} {}'.format(key, summary)
    if '--verbose' in ui:
        assignee_string = 'unassigned'
        assignee = fields.get('assignee', {})
        if assignee:
            assignee = colorise('light_blue', '{}'.format(stringifyAssignee(assignee)))
        assignee_string = colorise('light_blue', 'assignee: {}'.format(assignee))
        priority = fields.get('priority', {}).get('name')
        priority_string = colorise('green', priority)
        formatted_line = '{}'
        formats = [key]
        if '--status' not in ui:
            formatted_line +=  ' [{}/{}]'
            formats.append(colorise('cyan', '{}:{}'.format(fields.get('status', {}).get('id', 0), fields.get('status', {}).get('name', ''))))
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

def fetch_issue(issue_name):
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
        print("error: the requested issue is not found or the user does not have permission to view it.")
        exit(1)
    else:
        print('error: HTTP {}'.format(r.status_code))
        exit(1)
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

def get_message_from_editor(template='', fmt={}):
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
        message = ''.join([l for l in message_lines if not l.lstrip().startswith('#')]).strip()
    return message


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
            fmt['issue_summary'] = cached.get('fields.summary', default=summary_not_available).strip()
            fmt['issue_description'] = cached.get('fields.description', default=description_not_available).strip()
        message = get_message_from_editor('issue_comment_message', fmt)
    if not message.strip():
        print('error: aborting due to empty message')
        exit(1)
    comment = {
        'body': message,
    }
    r = requests.post('https://{}.atlassian.net/rest/api/2/issue/{}/comment'.format(settings.get('domain'), issue_name),
                      json=comment,
                      auth=settings.credentials())
    if r.status_code == 400:
        print('The input is invalid (e.g. missing required fields, invalid values, and so forth).')


def commandAssign(ui):
    issue_name = ui.operands()[0]
    store_last_active_issue_marker(issue_name)
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
    issue_name = expand_issue_name(ui.operands()[0])
    store_last_active_issue_marker(issue_name)
    cached = Cache(issue_name)
    if str(ui) == 'transition':
        if '--to' in ui:
            for to_id in ui.get('-t'):
                transition_to(issue_name, *to_id)
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
        show_issue(issue_name, ui, cached)
    elif str(ui) == 'show' or str(ui) == 'issue':
        show_issue(issue_name, ui, fetch_issue(issue_name))
    elif str(ui) == 'label':
        issue_name, *labels = ui.operands()
        issue_name = expand_issue_name(issue_name)
        for label in labels:
            add_label(issue_name, label)
    elif str(ui) == 'priority':
        issue_name, id = ui.operands()
        set_priority(issue_name, id)
    elif str(ui) == 'type':
        issue_name, type_name = ui.operands()
        set_type(issue_name, type_name)
    elif str(ui) == 'customfield-executor':
        issue_name, message = ui.operands()
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


def commandSlug(ui):
    ui = ui.down()
    issue_name = expand_issue_name(ui.operands()[0])
    store_last_active_issue_marker(issue_name)

    cached = Cache(issue_name)
    issue_message = cached.get('fields', 'summary')
    if not issue_message:
        issue_message = fetch_summary(issue_name)
        cached.set('fields', 'summary', value=issue_message)
        cached.store()

    issue_slug = sluggify(issue_message)

    default_slug_format = 'issue/{issue_key}/{slug}'
    slug_format = settings.get('slug', 'format', 'default', default=default_slug_format)
    if slug_format.startswith('@'):
        slug_format = settings.get('slug', 'format', slug_format[1:], default=default_slug_format)

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

    if '--git-branch' in ui:
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
    commandEstimate
)
