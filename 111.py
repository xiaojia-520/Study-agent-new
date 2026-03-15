import os
from flask import Flask, request, redirect, url_for, send_from_directory, render_template_string
from werkzeug.utils import secure_filename

app = Flask(__name__)

UPLOAD_FOLDER = "uploads"
ALLOWED_EXTENSIONS = {"zip"}

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


HTML = """
<!doctype html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>ZIP 文件共享站</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            max-width: 800px;
            margin: 40px auto;
            padding: 20px;
        }
        h1 {
            text-align: center;
        }
        form {
            margin-bottom: 30px;
            padding: 20px;
            border: 1px solid #ddd;
            border-radius: 8px;
        }
        input[type=file] {
            margin-right: 10px;
        }
        button {
            padding: 8px 16px;
            cursor: pointer;
        }
        ul {
            list-style: none;
            padding: 0;
        }
        li {
            padding: 10px;
            border-bottom: 1px solid #eee;
        }
        a {
            text-decoration: none;
            color: #007bff;
        }
        .msg {
            color: red;
            margin-bottom: 15px;
        }
    </style>
</head>
<body>
    <h1>ZIP 文件共享站</h1>

    {% if message %}
        <div class="msg">{{ message }}</div>
    {% endif %}

    <form method="post" enctype="multipart/form-data">
        <input type="file" name="file" accept=".zip" required>
        <button type="submit">上传 ZIP</button>
    </form>

    <h2>已上传文件</h2>
    <ul>
        {% for file in files %}
            <li>
                <a href="{{ url_for('download_file', filename=file) }}">{{ file }}</a>
            </li>
        {% else %}
            <li>暂时没有文件</li>
        {% endfor %}
    </ul>
</body>
</html>
"""


@app.route("/", methods=["GET", "POST"])
def index():
    message = ""

    if request.method == "POST":
        if "file" not in request.files:
            message = "没有选择文件"
        else:
            file = request.files["file"]

            if file.filename == "":
                message = "没有选择文件"
            elif not allowed_file(file.filename):
                message = "只允许上传 zip 文件"
            else:
                filename = secure_filename(file.filename)
                save_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
                file.save(save_path)
                return redirect(url_for("index"))

    files = os.listdir(app.config["UPLOAD_FOLDER"])
    return render_template_string(HTML, files=files, message=message)


@app.route("/download/<filename>")
def download_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename, as_attachment=True)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)