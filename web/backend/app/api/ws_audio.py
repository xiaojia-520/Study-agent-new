# 允许使用 Python 3.10+ 的类型注解延迟解析（避免循环引用问题）
from __future__ import annotations

# 异步编程库
import asyncio

# FastAPI 提供的 WebSocket 相关组件
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

# 实时语音服务（你自己封装的业务逻辑）
from web.backend.app.services.realtime_speech_service import realtime_speech_service

# 会话管理器（用于管理 session 生命周期）
from web.backend.app.services.session_manager import session_manager

# 创建一个路由器，并打上标签
router = APIRouter(tags=["realtime-audio"])


# 定义 WebSocket 路由，路径中包含 session_id
@router.websocket("/ws/audio/{session_id}")
async def ws_audio(websocket: WebSocket, session_id: str):
    # 根据 session_id 获取会话对象
    session = session_manager.get_session(session_id)

    # 如果 session 不存在，关闭连接（4404 类似 HTTP 404）
    if session is None:
        await websocket.close(code=4404, reason="session not found")
        return

    # 接受 WebSocket 连接
    await websocket.accept()

    # 标记该 session 已连接
    session_manager.mark_connected(session_id)

    # 获取当前事件循环（用于后续异步任务）
    loop = asyncio.get_running_loop()

    # 创建语音处理流水线（ASR、VAD 等）
    pipeline = realtime_speech_service.create_pipeline(
        websocket=websocket,
        loop=loop,
        session=session,
    )

    # 通知前端：session 已开始
    await websocket.send_json(
        await realtime_speech_service.make_session_started_payload(session)
    )

    # 用于控制“指标发送频率”的时间戳
    last_metrics_at = 0.0

    try:
        # 持续监听客户端消息
        while True:
            message = await websocket.receive()

            # ===== 处理音频数据（二进制）=====
            if message.get("bytes"):
                # 处理音频数据（如语音识别）
                last_metrics_at, metrics_payload = await realtime_speech_service.process_audio_message(
                    session_id=session_id,
                    audio_bytes=message["bytes"],
                    pipeline=pipeline,
                    last_metrics_at=last_metrics_at,
                )

                # 如果有指标数据（如延迟、识别状态），发送给前端
                if metrics_payload is not None:
                    await websocket.send_json(metrics_payload)

            # ===== 处理文本消息（控制指令）=====
            elif message.get("text"):
                text = message["text"].strip().lower()

                # 心跳检测：ping → pong
                if text == "ping":
                    await websocket.send_json(
                        await realtime_speech_service.make_pong_payload(session_id)
                    )

    # 客户端断开连接（正常情况）
    except WebSocketDisconnect:
        pass

    # 其他异常（如处理出错）
    except Exception as exc:
        try:
            # 向前端发送错误信息
            await websocket.send_json(
                await realtime_speech_service.make_error_payload(session_id, exc)
            )
        except Exception:
            # 如果发送失败（连接可能已断）
            pass

    # 无论如何都会执行（清理资源）
    finally:
        # 关闭 session，释放 pipeline
        stopped_payload = await realtime_speech_service.shutdown_session(
            session_id, pipeline
        )

        # 如果有“结束消息”，发送给前端
        if stopped_payload is not None:
            try:
                await websocket.send_json(stopped_payload)
            except Exception:
                pass