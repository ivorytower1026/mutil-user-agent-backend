from pathlib import Path


def get_project_root():
    """
    使用pathlib获取项目根路径
    通过标识文件进行定位
    适用于有.git和pyproject.toml的项目,亦或是其他的自定义标识文件
    """
    current_file = Path(__file__).resolve()
    current_dir = current_file.parent

    # 定义项目标识文件
    markers = ['.git', 'pyproject.toml']

    for parent in current_dir.parents:
        if any((parent / marker).exists() for marker in markers):
            return parent

    # 如果没找到标识,返回当前文件的祖父目录
    return current_file.parent.parent
