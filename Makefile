CXX ?= g++
CXXFLAGS := -std=c++17 -Wall -Wextra -Wpedantic -g -pthread -Iinclude
LDFLAGS := -pthread -lsqlite3
ifeq ($(RELEASE),1)
CXXFLAGS := -std=c++17 -Wall -Wextra -Wpedantic -O2 -DNDEBUG -pthread -Iinclude
endif

BUILD := build
DFT_PROJECT ?=
LAKE ?= $(shell command -v lake 2>/dev/null || getent passwd $$(id -u) | cut -d: -f6 | sed 's,$$,/.elan/bin/lake,')
LEAN_COMMAND ?= $(LAKE) env lean -j 1
DFT_CERT_TIMEOUT_S ?= 1800
CORE_SRC := src/protocol.cpp src/worker_pool.cpp src/lean_runner.cpp src/cache.cpp
SERVICE_SRC := src/main.cpp $(CORE_SRC)
TEST_SRC := tests/test_main.cpp $(CORE_SRC)
BENCH_SRC := src/benchmark.cpp $(CORE_SRC)

.PHONY: all test benchmark benchmark-repeat clean lean orchestrator-test dftcert-test dftcert-example \
	dftcert-obligations dftcert-assemble-example dftcert-certify-example \
	dftcert-search-example wsl-smoke

all: $(BUILD)/proof-search

$(BUILD):
	mkdir -p $(BUILD)

$(BUILD)/proof-search: $(SERVICE_SRC) | $(BUILD)
	$(CXX) $(CXXFLAGS) $(SERVICE_SRC) -o $@ $(LDFLAGS)

$(BUILD)/tests: $(TEST_SRC) | $(BUILD)
	$(CXX) $(CXXFLAGS) $(TEST_SRC) -o $@ $(LDFLAGS)

$(BUILD)/benchmark: $(BENCH_SRC) | $(BUILD)
	$(CXX) $(CXXFLAGS) $(BENCH_SRC) -o $@ $(LDFLAGS)

lean:
	cd lean && $(LAKE) build

orchestrator-test:
	python3 -m unittest -v tests.test_orchestrator

dftcert-test:
	python3 -m unittest -v tests.test_dftcert

dftcert-example:
	test -n "$(DFT_PROJECT)"
	python3 -m dftcert.cli certificate-check --project "$(DFT_PROJECT)" \
	  --source policies/lean/DFTArchitectureV1Example.lean \
	  --manifest examples/dft/example-manifest.json \
	  --lean-command "$(LEAN_COMMAND)" \
	  --timeout-s "$(DFT_CERT_TIMEOUT_S)" --trusted-local

dftcert-obligations:
	python3 -m dftcert.cli generate-obligations \
	  --manifest examples/dft/example-manifest.json \
	  --output build/dft-obligations.json

dftcert-assemble-example:
	python3 -m dftcert.cli assemble-certificate \
	  --manifest examples/dft/example-manifest.json \
	  --proof-results examples/dft/example-proof-results.json \
	  --source-output build/DFTGeneratedCertificate.lean \
	  --report-output build/dft-certificate-report.json

dftcert-certify-example:
	test -n "$(DFT_PROJECT)"
	python3 -m dftcert.cli certify-results \
	  --manifest examples/dft/example-manifest.json \
	  --proof-results examples/dft/example-proof-results.json \
	  --source-output build/DFTGeneratedCertificate.lean \
	  --report-output build/dft-certificate-report.json \
	  --project "$(DFT_PROJECT)" \
	  --lean-command "$(LEAN_COMMAND)" \
	  --timeout-s "$(DFT_CERT_TIMEOUT_S)" --trusted-local

dftcert-search-example: $(BUILD)/proof-search
	test -n "$(DFT_PROJECT)"
	test -n "$(LLM_COMMAND)"
	python3 -m dftcert.cli generate-obligations \
	  --manifest examples/dft/example-manifest.json --jsonl | \
	  PROOF_SEARCH_ALLOW_GENERATED_OBLIGATIONS=1 \
	  PROOF_SEARCH_PROJECT_DIR="$(DFT_PROJECT)" \
	  PROOF_SEARCH_DB="$(BUILD)/dft-proof-search.db" \
	  python3 -m orchestrator.cli --provider command \
	    --llm-command "$(LLM_COMMAND)" --verifier ./build/proof-search

test: $(BUILD)/proof-search $(BUILD)/tests lean orchestrator-test dftcert-test
	$(BUILD)/tests

wsl-smoke: $(BUILD)/proof-search lean
	printf '%s\n' '{"id":"wsl-smoke","project":"sample","module":"ProofSearch.Examples","target":"ProofSearch.Examples.add_zero","theorem":"theorem any_client_name (n : Nat) : n + 0 = n"}' | python3 -m orchestrator.cli --provider mock --max-rounds 1

benchmark: $(BUILD)/benchmark lean
	$(BUILD)/benchmark

benchmark-repeat: $(BUILD)/benchmark lean
	python3 scripts/benchmark_repeat.py --runs 5 --binary $(BUILD)/benchmark

clean:
	rm -rf $(BUILD) benchmark-results.json proof_search.db lean/.lake
