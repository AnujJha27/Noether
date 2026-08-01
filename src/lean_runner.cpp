#include "lean_runner.hpp"

#include <cerrno>
#include <chrono>
#include <csignal>
#include <cstring>
#include <fcntl.h>
#include <fstream>
#include <pwd.h>
#include <sstream>
#include <sys/resource.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <thread>
#include <unistd.h>

namespace proof_search {
namespace {

bool contains_memory_error(const std::string& text) {
  return text.find("out of memory") != std::string::npos ||
         text.find("failed to allocate") != std::string::npos ||
         text.find("memory exhausted") != std::string::npos ||
         text.find("failed to create thread") != std::string::npos ||
         text.find("failed to map segment") != std::string::npos ||
         text.find("cannot allocate memory") != std::string::npos;
}

std::string lake_executable() {
  if (const char* configured = std::getenv("PROOF_SEARCH_LAKE")) return configured;
  if (const passwd* user = getpwuid(getuid())) {
    const auto candidate = std::filesystem::path(user->pw_dir) / ".elan/bin/lake";
    if (std::filesystem::exists(candidate)) return candidate.string();
  }
  return "lake";
}

std::string declaration_suffix(const std::string& declaration) {
  const auto first = declaration.find_first_not_of(" \t\r\n");
  const bool theorem = declaration.compare(first, 7, "theorem") == 0;
  const std::size_t keyword_end = first + (theorem ? 7 : 5);
  const auto name = declaration.find_first_not_of(" \t\r\n", keyword_end);
  const auto name_end = declaration.find_first_of(" \t\r\n({[:", name);
  // Preserve universe binders from declarations such as `theorem t.{u}`.
  const auto suffix_start = declaration[name_end] == '{' && name_end > name &&
                                    declaration[name_end - 1] == '.'
                                ? name_end - 1 : name_end;
  return declaration.substr(suffix_start);
}

void drain_pipe(int fd, std::string& output) {
  char buffer[4096];
  for (;;) {
    const ssize_t count = read(fd, buffer, sizeof(buffer));
    if (count > 0) output.append(buffer, static_cast<std::size_t>(count));
    else if (count == 0 || (count < 0 && errno != EINTR)) break;
  }
}

std::filesystem::path module_artifact(const std::filesystem::path& project_dir,
                                      const std::string& module) {
  std::filesystem::path relative;
  std::string part;
  std::stringstream stream(module);
  while (std::getline(stream, part, '.')) relative /= part;
  relative += ".olean";
  return project_dir / ".lake/build/lib/lean" / relative;
}

}  // namespace

LeanRunner::LeanRunner(std::filesystem::path project_dir)
    : project_dir_(std::filesystem::absolute(std::move(project_dir))) {}

VerificationResult LeanRunner::verify(const VerifyRequest& request,
                                      const std::atomic_bool* cancelled) const {
  using Clock = std::chrono::steady_clock;
  const auto started = Clock::now();
  VerificationResult result;
  const auto artifact = module_artifact(project_dir_, request.module);
  if (!std::filesystem::exists(artifact)) {
    result.status = "project_not_built";
    result.diagnostics =
        "Lean project is not built or the requested module is missing.\n"
        "Expected compiled module: " + artifact.string() + "\n"
        "Run this before proof search:\n"
        "  cd " + project_dir_.string() + " && " + lake_executable() + " build";
    return result;
  }

  std::error_code error;
  const auto root = std::filesystem::temp_directory_path() / "proof-search-engine";
  std::filesystem::create_directories(root, error);
  std::string pattern = (root / "job-XXXXXX").string();
  std::vector<char> template_buffer(pattern.begin(), pattern.end());
  template_buffer.push_back('\0');
  char* made = mkdtemp(template_buffer.data());
  if (!made) {
    result.status = "worker_failure";
    result.diagnostics = std::string("cannot create temporary directory: ") + std::strerror(errno);
    return result;
  }
  const std::filesystem::path job_dir(made);
  struct Cleanup { std::filesystem::path path; ~Cleanup() { std::error_code e; std::filesystem::remove_all(path, e); } } cleanup{job_dir};
  const auto source = job_dir / "Check.lean";
  {
    std::ofstream file(source);
    if (!file) {
      result.status = "worker_failure";
      result.diagnostics = "cannot write temporary Lean source";
      return result;
    }
    const std::string candidate = "__proof_search_candidate_" + std::to_string(getpid());
    file << "import " << request.module << "\n\n";
    if (!request.preamble.empty()) file << request.preamble << "\n\n";
    file << "theorem " << candidate << declaration_suffix(request.declaration)
         << " := " << request.patch << "\n";
    if (request.verification_mode == "existing_target")
      file << "#check (" << candidate << " : type_of% " << request.target << ")\n";
  }

  int output_pipe[2];
  if (pipe(output_pipe) != 0) {
    result.status = "worker_failure";
    result.diagnostics = std::string("pipe failed: ") + std::strerror(errno);
    return result;
  }
  const pid_t child = fork();
  if (child < 0) {
    close(output_pipe[0]); close(output_pipe[1]);
    result.status = "worker_failure";
    result.diagnostics = std::string("fork failed: ") + std::strerror(errno);
    return result;
  }
  if (child == 0) {
    setpgid(0, 0);
    close(output_pipe[0]);
    dup2(output_pipe[1], STDOUT_FILENO);
    dup2(output_pipe[1], STDERR_FILENO);
    close(output_pipe[1]);
    struct rlimit cpu { static_cast<rlim_t>(request.limits.cpu_time_s), static_cast<rlim_t>(request.limits.cpu_time_s + 1) };
    struct rlimit memory { static_cast<rlim_t>(request.limits.memory_mb) * 1024U * 1024U,
                           static_cast<rlim_t>(request.limits.memory_mb) * 1024U * 1024U };
    setrlimit(RLIMIT_CPU, &cpu);
    setrlimit(RLIMIT_AS, &memory);
    setenv("LEAN_NUM_THREADS", "1", 1);
    if (chdir(project_dir_.c_str()) != 0) _exit(126);
    const std::string lake = lake_executable();
    const std::string lean_memory = std::to_string(request.limits.memory_mb);
    execlp(lake.c_str(), "lake", "env", "lean", "-j", "1", "-M",
           lean_memory.c_str(), source.c_str(), static_cast<char*>(nullptr));
    _exit(errno == ENOENT ? 127 : 126);
  }
  // Close the fork/setpgid race before a timeout or cancellation can signal it.
  setpgid(child, child);
  close(output_pipe[1]);
  fcntl(output_pipe[0], F_SETFL, fcntl(output_pipe[0], F_GETFL) | O_NONBLOCK);
  int status = 0;
  bool timed_out = false;
  bool was_cancelled = false;
  for (;;) {
    drain_pipe(output_pipe[0], result.diagnostics);
    const pid_t waited = waitpid(child, &status, WNOHANG);
    if (waited == child) break;
    if (waited < 0 && errno != EINTR) {
      result.status = "worker_failure";
      result.diagnostics += "\nwaitpid failed";
      close(output_pipe[0]);
      return result;
    }
    const auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(Clock::now() - started).count();
    if (cancelled && cancelled->load()) was_cancelled = true;
    if (elapsed >= request.limits.wall_time_ms) timed_out = true;
    if (was_cancelled || timed_out) {
      kill(-child, SIGKILL);
      waitpid(child, &status, 0);
      break;
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(5));
  }
  const int flags = fcntl(output_pipe[0], F_GETFL);
  fcntl(output_pipe[0], F_SETFL, flags & ~O_NONBLOCK);
  drain_pipe(output_pipe[0], result.diagnostics);
  close(output_pipe[0]);
  result.elapsed_ms = std::chrono::duration_cast<std::chrono::milliseconds>(Clock::now() - started).count();
  if (was_cancelled) result.status = "cancelled";
  else if (timed_out || (WIFSIGNALED(status) && WTERMSIG(status) == SIGXCPU)) result.status = "timeout";
  else if (contains_memory_error(result.diagnostics)) result.status = "memory_limit";
  else if (WIFEXITED(status)) {
    result.exit_code = WEXITSTATUS(status);
    if (result.exit_code == 0) result.status = "verified";
    else if (result.exit_code == 1) result.status = "lean_error";
    else result.status = "worker_failure";
  } else if (WIFSIGNALED(status)) {
    result.exit_code = 128 + WTERMSIG(status);
    result.status = WTERMSIG(status) == SIGKILL ? "memory_limit" : "worker_failure";
  } else result.status = "worker_failure";
  return result;
}

}  // namespace proof_search
