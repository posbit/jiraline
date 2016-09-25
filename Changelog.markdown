# Jiraline Changelog

Release notes for each version are based on this Changelog.
Changelog is updated as features and fixes are added to the code.

----

## From 0.1.2 to 0.2.0

- *incompat*, *enhancement*: move configuration file from `~/.jiraline` to `~/.config/jiraline/config.json`
- *feature*: added label management commands (to avoid typos): `issue label (new|rm|ls)`


## From 0.1.1 to 0.1.2

- *feature*: Jiraline saves key of last active issue, and provides `-` as a shortcut for it;
  `-` can be used everywhere where an issue key is expected
- *feature*: `search` command can filter issues by reporter
- *feature*: `search` command can limit issues by lower and upper bound (e.g. show only issues
  with keys betwen 1000 and 1200)
- *enhancement*: better issue caching, issue details are always displayed from cache;
  `issue show` command first updates the cache, and then display information from it
- *enhancement*: Jiraline displays better message when editing comments in editor
- *feature*: `--ref` option in `comment` command puts output of `git show` for requested ref in
  comment message when editing comment in editor
- *enhancement*: Jiraline puts issue description in comment message (if available) when editing
  comment in editor
- *feature*: `--reply` option puts text of last comment in comment message when editing comment
  in editor
- *enhancement*: more readable output of `issue` and `issue show` commands
- *feature*: `pin` command for locally pinning issues, with optional comment;
  serves as a local todo list not synchronised with Jira


----

## From 0.1.0 to 0.1.1

- *feature*: `issue transition --to` option is plural, meaning that running
  command: `jiraline issue transition -t 1 -t 2 -t 3 JL-42` will transition `JL-42` to status 1, then
  to status 2, and than 3
