from flask import Flask, request, send_from_directory, redirect, url_for, render_template_string
from werkzeug.utils import secure_filename
import os

app = Flask(__name__)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

HTML = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>局域网文件共享</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            max-width: 800px;
            margin: 40px auto;
        }
        h1 {
            text-align: center;
        }
        .upload {
            padding: 20px;
            border: 2px dashed #aaa;
            margin-bottom: 30px;
            text-align: center;
        }
        .file {
            padding: 10px;
            border-bottom: 1px solid #ddd;
        }
        a {
            text-decoration: none;
            color: #0078d7;
        }
    </style>
</head>
<body>
    <h1>局域网文件共享</h1>

    <div class="upload">
        <form method="post" action="/upload" enctype="multipart/form-data">
            <input type="file" name="file" required>
            <button type="submit">上传</button>
        </form>
    </div>

    <h2>可下载文件</h2>

    {% if files %}
        {% for file in files %}
            <div class="file">
                <a href="/download/{{ file }}">{{ file }}</a>
            </div>
        {% endfor %}
    {% else %}
        <p>暂无文件</p>
    {% endif %}
</body>
</html>
"""


@app.route("/")
def index():
    files = os.listdir(UPLOAD_FOLDER)
    return render_template_string(HTML, files=files)


@app.route("/upload", methods=["POST"])
def upload():
    file = request.files.get("file")

    if not file:
        return redirect(url_for("index"))

    filename = secure_filename(file.filename)

    if filename == "":
        return redirect(url_for("index"))

    file.save(os.path.join(UPLOAD_FOLDER, filename))
    return redirect(url_for("index"))


@app.route("/download/<filename>")
def download(filename):
    return send_from_directory(UPLOAD_FOLDER, filename, as_attachment=True)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
