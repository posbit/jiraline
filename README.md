# jiraline
Command Line Inteface for JIRA

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
