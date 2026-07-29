#pragma once

#include "lean_runner.hpp"

#include <filesystem>
#include <mutex>
#include <optional>
#include <sqlite3.h>
#include <string>

namespace proof_search {

class Cache {
 public:
  Cache(const std::filesystem::path& database_path,
        const std::filesystem::path& project_dir);
  ~Cache();
  Cache(const Cache&) = delete;
  Cache& operator=(const Cache&) = delete;

  std::string key_for(const VerifyRequest& request) const;
  std::optional<VerificationResult> lookup(const std::string& key);
  void store(const std::string& key, const VerificationResult& result);
  void record_attempt(const VerifyRequest& request, const std::string& key,
                      const std::string& status);

 private:
  void execute(const char* sql);
  sqlite3* database_ = nullptr;
  std::string fingerprint_;
  std::mutex mutex_;
};

}  // namespace proof_search
