---
title : "Transitions"
permalink : "/docs/transitions/"
---

While working with issue you do a transition and change state of it. Possible transitions depens on present state of the issue. To list possible transitions use below:

```bash
jiraline issue -t ISSUE_NAME
```

or

```bash
jiraline issue --transitions ISSUE_NAME
```

This will bring you an output on which every line represents a single transition:

```bash
ID TRANSITION_NAME
```

For example:

```bash
jiraline issue -t JL-42
4 In-progress
7 Done
```

All rigth, let`s do the transtion now. Look at the syntax:

```bash
jiraline issue -d TRANSITION_ID ISSUE_NAME
```

or

```bash
jiraline issue --do TRANSITION_ID ISSUE_NAME
```

Where transition ID could be obtained from transitions list described in beginning of this section. Example usage:

```bash
jiraline issue --do 7 JL-42
```

