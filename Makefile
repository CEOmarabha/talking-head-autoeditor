.PHONY: help install edit calibrate check clean
.DEFAULT_GOAL := help

PY := .venv/bin/python
OUT ?= $(HOME)/Desktop/autoedit-out

help:  ## Show this help
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | \
	  awk 'BEGIN{FS=":.*?## "}{printf "  \033[1;34m%-12s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "  Example:  make edit VIDEO=~/Movies/take1.mov SCRIPT=lesson1.txt"

install:  ## One-time setup (ffmpeg, venv, models)
	@bash install.sh

edit:  ## Edit a video.  VIDEO=raw.mov [SCRIPT=script.txt] [STYLE=long|short]
	@test -n "$(VIDEO)" || { echo "usage: make edit VIDEO=/path/to/raw.mov"; exit 1; }
	$(PY) -m autoeditor "$(VIDEO)" \
	  --out "$(OUT)/$(notdir $(basename $(VIDEO)))" \
	  $(if $(SCRIPT),--script "$(SCRIPT)") \
	  $(if $(STYLE),--style $(STYLE),--style long) \
	  $(if $(ASPECT),--aspects $(ASPECT),--aspects 16x9)

calibrate:  ## Measure your camera's audio/video offset.  VIDEO=take.mov
	@test -n "$(VIDEO)" || { echo "usage: make calibrate VIDEO=/path/to/take.mov"; exit 1; }
	$(PY) -m autoeditor.calibrate "$(VIDEO)"

check:  ## Verify the install is working
	@$(PY) -c "import faster_whisper, PIL, numpy; print('python deps  ok')"
	@ffmpeg -version >/dev/null && echo "ffmpeg       ok"
	@$(PY) -c "from autoeditor import providers; \
	  providers.load_dotenv(); \
	  print('llm          ' + ('ok' if providers.llm_available() else 'not configured (heuristic fallback will be used)'))"

clean:  ## Remove cached b-roll and generated assets
	rm -rf $(HOME)/.autoeditor/broll_cache/*
	@echo "cache cleared"
