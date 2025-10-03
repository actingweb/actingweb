# Minimal makefile for Sphinx documentation
#

# You can set these variables from the command line.
SPHINXOPTS    =
SPHINXBUILD   = sphinx-build
SOURCEDIR     = .
BUILDDIR      = _build

# Put it first so that "make" without argument is like "make help".
help:
	@$(SPHINXBUILD) -M help "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)

.PHONY: help Makefile test-integration test-integration-fast

# Integration test targets
test-integration:
	@echo "Starting integration tests..."
	docker-compose -f docker-compose.test.yml up -d
	@sleep 2
	poetry run pytest tests/integration/ -v --tb=short
	docker-compose -f docker-compose.test.yml down -v

test-integration-fast:
	@echo "Starting integration tests (fast mode - skipping slow tests)..."
	docker-compose -f docker-compose.test.yml up -d
	@sleep 2
	poetry run pytest tests/integration/ -v -m "not slow" --tb=short
	docker-compose -f docker-compose.test.yml down -v

# Catch-all target: route all unknown targets to Sphinx using the new
# "make mode" option.  $(O) is meant as a shortcut for $(SPHINXOPTS).
%: Makefile
	@$(SPHINXBUILD) -M $@ "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)