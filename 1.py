from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

app = FastAPI()
clients = []


@app.get("/")
async def index():
    return HTMLResponse("""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>内网聊天室</title>
</head>
<body>
    <h2>内网聊天室</h2>

    <input id="name" placeholder="昵称">
    <br><br>

    <div id="box" style="width:500px;height:300px;border:1px solid #ccc;overflow:auto;padding:10px;"></div>

    <br>

    <input id="msg" placeholder="输入消息" style="width:400px;">
    <button onclick="send()">发送</button>

    <script>
        const ws = new WebSocket("ws://" + location.host + "/ws");

        ws.onmessage = function(event) {
            const box = document.getElementById("box");
            box.innerHTML += "<div>" + event.data + "</div>";
            box.scrollTop = box.scrollHeight;
        };

        function send() {
            const name = document.getElementById("name").value || "匿名";
            const msg = document.getElementById("msg").value;
            if (!msg) return;

            ws.send(name + "：" + msg);
            document.getElementById("msg").value = "";
        }

        document.getElementById("msg").addEventListener("keydown", function(e) {
            if (e.key === "Enter") send();
        });
    </script>
</body>
</html>
    """)


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    clients.append(websocket)

    try:
        while True:
            msg = await websocket.receive_text()
            for client in clients:
                await client.send_text(msg)
    except WebSocketDisconnect:
        clients.remove(websocket)