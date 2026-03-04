# 免费数据源API与MCP工具集成指南 v2.0

优先级: **官方平台** > **无Token** > **开源项目**

## 📁 文件说明

| 文件名 | 说明 |
|--------|------|
| `免费数据源API与MCP工具集成文档.md` | 完整的集成文档， 包含所有API和MCP工具的详细说明 |
| `test_all_apis.py` | 综合测试脚本， 可一键测试所有API和MCP工具 |
| `README.md` | 本文件，使用说明 |

## ⚠️ 重要说明

本文档优先推荐：
1. ✅ **官方平台API**（数据可靠、稳定）
2. ✅ **完全免费无需Token**（开箱即用）
3. ⚠️ **官方免费需Token**（需注册但免费）
4. 📦 **开源项目**（社区维护）

❌ **不推荐**第三方聚合API（数据来源不明、稳定性差）

---

## 🚀 快速开始

### 1. 查看文档
```bash
# 查看完整文档
code "免费数据源API与MCP工具集成文档.md"
```

### 2. 运行测试

```bash
# 安装依赖
pip install requests

# 设置API密钥（可选）
export WORLD_NEWS_API_KEY="your_key"
export ALPHA_VANTAGE_KEY="your_key"

# 运行测试
python test_all_apis.py
```

### 3. 测试输出示例
```
============================================================
免费数据源API综合测试 v2.0
优先级: 官方平台 > 无Token > 开源项目
============================================================

[1] 测试 Hacker News API...
✓ 成功 (耗时: 0.45s)
  热门故事数: 500

  第一条故事:
    标题: My YC app: Dropbox
    作者: pg
    分数: 111
    链接: http://www.getdropbox.com/u/2/screencast.html

[2] 测试 Reddit JSON...
✓ 成功 (耗时: 0.52s)
  获取帖子数: 5

  前3条帖子:
  1. Python 3.12 Released...
     点赞: 1523 | 评论: 245
...
```

---

## 📊 推荐方案

### 方案A: 完全免费无需Token ⭐⭐⭐⭐⭐
```
Hacker News API + Reddit JSON + stock-mcp
```
- **优势**: 完全免费，无需注册，开箱即用
- **数据源**: 全部官方平台或开源项目
- **适用**: 个人项目、原型开发、学习研究

### 方案B: 官方免费需Token ⭐⭐⭐⭐
```
World News API + Alpha Vantage + The Guardian
```
- **优势**: 数据质量高，官方维护，稳定可靠
- **成本**: 免费注册，额度充足
- **适用**: 生产环境、商业应用

### 方案C: 混合方案 ⭐⭐⭐⭐⭐
```
Hacker News + Reddit + World News API + stock-mcp
```
- **优势**: 兼顾免费和功能完整
- **覆盖**: 技术新闻 + 社交媒体 + 全球新闻 + 金融数据
- **适用**: 综合性应用

---

## 📋 API密钥申请地址

### 官方免费无需Token
- **Hacker News**: https://github.com/HackerNews/API （无需注册）
- **Reddit**: https://www.reddit.com （无需注册）

### 官方免费需Token
- **World News API**: https://worldnewsapi.com/register （每天150次）
- **Alpha Vantage**: https://www.alphavantage.co/support/#api-key （每天500次）
- **The Guardian**: https://open-platform.theguardian.com/ （每天12,000次）
- **NYTimes API**: https://developer.nytimes.com/ （每天1,000次）

### 开源项目
- **stock-mcp**: https://github.com/huweihua123/stock-mcp （完全免费）
- **dailyhot-api**: https://github.com/DIYgod/RSSHub （完全免费）

---

## 🔧 使用示例

### 示例1: Hacker News API（无需Token）
```python
import requests

# 获取热门故事
url = "https://hacker-news.firebaseio.com/v0/topstories.json"
story_ids = requests.get(url).json()

# 获取第一个故事
story = requests.get(
    f"https://hacker-news.firebaseio.com/v0/item/{story_ids[0]}.json"
).json()

print(f"标题: {story['title']}")
print(f"作者: {story['by']}")
print(f"分数: {story['score']}")
```

### 示例2: Reddit JSON（无需Token）
```python
import requests

# 获取Python版块热门帖子
url = "https://www.reddit.com/r/Python/hot.json?limit=5"
headers = {"User-Agent": "Mozilla/5.0"}
data = requests.get(url, headers=headers).json()

for post in data['data']['children']:
    post_data = post['data']
    print(f"{post_data['title']}")
    print(f"点赞: {post_data['score']}")
```

### 示例3: World News API（需Token）
```python
import requests
import os

api_key = os.getenv("WORLD_NEWS_API_KEY")
url = "https://api.worldnewsapi.com/search-news"
params = {
    "api-key": api_key,
    "text": "artificial intelligence",
    "language": "en",
    "number": 10
}

data = requests.get(url, params=params).json()
for news in data['news']:
    print(f"{news['title']}")
    print(f"情感: {news['sentiment']}")
```

---

## 📌 注意事项

1. **API密钥管理**: 使用环境变量，不要硬编码
2. **频率限制**: 免费API有调用频率限制，请勿频繁测试
3. **数据缓存**: 建议实现数据缓存机制
4. **错误处理**: 实现重试机制和降级方案
5. **隐私保护**: 不要提交API密钥到Git仓库

---

## 📞 反馈

如有问题或建议，请在GitHub提交Issue

---

**文档版本**: v2.0  
**更新时间**: 2024-03-04  
**维护团队**: Multi-User Agent Team
