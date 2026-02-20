import time

from daytona import Daytona, DaytonaConfig

# Define the configuration
config = DaytonaConfig(
    api_url="http://localhost:3000/api",
    api_key="dtn_f8d613fd9319dce9f755730a628c39b4c25d4d2f872f40ca6b503c6d464d348f")

# Initialize the Daytona client
client = Daytona(config)

# Create the Sandbox instance
sandbox = client.create()

# Run the code securely inside the Sandbox
response = sandbox.process.code_run('print("Hello World from code!")')
if response.exit_code != 0:
    print(f"Error: {response.exit_code} {response.result}")
else:
    print(response.result)


# 列出现有 Sandbox
sandboxes = client.list()
print(f"Sandboxes: {sandboxes}")

# 列出现有 Volume
volumes = client.volume.list()
print(f"Volumes: {volumes}")

print("✅ Daytona SDK 连接成功！")