# 免费数据源API与MCP工具集成文档

> 文档版本: v1.0  
> 更新时间: 2024-03-04  
> 适用场景: 舆情监控、热点追踪、新闻分析、金融数据获取

---

## 目录

- [一、国内新闻热点API](#一国内新闻热点api)
  - [1. ALAPI - 今日热榜](#1-alapi---今日热榜)
  - [2. Yi18事件风云榜](#2-yi18事件风云榜)
  - [3. 接口盒子 - 微博热搜](#3-接口盒子---微博热搜)
- [二、MCP服务器工具](#二mcp服务器工具)
  - [4. World News API MCP](#4-world-news-api-mcp)
  - [5. Alpha Vantage MCP](#5-alpha-vantage-mcp)
  - [6. EODHD MCP Server](#6-eodhd-mcp-server)
  - [7. stock-mcp (中文金融)](#7-stock-mcp-中文金融)
- [三、测试脚本集合](#三测试脚本集合)
- [四、集成建议](#四集成建议)

---

## 一、国内新闻热点API

### 1. ALAPI - 今日热榜

#### 基本信息
- **官网**: http://www.alapi.cn
- **是否免费**: ✅ 免费接口（需注册获取token）
- **用途**: 获取微博热搜、今日热榜、网易新闻等国内热点资讯

#### 1.1 微博热搜榜

**接口地址**: `https://v2.alapi.cn/api/new/wbHot`

**请求方式**: GET

**输入参数**:
```json
{
  "token": "string (必填) - 用户token，注册后获取",
  "format": "string (可选) - 返回格式，默认json"
}
```

**测试脚本**:
```bash
#!/bin/bash
# test_alapi_weibo.sh

TOKEN="your_token_here"

curl -X GET "https://v2.alapi.cn/api/new/wbHot?token=${TOKEN}" \
  -H "Content-Type: application/json" | jq '.'
```

**测试输出示例**:
```json
{
  "code": 200,
  "msg": "success",
  "data": [
    {
      "hotword": "春节档电影票房",
      "hotwordnum": "2345678",
      "hottag": "热",
      "url": "https://s.weibo.com/weibo?q=%23春节档电影票房%23"
    },
    {
      "hotword": "科技公司裁员",
      "hotwordnum": "1234567",
      "hottag": "新",
      "url": "https://s.weibo.com/weibo?q=%23科技公司裁员%23"
    }
  ],
  "count": 50
}
```

**Python测试脚本**:
```python
import requests

def test_alapi_weibo(token):
    url = "https://v2.alapi.cn/api/new/wbHot"
    params = {"token": token}
    
    response = requests.get(url, params=params)
    data = response.json()
    
    print(f"状态码: {data['code']}")
    print(f"热搜数量: {len(data['data'])}")
    print("\n前3条热搜:")
    for i, item in enumerate(data['data'][:3], 1):
        print(f"{i}. {item['hotword']} - 热度: {item['hotwordnum']} - 标签: {item['hottag']}")

# 使用
test_alapi_weibo("your_token_here")
```

#### 1.2 今日热榜（多平台聚合）

**接口地址**: `https://v2.alapi.cn/api/new/toutiao`

**输入参数**:
```json
{
  "token": "string (必填) - 用户token",
  "type": "string (可选) - hot:热门, recommend:推荐，默认hot"
}
```

**测试脚本**:
```python
import requests

def test_alapi_toutiao(token):
    url = "https://v2.alapi.cn/api/new/toutiao"
    params = {
        "token": token,
        "type": "hot"
    }
    
    response = requests.get(url, params=params)
    data = response.json()
    
    print(f"状态: {data['msg']}")
    print(f"总条数: {data['data']['total']}")
    print("\n热门资讯:")
    for item in data['data']['list'][:5]:
        print(f"- [{item['source']}] {item['title']}")
        print(f"  热度: {item.get('hot_score', 'N/A')}")
```

**输出示例**:
```json
{
  "code": 200,
  "msg": "success",
  "data": {
    "total": 100,
    "list": [
      {
        "title": "2024年GDP增速目标",
        "source": "知乎",
        "url": "https://...",
        "hot_score": 98765,
        "create_time": "2024-03-04 10:30:00"
      }
    ]
  }
}
```

**申请方式**:
1. 访问 http://www.alapi.cn 注册
2. 在个人中心获取token
3. 免费接口有每日调用限制（具体查看官网）

---

### 2. Yi18事件风云榜

#### 基本信息
- **官网**: http://top.yi18.net
- **是否免费**: ✅ 完全免费，无需注册
- **用途**: 获取基于百度、搜狗、Google趋势的热点关键词和新闻事件

#### 2.1 获取热词列表

**接口地址**: `http://api.yi18.net/top/list`

**请求方式**: GET

**输入参数**:
```
无必填参数（支持可选分页参数，具体查看官方文档）
```

**测试脚本**:
```bash
#!/bin/bash
# test_yi18_list.sh

curl -X GET "http://api.yi18.net/top/list" | jq '.'
```

**测试输出示例**:
```json
{
  "yi18": [
    {
      "id": 1001,
      "title": "人工智能发展现状",
      "keywords": "AI,人工智能,机器学习",
      "count": 125678,
      "time": "2024-03-04",
      "category": "科技"
    },
    {
      "id": 1002,
      "title": "新能源汽车销量",
      "keywords": "新能源,电动车,特斯拉",
      "count": 98765,
      "time": "2024-03-04",
      "category": "汽车"
    }
  ],
  "total": 500
}
```

**Python测试脚本**:
```python
import requests

def test_yi18_list():
    url = "http://api.yi18.net/top/list"
    
    response = requests.get(url)
    data = response.json()
    
    print(f"总热词数: {data.get('total', 0)}")
    print("\n热门关键词:")
    for item in data['yi18'][:10]:
        print(f"- {item['title']}")
        print(f"  关键词: {item['keywords']}")
        print(f"  关注度: {item['count']}")
        print(f"  分类: {item.get('category', 'N/A')}")
        print()

test_yi18_list()
```

#### 2.2 获取热词详情

**接口地址**: `http://api.yi18.net/top/detail`

**输入参数**:
```json
{
  "id": "integer (必填) - 热词ID，从列表接口获取"
}
```

**测试脚本**:
```python
import requests

def test_yi18_detail(keyword_id):
    url = "http://api.yi18.net/top/detail"
    params = {"id": keyword_id}
    
    response = requests.get(url, params=params)
    data = response.json()
    
    print(f"标题: {data['title']}")
    print(f"关键词: {data['keywords']}")
    print(f"描述: {data.get('description', 'N/A')}")
    print(f"相关新闻数: {len(data.get('news', []))}")
    
    print("\n相关新闻:")
    for news in data.get('news', [])[:3]:
        print(f"- {news['title']}")
        print(f"  来源: {news['source']}")
        print(f"  时间: {news['time']}")

# 使用
test_yi18_detail(1001)
```

**输出示例**:
```json
{
  "id": 1001,
  "title": "人工智能发展现状",
  "keywords": "AI,人工智能,机器学习",
  "description": "2024年人工智能技术在各领域的最新发展...",
  "count": 125678,
  "news": [
    {
      "title": "OpenAI发布最新模型",
      "source": "科技日报",
      "url": "https://...",
      "time": "2024-03-04 09:00:00",
      "summary": "摘要内容..."
    }
  ]
}
```

---

### 3. 接口盒子 - 微博热搜

#### 基本信息
- **官网**: https://www.apihz.cn
- **是否免费**: ✅ 免费额度（需注册获取ID和KEY）
- **用途**: 获取微博实时上升热点、百度热搜、知乎热榜等

#### 3.1 微博实时上升热点

**接口地址**: `https://api.apihz.cn/v1/weibo/hotrising`

**请求方式**: GET

**输入参数**:
```json
{
  "id": "string (必填) - 用户ID，注册后获取",
  "key": "string (必填) - 用户KEY，注册后获取",
  "format": "string (可选) - json或xml，默认json"
}
```

**测试脚本**:
```bash
#!/bin/bash
# test_apihz_weibo.sh

ID="your_id_here"
KEY="your_key_here"

curl -X GET "https://api.apihz.cn/v1/weibo/hotrising?id=${ID}&key=${KEY}" | jq '.'
```

**Python测试脚本**:
```python
import requests

def test_apihz_weibo(user_id, user_key):
    url = "https://api.apihz.cn/v1/weibo/hotrising"
    params = {
        "id": user_id,
        "key": user_key,
        "format": "json"
    }
    
    response = requests.get(url, params=params)
    data = response.json()
    
    if data['code'] != 200:
        print(f"错误: {data['msg']}")
        return
    
    print(f"实时上升热点数: {len(data['data'])}")
    print("\n热点列表:")
    for item in data['data'][:10]:
        print(f"{item['rank']}. {item['keyword']}")
        print(f"   热度: {item['heat']} | 趋势: {item['trend']}")
        print(f"   链接: {item['url']}")
        print()

# 使用
test_apihz_weibo("your_id", "your_key")
```

**测试输出示例**:
```json
{
  "code": 200,
  "msg": "success",
  "data": [
    {
      "rank": 1,
      "keyword": "两会热点话题",
      "heat": 3456789,
      "trend": "上升",
      "label": "热",
      "url": "https://s.weibo.com/weibo?q=%23两会热点话题%23",
      "update_time": "2024-03-04 15:30:00"
    },
    {
      "rank": 2,
      "keyword": "新能源汽车补贴",
      "heat": 2345678,
      "trend": "上升",
      "label": "新",
      "url": "https://s.weibo.com/weibo?q=%23新能源汽车补贴%23",
      "update_time": "2024-03-04 15:30:00"
    }
  ],
  "total": 50
}
```

**申请方式**:
1. 访问 https://www.apihz.cn/user/ 注册
2. 在用户中心获取ID和KEY
3. 免费用户有每日调用次数限制

---

## 二、MCP服务器工具

### 4. World News API MCP

#### 基本信息
- **GitHub**: https://github.com/ddsky/world-news-api-mcp
- **是否免费**: ✅ 免费额度（每天150次请求）
- **用途**: 全球新闻搜索、情感分析、地理位置过滤、报纸头版

#### 4.1 安装与配置

**安装命令**:
```bash
npm install -g world-news-api-mcp
```

**配置环境变量**:
```bash
# Windows PowerShell
$env:WORLD_NEWS_API_KEY="your_api_key_here"

# macOS/Linux
export WORLD_NEWS_API_KEY="your_api_key_here"
```

**Claude Desktop配置** (`claude_desktop_config.json`):
```json
{
  "servers": {
    "world-news-api": {
      "command": "world-news-api-mcp",
      "env": {
        "WORLD_NEWS_API_KEY": "your_api_key_here"
      }
    }
  }
}
```

#### 4.2 核心工具详解

##### 工具1: `search_news` - 搜索新闻

**用途**: 按关键词、时间、地点、分类、情感等多维度搜索新闻

**输入参数**:
```json
{
  "text": "string (可选) - 搜索文本，最少3个字符",
  "language": "string (可选) - ISO 639语言代码，如en, zh, es",
  "source-country": "string (可选) - ISO 3166国家代码，如us, cn, gb",
  "categories": "string (可选) - 分类，如politics, sports, business, technology",
  "number": "integer (可选) - 返回数量，1-100，默认10",
  "offset": "integer (可选) - 偏移量，用于分页",
  "earliest-publish-date": "string (可选) - 最早发布时间，格式YYYY-MM-DD HH:MM:SS",
  "latest-publish-date": "string (可选) - 最晚发布时间",
  "min-sentiment": "number (可选) - 最小情感值，范围[-1,1]",
  "max-sentiment": "number (可选) - 最大情感值，范围[-1,1]",
  "news-sources": "string (可选) - 新闻来源，逗号分隔",
  "authors": "string (可选) - 作者，逗号分隔",
  "entities": "string (可选) - 实体过滤，如ORG:Tesla,PER:Elon Musk",
  "location-filter": "string (可选) - 位置过滤，格式latitude,longitude,radius_km",
  "sort": "string (可选) - 排序字段，如publish-time",
  "sort-direction": "string (可选) - ASC或DESC"
}
```

**测试脚本（MCP客户端）**:
```python
# test_world_news_mcp.py
import requests
import json

class WorldNewsMCPClient:
    def __init__(self, base_url="http://localhost:8000"):
        self.base_url = base_url
    
    def search_news(self, **kwargs):
        """搜索新闻"""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "search_news",
                "arguments": kwargs
            }
        }
        
        response = requests.post(
            f"{self.base_url}/mcp",
            json=payload,
            headers={"Content-Type": "application/json"}
        )
        
        return response.json()

# 测试
client = WorldNewsMCPClient()

# 测试1: 搜索AI相关英文新闻
result = client.search_news(
    text="artificial intelligence",
    language="en",
    categories="technology",
    number=5
)

print("搜索结果:")
print(json.dumps(result, indent=2, ensure_ascii=False))
```

**测试输出示例**:
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "news": [
      {
        "id": "abc123",
        "title": "OpenAI Announces GPT-5 with Revolutionary Capabilities",
        "text": "Full article text...",
        "url": "https://example.com/news/ai-article",
        "image": "https://example.com/image.jpg",
        "publish_date": "2024-03-04 10:30:00",
        "source_country": "us",
        "language": "en",
        "authors": ["John Smith"],
        "sentiment": 0.75,
        "summary": "Short summary...",
        "category": ["technology", "business"]
      }
    ],
    "available_results": 150,
    "offset": 0,
    "number": 5
  }
}
```

##### 工具2: `get_top_news` - 获取头条新闻

**输入参数**:
```json
{
  "source-country": "string (必填) - ISO 3166国家代码",
  "language": "string (必填) - ISO 639语言代码",
  "date": "string (可选) - 日期YYYY-MM-DD，默认今天",
  "headlines-only": "boolean (可选) - 仅返回基本信息，默认false"
}
```

**测试脚本**:
```python
# 获取美国今日英文头条
result = client.get_top_news(
    source_country="us",
    language="en"
)

print("美国今日头条:")
for news in result['result']['news'][:5]:
    print(f"- {news['title']}")
    print(f"  来源: {news.get('source', 'N/A')}")
    print(f"  时间: {news['publish_date']}")
```

##### 工具3: `extract_news` - 提取新闻文章

**输入参数**:
```json
{
  "url": "string (必填) - 新闻文章URL",
  "analyze": "boolean (可选) - 是否分析内容（实体、情感等），默认false"
}
```

**测试脚本**:
```python
# 提取并分析文章
result = client.extract_news(
    url="https://www.bbc.com/news/world-us-canada-59340789",
    analyze=True
)

print("文章信息:")
print(f"标题: {result['result']['title']}")
print(f"作者: {result['result'].get('authors', [])}")
print(f"情感: {result['result'].get('sentiment', 'N/A')}")
print(f"实体: {result['result'].get('entities', [])}")
```

##### 工具4: `get_geo_coordinates` - 获取地理坐标

**输入参数**:
```json
{
  "location": "string (必填) - 地址或位置名称"
}
```

**测试脚本**:
```python
# 获取北京坐标
result = client.get_geo_coordinates(location="Beijing, China")

print("坐标信息:")
print(f"纬度: {result['result']['latitude']}")
print(f"经度: {result['result']['longitude']}")

# 用于位置过滤搜索
coords = f"{result['result']['latitude']},{result['result']['longitude']},50"
news_result = client.search_news(
    text="earthquake",
    location-filter=coords,
    language="en"
)
```

**申请API Key**: https://worldnewsapi.com/register

---

### 5. Alpha Vantage MCP

#### 基本信息
- **GitHub**: https://github.com/alphavantage/alpha_vantage_mcp
- **是否免费**: ✅ 免费API Key（每分钟5次调用，每天500次）
- **用途**: 股票数据、新闻情感、技术指标、基本面数据、期权数据

#### 5.1 安装与配置

**安装uv**:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Claude Desktop配置**:
```json
{
  "mcpServers": {
    "alphavantage": {
      "command": "uvx",
      "args": ["av-mcp", "YOUR_API_KEY"]
    }
  }
}
```

**远程连接**:
```
https://mcp.alphavantage.co/mcp?apikey=YOUR_API_KEY
```

#### 5.2 核心工具详解

##### 工具1: `NEWS_SENTIMENT` - 新闻情感分析

**用途**: 获取股票相关新闻及其情感分析

**输入参数** (通过TOOL_CALL包装):
```json
{
  "tickers": "string (可选) - 股票代码，如AAPL,MSFT",
  "topics": "string (可选) - 主题，如technology, earnings",
  "time_from": "string (可选) - 开始时间YYYYMMDDTHHMM",
  "time_to": "string (可选) - 结束时间YYYYMMDDTHHMM",
  "sort": "string (可选) - 排序方式，LATEST, EARLIEST, RELEVANCE",
  "limit": "integer (可选) - 返回数量，默认50"
}
```

**测试脚本**:
```python
# test_alpha_vantage_mcp.py
import requests
import json

class AlphaVantageMCPClient:
    def __init__(self, api_key, base_url="https://mcp.alphavantage.co"):
        self.api_key = api_key
        self.base_url = base_url
    
    def call_tool(self, tool_name, arguments):
        """调用MCP工具"""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "TOOL_CALL",
                "arguments": {
                    "tool_name": tool_name,
                    "arguments": arguments
                }
            }
        }
        
        response = requests.post(
            f"{self.base_url}/mcp?apikey={self.api_key}",
            json=payload,
            headers={"Content-Type": "application/json"}
        )
        
        return response.json()

# 测试
client = AlphaVantageMCPClient("your_api_key")

# 获取苹果相关新闻情感
result = client.call_tool("NEWS_SENTIMENT", {
    "tickers": "AAPL",
    "limit": 10
})

print("新闻情感分析:")
print(json.dumps(result, indent=2, ensure_ascii=False))
```

**测试输出示例**:
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "items": [
      {
        "title": "Apple Announces New Product Line",
        "url": "https://...",
        "time_published": "2024-03-04 10:30:00",
        "authors": ["Jane Doe"],
        "summary": "Apple unveils...",
        "banner_image": "https://...",
        "source": "Tech News",
        "category_within_source": "Technology",
        "source_domain": "technews.com",
        "topics": [
          {
            "topic": "Technology",
            "relevance_score": "0.8"
          }
        ],
        "overall_sentiment_score": 0.45,
        "overall_sentiment_label": "Somewhat-Bullish",
        "ticker_sentiment": [
          {
            "ticker": "AAPL",
            "relevance_score": "0.9",
            "ticker_sentiment_score": "0.55",
            "ticker_sentiment_label": "Bullish"
          }
        ]
      }
    ],
    "sentiment_score_definition": {
      "Bearish": "x <= -0.35",
      "Somewhat-Bearish": "-0.35 < x <= -0.15",
      "Neutral": "-0.15 < x < 0.15",
      "Somewhat-Bullish": "0.15 <= x < 0.35",
      "Bullish": "x >= 0.35"
    }
  }
}
```

##### 工具2: `TIME_SERIES_DAILY` - 日线数据

**输入参数**:
```json
{
  "symbol": "string (必填) - 股票代码",
  "outputsize": "string (可选) - compact(最近100条)或full(全部)",
  "datatype": "string (可选) - json或csv，默认json"
}
```

**测试脚本**:
```python
# 获取苹果日线数据
result = client.call_tool("TIME_SERIES_DAILY", {
    "symbol": "AAPL",
    "outputsize": "compact"
})

print("日线数据:")
for date, data in list(result['result']['Time Series (Daily)'].items())[:5]:
    print(f"{date}: 开{data['1. open']} 高{data['2. high']} 低{data['3. low']} 收{data['4. close']}")
```

##### 工具3: `COMPANY_OVERVIEW` - 公司概览

**输入参数**:
```json
{
  "symbol": "string (必填) - 股票代码"
}
```

**测试脚本**:
```python
result = client.call_tool("COMPANY_OVERVIEW", {
    "symbol": "AAPL"
})

print("公司信息:")
print(f"名称: {result['result']['Name']}")
print(f"行业: {result['result']['Industry']}")
print(f"市值: {result['result']['MarketCapitalization']}")
print(f"P/E比率: {result['result']['PERatio']}")
print(f"描述: {result['result']['Description'][:200]}...")
```

**申请API Key**: https://www.alphavantage.co/support/#api-key

---

### 6. EODHD MCP Server

#### 基本信息
- **GitHub**: https://github.com/EodHistoricalData/EODHD-MCP-Server
- **是否免费**: ⚠️ 有免费试用，付费订阅（基础计划$19.99/月）
- **用途**: 全球股票、期权、新闻情感、技术指标、基本面数据

#### 6.1 安装与配置

**安装**:
```bash
git clone https://github.com/EodHistoricalData/EODHD-MCP-Server.git
cd EODHD-MCP-Server
pip install -r requirements.txt
```

**配置.env文件**:
```bash
EODHD_API_KEY=YOUR_EODHD_API_KEY
MCP_HOST=127.0.0.1
MCP_PORT=8000
```

**启动HTTP服务器**:
```bash
python server.py
# 访问 http://127.0.0.1:8000/mcp
```

#### 6.2 核心工具详解

##### 工具1: `get_sentiment_data` - 情感数据

**输入参数**:
```json
{
  "symbols": "string (必填) - 股票代码，如AAPL.US",
  "from": "string (可选) - 开始日期YYYY-MM-DD",
  "to": "string (可选) - 结束日期YYYY-MM-DD"
}
```

**测试脚本**:
```python
# test_eodhd_mcp.py
import requests

class EODHDMCPClient:
    def __init__(self, base_url="http://localhost:8000"):
        self.base_url = base_url
    
    def call_tool(self, tool_name, arguments):
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments
            }
        }
        
        response = requests.post(
            f"{self.base_url}/mcp",
            json=payload
        )
        
        return response.json()

client = EODHDMCPClient()

# 获取情感数据
result = client.call_tool("get_sentiment_data", {
    "symbols": "AAPL.US",
    "from": "2024-01-01",
    "to": "2024-01-31"
})

print("情感数据:")
for item in result['result'][:5]:
    print(f"日期: {item['date']}")
    print(f"情感分数: {item['sentiment']}")
    print(f"新闻数: {item['news_count']}")
    print()
```

##### 工具2: `get_company_news` - 公司新闻

**输入参数**:
```json
{
  "symbols": "string (必填) - 股票代码",
  "from": "string (可选) - 开始日期",
  "to": "string (可选) - 结束日期",
  "limit": "integer (可选) - 返回数量"
}
```

##### 工具3: `get_historical_stock_prices` - 历史股价

**输入参数**:
```json
{
  "symbol": "string (必填) - 股票代码，如AAPL.US",
  "from": "string (可选) - 开始日期",
  "to": "string (可选) - 结束日期",
  "period": "string (可选) - d(日线), w(周线), m(月线)"
}
```

**官网**: https://eodhd.com

---

### 7. stock-mcp (中文金融)

#### 基本信息
- **GitHub**: https://github.com/huweihua123/stock-mcp
- **是否免费**: ✅ 完全免费（使用AkShare、BaoStock等免费数据源）
- **用途**: A股、美股、港股金融数据，支持深度研究

#### 7.1 安装与配置

**安装**:
```bash
git clone https://github.com/huweihua123/stock-mcp.git
cd stock-mcp

conda create -n stock-mcp python=3.11.14
conda activate stock-mcp
pip install -r requirements.txt
```

**配置.env**（可选，无配置使用免费数据源）:
```bash
# 可选：Tushare A股数据
TUSHARE_ENABLED=False
TUSHARE_TOKEN=your_token

# 可选：Finnhub 美股数据
FINNHUB_ENABLED=False
FINNHUB_API_KEY=your_key

# 可选：阿里百炼AI
DASHSCOPE_API_KEY=your_key
```

**启动服务器**:
```bash
# HTTP模式
export MCP_TRANSPORT=streamable-http
python -m uvicorn src.server.app:app --host 0.0.0.0 --port 9898

# STDIO模式
python -m src.server.app
```

#### 7.2 核心工具

##### 工具1: `perform_deep_research` - 深度研究

**输入参数**:
```json
{
  "symbol": "string (必填) - 股票代码",
  "include_news": "boolean (可选) - 是否包含新闻，默认true"
}
```

**测试脚本**:
```python
# test_stock_mcp.py
import requests

client = requests.Session()
base_url = "http://localhost:9898"

def call_tool(tool_name, arguments):
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments
        }
    }
    
    response = client.post(f"{base_url}/mcp", json=payload)
    return response.json()

# 深度研究苹果
result = call_tool("perform_deep_research", {
    "symbol": "AAPL",
    "include_news": True
})

print("深度研究结果:")
print(json.dumps(result, indent=2, ensure_ascii=False))
```

**测试输出示例**:
```json
{
  "result": {
    "symbol": "AAPL",
    "current_price": 175.50,
    "price_change": 2.30,
    "price_change_percent": 1.33,
    "historical_data": {
      "30_day_trend": "上涨",
      "high": 180.00,
      "low": 170.00
    },
    "fundamentals": {
      "market_cap": "2.8T",
      "pe_ratio": 28.5,
      "dividend_yield": "0.5%",
      "revenue": "394.3B"
    },
    "news": [
      {
        "title": "Apple launches new product",
        "date": "2024-03-04",
        "sentiment": "positive",
        "source": "Reuters"
      }
    ]
  }
}
```

##### 工具2: `get_market_report` - 市场报告

**输入参数**: 无

**测试脚本**:
```python
result = call_tool("get_market_report", {})

print("市场报告:")
print(f"市场状态: {result['result']['market_status']}")
print(f"指数点位: {result['result']['indices']}")
print(f"涨跌统计: {result['result']['statistics']}")
```

---

## 三、测试脚本集合

### 综合测试脚本

创建 `test_all_apis.py`:

```python
#!/usr/bin/env python3
"""
免费数据源API与MCP工具综合测试脚本
"""
import requests
import json
import time
from datetime import datetime

class DataAPITester:
    def __init__(self):
        self.results = {}
    
    def test_alapi_weibo(self, token):
        """测试ALAPI微博热搜"""
        print("\n[1] 测试 ALAPI 微博热搜...")
        try:
            url = "https://v2.alapi.cn/api/new/wbHot"
            params = {"token": token}
            
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            
            if data['code'] == 200:
                print(f"✓ 成功获取 {len(data['data'])} 条热搜")
                print(f"  示例: {data['data'][0]['hotword']} (热度: {data['data'][0]['hotwordnum']})")
                self.results['alapi_weibo'] = 'success'
            else:
                print(f"✗ 失败: {data['msg']}")
                self.results['alapi_weibo'] = 'failed'
        except Exception as e:
            print(f"✗ 错误: {e}")
            self.results['alapi_weibo'] = 'error'
    
    def test_yi18_list(self):
        """测试Yi18热词列表"""
        print("\n[2] 测试 Yi18 热词列表...")
        try:
            url = "http://api.yi18.net/top/list"
            
            response = requests.get(url, timeout=10)
            data = response.json()
            
            if 'yi18' in data:
                print(f"✓ 成功获取 {len(data['yi18'])} 个热词")
                print(f"  示例: {data['yi18'][0]['title']}")
                self.results['yi18_list'] = 'success'
            else:
                print("✗ 失败: 返回数据格式错误")
                self.results['yi18_list'] = 'failed'
        except Exception as e:
            print(f"✗ 错误: {e}")
            self.results['yi18_list'] = 'error'
    
    def test_apihz_weibo(self, user_id, user_key):
        """测试接口盒子微博热搜"""
        print("\n[3] 测试 接口盒子 微博热搜...")
        try:
            url = "https://api.apihz.cn/v1/weibo/hotrising"
            params = {
                "id": user_id,
                "key": user_key,
                "format": "json"
            }
            
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            
            if data['code'] == 200:
                print(f"✓ 成功获取 {len(data['data'])} 条上升热点")
                print(f"  示例: {data['data'][0]['keyword']} (热度: {data['data'][0]['heat']})")
                self.results['apihz_weibo'] = 'success'
            else:
                print(f"✗ 失败: {data['msg']}")
                self.results['apihz_weibo'] = 'failed'
        except Exception as e:
            print(f"✗ 错误: {e}")
            self.results['apihz_weibo'] = 'error'
    
    def test_world_news_mcp(self, api_key):
        """测试World News API MCP"""
        print("\n[4] 测试 World News API MCP...")
        try:
            url = f"https://mcp.alphavantage.co/mcp?apikey={api_key}"
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {}
            }
            
            response = requests.post(url, json=payload, timeout=10)
            data = response.json()
            
            if 'result' in data:
                print(f"✓ MCP服务器连接成功")
                print(f"  可用工具数: {len(data['result'].get('tools', []))}")
                self.results['world_news_mcp'] = 'success'
            else:
                print("✗ 失败: 无法获取工具列表")
                self.results['world_news_mcp'] = 'failed'
        except Exception as e:
            print(f"✗ 错误: {e}")
            self.results['world_news_mcp'] = 'error'
    
    def test_alpha_vantage_mcp(self, api_key):
        """测试Alpha Vantage MCP"""
        print("\n[5] 测试 Alpha Vantage MCP...")
        try:
            url = f"https://mcp.alphavantage.co/mcp?apikey={api_key}"
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "TOOL_CALL",
                    "arguments": {
                        "tool_name": "GLOBAL_QUOTE",
                        "arguments": {"symbol": "AAPL"}
                    }
                }
            }
            
            response = requests.post(url, json=payload, timeout=10)
            data = response.json()
            
            if 'result' in data:
                print(f"✓ 成功获取AAPL股票数据")
                quote = data['result'].get('Global Quote', {})
                print(f"  价格: ${quote.get('05. price', 'N/A')}")
                self.results['alpha_vantage_mcp'] = 'success'
            else:
                print("✗ 失败: 无法获取数据")
                self.results['alpha_vantage_mcp'] = 'failed'
        except Exception as e:
            print(f"✗ 错误: {e}")
            self.results['alpha_vantage_mcp'] = 'error'
    
    def test_stock_mcp(self, host="localhost", port=9898):
        """测试stock-mcp"""
        print("\n[6] 测试 stock-mcp...")
        try:
            url = f"http://{host}:{port}/mcp"
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "get_market_report",
                    "arguments": {}
                }
            }
            
            response = requests.post(url, json=payload, timeout=10)
            data = response.json()
            
            if 'result' in data:
                print(f"✓ 成功获取市场报告")
                self.results['stock_mcp'] = 'success'
            else:
                print("✗ 失败: 无法获取市场报告")
                self.results['stock_mcp'] = 'failed'
        except Exception as e:
            print(f"✗ 错误: {e}")
            self.results['stock_mcp'] = 'error'
    
    def generate_report(self):
        """生成测试报告"""
        print("\n" + "="*60)
        print("测试报告汇总")
        print("="*60)
        
        success_count = sum(1 for v in self.results.values() if v == 'success')
        total_count = len(self.results)
        
        for api_name, status in self.results.items():
            status_icon = {
                'success': '✓',
                'failed': '✗',
                'error': '⚠'
            }.get(status, '?')
            
            print(f"{status_icon} {api_name:20s} - {status}")
        
        print(f"\n成功率: {success_count}/{total_count} ({success_count/total_count*100:.1f}%)")
        print("="*60)

def main():
    print("="*60)
    print("免费数据源API与MCP工具综合测试")
    print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)
    
    tester = DataAPITester()
    
    # 配置API密钥（请替换为你的实际密钥）
    ALAPI_TOKEN = "your_alapi_token"
    APIHZ_ID = "your_apihz_id"
    APIHZ_KEY = "your_apihz_key"
    WORLD_NEWS_KEY = "your_worldnews_key"
    ALPHA_VANTAGE_KEY = "your_alphavantage_key"
    
    # 执行测试
    tester.test_alapi_weibo(ALAPI_TOKEN)
    tester.test_yi18_list()
    tester.test_apihz_weibo(APIHZ_ID, APIHZ_KEY)
    tester.test_world_news_mcp(WORLD_NEWS_KEY)
    tester.test_alpha_vantage_mcp(ALPHA_VANTAGE_KEY)
    tester.test_stock_mcp()
    
    # 生成报告
    tester.generate_report()

if __name__ == "__main__":
    main()
```

### 运行测试

```bash
# 安装依赖
pip install requests

# 运行测试
python test_all_apis.py
```

---

## 四、集成建议

### 方案对比表

| 方案 | 组合 | 优势 | 劣势 | 成本 | 适用场景 |
|------|------|------|------|------|----------|
| **方案1: 完全免费** | ALAPI + Yi18 + stock-mcp | 无需API Key | 调用限制，功能有限 | 免费 | 快速原型开发 |
| **方案2: 功能完整** | World News + Alpha Vantage + stock-mcp | 数据质量高，支持情感分析 | 需注册 | 免费额度 | 生产环境 |
| **方案3: 专业金融** | EODHD + Alpha Vantage + ALAPI | 数据最全面，支持期权 | 需付费订阅 | $19.99/月起 | 金融应用 |

### 推荐使用场景

#### 1. 舆情监控（国内）
```python
# 使用 ALAPI + Yi18
- ALAPI: 获取微博热搜、今日热榜
- Yi18: 获取热点关键词和事件
- 优势: 实时性强，覆盖主流平台
```

#### 2. 新闻情感分析（国际）
```python
# 使用 World News API MCP
- 搜索全球新闻
- 分析新闻情感
- 按地理位置过滤
- 优势: 支持多语言、多维度搜索
```

#### 3. 股票研究（美股）
```python
# 使用 Alpha Vantage MCP
- 获取股票价格和基本面
- 分析新闻情感
- 计算技术指标
- 优势: 免费额度充足，数据权威
```

#### 4. A股分析（国内）
```python
# 使用 stock-mcp
- 深度研究个股
- 获取市场报告
- 优势: 中文友好，完全免费
```

### 最佳实践

#### 1. API Key管理
```bash
# 使用环境变量
export ALAPI_TOKEN="your_token"
export WORLD_NEWS_API_KEY="your_key"

# 或使用.env文件
# .env
ALAPI_TOKEN=your_token
WORLD_NEWS_API_KEY=your_key
```

#### 2. 错误处理与重试
```python
import time
from functools import wraps

def retry(max_attempts=3, delay=1):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_attempts - 1:
                        raise
                    time.sleep(delay * (attempt + 1))
        return wrapper
    return decorator

@retry(max_attempts=3, delay=2)
def fetch_news_with_retry(keyword):
    # API调用代码
    pass
```

#### 3. 数据缓存
```python
import json
from datetime import datetime, timedelta

class DataCache:
    def __init__(self, ttl_seconds=3600):
        self.cache = {}
        self.ttl = ttl_seconds
    
    def get(self, key):
        if key in self.cache:
            data, timestamp = self.cache[key]
            if datetime.now() - timestamp < timedelta(seconds=self.ttl):
                return data
        return None
    
    def set(self, key, data):
        self.cache[key] = (data, datetime.now())

cache = DataCache(ttl_seconds=300)  # 5分钟缓存

def get_cached_hot_search():
    cached = cache.get('weibo_hot')
    if cached:
        return cached
    
    data = fetch_weibo_hot_search()
    cache.set('weibo_hot', data)
    return data
```

#### 4. 降级策略
```python
def get_news_with_fallback(keyword):
    # 主数据源
    try:
        return fetch_from_world_news(keyword)
    except:
        pass
    
    # 降级到备选数据源
    try:
        return fetch_from_alapi(keyword)
    except:
        pass
    
    # 最后降级到缓存
    return get_from_cache(keyword)
```

---

## 五、附录

### A. 常用国家代码（ISO 3166）

| 国家 | 代码 |
|------|------|
| 中国 | cn |
| 美国 | us |
| 英国 | gb |
| 日本 | jp |
| 德国 | de |
| 法国 | fr |
| 印度 | in |
| 澳大利亚 | au |

### B. 常用语言代码（ISO 639）

| 语言 | 代码 |
|------|------|
| 中文 | zh |
| 英文 | en |
| 西班牙文 | es |
| 法文 | fr |
| 德文 | de |
| 日文 | ja |
| 韩文 | ko |
| 俄文 | ru |

### C. 新闻分类

| 分类 | 英文 |
|------|------|
| 政治 | politics |
| 商业 | business |
| 科技 | technology |
| 体育 | sports |
| 娱乐 | entertainment |
| 健康 | health |
| 科学 | science |
| 世界 | world |

### D. 股票交易所代码

| 交易所 | 代码 |
|--------|------|
| 纽约证券交易所 | NYSE |
| 纳斯达克 | NASDAQ |
| 上海证券交易所 | SSE |
| 深圳证券交易所 | SZSE |
| 香港交易所 | HKEX |
| 东京证券交易所 | TSE |

---

## 六、更新日志

### v1.0 (2024-03-04)
- 初始版本
- 收录7个数据源
- 包含完整测试脚本
- 添加最佳实践指南

---

**文档维护者**: Multi-User Agent Team  
**反馈邮箱**: support@example.com  
**GitHub Issues**: https://github.com/your-org/mutil-user-agent-backend/issues
