#pragma once

#include <nlohmann/json.hpp>
#include <optional>
#include <string>
#include <vector>

namespace proof_search {

using json = nlohmann::json;

struct Limits {
  int wall_time_ms = 15000;
  int cpu_time_s = 4;
  // Lean 4.31 reserves more than 2 GiB of virtual address space at startup.
  int memory_mb = 4096;
};

struct VerifyRequest {
  std::string id;
  std::string project;
  std::string module;
  std::string declaration;
  std::string verification_mode = "existing_target";
  std::string preamble;
  std::string target;
  std::string patch;
  Limits limits;
  std::optional<std::string> parent_attempt_id;
  std::optional<std::string> subgoal_description;
};

struct Candidate {
  std::string id;
  std::string patch;
};

struct BatchRequest {
  std::string id;
  std::string project;
  std::string module;
  std::string declaration;
  std::string verification_mode = "existing_target";
  std::string preamble;
  std::string target;
  std::vector<Candidate> candidates;
  Limits limits;
  unsigned max_parallel = 0;
  bool stop_on_first_success = false;
  std::optional<std::string> parent_attempt_id;
};

struct ParseError { std::string message; };

json invalid_response(const std::string& id, const std::string& message);
bool generated_obligations_enabled();
std::optional<ParseError> parse_verify(const json& value, VerifyRequest& out);
std::optional<ParseError> parse_batch(const json& value, BatchRequest& out);

}  // namespace proof_search
