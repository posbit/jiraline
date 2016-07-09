# jiraline
Command Line Inteface for JIRA

> The aim of the project is to make developers
> work with Jira faster. For those who work in the
> terminal and don`t want to break workflow to
> maintain Jira.
>
> Forget GUI, use jiraline!
>

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
