---
title : "Requirements"
permalink : "/docs/requirements/"
---

Jiraline is written in Python 3, so you should have an interpreter installed on your computer.

More over, Jiraline needs two external Python modules: [requests](http://docs.python-requests.org/en/master/) and [clap](https://github.com/marekjm/clap).

### Requests

This is very popular module for making http requests. It is availible on Python Package Index and also in distribution repository.

Install from PyPI:

```bash
pip install requests
```

Or install from distribution repositories:

**Debian:**
```
apt-get install python3-requests
```
{: .notice--info}

**Arch:**
```
pacman -S python-requests
```
{: .notice--info}

### Clap

Command line argument parser is used in project. This module organize user input and help to manage it in very convienient way. Clap can be installed using PyPI.

```bash
pip install clap-api
```
