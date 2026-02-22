import time
import os
from daytona import Daytona, DaytonaConfig

# ────────────────────────────────────────────────
# 配置（请确保 api_url 和 api_key 正确，你的本地 server）
# ────────────────────────────────────────────────
config = DaytonaConfig(
    api_url="http://localhost:3000/api",
    api_key="dtn_f8d613fd9319dce9f755730a628c39b4c25d4d2f872f40ca6b503c6d464d348f"
)

client = Daytona(config)

# ────────────────────────────────────────────────
# 1. 创建一个新的 Sandbox
# ────────────────────────────────────────────────
print("正在创建 Sandbox...")
# sandbox = client.create()           # 可以加参数如 workspace 等
sandbox = client.find_one(sandbox_id_or_name="96e75a3f-230c-421c-ab37-c5b388c676ff")
print(f"Sandbox 创建成功：ID = {sandbox.id}")

# 等待 Sandbox 完全启动（有时需要几秒）
time.sleep(4)

# ────────────────────────────────────────────────
# 2. 测试文件上传
# ────────────────────────────────────────────────
local_upload_file = "test_upload.txt"
remote_path = "/home/daytona/test_upload.txt"

# 先在本地创建一个测试文件
if not os.path.exists(local_upload_file):
    with open(local_upload_file, "w", encoding="utf-8") as f:
        f.write("这是从本地上传的测试内容\n当前时间：" + time.strftime("%Y-%m-%d %H:%M:%S"))

print(f"准备上传：{local_upload_file} → {remote_path}")

# 方式一：直接传 bytes（推荐）
with open(local_upload_file, "rb") as f:
    content = f.read()
    sandbox.fs.upload_file(content, remote_path)

# 方式二：也可以直接传本地路径（部分版本支持）
# sandbox.fs.upload_file(local_upload_file, remote_path)

print("↑ 文件上传完成")

# 验证文件是否存在（用 code_run 执行 ls）
ls_result = sandbox.process.code_run(f"ls -l {remote_path}")
print("Sandbox 内文件信息：")
print(ls_result.result.strip())

# ────────────────────────────────────────────────
# 3. 在 Sandbox 里稍微改动文件（可选，演示用）
# ────────────────────────────────────────────────
sandbox.process.code_run(f'echo "我在 Sandbox 内追加了一行" >> {remote_path}')

# ────────────────────────────────────────────────
# 4. 测试文件下载
# ────────────────────────────────────────────────
local_download_file = "downloaded_test.txt"

print(f"准备下载：{remote_path} → 本地 {local_download_file}")

# 下载返回 bytes
content_bytes = sandbox.fs.download_file(remote_path)

with open(local_download_file, "wb") as f:
    f.write(content_bytes)

print("↓ 文件下载完成")

# 显示下载后的内容（验证）
with open(local_download_file, "r", encoding="utf-8") as f:
    print("下载回来的文件内容：")
    print(f.read())

# ────────────────────────────────────────────────
# 5. （可选）列出所有 Sandbox 和 Volume
# ────────────────────────────────────────────────
print("\n当前所有 Sandbox：")
for sb in client.list():
    print(f"  • ID: {sb.id}   状态: {sb.status}")

print("\n当前所有 Volume：")
volumes = client.volume.list()
print(volumes)

# 如果测试完想删除 Sandbox（节省资源）
# client.remove(sandbox.id)
# print(f"已删除 Sandbox {sandbox.id}")

print("\n✅ 测试完成！上传和下载都正常工作。")