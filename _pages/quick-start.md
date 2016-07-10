---
title: "Quick-start Guide"
permalink: /quick-start/
---

{% include base_path %}

# Quick start

In this section most common operations will be shown. Let`s start and see how to comment an issue.
Here is syntax:

```bash
jiraline comment -m "Message text" ISSUE_NAME
```

For example:

    jiraline comment -m "This is comment made from my terminal" JL-42

Next step will be assigning an issue to user:

    jiraline assing -u USER_NAME ISSUE_NAME
