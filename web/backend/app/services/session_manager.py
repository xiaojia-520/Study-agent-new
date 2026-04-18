# 允许使用延迟类型注解（解决循环引用、提升类型提示体验）
from __future__ import annotations

# 线程锁（用于并发安全）
import threading

# 时间戳（记录 session 创建 / 更新）
import time

# 用于标准化 course_id / lesson_id
import re

# 用于生成唯一 session_id
import uuid

# 类型提示
from typing import Optional

# 你的 session 数据结构 和 状态枚举
from web.backend.app.domain.session import RealtimeSession, SessionStatus


class SessionManager:
    """内存版实时 session 生命周期管理器"""

    def __init__(self) -> None:
        # 存储所有 session（核心数据结构）
        # key: session_id
        # value: RealtimeSession 对象
        self._sessions: dict[str, RealtimeSession] = {}

        # 可重入锁（保证多线程/并发访问安全）
        self._lock = threading.RLock()

    def create_session(
        self,
        *,
        course_id: Optional[str] = None,    # 课程主键
        lesson_id: Optional[str] = None,    # 单节课主键
        subject: Optional[str] = None,      # 会话主题（可选）
        client_id: Optional[str] = None,    # 客户端标识
        sample_rate: int = 16000,           # 音频采样率
        channels: int = 1,                  # 声道数
        model_name: Optional[str] = None,   # 使用的模型名称
    ) -> RealtimeSession:
        # 当前时间戳（秒）
        now = int(time.time())
        session_id = uuid.uuid4().hex
        resolved_course_id = self._resolve_course_id(course_id=course_id, subject=subject)
        resolved_lesson_id = self._resolve_lesson_id(
            lesson_id=lesson_id,
            course_id=resolved_course_id,
            created_at=now,
            session_id=session_id,
        )

        # 创建一个新的 session 对象
        session = RealtimeSession(
            session_id=session_id,         # 生成唯一 session_id
            course_id=resolved_course_id,
            lesson_id=resolved_lesson_id,
            subject=subject,
            client_id=client_id,
            sample_rate=sample_rate,
            channels=channels,
            model_name=model_name,
            status=SessionStatus.IDLE,     # 初始状态：空闲
            created_at=now,
            updated_at=now,
        )

        # 加锁写入（防止并发冲突）
        with self._lock:
            self._sessions[session.session_id] = session

        return session

    def get_session(self, session_id: str) -> Optional[RealtimeSession]:
        """获取 session（不存在返回 None）"""
        with self._lock:
            return self._sessions.get(session_id)

    def require_session(self, session_id: str) -> RealtimeSession:
        """获取 session（不存在直接抛异常）"""
        session = self.get_session(session_id)
        if session is None:
            raise KeyError(session_id)
        return session

    def list_sessions(self) -> list[RealtimeSession]:
        """列出所有 session（用于调试 / 管理）"""
        with self._lock:
            return list(self._sessions.values())

    def mark_connected(self, session_id: str) -> RealtimeSession:
        """标记：有新的连接建立（WebSocket 连接）"""
        with self._lock:
            session = self.require_session(session_id)

            # 活跃连接数 +1（支持多连接）
            session.active_connections += 1

            # 状态变为已连接
            session.status = SessionStatus.CONNECTED

            # 更新时间
            session.updated_at = int(time.time())

            # 清除历史错误
            session.last_error = None

            return session

    @staticmethod
    def _resolve_course_id(*, course_id: Optional[str], subject: Optional[str]) -> str:
        normalized = SessionManager._normalize_identifier(course_id)
        if normalized is not None:
            return normalized

        normalized_subject = SessionManager._normalize_identifier(subject)
        if normalized_subject is not None:
            return normalized_subject
        return "general"

    @staticmethod
    def _resolve_lesson_id(
        *,
        lesson_id: Optional[str],
        course_id: str,
        created_at: int,
        session_id: str,
    ) -> str:
        normalized = SessionManager._normalize_identifier(lesson_id)
        if normalized is not None:
            return normalized

        lesson_date = time.strftime("%Y%m%d_%H%M%S", time.localtime(created_at))
        return f"{course_id}_{lesson_date}_{session_id[:8]}"

    @staticmethod
    def _normalize_identifier(value: Optional[str]) -> Optional[str]:
        text = (value or "").strip()
        if not text:
            return None
        text = re.sub(r"[^\w\u4e00-\u9fff\-]+", "_", text)
        text = re.sub(r"_+", "_", text).strip("_")
        return text or None

    def mark_running(self, session_id: str) -> RealtimeSession:
        """标记：session 正在运行（例如语音识别处理中）"""
        with self._lock:
            session = self.require_session(session_id)

            # 状态变为运行中
            session.status = SessionStatus.RUNNING

            # 更新时间
            session.updated_at = int(time.time())

            return session

    def mark_disconnected(self, session_id: str) -> Optional[RealtimeSession]:
        """标记：有连接断开"""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None

            # 活跃连接数 -1（不会小于0）
            session.active_connections = max(0, session.active_connections - 1)

            # 如果没有连接了 → STOPPED，否则仍然 CONNECTED
            session.status = (
                SessionStatus.STOPPED if session.active_connections == 0 else SessionStatus.CONNECTED
            )

            # 更新时间
            session.updated_at = int(time.time())

            return session

    def mark_error(self, session_id: str, error: str) -> Optional[RealtimeSession]:
        """标记：session 出现错误"""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None

            # 状态变为错误
            session.status = SessionStatus.ERROR

            # 记录错误信息
            session.last_error = error

            # 更新时间
            session.updated_at = int(time.time())

            return session

    def next_event_seq(self, session_id: str) -> int:
        """获取下一个事件序列号（用于事件排序/同步）"""
        with self._lock:
            session = self.require_session(session_id)

            # 事件序号自增
            session.event_seq += 1

            # 更新时间
            session.updated_at = int(time.time())

            return session.event_seq


# 创建全局单例（整个服务共用一个 SessionManager）
session_manager = SessionManager()
