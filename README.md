# jiraline

Official website: jiraline.org

Command Line Inteface for JIRA

 The aim of the project is to make developers
 work with Jira faster. For those who work in the
 terminal and don`t want to break workflow to
 maintain Jira.

## Forget GUI, use jiraline!


----
# Quick start

In this section most common operations will be shown. Let`s start and see how to comment an issue.
Here is syntax:

    jiraline comment -m "Message text" ISSUE_NAME

For example:

    jiraline comment -m "This is comment made from my terminal" JL-42

Next step will be assigning an issue to user:

    jiraline assing -u USER_NAME ISSUE_NAME


----
# Settings

In file `~/.jiraline` put the following contents:


```
{
    "domain": <your JIRA cloud domain>,
    "credentials": {
        "user": <your user name>,
        "password": <your password>
     }
}
```

Sample valid config that will let you connect to `example.atlassian.net`:

```
{
    "domain": "example",
    "credentials": {
        "user": "username"
        "password": "$ecretP4s$w0rd1"
     }
}
```
