#include "cache.hpp"
#include "lean_runner.hpp"
#include "protocol.hpp"
#include "worker_pool.hpp"

#include <atomic>
#include <chrono>
#include <cstdlib>
#include <filesystem>
#include <iostream>
#include <stdexcept>
#include <thread>
#include <vector>

using namespace proof_search;

namespace {
int assertions = 0;

void expect(bool condition, const char* message) {
  ++assertions;
  if (!condition) throw std::runtime_error(message);
}

void protocol_tests() {
  VerifyRequest request;
  json valid = {{"version", 1}, {"id", "a"}, {"type", "verify"}, {"project", "sample"},
                {"module", "ProofSearch.Examples"},
                {"declaration", "theorem arbitrary_name (n : Nat) : n + 0 = n"},
                {"target", "ProofSearch.Examples.add_zero"}, {"patch", "by rfl"}};
  expect(!parse_verify(valid, request), "valid verify request was rejected");
  expect(request.limits.wall_time_ms == 15000, "wrong default wall limit");
  valid["version"] = 2;
  expect(parse_verify(valid, request).has_value(), "unsupported version accepted");
  valid["version"] = 1;
  valid.erase("declaration");
  expect(parse_verify(valid, request).has_value(), "missing declaration accepted");
  valid["declaration"] = "theorem arbitrary_name (n : Nat) : n + 0 = n";
  valid["module"] = "ProofSearch.Examples\n#check Nat";
  expect(parse_verify(valid, request).has_value(), "invalid module accepted");
  valid["module"] = "ProofSearch.Examples";
  valid["preamble"] = "def injected := True";
  expect(parse_verify(valid, request).has_value(), "preamble accepted in existing-target mode");
  valid.erase("target");
  valid["verification_mode"] = "generated_obligation";
  expect(!parse_verify(valid, request), "valid generated obligation was rejected");
  expect(request.preamble == "def injected := True" && request.target.empty(),
         "generated proof context fields were lost");
  valid["target"] = "ProofSearch.Examples.add_zero";
  expect(parse_verify(valid, request).has_value(), "generated obligation accepted a target");

  unsetenv("PROOF_SEARCH_ALLOW_GENERATED_OBLIGATIONS");
  expect(!generated_obligations_enabled(), "generated mode defaulted to enabled");
  setenv("PROOF_SEARCH_ALLOW_GENERATED_OBLIGATIONS", "1", 1);
  expect(generated_obligations_enabled(), "generated mode opt-in was ignored");
  unsetenv("PROOF_SEARCH_ALLOW_GENERATED_OBLIGATIONS");

  BatchRequest batch;
  json batch_json = {{"version", 1}, {"id", "b"}, {"type", "search_batch"}, {"project", "sample"},
                     {"module", "ProofSearch.Examples"},
                     {"declaration", "theorem arbitrary_name (n : Nat) : n + 0 = n"},
                     {"target", "ProofSearch.Examples.add_zero"},
                     {"candidates", json::array({{{"id", "x"}, {"patch", "by rfl"}}})},
                     {"max_parallel", 1}, {"stop_on_first_success", true}};
  expect(!parse_batch(batch_json, batch), "valid batch was rejected");
  expect(batch.candidates.size() == 1 && batch.stop_on_first_success, "batch fields lost");
}

void worker_pool_tests() {
  WorkerPool pool(2);
  std::atomic_int active{0};
  std::atomic_int maximum{0};
  std::vector<std::future<int>> jobs;
  for (int i = 0; i < 8; ++i) jobs.push_back(pool.submit([&] {
    const int now = ++active;
    int seen = maximum.load();
    while (now > seen && !maximum.compare_exchange_weak(seen, now)) {}
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
    --active;
    return 1;
  }));
  for (auto& job : jobs) expect(job.get() == 1, "worker job failed");
  expect(maximum.load() <= 2, "worker bound exceeded");
}

void cache_tests() {
  const auto path = std::filesystem::temp_directory_path() / "proof-search-cache-test.db";
  std::filesystem::remove(path);
  {
    Cache cache(path, "lean");
    VerifyRequest request;
    request.id = "cache-attempt"; request.project = "sample";
    request.module = "ProofSearch.Examples";
    request.declaration = "theorem arbitrary_name (n : Nat) : n + 0 = n";
    request.target = "ProofSearch.Examples.add_zero";
    request.patch = "by rfl";
    request.parent_attempt_id = "parent";
    request.subgoal_description = "identity subgoal";
    const auto key = cache.key_for(request);
    VerificationResult saved{"verified", "", 12, false, 0};
    cache.store(key, saved);
    cache.record_attempt(request, key, saved.status);
    auto found = cache.lookup(key);
    expect(found && found->cached && found->status == "verified", "cache round trip failed");
  }
  std::filesystem::remove(path);
}

void lean_tests() {
  LeanRunner runner("lean");
  VerifyRequest valid;
  valid.id = "lean-valid"; valid.project = "sample";
  valid.module = "ProofSearch.Examples";
  valid.declaration = "theorem completely_arbitrary.{u} {α : Sort u} (x : α) : x = x";
  valid.target = "ProofSearch.Examples.identity";
  valid.patch = "by rfl";
  valid.limits.wall_time_ms = 30000;
  valid.limits.memory_mb = 8192;
  expect(runner.verify(valid).status == "verified", "valid Lean proof was not verified");

  VerifyRequest invalid;
  invalid.id = "lean-invalid"; invalid.project = valid.project; invalid.module = valid.module;
  invalid.declaration = valid.declaration; invalid.target = valid.target;
  invalid.patch = "by exact x";
  invalid.limits = valid.limits;
  expect(runner.verify(invalid).status == "lean_error", "invalid Lean proof was misclassified");

  VerifyRequest mismatch = valid;
  mismatch.id = "lean-mismatched-statement";
  mismatch.declaration = "theorem unrelated_statement : True";
  mismatch.patch = "by trivial";
  expect(runner.verify(mismatch).status == "lean_error",
         "a proof of a mismatched statement was accepted for the target");

  VerifyRequest generated = valid;
  generated.id = "lean-generated";
  generated.verification_mode = "generated_obligation";
  generated.target.clear();
  generated.preamble = "def generatedWitness : Nat := 1";
  generated.declaration = "theorem generated_goal : generatedWitness = 1";
  generated.patch = "by rfl";
  expect(runner.verify(generated).status == "verified",
         "generated Lean obligation was not verified");

  VerifyRequest timeout = valid;
  timeout.id = "lean-timeout";
  timeout.limits.wall_time_ms = 1;
  expect(runner.verify(timeout).status == "timeout", "wall timeout was not enforced");

  VerifyRequest memory = valid;
  memory.id = "lean-memory";
  memory.limits.memory_mb = 64;
  const auto memory_result = runner.verify(memory);
  expect(memory_result.status == "memory_limit", "memory limit was not classified");
}
}  // namespace

int main() {
  try {
    protocol_tests();
    worker_pool_tests();
    cache_tests();
    lean_tests();
    std::cout << "passed " << assertions << " assertions\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "test failure: " << error.what() << '\n';
    return 1;
  }
}
