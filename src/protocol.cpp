#include "protocol.hpp"

#include <cstdlib>
#include <limits>

namespace proof_search {
namespace {

bool valid_target(const std::string& target) {
  if (target.empty() || target.front() == '.' || target.back() == '.') return false;
  for (const unsigned char character : target) {
    if (!(std::isalnum(character) || character >= 0x80 || character == '_' ||
          character == '\'' || character == '.'))
      return false;
  }
  return true;
}

bool valid_declaration(const std::string& declaration) {
  const auto first = declaration.find_first_not_of(" \t\r\n");
  if (first == std::string::npos || declaration.find(":=") != std::string::npos) return false;
  const bool theorem = declaration.compare(first, 7, "theorem") == 0;
  const bool lemma = declaration.compare(first, 5, "lemma") == 0;
  const std::size_t keyword_end = first + (theorem ? 7 : lemma ? 5 : 0);
  if ((!theorem && !lemma) || keyword_end >= declaration.size() ||
      !std::isspace(static_cast<unsigned char>(declaration[keyword_end]))) return false;
  const auto name = declaration.find_first_not_of(" \t\r\n", keyword_end);
  if (name == std::string::npos) return false;
  const auto name_end = declaration.find_first_of(" \t\r\n({[:", name);
  return name_end != std::string::npos && name_end != name;
}

std::optional<ParseError> common(const json& value, std::string& id,
                                 std::string& project, Limits& limits) {
  if (!value.is_object()) return ParseError{"request must be a JSON object"};
  if (!value.contains("version") || !value["version"].is_number_integer() ||
      value["version"].get<int>() != 1)
    return ParseError{"version must be the integer 1"};
  if (!value.contains("id") || !value["id"].is_string() ||
      value["id"].get<std::string>().empty())
    return ParseError{"id must be a non-empty string"};
  id = value["id"].get<std::string>();
  if (!value.contains("project") || !value["project"].is_string() ||
      value["project"].get<std::string>().empty())
    return ParseError{"project must be a non-empty string"};
  project = value["project"].get<std::string>();
  if (!value.contains("limits")) return std::nullopt;
  const auto& l = value["limits"];
  if (!l.is_object()) return ParseError{"limits must be an object"};
  auto positive = [&l](const char* name, int& field) -> std::optional<ParseError> {
    if (!l.contains(name)) return std::nullopt;
    if (!l[name].is_number_integer()) return ParseError{std::string(name) + " must be an integer"};
    const long long number = l[name].get<long long>();
    if (number <= 0 || number > std::numeric_limits<int>::max())
      return ParseError{std::string(name) + " must be a positive integer"};
    field = static_cast<int>(number);
    return std::nullopt;
  };
  if (auto error = positive("wall_time_ms", limits.wall_time_ms)) return error;
  if (auto error = positive("cpu_time_s", limits.cpu_time_s)) return error;
  return positive("memory_mb", limits.memory_mb);
}

std::optional<ParseError> optional_string(const json& value, const char* name,
                                          std::optional<std::string>& out) {
  if (!value.contains(name)) return std::nullopt;
  if (!value[name].is_string() || value[name].get<std::string>().empty())
    return ParseError{std::string(name) + " must be a non-empty string"};
  out = value[name].get<std::string>();
  return std::nullopt;
}

std::optional<ParseError> proof_context(const json& value, std::string& mode,
                                        std::string& preamble, std::string& target) {
  mode = "existing_target";
  preamble.clear();
  target.clear();
  if (value.contains("verification_mode")) {
    if (!value["verification_mode"].is_string())
      return ParseError{"verification_mode must be a string"};
    mode = value["verification_mode"].get<std::string>();
  }
  if (mode != "existing_target" && mode != "generated_obligation")
    return ParseError{"unsupported verification_mode"};
  if (mode == "existing_target") {
    if (value.contains("preamble"))
      return ParseError{"preamble is only allowed for generated obligations"};
    if (!value.contains("target") || !value["target"].is_string() ||
        !valid_target(value["target"].get<std::string>()))
      return ParseError{"target must be a dotted Lean identifier"};
    target = value["target"].get<std::string>();
    return std::nullopt;
  }
  if (value.contains("target"))
    return ParseError{"generated obligations must not contain target"};
  if (value.contains("preamble")) {
    if (!value["preamble"].is_string())
      return ParseError{"preamble must be a string"};
    preamble = value["preamble"].get<std::string>();
  }
  return std::nullopt;
}

}  // namespace

json invalid_response(const std::string& id, const std::string& message) {
  return {{"version", 1}, {"id", id}, {"status", "invalid_request"},
          {"diagnostics", message}};
}

bool generated_obligations_enabled() {
  const char* value = std::getenv("PROOF_SEARCH_ALLOW_GENERATED_OBLIGATIONS");
  return value && std::string(value) == "1";
}

std::optional<ParseError> parse_verify(const json& value, VerifyRequest& out) {
  if (auto error = common(value, out.id, out.project, out.limits)) return error;
  if (!value.contains("module") || !value["module"].is_string() ||
      !valid_target(value["module"].get<std::string>()))
    return ParseError{"module must be a dotted Lean identifier"};
  if (!value.contains("declaration") || !value["declaration"].is_string() ||
      !valid_declaration(value["declaration"].get<std::string>()))
    return ParseError{"declaration must be a theorem or lemma statement without a proof body"};
  if (!value.contains("patch") || !value["patch"].is_string() ||
      value["patch"].get<std::string>().empty())
    return ParseError{"patch must be a non-empty string"};
  out.module = value["module"].get<std::string>();
  out.declaration = value["declaration"].get<std::string>();
  if (auto error = proof_context(
          value, out.verification_mode, out.preamble, out.target)) return error;
  out.patch = value["patch"].get<std::string>();
  if (auto error = optional_string(value, "parent_attempt_id", out.parent_attempt_id)) return error;
  return optional_string(value, "subgoal_description", out.subgoal_description);
}

std::optional<ParseError> parse_batch(const json& value, BatchRequest& out) {
  if (auto error = common(value, out.id, out.project, out.limits)) return error;
  if (!value.contains("module") || !value["module"].is_string() ||
      !valid_target(value["module"].get<std::string>()))
    return ParseError{"module must be a dotted Lean identifier"};
  if (!value.contains("declaration") || !value["declaration"].is_string() ||
      !valid_declaration(value["declaration"].get<std::string>()))
    return ParseError{"declaration must be a theorem or lemma statement without a proof body"};
  out.module = value["module"].get<std::string>();
  out.declaration = value["declaration"].get<std::string>();
  if (auto error = proof_context(
          value, out.verification_mode, out.preamble, out.target)) return error;
  if (!value.contains("candidates") || !value["candidates"].is_array() ||
      value["candidates"].empty())
    return ParseError{"candidates must be a non-empty array"};
  for (const auto& item : value["candidates"]) {
    if (!item.is_object() || !item.contains("id") || !item["id"].is_string() ||
        item["id"].get<std::string>().empty() || !item.contains("patch") ||
        !item["patch"].is_string() || item["patch"].get<std::string>().empty())
      return ParseError{"each candidate needs non-empty string id and patch fields"};
    out.candidates.push_back({item["id"].get<std::string>(), item["patch"].get<std::string>()});
  }
  if (value.contains("max_parallel")) {
    if (!value["max_parallel"].is_number_integer() || value["max_parallel"].get<long long>() <= 0 ||
        value["max_parallel"].get<long long>() > std::numeric_limits<unsigned>::max())
      return ParseError{"max_parallel must be a positive integer"};
    out.max_parallel = static_cast<unsigned>(value["max_parallel"].get<long long>());
  }
  if (value.contains("stop_on_first_success")) {
    if (!value["stop_on_first_success"].is_boolean())
      return ParseError{"stop_on_first_success must be boolean"};
    out.stop_on_first_success = value["stop_on_first_success"].get<bool>();
  }
  return optional_string(value, "parent_attempt_id", out.parent_attempt_id);
}

}  // namespace proof_search
