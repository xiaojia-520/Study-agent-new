import numpy as np
from typing import List
from collections import deque


class FrameSlicer:
    """
    把连续音频流切成固定窗口（比如 512 samples）

    ✅ 极限优化点：
    - 原实现每次 push 都 np.concatenate，会频繁分配/拷贝（回调线程里很亏）
    - 这里改成 “deque + head_offset” 的无拷贝累计
    - 只有在真正 pop 出固定窗口时，才拷贝出一个 window_size 的新数组
    """

    def __init__(self, window_size: int):
        self.window_size = window_size

        # 用 deque 存多个 numpy chunk，避免不停 concatenate
        self._chunks = deque()          # deque[np.ndarray]
        self._head_offset = 0           # 当前头 chunk 已消费到的位置
        self._size = 0                  # 总剩余 samples 数

    def push(self, audio_1d: np.ndarray) -> List[np.ndarray]:
        """
        输入：1D float32 音频（任意长度）
        输出：若干个固定长度窗口块（每个长度=window_size）
        """
        arr = np.asarray(audio_1d, dtype=np.float32).reshape(-1)
        if arr.size == 0:
            return []

        self._chunks.append(arr)
        self._size += arr.size

        out: List[np.ndarray] = []
        while self._size >= self.window_size:
            out.append(self._pop_n(self.window_size))
        return out

    def _pop_n(self, n: int) -> np.ndarray:
        """从内部 FIFO 弹出 n 个 samples，返回连续 ndarray（发生一次拷贝）。"""
        out = np.empty((n,), dtype=np.float32)
        filled = 0

        while filled < n:
            head = self._chunks[0]
            remain_in_head = head.size - self._head_offset
            take = min(n - filled, remain_in_head)

            out[filled:filled + take] = head[self._head_offset:self._head_offset + take]
            filled += take
            self._head_offset += take

            # 头 chunk 用完就丢掉
            if self._head_offset >= head.size:
                self._chunks.popleft()
                self._head_offset = 0

        self._size -= n
        return out
