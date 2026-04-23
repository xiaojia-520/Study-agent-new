import os
from flask import Flask, request

UPLOAD_DIR = os.environ.get(
    "TEST_UPLOAD_DIR",
    os.path.join(os.path.dirname(__file__), "uploads"),
)
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024  # 2GB，可按需改

HTML = """
<!doctype html>
<html>
<head><meta charset="utf-8"><title>LAN Upload</title></head>
<body style="font-family: Arial; max-width: 720px; margin: 40px auto;">
  <h2>局域网文件上传</h2>
  <form method="post" action="/upload" enctype="multipart/form-data">
    <input type="file" name="file" required />
    <button type="submit">上传</button>
  </form>
  <p>保存路径：{path}</p>
</body>
</html>
""".format(path=UPLOAD_DIR)

@app.get("/")
def index():
    return HTML

@app.post("/upload")
def upload():
    f = request.files.get("file")
    if not f or f.filename.strip() == "":
        return "No file", 400

    # 简单去掉路径穿越，只保留文件名
    filename = os.path.basename(f.filename)
    save_path = os.path.join(UPLOAD_DIR, filename)

    # 同名自动改名：xxx(1).ext
    base, ext = os.path.splitext(filename)
    i = 1
    while os.path.exists(save_path):
        save_path = os.path.join(UPLOAD_DIR, f"{base}({i}){ext}")
        i += 1

    f.save(save_path)
    return f"OK: {os.path.basename(save_path)}"

if __name__ == "__main__":
    # host=0.0.0.0 让局域网能访问
    app.run(host="0.0.0.0", port=8000)
