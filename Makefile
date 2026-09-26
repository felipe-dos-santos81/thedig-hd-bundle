# Makefile for thedig-hd-bundle: runs both projects from the root
# Order: extract (exporter) -> caption, batch, objects, review, verify (kit)
SERVICE = The Dig HD Bundle

EXPORTER = thedig-textures-exporter
KIT = thedig-texture-enhancement

# Arguments, e.g. make extract game="$$HOME/Documents/The Dig®.app"
game ?=
GAME_ARG = $(if $(game),--game "$(game)")

.PHONY: help install check extract

help: ## Print this help message
	@printf '\033[01;32m${SERVICE}\033[00;37m\n\n'
	@printf "\033[33mUsage:\033[0m\n  make [target] [arg=\"val\"...]\n\n\033[33mTargets:\033[0m\n"
	@grep -E '^[-a-zA-Z0-9_\.\/]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; \
		{printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'
	@printf "\nThe render pipeline runs in $(KIT)/: make -C $(KIT) help\n"

install: ## Create both projects' virtualenvs
	$(MAKE) -C $(EXPORTER) install
	$(MAKE) -C $(KIT) install

check: ## Run both projects' unit tests (no game, no GPU)
	$(MAKE) -C $(EXPORTER) check
	$(MAKE) -C $(KIT) check test

extract: ## Extract the rooms and objects the kit reads into the exporter's out/ (game=)
	$(MAKE) -C $(EXPORTER) install
	cd $(EXPORTER) && .venv/bin/thedig-textures extract --only la1 $(GAME_ARG)
