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

.PHONY: help Makefile test-integration test-integration-fast test-integration-parallel test-integration-parallel-fast test-parallel test-parallel-fast

# Integration test targets (sequential execution)
test-integration:
	@echo "Starting integration tests (sequential)..."
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

# Integration test targets (parallel execution with pytest-xdist)
test-integration-parallel:
	@echo "Starting integration tests (parallel with auto worker detection)..."
	docker-compose -f docker-compose.test.yml up -d
	@sleep 2
	poetry run pytest tests/integration/ -n auto -v --tb=short --dist loadgroup
	docker-compose -f docker-compose.test.yml down -v

test-integration-parallel-fast:
	@echo "Starting integration tests (parallel, fast mode - skipping slow tests)..."
	docker-compose -f docker-compose.test.yml up -d
	@sleep 2
	poetry run pytest tests/integration/ -n auto -v -m "not slow" --tb=short --dist loadgroup
	docker-compose -f docker-compose.test.yml down -v

# Shorter aliases for parallel testing
test-parallel:
	@$(MAKE) test-integration-parallel

test-parallel-fast:
	@$(MAKE) test-integration-parallel-fast

# Run all tests (unit + integration) in parallel
test-all-parallel:
	@echo "Starting all tests (parallel)..."
	docker-compose -f docker-compose.test.yml up -d
	@sleep 2
	poetry run pytest tests/ -n auto -v --tb=short --dist loadgroup
	docker-compose -f docker-compose.test.yml down -v

# Catch-all target: route all unknown targets to Sphinx using the new
# "make mode" option.  $(O) is meant as a shortcut for $(SPHINXOPTS).
%: Makefile
	@$(SPHINXBUILD) -M $@ "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)