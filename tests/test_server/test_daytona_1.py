import time

from daytona import Daytona, DaytonaConfig, CreateSandboxFromSnapshotParams, VolumeMount

# Define the configuration
config = DaytonaConfig(
    api_url="http://localhost:3000/api",
    api_key="dtn_f8d613fd9319dce9f755730a628c39b4c25d4d2f872f40ca6b503c6d464d348f")

# Initialize the Daytona client
client = Daytona(config)

# Create a new volume or get an existing one
volume = client.volume.get("my-volume", create=True)

# Mount the volume to the sandbox
mount_dir_1 = "/home/daytona/volume"

params = CreateSandboxFromSnapshotParams(
    language="python",
    volumes=[VolumeMount(volume_id=volume.id, mount_path=mount_dir_1)],
)
sandbox = client.create(params)

# Mount a specific subpath within the volume
# This is useful for isolating data or implementing multi-tenancy
params = CreateSandboxFromSnapshotParams(
    language="python",
    volumes=[VolumeMount(volume_id=volume.id, mount_path=mount_dir_1, subpath="users/alice")],
)
sandbox2 = client.create(params)