---
title : "Settings"
permalink : "/docs/settings/"
---

Jiraline needs configuration file for proper working. You have to store your settings there, otherwise you will have to enter them all the time.

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
