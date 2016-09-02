# Jiraline Changelog

Release notes for each version are based on this Changelog.
Changelog is updated as features and fixes are added to the code.

----

## From 0.1.0 to 0.1.1

- *feature*: `issue transition --to` option is plural, meaning that running
  command: `jiraline issue transition -t 1 -t 2 -t 3 JL-42` will transition `JL-42` to status 1, then
  to status 2, and than 3
