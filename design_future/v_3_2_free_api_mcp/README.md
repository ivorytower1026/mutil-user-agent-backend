# 免费数据源API与MCP工具集成指南

本目录包含完整的免费数据源API和MCP工具的集成文档及测试脚本。

## 📁 文件说明

| 文件名 | 说明 |
|--------|------|
| `免费数据源API与MCP工具集成文档.md` | 完整的集成文档，包含所有API和MCP工具的详细说明 |
| `test_all_apis.py` | 综合测试脚本，可一键测试所有API和MCP工具 |
| `README.md` | 本文件，使用说明 |

## 🚀 快速开始

### 1. 查看文档

```bash
# 查看完整文档
code "免费数据源API与MCP工具集成文档.md"
# 或使用其他Markdown阅读器
```

### 2. 运行测试脚本

#### 安装依赖

```bash
pip install requests
```

#### 配置API密钥

编辑 `test_all_apis.py`，修改配置区的密钥：

```python
CONFIG = {
    "ALAPI_TOKEN": "your_real_token",           # ALAPI token
    "APIHZ_ID": "your_real_id",                 # 接口盒子ID
    "APIHZ_KEY": "your_real_key",               # 接口盒子KEY
    "WORLD_NEWS_API_KEY": "your_real_key",      # World News API
    "ALPHA_VANTAGE_KEY": "your_real_key",       # Alpha Vantage
    "STOCK_MCP_HOST": "localhost",              # stock-mcp主机
    "STOCK_MCP_PORT": 9898                      # stock-mcp端口
}
```

#### 运行测试

```bash
# 运行所有测试
python test_all_apis.py
```

### 3. 测试输出示例

```
============================================================
免费数据源API与MCP工具综合测试
============================================================
测试时间: 2024-03-04 20:30:00
测试项目: 8个API/MCP工具

[1] 测试 ALAPI 微博热搜...
✓ 成功 (耗时: 0.45s)
  热搜数量: 50

  热搜示例:
  1. 春节档电影票房
     热度: 2345678 | 标签: 热

...

============================================================
测试报告汇总
============================================================
✓ alapi_weibo             - 成功
✓ yi18_list               - 成功
✓ alpha_vantage_mcp       - 成功

统计:
  成功: 5
  失败: 0
  错误: 0
  总计: 5

成功率: 100.0%
============================================================
```

## 📋 API密钥申请地址

### 国内API（免费）

| API名称 | 申请地址 | 免费额度 |
|---------|----------|----------|
| ALAPI | http://www.alapi.cn | 每日免费调用 |
| Yi18 | http://top.yi18.net | 完全免费，无需注册 |
| 接口盒子 | https://www.apihz.cn | 免费额度 |

### 国际API（免费额度）

| API名称 | 申请地址 | 免费额度 |
|---------|----------|----------|
| World News API | https://worldnewsapi.com/register | 每天150次 |
| Alpha Vantage | https://www.alphavantage.co/support/#api-key | 每分钟5次，每天500次 |
| EODHD | https://eodhd.com | 免费试用 |

### MCP服务器

| MCP名称 | GitHub地址 | 是否免费 |
|---------|------------|----------|
| World News MCP | https://github.com/ddsky/world-news-api-mcp | 需要API Key |
| Alpha Vantage MCP | https://github.com/alphavantage/alpha_vantage_mcp | 需要API Key |
| EODHD MCP | https://github.com/EodHistoricalData/EODHD-MCP-Server | 需要API Key |
| stock-mcp | https://github.com/huweihua123/stock-mcp | ✅ 完全免费 |

## 🔧 使用示例

### 示例1: 获取微博热搜（ALAPI）

```python
import requests

def get_weibo_hot_search(token):
    url = "https://v2.alapi.cn/api/new/wbHot"
    params = {"token": token}
    
    response = requests.get(url, params=params)
    data = response.json()
    
    if data['code'] == 200:
        for item in data['data'][:10]:
            print(f"{item['hotword']} - 热度: {item['hotwordnum']}")
    
    return data

# 使用
get_weibo_hot_search("your_token")
```

### 示例2: 搜索全球新闻（World News MCP）

```python
import requests

def search_world_news(api_key, keyword):
    url = f"https://mcp.alphavantage.co/mcp?apikey={api_key}"
    
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "search_news",
            "arguments": {
                "text": keyword,
                "language": "en",
                "number": 10
            }
        }
    }
    
    response = requests.post(url, json=payload)
    return response.json()

# 使用
result = search_world_news("your_key", "artificial intelligence")
```

### 示例3: 获取股票情感（Alpha Vantage MCP）

```python
import requests

def get_stock_sentiment(api_key, symbol):
    url = f"https://mcp.alphavantage.co/mcp?apikey={api_key}"
    
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "TOOL_CALL",
            "arguments": {
                "tool_name": "NEWS_SENTIMENT",
                "arguments": {
                    "tickers": symbol,
                    "limit": 10
                }
            }
        }
    }
    
    response = requests.post(url, json=payload)
    return response.json()

# 使用
result = get_stock_sentiment("your_key", "AAPL")
```

## 📊 推荐组合方案

### 方案1: 完全免费（快速原型）

```
ALAPI（今日热榜） + Yi18（热点热词） + stock-mcp（金融数据）
```

**优势**: 无需API Key，快速上手  
**适用**: 原型开发、概念验证

### 方案2: 功能完整（生产环境）

```
World News API MCP（国际新闻+情感） + Alpha Vantage MCP（美股+情感） + ALAPI（国内热点）
```

**优势**: 数据质量高，支持情感分析  
**适用**: 生产环境应用

### 方案3: 专业金融

```
EODHD MCP（全面金融数据） + Alpha Vantage MCP（补充数据） + ALAPI（国内热点）
```

**优势**: 数据最全面，支持期权、宏观指标  
**适用**: 金融专业应用

## 📌 注意事项

1. **API密钥管理**: 请使用环境变量存储API密钥，不要硬编码
2. **频率限制**: 免费API有调用频率限制，请勿频繁测试
3. **数据缓存**: 建议实现数据缓存机制，减少API调用
4. **错误处理**: 实现重试机制和降级方案
5. **隐私保护**: 不要在公开代码仓库中提交API密钥

## 🔗 相关链接

- [完整文档](免费数据源API与MCP工具集成文档.md)
- [测试脚本](test_all_apis.py)

## 📞 反馈

如有问题或建议，请：
- 提交 GitHub Issue
- 发送邮件至: support@example.com

---

**文档版本**: v1.0  
**更新时间**: 2024-03-04  
**维护团队**: Multi-User Agent Team
