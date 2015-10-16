SERVER_URL = https://api-accounts.stage.mozaws.net/v1

# Hackety-hack around OSX system python bustage.
# The need for this should go away with a future osx/xcode update.
ARCHFLAGS = -Wno-error=unused-command-line-argument-hard-error-in-future
INSTALL = ARCHFLAGS=$(ARCHFLAGS) PYTHONPATH= ./bin/pip install

.PHONY: build install test lint run clean

build:
	virtualenv --no-site-packages .
	$(INSTALL) PyFxA[openssl]
	$(INSTALL) flake8

install: build

test:
	bin/flake8 ./main.py ./restmail.py

lint: test

run:
	@PYTHONPATH= ./main.py

# Clean all the things installed by `make build`.
clean:
	rm -rf ./include ./bin ./lib ./lib64 *.pyc .Python pip-selfcheck.json
