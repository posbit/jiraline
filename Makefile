.PHONY: install

install:
	mkdir -p ~/.local/bin
	cp ./jiraline.py ~/.local/bin/jiraline
	chmod +x ~/.local/bin/jiraline
	mkdir -p ~/.local/share/jiraline
	cp ./ui.json ~/.local/share/jiraline/ui.json
	mkdir -p ~/.local/share/jiraline/messages
	cp ./share/messages/* ~/.local/share/jiraline/messages/
	mkdir -p ~/.cache/jiraline
