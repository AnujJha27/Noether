#include "cache.hpp"
#include "lean_runner.hpp"
#include "protocol.hpp"
#include "worker_pool.hpp"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdlib>
#include <filesystem>
#include <future>
#include <iostream>
#include <thread>

namespace proof_search {
namespace {

json result_json(const std::string& id, const VerificationResult& result) {
  json response{{"version", 1}, {"id", id}, {"status", result.status},
                {"cached", result.cached}, {"elapsed_ms", result.elapsed_ms}};
  if (!result.diagnostics.empty()) response["diagnostics"] = result.diagnostics;
  return response;
}

VerificationResult check_one(const VerifyRequest& request, LeanRunner& runner,
                             Cache& cache, const std::atomic_bool* cancelled = nullptr) {
  if (cancelled && cancelled->load()) return {"cancelled", "", 0, false, -1};
  const std::string key = cache.key_for(request);
  if (auto hit = cache.lookup(key)) {
    cache.record_attempt(request, key, hit->status);
    return *hit;
  }
  auto result = runner.verify(request, cancelled);
  cache.store(key, result);
  cache.record_attempt(request, key, result.status);
  return result;
}

json process_batch(const BatchRequest& batch, LeanRunner& runner, Cache& cache,
                   unsigned service_workers) {
  const unsigned requested = batch.max_parallel == 0 ? service_workers : batch.max_parallel;
  const unsigned count = std::max(1U, std::min({requested, service_workers,
                                                static_cast<unsigned>(batch.candidates.size())}));
  WorkerPool pool(count);
  auto cancelled = std::make_shared<std::atomic_bool>(false);
  std::vector<std::future<VerificationResult>> futures;
  futures.reserve(batch.candidates.size());
  for (const auto& candidate : batch.candidates) {
    VerifyRequest request;
    request.id = candidate.id;
    request.project = batch.project;
    request.module = batch.module;
    request.declaration = batch.declaration;
    request.verification_mode = batch.verification_mode;
    request.preamble = batch.preamble;
    request.target = batch.target;
    request.patch = candidate.patch;
    request.limits = batch.limits;
    request.parent_attempt_id = batch.parent_attempt_id;
    futures.push_back(pool.submit([request, &runner, &cache, cancelled] {
      return check_one(request, runner, cache, cancelled.get());
    }));
  }
  std::vector<std::optional<VerificationResult>> results(batch.candidates.size());
  std::size_t remaining = futures.size();
  while (remaining != 0) {
    bool progress = false;
    for (std::size_t i = 0; i < futures.size(); ++i) {
      if (results[i] || futures[i].wait_for(std::chrono::milliseconds(0)) != std::future_status::ready) continue;
      results[i] = futures[i].get();
      --remaining;
      progress = true;
      if (batch.stop_on_first_success && results[i]->status == "verified") cancelled->store(true);
    }
    if (!progress) std::this_thread::sleep_for(std::chrono::milliseconds(2));
  }
  json entries = json::array();
  std::optional<std::string> winner;
  for (std::size_t i = 0; i < results.size(); ++i) {
    entries.push_back(result_json(batch.candidates[i].id, *results[i]));
    if (!winner && results[i]->status == "verified") winner = batch.candidates[i].id;
  }
  json response{{"version", 1}, {"id", batch.id}, {"status", winner ? "verified" : "no_candidate_verified"},
                {"results", entries}};
  if (winner) response["winner_id"] = *winner;
  return response;
}

unsigned configured_workers() {
  const char* value = std::getenv("PROOF_SEARCH_WORKERS");
  if (value) {
    try { const unsigned parsed = static_cast<unsigned>(std::stoul(value)); if (parsed > 0) return parsed; }
    catch (...) {}
  }
  const unsigned hardware = std::thread::hardware_concurrency();
  return hardware > 1 ? hardware - 1 : 1;
}

}  // namespace
}  // namespace proof_search

int main() {
  using namespace proof_search;
  try {
    const std::filesystem::path project = std::getenv("PROOF_SEARCH_PROJECT_DIR")
        ? std::getenv("PROOF_SEARCH_PROJECT_DIR") : "lean";
    const std::filesystem::path database = std::getenv("PROOF_SEARCH_DB")
        ? std::getenv("PROOF_SEARCH_DB") : "proof_search.db";
    LeanRunner runner(project);
    Cache cache(database, project);
    const unsigned workers = configured_workers();
    std::string line;
    while (std::getline(std::cin, line)) {
      json response;
      try {
        json request = json::parse(line);
        std::string id = request.is_object() && request.contains("id") && request["id"].is_string()
            ? request["id"].get<std::string>() : "";
        if (!request.is_object() || !request.contains("type") || !request["type"].is_string())
          response = invalid_response(id, "type must be a string");
        else if (request["type"] == "ping") {
          if (!request.contains("version") || !request["version"].is_number_integer() || request["version"] != 1 || id.empty())
            response = invalid_response(id, "ping requires version 1 and a non-empty string id");
          else response = {{"version", 1}, {"id", id}, {"status", "ok"}};
        } else if (request["type"] == "verify") {
          VerifyRequest parsed;
          if (auto error = parse_verify(request, parsed)) response = invalid_response(id, error->message);
          else if (parsed.verification_mode == "generated_obligation" &&
                   !generated_obligations_enabled())
            response = invalid_response(id, "generated obligations are disabled");
          else response = result_json(parsed.id, check_one(parsed, runner, cache));
        } else if (request["type"] == "search_batch") {
          BatchRequest parsed;
          if (auto error = parse_batch(request, parsed)) response = invalid_response(id, error->message);
          else if (parsed.verification_mode == "generated_obligation" &&
                   !generated_obligations_enabled())
            response = invalid_response(id, "generated obligations are disabled");
          else response = process_batch(parsed, runner, cache, workers);
        } else response = invalid_response(id, "unsupported request type");
      } catch (const json::exception& error) {
        response = invalid_response("", std::string("malformed JSON: ") + error.what());
      } catch (const std::exception& error) {
        response = {{"version", 1}, {"id", ""}, {"status", "worker_failure"}, {"diagnostics", error.what()}};
      }
      std::cout << response.dump() << '\n' << std::flush;
    }
  } catch (const std::exception& error) {
    std::cerr << "fatal: " << error.what() << '\n';
    return 1;
  }
}
