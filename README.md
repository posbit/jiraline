# jiraline

Official website: http://jiraline.org

**Command Line Inteface for JIRA**

The aim of the project is to make developers
work with Jira faster. For those who work in the
terminal and don't want to break workflow to
maintain Jira.

## Forget GUI, use jiraline!


----

# Quick start

This section show how to perform some of the most common Jira
operations.

### Commenting

Let's start and see how to comment an issue.
Here is the syntax:

```
jiraline comment -m "Message text" <issue_name>
```

For example:

```
jiraline comment -m "This is comment made from my terminal" JL-42
```


### Assigning issues

Next step will be assigning an issue to user:

```
jiraline assign -u <user_name> <issue_name>
```


### Transitions

Displaying transitions available for an issue:

```
jiraline issue transition <issue_name>
```

Transitioning an issue to a new state:

```
jiraline issue transition --to <transition_id> <issue_name>
```


### Displaying issues

```
jiraline issue show <issue_name>
```

**Shortcut**

If only basic information is needed, a shortcut may be used:

```
jiraline issue <issue_name>
```


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
