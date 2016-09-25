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

#### Note about caching

Jira is slow.
Network is also slow.
Disk reads are (relatively) fast.

This is why Jiraline tries to cache issue details whenever it can.
Running `jiraline issue <issue-name>` command will display cached data if
available.
Running `jiraline issue show <issue-name>` command will always fetch fresh
data from network disregarding cache.


#### Displaying detailed fields

To access nested fields in Jira responses use dot-separated keys parts:

```
~]$ jiraline issue show -f assigne JL-42
assignee = John Doe <email@example.com>
~]$ jiraline issue show -f assigne.emailAddress JL-42
assignee.emailAddress = email@example.com
```

### Sluggification and branching

Jiraline provides `slug` command which can be used to generate branch names from issue titles.
It can also create and checkout Git branches based on issue titles.

#### Sluggification

```
jiraline slug [-F/--use-format <format_name>] [-f/--format <format_string>] [--git] <issue_name>
```

The simplest form of this command is just `jiraline slug JL-42`, which will print a branch name to standard output.
It provides options for adjusting slug formats:

- `--use-format` will load a format from settings
- `--format` will use supplied parameter as format
- `--git` will use simple Git-ready format

#### Branching

```
jiraline slug [-B/--git-branch] [-C/--git-checkout] <issue_name>
```

To create a Git branch from slug use `-B/--git-branch` option.
To checkout a Git branch use `-C/--git-checkout` option (*note*: `-C` does not automatically create branches).
To create and checkout a branch use `-BC` combo.

Example:

```
jiraline ba0bab4 (devel) ]$ jiraline slug -BCg JL-42
jiraline ba0bab4 (issue/jl-42/example) ]$
```


### Time estimating

To estimate work time for issue use `estimate` command:

```
jiraline estimate <issue_name> <time> 
```

Time is in JIRA format.

Example:
```
jiraline estimate IP-1345 3h
jiraline estimate IP-1345 "3h 15m"
```


### Shortcuts

Jiraline has a few shortcuts that can speed up working with issues.

#### Using `-` as "last active issue"

When specifying issue id in `comment`, `issue show` etc. commands `-` can be used as the id.
Jiraline will expand it to mean "last active issue".
Last active issue is an issue that has been specified last.
Every command that requires a specific issue id updates the marker.


### Built-in help screens

To display built-in help screens use `help` command (help screens are automatically
generated by CLAP library):

```
jiraline help [--verbose]
```

The `--verbose` option forces recursive help screen builting; use it to get one, big
help screen browsable with `less`.


#### Detailed help screens

To get detailed help on a subcommand use:

```
jiraline help -v <subcommand>...
```

For example, to get help on transitions:

```
jiraline help -v issue transition
```

To get help on an option use:

```
jiraline help -v <subcommand>... <option>
```

For example, to get help on transitions:

```
jiraline help -v issue transition --to
```


----

# Settings

In file `~/.config/jiraline/config.json` put the following contents:


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

### Slug formats

Put slug formats in `slug.format` dictionary:

```
{
    "slug": {
        "format": {
            "<format name>": "<your example format>"
        }
    }
}
```

By default Jiraline uses `default` format.
You can either put default format in `slug.format.default` key, or
use indirection, i.e. set `slug.format.default` key to `@example` and
Jiraline will use the format named `example`.

Example with direct format:

```
{
    "slug": {
        "format": {
            "default": "issue/{issue_key}/{slug}"
        }
    }
}
```

Example with indirection:

```
{
    "slug": {
        "format": {
            "default": "@non-default"
            "non-default": "non-default-format/{issue_key}/{slug}"
        }
    }
}
```

You can switch formats on-fly using `-F` option.
For example, using the following config:

```
{
    "slug": {
        "format": {
            "default": "@foo"
            "foo": "foo/{issue_key}/{slug}",
            "bat": "bar/{issue_key}/{slug}"
        }
    }
}
```

You can achieve following results:

````
jiraline ba0bab4 (devel) ]$ jiraline slug JL-42
foo/jl-42/example
jiraline ba0bab4 (devel) ]$ jiraline slug -F foo JL-42
foo/jl-42/example
jiraline ba0bab4 (devel) ]$ jiraline slug -F bar JL-42
bar/jl-42/example
```

### Default project

Setting default project allows writing just the numeric ID of an issue without prepending project prefix to it when
specifying the issue for `jiraline` to work on.
Example:

```
~]$ jiraline i sh JL-42
~]$ jiraline i sh 42
```

If `default_project` key in configuration file is set to `JL` the above lines are equivalent.
Example configuration:

```
{
    ...
    "default_project": "JL"
}
```
