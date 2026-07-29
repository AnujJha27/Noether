#include "cache.hpp"
#include "lean_runner.hpp"

#include <algorithm>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <thread>
#include <vector>

using namespace proof_search;

int main(int argc, char** argv) {
  const std::filesystem::path database = std::filesystem::temp_directory_path() / "proof-search-benchmark.db";
  std::filesystem::remove(database);
  LeanRunner runner("lean");
  Cache cache(database, "lean");
  const std::filesystem::path fixture_path = argc > 1 ? argv[1] : "tests/fixtures/benchmark.json";
  std::ifstream fixture_file(fixture_path);
  json fixture_json;
  fixture_file >> fixture_json;
  if (!fixture_json.is_array() || fixture_json.empty()) {
    std::cerr << "benchmark fixture must be a non-empty JSON array\n";
    return 1;
  }
  std::vector<VerifyRequest> requests;
  for (const auto& value : fixture_json) {
    VerifyRequest request;
    if (const auto error = parse_verify(value, request)) {
      std::cerr << "invalid benchmark fixture: " << error->message << '\n';
      return 1;
    }
    requests.push_back(std::move(request));
  }
  std::vector<long long> latencies;
  std::map<std::string, int> failures;
  int verified = 0;
  int cache_hits = 0;
  std::vector<long long> pass_elapsed_ms;
  const auto started = std::chrono::steady_clock::now();
  for (int pass = 0; pass < 2; ++pass) {
    const auto pass_started = std::chrono::steady_clock::now();
    for (auto request : requests) {
      const auto attempt_started = std::chrono::steady_clock::now();
      request.id += "-" + std::to_string(pass);
      const auto key = cache.key_for(request);
      VerificationResult result;
      if (auto hit = cache.lookup(key)) { result = *hit; ++cache_hits; }
      else { result = runner.verify(request); cache.store(key, result); }
      latencies.push_back(std::chrono::duration_cast<std::chrono::milliseconds>(
          std::chrono::steady_clock::now() - attempt_started).count());
      if (result.status == "verified") ++verified;
      else ++failures[result.status];
    }
    pass_elapsed_ms.push_back(std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now() - pass_started).count());
  }
  const auto total_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
      std::chrono::steady_clock::now() - started).count();
  std::sort(latencies.begin(), latencies.end());
  const auto percentile = [&](double p) {
    const std::size_t index = static_cast<std::size_t>((latencies.size() - 1) * p);
    return latencies[index];
  };
  json configured_limits = json::array();
  for (const auto& request : requests)
    configured_limits.push_back({{"id", request.id},
                                 {"wall_time_ms", request.limits.wall_time_ms},
                                 {"cpu_time_s", request.limits.cpu_time_s},
                                 {"memory_mb", request.limits.memory_mb}});
  json output{{"total_attempts", latencies.size()}, {"verified_attempts", verified},
              {"checks_per_second", total_ms ? latencies.size() * 1000.0 / total_ms : 0.0},
              {"p50_latency_ms", percentile(0.50)}, {"p95_latency_ms", percentile(0.95)},
              {"cache_hits", cache_hits}, {"cache_hit_rate", cache_hits * 1.0 / latencies.size()},
              {"cold_cache", {{"attempts", requests.size()}, {"elapsed_ms", pass_elapsed_ms[0]}}},
              {"warm_cache", {{"attempts", requests.size()}, {"elapsed_ms", pass_elapsed_ms[1]}}},
              {"failure_counts", failures},
              {"worker_count", std::thread::hardware_concurrency() > 1
                                   ? std::thread::hardware_concurrency() - 1 : 1},
              {"configured_limits", configured_limits}};
  std::ofstream file("benchmark-results.json");
  file << output.dump(2) << '\n';
  std::cout << output.dump(2) << '\n';
  std::filesystem::remove(database);
}
