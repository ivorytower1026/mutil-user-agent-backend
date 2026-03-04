# 免费数据源API与MCP工具集成文档

> 文档版本: v2.0  
> 更新时间: 2024-03-04  
> 优先级: **官方平台优先** > **无Token优先** > **开源项目**  
> 适用场景: 舆情监控、热点追踪、新闻分析、金融数据获取

---

## ⚠️ 重要说明

本文档优先推荐：
1. ✅ **官方平台API**（数据可靠、稳定）
2. ✅ **完全免费无需Token**（开箱即用）
3. ⚠️ **官方免费需Token**（需注册但免费）
4. 📦 **开源项目**（社区维护）

❌ **不推荐**第三方聚合API（数据来源不明、稳定性差）

---

## 目录

- [第一优先级：官方免费无需Token](#第一优先级官方免费无需token)
  - [1. Hacker News API](#1-hacker-news-api)
  - [2. Reddit JSON Hack](#2-reddit-json-hack)
- [第二优先级：官方免费需Token](#第二优先级官方免费需token)
  - [3. World News API](#3-world-news-api)
  - [4. Alpha Vantage](#4-alpha-vantage)
  - [5. The Guardian](#5-the-guardian)
  - [6. NYTimes API](#6-nytimes-api)
- [第三优先级：开源项目](#第三优先级开源项目)
  - [7. stock-mcp](#7-stock-mcp)
  - [8. dailyhot-api](#8-dailyhot-api)
- [测试脚本集合](#测试脚本集合)
- [集成建议](#集成建议)

---

## 第一优先级：官方免费无需Token

### 1. Hacker News API ⭐⭐⭐⭐⭐

#### 基本信息
- **官方平台**: Y Combinator（硅谷创业孵化器）
- **是否免费**: ✅ 完全免费
- **需要Token**: ❌ 不需要
- **官方文档**: https://github.com/HackerNews/API
- **用途**: 获取技术社区热门新闻、评论、用户信息
- **可靠性**: ⭐⭐⭐⭐⭐（官方维护，稳定可靠）

#### 1.1 获取热门故事列表

**接口地址**: `https://hacker-news.firebaseio.com/v0/topstories.json`

**请求方式**: GET

**输入参数**: 无

**测试脚本**:
```bash
#!/bin/bash
# test_hackernews_top.sh

curl -X GET "https://hacker-news.firebaseio.com/v0/topstories.json" | jq '.'
```

**测试输出**:
```json
[
  8863,
  9001,
  9074,
  8956,
  ...
]
```

#### 1.2 获取故事详情

**接口地址**: `https://hacker-news.firebaseio.com/v0/item/{id}.json`

**请求方式**: GET

**输入参数**:
- `id` (路径参数): 故事ID

**测试脚本**:
```python
# test_hackernews_detail.py
import requests

def get_story_detail(story_id):
    """获取故事详情"""
    url = f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json"
    
    response = requests.get(url, timeout=10)
    data = response.json()
    
    print(f"ID: {data['id']}")
    print(f"标题: {data['title']}")
    print(f"作者: {data['by']}")
    print(f"分数: {data['score']}")
    print(f"链接: {data.get('url', 'N/A')}")
    print(f"时间: {data['time']}")
    print(f"评论数: {data.get('descendants', 0)}")
    
    return data

# 获取第1个热门故事
top_stories = requests.get(
    "https://hacker-news.firebaseio.com/v0/topstories.json"
).json()

get_story_detail(top_stories[0])
```

**测试输出示例**:
```json
{
  "by": "pg",
  "descendants": 150,
  "id": 8863,
  "kids": [8952, 9168, ...],
  "score": 111,
  "time": 1175714200,
  "title": "My YC app: Dropbox",
  "type": "story",
  "url": "http://www.getdropbox.com/u/2/screencast.html"
}
```

#### 1.3 获取用户信息

**接口地址**: `https://hacker-news.firebaseio.com/v0/user/{username}.json`

**测试脚本**:
```python
def get_user_info(username):
    """获取用户信息"""
    url = f"https://hacker-news.firebaseio.com/v0/user/{username}.json"
    
    response = requests.get(url, timeout=10)
    data = response.json()
    
    print(f"用户名: {data['id']}")
    print(f"Karma积分: {data['karma']}")
    print(f"创建时间: {data['created']}")
    print(f"提交数: {len(data.get('submitted', []))}")
    
    return data

get_user_info("pg")  # Paul Graham
```

**可用端点**:
- `/topstories.json` - 热门故事
- `/newstories.json` - 最新故事
- `/beststories.json` - 最佳故事
- `/askstories.json` - Ask HN
- `/showstories.json` - Show HN
- `/jobstories.json` - 工作机会

---

### 2. Reddit JSON Hack ⭐⭐⭐⭐

#### 基本信息
- **官方平台**: Reddit
- **是否免费**: ✅ 完全免费
- **需要Token**: ❌ 不需要（使用特殊技巧）
- **官方说明**: Reddit官方支持`.json`格式输出
- **用途**: 获取Reddit帖子和评论
- **可靠性**: ⭐⭐⭐⭐（官方功能，但需注意频率限制）

#### 2.1 获取帖子JSON

**方法**: 任何Reddit帖子URL后加 `.json`

**接口格式**: `https://www.reddit.com/r/{subreddit}/comments/{post_id}/{title}/.json`

**输入参数**: 无（URL路径参数）

**测试脚本**:
```python
# test_reddit_json.py
import requests

def get_reddit_post(subreddit, post_id):
    """获取Reddit帖子JSON数据"""
    url = f"https://www.reddit.com/r/{subreddit}/comments/{post_id}/.json"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    response = requests.get(url, headers=headers, timeout=10)
    data = response.json()
    
    # data[0] 是帖子信息
    post_data = data[0]['data']['children'][0]['data']
    
    print(f"标题: {post_data['title']}")
    print(f"作者: {post_data['author']}")
    print(f"点赞数: {post_data['score']}")
    print(f"评论数: {post_data['num_comments']}")
    print(f"URL: {post_data['url']}")
    print(f"创建时间: {post_data['created_utc']}")
    
    # data[1] 是评论信息
    if len(data) > 1:
        comments = data[1]['data']['children']
        print(f"\n前3条评论:")
        for i, comment in enumerate(comments[:3], 1):
            if comment['kind'] == 't1':
                print(f"{i}. {comment['data']['author']}: {comment['data']['body'][:100]}...")
    
    return data

# 使用示例（替换为实际的post_id）
# get_reddit_post("Python", "actual_post_id_here")
```

#### 2.2 获取Subreddit热门

**接口格式**: `https://www.reddit.com/r/{subreddit}/hot.json?limit={count}`

**测试脚本**:
```python
def get_subreddit_hot(subreddit, limit=10):
    """获取Subreddit热门帖子"""
    url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit={limit}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    response = requests.get(url, headers=headers, timeout=10)
    data = response.json()
    
    posts = data['data']['children']
    
    print(f"r/{subreddit} 热门帖子:")
    for i, post in enumerate(posts, 1):
        post_data = post['data']
        print(f"{i}. {post_data['title']}")
        print(f"   点赞: {post_data['score']} | 评论: {post_data['num_comments']}")
        print(f"   作者: u/{post_data['author']}")
        print()
    
    return data

# 获取Python版块热门
get_subreddit_hot("Python", limit=5)
```

**测试输出示例**:
```json
{
  "kind": "Listing",
  "data": {
    "children": [
      {
        "kind": "t3",
        "data": {
          "title": "Python 3.12 Released",
          "author": "python_dev",
          "score": 1523,
          "num_comments": 245,
          "url": "https://...",
          "created_utc": 1234567890
        }
      }
    ]
  }
}
```

**注意事项**:
- ⚠️ 需要设置User-Agent，否则可能被限制
- ⚠️ 建议每次请求间隔2秒，避免被封IP
- ⚠️ 官方API收费，此方法仅适用于小规模使用

---

## 第二优先级：官方免费需Token

### 3. World News API ⭐⭐⭐⭐⭐

#### 基本信息
- **官方平台**: worldnewsapi.com
- **是否免费**: ✅ 每天150次免费请求
- **需要Token**: ✅ 需要（免费注册）
- **申请地址**: https://worldnewsapi.com/register
- **用途**: 全球新闻搜索、情感分析、地理位置过滤
- **可靠性**: ⭐⭐⭐⭐⭐（官方维护，数据质量高）

#### 3.1 搜索新闻

**接口地址**: `https://api.worldnewsapi.com/search-news`

**请求方式**: GET

**输入参数**:
```json
{
  "api-key": "string (必填) - API密钥",
  "text": "string (可选) - 搜索文本",
  "language": "string (可选) - 语言代码，如en, zh",
  "source-country": "string (可选) - 国家代码，如us, cn",
  "categories": "string (可选) - 分类，如politics, technology",
  "number": "integer (可选) - 返回数量，默认10",
  "earliest-publish-date": "string (可选) - 最早发布时间",
  "latest-publish-date": "string (可选) - 最晚发布时间"
}
```

**测试脚本**:
```python
# test_worldnews_api.py
import requests
import os

def search_news(api_key, text, language="en", number=10):
    """搜索新闻"""
    url = "https://api.worldnewsapi.com/search-news"
    
    params = {
        "api-key": api_key,
        "text": text,
        "language": language,
        "number": number
    }
    
    response = requests.get(url, params=params, timeout=10)
    data = response.json()
    
    print(f"找到 {data.get('available_results', 0)} 条新闻")
    print(f"\n前{len(data['news'])}条:")
    
    for i, news in enumerate(data['news'], 1):
        print(f"\n{i}. {news['title']}")
        print(f"   来源: {news.get('source', 'N/A')}")
        print(f"   时间: {news['publish_date']}")
        print(f"   情感: {news.get('sentiment', 'N/A')}")
        print(f"   URL: {news['url']}")
    
    return data

# 使用
api_key = os.getenv("WORLD_NEWS_API_KEY", "your_key_here")
search_news(api_key, "artificial intelligence", language="en", number=5)
```

**测试输出示例**:
```json
{
  "available_results": 1500,
  "news": [
    {
      "id": "abc123",
      "title": "OpenAI Announces GPT-5",
      "text": "Full article text...",
      "url": "https://example.com/article",
      "image": "https://example.com/image.jpg",
      "publish_date": "2024-03-04 10:30:00",
      "source_country": "us",
      "language": "en",
      "sentiment": 0.75,
      "authors": ["John Smith"],
      "category": ["technology", "business"]
    }
  ]
}
```

#### 3.2 获取头条新闻

**接口地址**: `https://api.worldnewsapi.com/top-news`

**测试脚本**:
```python
def get_top_news(api_key, country="us", language="en"):
    """获取头条新闻"""
    url = "https://api.worldnewsapi.com/top-news"
    
    params = {
        "api-key": api_key,
        "source-country": country,
        "language": language
    }
    
    response = requests.get(url, params=params, timeout=10)
    data = response.json()
    
    print(f"{country.upper()} 今日头条:")
    for i, news in enumerate(data['news'][:5], 1):
        print(f"{i}. {news['title']}")
    
    return data

get_top_news(api_key, country="us", language="en")
```

**申请步骤**:
1. 访问 https://worldnewsapi.com/register
2. 填写邮箱和密码
3. 验证邮箱
4. 获取API Key（立即生效）
5. 免费额度：每天150次请求

---

### 4. Alpha Vantage ⭐⭐⭐⭐⭐

#### 基本信息
- **官方平台**: alphavantage.co
- **是否免费**: ✅ 每天500次，每分钟5次
- **需要Token**: ✅ 需要（免费注册）
- **申请地址**: https://www.alphavantage.co/support/#api-key
- **用途**: 股票数据、新闻情感、技术指标、基本面数据
- **可靠性**: ⭐⭐⭐⭐⭐（全球知名金融数据提供商）

#### 4.1 获取股票报价

**接口地址**: `https://www.alphavantage.co/query`

**请求方式**: GET

**输入参数**:
```json
{
  "function": "GLOBAL_QUOTE",
  "symbol": "string (必填) - 股票代码",
  "apikey": "string (必填) - API密钥"
}
```

**测试脚本**:
```python
# test_alpha_vantage.py
import requests
import os

def get_stock_quote(api_key, symbol):
    """获取股票报价"""
    url = "https://www.alphavantage.co/query"
    
    params = {
        "function": "GLOBAL_QUOTE",
        "symbol": symbol,
        "apikey": api_key
    }
    
    response = requests.get(url, params=params, timeout=10)
    data = response.json()
    
    quote = data.get('Global Quote', {})
    
    print(f"股票: {symbol}")
    print(f"开盘价: ${quote.get('02. open', 'N/A')}")
    print(f"最高价: ${quote.get('03. high', 'N/A')}")
    print(f"最低价: ${quote.get('04. low', 'N/A')}")
    print(f"收盘价: ${quote.get('05. price', 'N/A')}")
    print(f"成交量: {quote.get('06. volume', 'N/A')}")
    print(f"涨跌幅: {quote.get('10. change percent', 'N/A')}")
    
    return data

api_key = os.getenv("ALPHA_VANTAGE_KEY", "your_key_here")
get_stock_quote(api_key, "AAPL")
```

**测试输出示例**:
```json
{
  "Global Quote": {
    "01. symbol": "AAPL",
    "02. open": "175.50",
    "03. high": "178.20",
    "04. low": "174.80",
    "05. price": "177.30",
    "06. volume": "52345678",
    "07. latest trading day": "2024-03-04",
    "08. previous close": "174.20",
    "09. change": "3.10",
    "10. change percent": "1.7793%"
  }
}
```

#### 4.2 获取新闻情感

**接口地址**: `https://www.alphavantage.co/query?function=NEWS_SENTIMENT`

**测试脚本**:
```python
def get_news_sentiment(api_key, tickers="AAPL"):
    """获取股票新闻情感"""
    url = "https://www.alphavantage.co/query"
    
    params = {
        "function": "NEWS_SENTIMENT",
        "tickers": tickers,
        "apikey": api_key,
        "limit": 10
    }
    
    response = requests.get(url, params=params, timeout=10)
    data = response.json()
    
    print(f"{tickers} 相关新闻:")
    
    for i, item in enumerate(data.get('feed', [])[:5], 1):
        print(f"\n{i}. {item['title']}")
        print(f"   时间: {item['time_published']}")
        print(f"   整体情感: {item['overall_sentiment_label']}")
        print(f"   情感分数: {item['overall_sentiment_score']}")
        
        # 股票特定情感
        for ticker_sentiment in item.get('ticker_sentiment', []):
            if ticker_sentiment['ticker'] == tickers:
                print(f"   {tickers}情感: {ticker_sentiment['ticker_sentiment_label']}")
    
    return data

get_news_sentiment(api_key, "AAPL")
```

**申请步骤**:
1. 访问 https://www.alphavantage.co/support/#api-key
2. 输入邮箱
3. 立即获得API Key（无需验证）
4. 免费额度：每天500次，每分钟5次

---

### 5. The Guardian ⭐⭐⭐⭐

#### 基本信息
- **官方平台**: theguardian.com（英国《卫报》）
- **是否免费**: ✅ 每天12,000次
- **需要Token**: ✅ 需要（免费注册）
- **申请地址**: https://open-platform.theguardian.com/
- **用途**: 英国新闻、文章搜索
- **可靠性**: ⭐⭐⭐⭐⭐（百年老牌媒体）

#### 5.1 搜索文章

**接口地址**: `https://content.guardianapis.com/search`

**测试脚本**:
```python
# test_guardian.py
import requests
import os

def search_guardian(api_key, query, page_size=10):
    """搜索卫报文章"""
    url = "https://content.guardianapis.com/search"
    
    params = {
        "q": query,
        "api-key": api_key,
        "page-size": page_size
    }
    
    response = requests.get(url, params=params, timeout=10)
    data = response.json()
    
    results = data['response']['results']
    
    print(f"找到 {data['response']['total']} 篇文章")
    print(f"\n前{len(results)}篇:")
    
    for i, article in enumerate(results, 1):
        print(f"\n{i}. {article['webTitle']}")
        print(f"   类型: {article['type']}")
        print(f"   版块: {article['sectionName']}")
        print(f"   时间: {article['webPublicationDate']}")
        print(f"   URL: {article['webUrl']}")
    
    return data

api_key = os.getenv("GUARDIAN_API_KEY", "your_key_here")
search_guardian(api_key, "artificial intelligence", page_size=5)
```

**申请步骤**:
1. 访问 https://open-platform.theguardian.com/
2. 点击"Get API Key"
3. 注册账号
4. 获取API Key
5. 免费额度：每天12,000次

---

### 6. NYTimes API ⭐⭐⭐⭐

#### 基本信息
- **官方平台**: nytimes.com（纽约时报）
- **是否免费**: ✅ 每天1,000次
- **需要Token**: ✅ 需要（免费注册）
- **申请地址**: https://developer.nytimes.com/
- **用途**: 纽约时报新闻、文章搜索
- **可靠性**: ⭐⭐⭐⭐⭐（美国顶级媒体）

#### 6.1 搜索文章

**接口地址**: `https://api.nytimes.com/svc/search/v2/articlesearch.json`

**测试脚本**:
```python
# test_nytimes.py
import requests
import os

def search_nytimes(api_key, query):
    """搜索纽约时报文章"""
    url = "https://api.nytimes.com/svc/search/v2/articlesearch.json"
    
    params = {
        "q": query,
        "api-key": api_key
    }
    
    response = requests.get(url, params=params, timeout=10)
    data = response.json()
    
    articles = data['response']['docs']
    
    print(f"找到 {data['response']['meta']['hits']} 篇文章")
    print(f"\n前{len(articles)}篇:")
    
    for i, article in enumerate(articles, 1):
        print(f"\n{i}. {article['headline']['main']}")
        print(f"   作者: {', '.join(article['byline']['person'][0]['firstname'] if article['byline']['person'] else 'N/A')}")
        print(f"   时间: {article['pub_date']}")
        print(f"   URL: {article['web_url']}")
        print(f"   摘要: {article['snippet']}")
    
    return data

api_key = os.getenv("NYTIMES_API_KEY", "your_key_here")
search_nytimes(api_key, "technology")
```

**申请步骤**:
1. 访问 https://developer.nytimes.com/
2. 注册账号
3. 创建应用
4. 获取API Key
5. 免费额度：每天1,000次

---

## 第三优先级：开源项目

### 7. stock-mcp ⭐⭐⭐⭐⭐

#### 基本信息
- **项目来源**: GitHub开源项目
- **GitHub**: https://github.com/huweihua123/stock-mcp
- **是否免费**: ✅ 完全免费
- **需要Token**: ❌ 不需要（使用免费数据源）
- **用途**: A股、美股、港股金融数据
- **可靠性**: ⭐⭐⭐⭐（开源项目，社区维护）

#### 7.1 安装与配置

**安装**:
```bash
git clone https://github.com/huweihua123/stock-mcp.git
cd stock-mcp

conda create -n stock-mcp python=3.11.14
conda activate stock-mcp
pip install -r requirements.txt
```

**启动HTTP服务**:
```bash
export MCP_TRANSPORT=streamable-http
python -m uvicorn src.server.app:app --host 0.0.0.0 --port 9898
```

#### 7.2 使用工具

**工具1: perform_deep_research - 深度研究**

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

def call_tool(tool_name, arguments):
    """调用stock-mcp工具"""
    url = "http://localhost:9898/mcp"
    
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments
        }
    }
    
    response = requests.post(url, json=payload, timeout=10)
    return response.json()

# 深度研究苹果股票
result = call_tool("perform_deep_research", {
    "symbol": "AAPL",
    "include_news": True
})

print("深度研究结果:")
print(json.dumps(result, indent=2, ensure_ascii=False))
```

**数据来源**:
- A股: AkShare、BaoStock（完全免费）
- 美股: Yahoo Finance（免费）
- 港股: 同花顺（免费）

---

### 8. dailyhot-api ⭐⭐⭐⭐

#### 基本信息
- **项目来源**: GitHub开源项目（RSSHub生态）
- **GitHub**: https://github.com/DIYgod/RSSHub
- **是否免费**: ✅ 完全免费
- **需要Token**: ❌ 不需要
- **用途**: 聚合知乎、微博、抖音、B站等热榜
- **可靠性**: ⭐⭐⭐⭐（开源项目，活跃维护）

#### 8.1 使用公开实例

**公开实例**: https://rsshub.app

**接口示例**:
```bash
# 知乎热榜
curl "https://rsshub.app/zhihu/hotlist.json"

# 微博热搜
curl "https://rsshub.app/weibo/search/hot.json"

# 抖音热点
curl "https://rsshub.app/douyin/trending.json"

# B站热门
curl "https://rsshub.app/bilibili/ranking/0/3.json"
```

**测试脚本**:
```python
# test_rsshub.py
import requests

def get_zhihu_hot():
    """获取知乎热榜"""
    url = "https://rsshub.app/zhihu/hotlist.json"
    
    response = requests.get(url, timeout=10)
    data = response.json()
    
    print("知乎热榜:")
    for i, item in enumerate(data['data'][:10], 1):
        print(f"{i}. {item['title']}")
        print(f"   热度: {item.get('score', 'N/A')}")
        print(f"   URL: {item['url']}")
    
    return data

get_zhihu_hot()
```

---

## 测试脚本集合

### 综合测试脚本

创建 `test_all_apis.py`:

```python
#!/usr/bin/env python3
"""
免费数据源API综合测试脚本
优先级：官方平台 > 无Token > 开源项目
"""
import requests
import json
import os
from datetime import datetime

class APITester:
    def __init__(self):
        self.results = {}
    
    def test_hackernews(self):
        """测试Hacker News API（官方、免费、无Token）"""
        print("\n[1] 测试 Hacker News API...")
        try:
            # 获取热门故事
            url = "https://hacker-news.firebaseio.com/v0/topstories.json"
            response = requests.get(url, timeout=10)
            story_ids = response.json()
            
            # 获取第一个故事
            story_url = f"https://hacker-news.firebaseio.com/v0/item/{story_ids[0]}.json"
            story = requests.get(story_url, timeout=10).json()
            
            print(f"✓ 成功")
            print(f"  标题: {story['title']}")
            print(f"  分数: {story['score']}")
            print(f"  来源: 官方API，无需Token")
            self.results['hackernews'] = 'success'
            
        except Exception as e:
            print(f"✗ 失败: {e}")
            self.results['hackernews'] = 'failed'
    
    def test_reddit_json(self):
        """测试Reddit JSON Hack（官方、免费、无Token）"""
        print("\n[2] 测试 Reddit JSON...")
        try:
            url = "https://www.reddit.com/r/Python/hot.json?limit=5"
            headers = {"User-Agent": "Mozilla/5.0"}
            
            response = requests.get(url, headers=headers, timeout=10)
            data = response.json()
            
            posts = data['data']['children']
            
            print(f"✓ 成功")
            print(f"  获取帖子数: {len(posts)}")
            print(f"  第一条: {posts[0]['data']['title']}")
            print(f"  来源: 官方功能，无需Token")
            self.results['reddit'] = 'success'
            
        except Exception as e:
            print(f"✗ 失败: {e}")
            self.results['reddit'] = 'failed'
    
    def test_worldnews(self, api_key):
        """测试World News API（官方、免费需Token）"""
        print("\n[3] 测试 World News API...")
        if api_key == "your_key_here":
            print("⊘ 跳过（未配置API Key）")
            self.results['worldnews'] = 'skipped'
            return
        
        try:
            url = "https://api.worldnewsapi.com/search-news"
            params = {
                "api-key": api_key,
                "text": "technology",
                "number": 3
            }
            
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            
            print(f"✓ 成功")
            print(f"  新闻数: {len(data['news'])}")
            print(f"  第一条: {data['news'][0]['title']}")
            print(f"  来源: 官方API，免费额度150次/天")
            self.results['worldnews'] = 'success'
            
        except Exception as e:
            print(f"✗ 失败: {e}")
            self.results['worldnews'] = 'failed'
    
    def test_alpha_vantage(self, api_key):
        """测试Alpha Vantage（官方、免费需Token）"""
        print("\n[4] 测试 Alpha Vantage...")
        if api_key == "your_key_here":
            print("⊘ 跳过（未配置API Key）")
            self.results['alphavantage'] = 'skipped'
            return
        
        try:
            url = "https://www.alphavantage.co/query"
            params = {
                "function": "GLOBAL_QUOTE",
                "symbol": "AAPL",
                "apikey": api_key
            }
            
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            
            quote = data.get('Global Quote', {})
            
            print(f"✓ 成功")
            print(f"  AAPL价格: ${quote.get('05. price', 'N/A')}")
            print(f"  来源: 官方API，免费额度500次/天")
            self.results['alphavantage'] = 'success'
            
        except Exception as e:
            print(f"✗ 失败: {e}")
            self.results['alphavantage'] = 'failed'
    
    def generate_report(self):
        """生成测试报告"""
        print("\n" + "="*60)
        print("测试报告")
        print("="*60)
        
        for api_name, status in self.results.items():
            icon = {
                'success': '✓',
                'failed': '✗',
                'skipped': '⊘'
            }.get(status, '?')
            
            print(f"{icon} {api_name:20s} - {status}")
        
        success = sum(1 for v in self.results.values() if v == 'success')
        total = len(self.results)
        
        print(f"\n成功率: {success}/{total}")
        print("="*60)

def main():
    print("="*60)
    print("免费数据源API综合测试")
    print("优先级: 官方平台 > 无Token > 开源项目")
    print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)
    
    tester = APITester()
    
    # 测试无需Token的API
    tester.test_hackernews()
    tester.test_reddit_json()
    
    # 测试需要Token的API（从环境变量读取）
    tester.test_worldnews(os.getenv("WORLD_NEWS_API_KEY", "your_key_here"))
    tester.test_alpha_vantage(os.getenv("ALPHA_VANTAGE_KEY", "your_key_here"))
    
    # 生成报告
    tester.generate_report()

if __name__ == "__main__":
    main()
```

### 运行测试

```bash
# 1. 安装依赖
pip install requests

# 2. 设置API密钥（可选）
export WORLD_NEWS_API_KEY="your_key"
export ALPHA_VANTAGE_KEY="your_key"

# 3. 运行测试
python test_all_apis.py
```

---

## 集成建议

### 推荐方案

#### 方案A: 完全免费无需Token ⭐⭐⭐⭐⭐
```
Hacker News API + Reddit JSON + stock-mcp
```
- **优势**: 完全免费，无需注册，开箱即用
- **数据源**: 全部官方平台或开源项目
- **适用**: 个人项目、原型开发、学习研究

#### 方案B: 官方免费需Token ⭐⭐⭐⭐
```
World News API + Alpha Vantage + The Guardian
```
- **优势**: 数据质量高，官方维护，稳定可靠
- **成本**: 免费注册，额度充足
- **适用**: 生产环境、商业应用

#### 方案C: 混合方案 ⭐⭐⭐⭐⭐
```
Hacker News + Reddit + World News API + stock-mcp
```
- **优势**: 兼顾免费和功能完整
- **覆盖**: 技术新闻 + 社交媒体 + 全球新闻 + 金融数据
- **适用**: 综合性应用

### 不推荐方案

❌ **第三方聚合API**（如ALAPI、Yi18、接口盒子）
- 数据来源不明
- 稳定性差
- 需要付费
- 可能违反平台ToS

---

## API密钥管理

### 环境变量方式（推荐）

```bash
# .env文件
WORLD_NEWS_API_KEY=your_worldnews_key
ALPHA_VANTAGE_KEY=your_alphavantage_key
GUARDIAN_API_KEY=your_guardian_key
NYTIMES_API_KEY=your_nytimes_key
```

```python
# Python代码
import os
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv('WORLD_NEWS_API_KEY')
```

### 安全建议

1. ✅ 使用环境变量存储API密钥
2. ✅ 不要在代码中硬编码
3. ✅ 不要提交到Git仓库
4. ✅ 使用`.gitignore`排除`.env`文件

---

## 常见问题

### Q1: 为什么要优先使用官方API？
**A**: 官方API数据来源可靠、稳定，不会因为第三方平台关闭而失效。

### Q2: Reddit JSON Hack合法吗？
**A**: 这是Reddit官方支持的公开功能，但要注意频率限制，避免被封IP。

### Q3: 免费额度够用吗？
**A**: 
- World News API: 150次/天（足够测试和个人使用）
- Alpha Vantage: 500次/天（足够大多数应用）
- The Guardian: 12,000次/天（非常充足）

### Q4: stock-mcp的数据可靠吗？
**A**: stock-mcp使用的是AkShare、Yahoo Finance等知名免费数据源，数据质量有保障。

---

## 更新日志

### v2.0 (2024-03-04)
- ✅ 重新整理API优先级：官方平台 > 无Token > 开源项目
- ✅ 删除不可靠的第三方聚合API
- ✅ 明确标注每个API的来源和可靠性
- ✅ 添加官方平台说明
- ✅ 优化测试脚本

### v1.0 (2024-03-04)
- 初始版本

---

**文档维护**: Multi-User Agent Team  
**最后更新**: 2024-03-04  
**反馈**: GitHub Issues
