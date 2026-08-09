#include "cache.hpp"

#include <algorithm>
#include <fstream>
#include <iomanip>
#include <openssl/sha.h>
#include <sstream>
#include <stdexcept>
#include <vector>

namespace proof_search {
namespace {

std::string read_file(const std::filesystem::path& path) {
  std::ifstream input(path, std::ios::binary);
  return input ? std::string(std::istreambuf_iterator<char>(input), {}) : std::string();
}

std::string hash_text(const std::string& text) {
  unsigned char digest[SHA256_DIGEST_LENGTH];
  SHA256(reinterpret_cast<const unsigned char*>(text.data()), text.size(), digest);
  std::ostringstream output;
  output << std::hex << std::setfill('0');
  for (const unsigned char byte : digest) output << std::setw(2) << static_cast<int>(byte);
  return output.str();
}

void bind(sqlite3_stmt* statement, int index, const std::string& value) {
  sqlite3_bind_text(statement, index, value.c_str(), static_cast<int>(value.size()), SQLITE_TRANSIENT);
}

}  // namespace

Cache::Cache(const std::filesystem::path& database_path,
             const std::filesystem::path& project_dir)
    : project_dir_(std::filesystem::absolute(project_dir)) {
  std::vector<std::filesystem::path> inputs;
  std::error_code filesystem_error;
  for (std::filesystem::recursive_directory_iterator iterator(project_dir_, filesystem_error), end;
       !filesystem_error && iterator != end; iterator.increment(filesystem_error)) {
    if (iterator->is_directory() && iterator->path().filename() == ".lake") {
      iterator.disable_recursion_pending();
      continue;
    }
    if (!iterator->is_regular_file()) continue;
    const auto filename = iterator->path().filename().string();
    if (iterator->path().extension() == ".lean" || filename == "lean-toolchain" ||
        filename == "lakefile.toml" || filename == "lakefile.lean" ||
        filename == "lake-manifest.json")
      inputs.push_back(iterator->path());
  }
  std::sort(inputs.begin(), inputs.end());
  std::string project_contents = "noether-verifier-cache-v2\0" +
                                 project_dir_.string() + '\0' +
                                 lean_toolchain_identity(project_dir_) + '\0';
  for (const auto& input : inputs)
    project_contents += std::filesystem::relative(input, project_dir_).string() + "\0" + read_file(input) + "\0";
  fingerprint_ = hash_text(project_contents);

  if (sqlite3_open_v2(database_path.c_str(), &database_,
                      SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE | SQLITE_OPEN_FULLMUTEX,
                      nullptr) != SQLITE_OK) {
    const std::string message = database_ ? sqlite3_errmsg(database_) : "unknown error";
    if (database_) sqlite3_close(database_);
    database_ = nullptr;
    throw std::runtime_error("cannot open cache database: " + message);
  }
  sqlite3_busy_timeout(database_, 5000);
  execute("PRAGMA journal_mode=WAL");
  execute("CREATE TABLE IF NOT EXISTS verification_cache ("
          "cache_key TEXT PRIMARY KEY, status TEXT NOT NULL, diagnostics_json TEXT NOT NULL, "
          "elapsed_ms INTEGER NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)");
  execute("CREATE TABLE IF NOT EXISTS attempts ("
          "attempt_id TEXT PRIMARY KEY, cache_key TEXT NOT NULL, target TEXT NOT NULL, "
          "parent_attempt_id TEXT NULL, status TEXT NOT NULL, "
          "submitted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)");
  execute("CREATE TABLE IF NOT EXISTS subgoal_links ("
          "parent_attempt_id TEXT NOT NULL, child_attempt_id TEXT NOT NULL, description TEXT, "
          "PRIMARY KEY(parent_attempt_id, child_attempt_id))");
}

Cache::~Cache() { if (database_) sqlite3_close(database_); }

void Cache::execute(const char* sql) {
  char* error = nullptr;
  if (sqlite3_exec(database_, sql, nullptr, nullptr, &error) != SQLITE_OK) {
    const std::string message = error ? error : "unknown SQLite error";
    sqlite3_free(error);
    throw std::runtime_error(message);
  }
}

std::string Cache::key_for(const VerifyRequest& request) const {
  std::ostringstream value;
  const auto artifact = module_artifact(project_dir_, request.module);
  value << fingerprint_ << '\0' << (std::filesystem::exists(artifact) ? hash_text(read_file(artifact)) : "module-missing")
        << '\0' << request.project << '\0' << request.module << '\0'
        << request.verification_mode << '\0' << request.preamble << '\0'
        << request.declaration << '\0' << request.target << '\0' << request.patch << '\0'
        << request.limits.wall_time_ms << ':'
        << request.limits.cpu_time_s << ':' << request.limits.memory_mb;
  return hash_text(value.str());
}

std::optional<VerificationResult> Cache::lookup(const std::string& key) {
  std::lock_guard<std::mutex> lock(mutex_);
  sqlite3_stmt* raw = nullptr;
  sqlite3_prepare_v2(database_, "SELECT status, diagnostics_json, elapsed_ms FROM verification_cache WHERE cache_key=?", -1, &raw, nullptr);
  std::unique_ptr<sqlite3_stmt, decltype(&sqlite3_finalize)> statement(raw, sqlite3_finalize);
  bind(statement.get(), 1, key);
  if (sqlite3_step(statement.get()) != SQLITE_ROW) return std::nullopt;
  VerificationResult result;
  result.status = reinterpret_cast<const char*>(sqlite3_column_text(statement.get(), 0));
  const auto* diagnostics = reinterpret_cast<const char*>(sqlite3_column_text(statement.get(), 1));
  result.diagnostics = diagnostics ? diagnostics : "";
  result.elapsed_ms = sqlite3_column_int64(statement.get(), 2);
  result.cached = true;
  return result;
}

void Cache::store(const std::string& key, const VerificationResult& result) {
  if (result.status != "verified" && result.status != "lean_error") return;
  std::lock_guard<std::mutex> lock(mutex_);
  sqlite3_stmt* raw = nullptr;
  sqlite3_prepare_v2(database_, "INSERT OR REPLACE INTO verification_cache(cache_key,status,diagnostics_json,elapsed_ms,created_at) VALUES(?,?,?,?,CURRENT_TIMESTAMP)", -1, &raw, nullptr);
  std::unique_ptr<sqlite3_stmt, decltype(&sqlite3_finalize)> statement(raw, sqlite3_finalize);
  bind(statement.get(), 1, key); bind(statement.get(), 2, result.status);
  bind(statement.get(), 3, result.diagnostics);
  sqlite3_bind_int64(statement.get(), 4, result.elapsed_ms);
  sqlite3_step(statement.get());
}

void Cache::record_attempt(const VerifyRequest& request, const std::string& key,
                           const std::string& status) {
  std::lock_guard<std::mutex> lock(mutex_);
  sqlite3_stmt* raw = nullptr;
  sqlite3_prepare_v2(database_, "INSERT OR REPLACE INTO attempts(attempt_id,cache_key,target,parent_attempt_id,status,submitted_at) VALUES(?,?,?,?,?,CURRENT_TIMESTAMP)", -1, &raw, nullptr);
  std::unique_ptr<sqlite3_stmt, decltype(&sqlite3_finalize)> statement(raw, sqlite3_finalize);
  bind(statement.get(), 1, request.id); bind(statement.get(), 2, key);
  bind(statement.get(), 3, request.target.empty() ? request.declaration : request.target);
  if (request.parent_attempt_id) bind(statement.get(), 4, *request.parent_attempt_id);
  else sqlite3_bind_null(statement.get(), 4);
  bind(statement.get(), 5, status);
  sqlite3_step(statement.get());
  if (!request.parent_attempt_id) return;
  raw = nullptr;
  sqlite3_prepare_v2(database_, "INSERT OR REPLACE INTO subgoal_links(parent_attempt_id,child_attempt_id,description) VALUES(?,?,?)", -1, &raw, nullptr);
  std::unique_ptr<sqlite3_stmt, decltype(&sqlite3_finalize)> link(raw, sqlite3_finalize);
  bind(link.get(), 1, *request.parent_attempt_id); bind(link.get(), 2, request.id);
  if (request.subgoal_description) bind(link.get(), 3, *request.subgoal_description);
  else sqlite3_bind_null(link.get(), 3);
  sqlite3_step(link.get());
}

}  // namespace proof_search
