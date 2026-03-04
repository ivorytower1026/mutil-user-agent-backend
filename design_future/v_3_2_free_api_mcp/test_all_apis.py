#!/usr/bin/env python3
"""
免费数据源API综合测试脚本 v2.0
优先级: 官方平台 > 无Token > 开源项目
"""

import requests
import json
import os
from datetime import datetime


class APITester:
    def __init__(self):
        self.results = {}

    def print_header(self, title):
        print("\n" + "=" * 60)
        print(title)
        print("=" * 60)

    def test_hackernews(self):
        """测试Hacker News API（官方、免费、无Token）⭐⭐⭐⭐⭐"""
        print("\n[1] 测试 Hacker News API...")
        print("    官方平台: Y Combinator")
        print("    是否免费: ✅ 完全免费")
        print("    需要Token: ❌ 不需要")
        print("    接口: https://hacker-news.firebaseio.com/v0/topstories.json")

        try:
            # 获取热门故事
            url = "https://hacker-news.firebaseio.com/v0/topstories.json"
            start_time = datetime.now()
            response = requests.get(url, timeout=10)
            elapsed = (datetime.now() - start_time).total_seconds()

            story_ids = response.json()

            # 获取第一个故事详情
            story_url = (
                f"https://hacker-news.firebaseio.com/v0/item/{story_ids[0]}.json"
            )
            story = requests.get(story_url, timeout=10).json()

            print(f"✓ 成功 (耗时: {elapsed:.2f}s)")
            print(f"  热门故事数: {len(story_ids)}")
            print(f"\n  第一条故事:")
            print(f"    标题: {story['title']}")
            print(f"    作者: {story['by']}")
            print(f"    分数: {story['score']}")
            print(f"    链接: {story.get('url', 'N/A')}")

            self.results["hackernews"] = {
                "status": "success",
                "source": "官方API",
                "token_required": False,
            }

        except Exception as e:
            print(f"✗ 失败: {e}")
            self.results["hackernews"] = {"status": "failed", "error": str(e)}

    def test_reddit_json(self):
        """测试Reddit JSON Hack（官方、免费、无Token）⭐⭐⭐⭐"""
        print("\n[2] 测试 Reddit JSON...")
        print("    官方平台: Reddit")
        print("    是否免费: ✅ 完全免费")
        print("    需要Token: ❌ 不需要")
        print("    接口: https://www.reddit.com/r/Python/hot.json")

        try:
            url = "https://www.reddit.com/r/Python/hot.json?limit=5"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }

            start_time = datetime.now()
            response = requests.get(url, headers=headers, timeout=10)
            elapsed = (datetime.now() - start_time).total_seconds()

            data = response.json()
            posts = data["data"]["children"]

            print(f"✓ 成功 (耗时: {elapsed:.2f}s)")
            print(f"  获取帖子数: {len(posts)}")
            print(f"\n  前3条帖子:")

            for i, post in enumerate(posts[:3], 1):
                post_data = post["data"]
                print(f"  {i}. {post_data['title'][:60]}...")
                print(
                    f"     点赞: {post_data['score']} | 评论: {post_data['num_comments']}"
                )

            self.results["reddit"] = {
                "status": "success",
                "source": "官方功能",
                "token_required": False,
            }

        except Exception as e:
            print(f"✗ 失败: {e}")
            self.results["reddit"] = {"status": "failed", "error": str(e)}

    def test_worldnews(self, api_key):
        """测试World News API（官方、免费需Token）⭐⭐⭐⭐⭐"""
        print("\n[3] 测试 World News API...")
        print("    官方平台: worldnewsapi.com")
        print("    是否免费: ✅ 每天150次")
        print("    需要Token: ✅ 需要（免费注册）")
        print("    接口: https://api.worldnewsapi.com/search-news")

        if api_key == "your_key_here":
            print("⊘ 跳过（未配置API Key）")
            print("    申请地址: https://worldnewsapi.com/register")
            self.results["worldnews"] = {"status": "skipped", "reason": "未配置API Key"}
            return

        try:
            url = "https://api.worldnewsapi.com/search-news"
            params = {
                "api-key": api_key,
                "text": "technology",
                "language": "en",
                "number": 3,
            }

            start_time = datetime.now()
            response = requests.get(url, params=params, timeout=10)
            elapsed = (datetime.now() - start_time).total_seconds()

            data = response.json()

            print(f"✓ 成功 (耗时: {elapsed:.2f}s)")
            print(f"  新闻数: {len(data['news'])}")
            print(f"\n  前3条新闻:")

            for i, news in enumerate(data["news"][:3], 1):
                print(f"  {i}. {news['title'][:60]}...")
                print(f"     时间: {news['publish_date']}")
                print(f"     情感: {news.get('sentiment', 'N/A')}")

            self.results["worldnews"] = {
                "status": "success",
                "source": "官方API",
                "token_required": True,
            }

        except Exception as e:
            print(f"✗ 失败: {e}")
            self.results["worldnews"] = {"status": "failed", "error": str(e)}

    def test_alpha_vantage(self, api_key):
        """测试Alpha Vantage（官方、免费需Token）⭐⭐⭐⭐⭐"""
        print("\n[4] 测试 Alpha Vantage...")
        print("    官方平台: alphavantage.co")
        print("    是否免费: ✅ 每天500次")
        print("    需要Token: ✅ 需要（免费注册）")
        print("    接口: https://www.alphavantage.co/query")

        if api_key == "your_key_here":
            print("⊘ 跳过（未配置API Key）")
            print("    申请地址: https://www.alphavantage.co/support/#api-key")
            self.results["alphavantage"] = {
                "status": "skipped",
                "reason": "未配置API Key",
            }
            return

        try:
            url = "https://www.alphavantage.co/query"
            params = {"function": "GLOBAL_QUOTE", "symbol": "AAPL", "apikey": api_key}

            start_time = datetime.now()
            response = requests.get(url, params=params, timeout=10)
            elapsed = (datetime.now() - start_time).total_seconds()

            data = response.json()
            quote = data.get("Global Quote", {})

            print(f"✓ 成功 (耗时: {elapsed:.2f}s)")
            print(f"\n  AAPL股票报价:")
            print(f"    开盘: ${quote.get('02. open', 'N/A')}")
            print(f"    最高: ${quote.get('03. high', 'N/A')}")
            print(f"    最低: ${quote.get('04. low', 'N/A')}")
            print(f"    收盘: ${quote.get('05. price', 'N/A')}")
            print(f"    涨跌: {quote.get('10. change percent', 'N/A')}")

            self.results["alphavantage"] = {
                "status": "success",
                "source": "官方API",
                "token_required": True,
            }

        except Exception as e:
            print(f"✗ 失败: {e}")
            self.results["alphavantage"] = {"status": "failed", "error": str(e)}

    def test_guardian(self, api_key):
        """测试The Guardian（官方、免费需Token）⭐⭐⭐⭐"""
        print("\n[5] 测试 The Guardian...")
        print("    官方平台: theguardian.com")
        print("    是否免费: ✅ 每天12,000次")
        print("    需要Token: ✅ 需要（免费注册）")
        print("    接口: https://content.guardianapis.com/search")

        if api_key == "your_key_here":
            print("⊘ 跳过（未配置API Key）")
            print("    申请地址: https://open-platform.theguardian.com/")
            self.results["guardian"] = {"status": "skipped", "reason": "未配置API Key"}
            return

        try:
            url = "https://content.guardianapis.com/search"
            params = {"q": "technology", "api-key": api_key, "page-size": 3}

            start_time = datetime.now()
            response = requests.get(url, params=params, timeout=10)
            elapsed = (datetime.now() - start_time).total_seconds()

            data = response.json()
            results = data["response"]["results"]

            print(f"✓ 成功 (耗时: {elapsed:.2f}s)")
            print(f"  总文章数: {data['response']['total']}")
            print(f"\n  前3篇文章:")

            for i, article in enumerate(results, 1):
                print(f"  {i}. {article['webTitle'][:60]}...")
                print(f"     版块: {article['sectionName']}")

            self.results["guardian"] = {
                "status": "success",
                "source": "官方API",
                "token_required": True,
            }

        except Exception as e:
            print(f"✗ 失败: {e}")
            self.results["guardian"] = {"status": "failed", "error": str(e)}

    def generate_report(self):
        """生成测试报告"""
        print("\n" + "=" * 60)
        print("测试报告汇总")
        print("=" * 60)

        # 按优先级排序
        priority_order = [
            "hackernews",
            "reddit",
            "worldnews",
            "alphavantage",
            "guardian",
        ]

        for api_name in priority_order:
            if api_name not in self.results:
                continue

            result = self.results[api_name]
            status = result["status"]

            icon = {"success": "✓", "failed": "✗", "skipped": "⊘"}.get(status, "?")

            source = result.get("source", "未知")
            token = result.get("token_required", False)
            token_text = "需Token" if token else "无Token"

            print(f"{icon} {api_name:15s} - {status:8s} | {source:10s} | {token_text}")

        # 统计
        success_count = sum(
            1 for r in self.results.values() if r["status"] == "success"
        )
        total_count = len(self.results)

        print(
            f"\n成功率: {success_count}/{total_count} ({success_count / total_count * 100:.1f}%)"
        )

        # 推荐总结
        print("\n推荐方案:")
        print("  方案A（完全免费）: Hacker News + Reddit + stock-mcp")
        print("  方案B（官方平台）: World News + Alpha Vantage + Guardian")
        print("  方案C（混合）: Hacker News + Reddit + World News + stock-mcp")

        print("=" * 60)


def main():
    tester = APITester()

    tester.print_header("免费数据源API综合测试 v2.0")
    print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("优先级: 官方平台 > 无Token > 开源项目")

    # 读取环境变量
    worldnews_key = os.getenv("WORLD_NEWS_API_KEY", "your_key_here")
    alphavantage_key = os.getenv("ALPHA_VANTAGE_KEY", "your_key_here")
    guardian_key = os.getenv("GUARDIAN_API_KEY", "your_key_here")

    # 执行测试（按优先级）
    # 第一优先级：官方免费无Token
    tester.test_hackernews()
    tester.test_reddit_json()

    # 第二优先级：官方免费需Token
    tester.test_worldnews(worldnews_key)
    tester.test_alpha_vantage(alphavantage_key)
    tester.test_guardian(guardian_key)

    # 生成报告
    tester.generate_report()

    print("\n提示:")
    print("1. 未配置API Key的测试已跳过")
    print("2. 申请地址已在测试中显示")
    print("3. 详细文档请查看: 免费数据源API与MCP工具集成文档.md")


if __name__ == "__main__":
    main()
