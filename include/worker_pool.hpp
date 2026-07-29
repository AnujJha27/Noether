#pragma once

#include <condition_variable>
#include <functional>
#include <future>
#include <mutex>
#include <queue>
#include <thread>
#include <type_traits>
#include <vector>

namespace proof_search {

class WorkerPool {
 public:
  explicit WorkerPool(unsigned worker_count = 0);
  ~WorkerPool();
  WorkerPool(const WorkerPool&) = delete;
  WorkerPool& operator=(const WorkerPool&) = delete;

  template <class Function>
  auto submit(Function&& function) -> std::future<std::invoke_result_t<Function>> {
    using Result = std::invoke_result_t<Function>;
    auto task = std::make_shared<std::packaged_task<Result()>>(
        std::forward<Function>(function));
    std::future<Result> future = task->get_future();
    {
      std::lock_guard<std::mutex> lock(mutex_);
      if (stopping_) throw std::runtime_error("worker pool is stopping");
      jobs_.emplace([task] { (*task)(); });
    }
    ready_.notify_one();
    return future;
  }

  unsigned size() const { return static_cast<unsigned>(workers_.size()); }

 private:
  std::vector<std::thread> workers_;
  std::queue<std::function<void()>> jobs_;
  mutable std::mutex mutex_;
  std::condition_variable ready_;
  bool stopping_ = false;
};

}  // namespace proof_search
