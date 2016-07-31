#!/usr/bin/python

import json
import sys
import os

import requests
import clap

model = {}
with open('./ui.json', 'r') as ifstream: model = json.loads(ifstream.read())
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
finally:
    if fail: exit(1)
    ui = parser.parse().ui().finalise()

if clap.helper.HelpRunner(ui=ui, program=sys.argv[0]).adjust(options=['-h', '--help']).run().displayed(): exit(0)


ui = ui.down()

settings = {}
if os.path.isfile(os.path.expanduser("~/.jiraline")):
    with open(os.path.expanduser("~/.jiraline")) as ifstream: settings = json.loads(ifstream.read())
    
def commandComment(ui):
    issue_name = ui.operands()[0]
    message = ""
    if "-m" in ui:
        message = ui.get("-m")
    else:
        message = input("Please type comment message: ")
    comment={"body":message}
    r = requests.post('https://{}.atlassian.net/rest/api/2/issue/{}/comment'.format(settings["domain"],issue_name),
                      json=comment,
                      auth=(settings["credentials"]["user"],settings["credentials"]["password"]))
    if r.status_code == 400:
        print('The input is invalid (e.g. missing required fields, invalid values, and so forth).')

def commandAssign(ui):
    issue_name = ui.operands()[0]
    user_name = ""
    if "-u" in ui:
        user_name = ui.get("-u")
    else:
        exit(1)
    assing={"name":user_name}
    r = requests.put('https://{}.atlassian.net/rest/api/2/issue/{}/assignee'.format(settings["domain"],issue_name),
                      json=assing,
                      auth=(settings["credentials"]["user"],settings["credentials"]["password"]))
    if r.status_code == 400:
        print('There is a problem with the received user representation.')
    elif r.status_code == 401:
        print("Calling user does not have permission to assign the issue.")
    elif r.status_code == 404:
        print("Either the issue or the user does not exist.")

def commandIssue(ui):
    issue_name = ui.operands()[0]
    if "-t" in ui:
        r = requests.get('https://{}.atlassian.net/rest/api/2/issue/{}/transitions'.format(settings["domain"],issue_name),
                      auth=(settings["credentials"]["user"],settings["credentials"]["password"]))
        if r.status_code == 404:
            print("The requested issue is not found or the user does not have permission to view it.")
        elif r.status_code == 200:
            response = json.loads(r.text)
            for t in response["transitions"]:
                print(t["name"],t["id"])
    elif "-d" in ui:
        transition = {
            "transition":{
                "id":ui.get("-d")
            }
        }
        r = requests.post('https://{}.atlassian.net/rest/api/2/issue/{}/transitions'.format(settings["domain"],issue_name),
                          json=transition,
                          auth=(settings["credentials"]["user"],settings["credentials"]["password"]))
        if r.status_code == 404:
            print("The issue does not exist or the user does not have permission to view it")
        elif r.status_code == 400:
            print("There is no transition specified.")
        elif r.status_code == 500:
            print("500 Internal server error")
    elif "-s" in ui:
        request_content = {
            "fields" : "summary,description,comment,created"
        }
        r = requests.get('https://{}.atlassian.net/rest/api/2/issue/{}'.format(settings["domain"],issue_name),
                          params=request_content,
                          auth=(settings["credentials"]["user"],settings["credentials"]["password"]))
        if r.status_code == 404:
            print("The requested issue is not found or the user does not have permission to view it.")
        elif r.status_code == 200:
            response = json.loads(r.text)
            print('{} | {} | Created: {}'.format(response["key"],response["fields"]["summary"],response["fields"]["created"]))
            print('\nDescription:\n{}'.format(response["fields"]["description"]))
            print("\nComments:")
            for c in response["fields"]["comment"]["comments"]:
                print('----------------------------------')
                print('Author: {} | Date: {}'.format(c["updateAuthor"]["displayName"],c["created"]))
                print('{}'.format(c["body"]))
    else:
        exit(1)

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

    request_content["jql"] = " AND ".join(conditions)
    r = requests.get('https://{}.atlassian.net/rest/api/2/search'.format(settings["domain"]),
                      params=request_content,
                      auth=(settings["credentials"]["user"],settings["credentials"]["password"]))
    if r.status_code == 200:
        response = json.loads(r.text)
        print('{:<7} | {:<50} | {:<20} | {:<19} | {:<20}'.format('Key','Summary','Assignee','Created','Status'))
        print('-' * 130)
        for i in response["issues"]:
            print('{:<.7} | {:<50.50} | {:<20.20} | {:<19.19} | {:<20.20}'.format(i["key"],i["fields"]["summary"],i["fields"]["assignee"]["displayName"],i["fields"]["created"],i["fields"]["status"]["name"]))

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
)
