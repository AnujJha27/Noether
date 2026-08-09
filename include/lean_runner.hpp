#pragma once

#include "protocol.hpp"

#include <atomic>
#include <filesystem>
#include <string>

namespace proof_search {

struct VerificationResult {
  std::string status;
  std::string diagnostics;
  long long elapsed_ms = 0;
  bool cached = false;
  int exit_code = -1;
};

std::filesystem::path resolved_lake_executable();
std::filesystem::path module_artifact(const std::filesystem::path& project_dir,
                                      const std::string& module);
std::string lean_toolchain_identity(const std::filesystem::path& project_dir);

class LeanRunner {
 public:
  explicit LeanRunner(std::filesystem::path project_dir);
  VerificationResult verify(const VerifyRequest& request,
                            const std::atomic_bool* cancelled = nullptr) const;
  const std::filesystem::path& project_dir() const { return project_dir_; }

 private:
  std::filesystem::path project_dir_;
};

}  // namespace proof_search
