#!/usr/bin/python

import getpass
import json
import re
import sys
import os

import clap
import requests
import unidecode


# Jiraline version
__version__ = '0.1.0'


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

def commandComment(ui):
    issue_name = ui.operands()[0]
    message = ""
    if "-m" in ui:
        message = ui.get("-m")
    else:
        message = input("Please type comment message: ")
    comment={"body":message}
    r = requests.post('https://{}.atlassian.net/rest/api/2/issue/{}/comment'.format(settings.get('domain'), issue_name),
                      json=comment,
                      auth=settings.credentials())
    if r.status_code == 400:
        print('The input is invalid (e.g. missing required fields, invalid values, and so forth).')

def commandAssign(ui):
    issue_name = ui.operands()[0]
    user_name = ui.get('-u')
    assign = {'name': user_name}
    r = connection.put('/rest/api/2/issue/{}/assignee'.format(issue_name), json=assign)
    if r.status_code == 400:
        print('There is a problem with the received user representation.')
    elif r.status_code == 401:
        print("Calling user does not have permission to assign the issue.")
    elif r.status_code == 404:
        print("Either the issue or the user does not exist.")

def displayBasicInformation(data):
    fields = data.get('fields', {})
    print('issue {}'.format(data['key']))

    created = fields.get('created', '')
    if created:
        print('Created {}'.format(created))

    summary = fields.get('summary', '')
    if summary:
        print('\n    {}'.format(summary))

    description = fields.get('description', '')
    if description:
        print('\nDescription:\n{}'.format(description))

def displayComments(comments):
    if comments:
        print("\nComments:")
        for c in comments:
            print('----------------------------------')
            print('Author: {} | Date: {}'.format(c["updateAuthor"]["displayName"],c["created"]))
            print('{}'.format(c["body"]))

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

def commandIssue(ui):
    ui = ui.down()
    issue_name = ui.operands()[0]
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
        if '--field' not in ui:
            displayBasicInformation({
                'key': issue_name,
                'fields': {
                    'created': cached.get('fields', 'created'),
                    'summary': cached.get('fields', 'summary'),
                    'description': cached.get('fields', 'description'),
                }
            })
            displayComments(cached.get('fields', 'comment', default={}).get('comments', []))
        else:
            fields = cached.raw()
            real_fields = ('summary', 'description', 'comment', 'created',)
            selected_fields = []
            if '--field' in ui:
                real_fields = [_[0] for _ in ui.get('-f')]
                selected_fields = [_.split('.')[0] for _ in real_fields]
            for i, key in enumerate(real_fields):
                if key == 'comment': continue
                value = fields.get(key)
                if key == 'assignee':
                    value = stringifyAssignee(value)
                if value is None:
                    print('{} (undefined)'.format(key))
                else:
                    print('{} = {}'.format(key, str(value).strip()))
            displayComments(cached.get('fields', 'comment', default={}).get('comments', []))
    elif str(ui) == 'show' or str(ui) == 'issue':
        real_fields = ('summary', 'description', 'comment', 'created',)
        selected_fields = []
        if '--field' in ui:
            real_fields = [_[0] for _ in ui.get('-f')]
            selected_fields = [_.split('.')[0] for _ in real_fields]
        request_content = {
            'fields': ','.join(selected_fields),
        }
        r = connection.get('/rest/api/2/issue/{}'.format(issue_name), params=request_content)
        if r.status_code == 200:
            response = json.loads(r.text)
            for k, v in response.get('fields', {}).items():
                cached.set('fields', k, value=v)
            cached.store()

            if '--field' not in ui:
                displayBasicInformation(response)
                displayComments(response.get('fields', {}).get('comment', {}).get('comments', []))
            elif '--pretty' in ui:
                print(json.dumps(response.get('fields', {}), indent=ui.get('--pretty')))
            elif '--raw' in ui:
                print(json.dumps(response.get('fields', {})))
            else:
                fields = response.get('fields', {})
                for i, key in enumerate(real_fields):
                    if key == 'comment': continue
                    value = obtain(fields, *key.split('.'))
                    if key == 'assignee':
                        value = stringifyAssignee(value)
                    if value is None:
                        print('{} (undefined)'.format(key))
                    else:
                        print('{} = {}'.format(key, str(value).strip()))
                displayComments(response.get('fields', {}).get('comment', {}).get('comments', []))
        elif r.status_code == 404:
            print("error: the requested issue is not found or the user does not have permission to view it.")
            exit(1)
        else:
            print('error: HTTP {}'.format(r.status_code))
            exit(1)
    elif str(ui) == 'label':
        issue_name, label = ui.operands()
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
        "jql": "",
        "startAt": 0,
        "maxResults": 15,
        "fields": [
            "summary",
            "status",
            "assignee",
            "status",
            "created",
            "status"
        ],
        "fieldsByKeys": False
    }
    conditions = []
    if "-p" in ui:
        conditions.append('project = {}'.format(ui.get("-p")))
    if "-a" in ui:
        conditions.append('assignee = {}'.format(ui.get("-a")))
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


def sluggify(issue_message):
    return '-'.join(re.compile('[^ a-zA-Z0-9_]').sub(' ', unidecode.unidecode(issue_message).lower()).split())

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

def commandSlug(ui):
    ui = ui.down()
    issue_name = ui.operands()[0]

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
    issue_name = ui.operands()[0]
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
        print('The input is invalid (e.g. missing required fields, invalid values, and so forth).')
    elif r.status_code == 403:
        print('Returned if the calling user does not have permission to add the worklog')


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
