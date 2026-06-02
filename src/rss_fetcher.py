"""
RSS Feed 获取模块
"""
import feedparser
import requests
from typing import Any, List, Dict
import re


class RSSFetcher:
    """RSS 订阅源获取器"""

    def __init__(self, base_url: str, feed_path: str):
        """
        初始化 RSS 获取器

        Args:
            base_url: RSSHub 基础 URL
            feed_path: Feed 路径
        """
        self.base_url = base_url.rstrip('/')
        self.feed_path = feed_path
        self.full_url = f"{self.base_url}{self.feed_path}"

    def fetch(self) -> List[Dict]:
        """
        获取 RSS Feed 内容

        Returns:
            包含新闻条目的列表
        """
        try:
            print(f"正在获取 RSS Feed: {self.full_url}")

            # 使用 requests 获取内容，设置超时和请求头
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(self.full_url, headers=headers, timeout=30)
            response.raise_for_status()

            # 解析 RSS
            feed = feedparser.parse(response.content)

            if feed.bozo:
                print(f"警告: RSS 解析可能存在问题")

            items = []
            for entry in feed.entries:
                item = {
                    'title': entry.get('title', '无标题'),
                    'link': entry.get('link', ''),
                    'description': self._clean_description(
                        self._coerce_to_text(entry.get('description', entry.get('summary', '')))
                    ),
                    'pub_date': entry.get('published', ''),
                    'author': entry.get('author', '未知')
                }
                items.append(item)

            print(f"✓ 成功获取 {len(items)} 条新闻")
            return items

        except requests.RequestException as e:
            print(f"❌ 网络请求失败: {e}")
            raise
        except Exception as e:
            print(f"❌ RSS 解析失败: {e}")
            raise

    def fetch_top_items(self, limit: int = 10) -> List[Dict]:
        """
        获取前 N 条新闻

        Args:
            limit: 返回的最大条目数

        Returns:
            新闻条目列表
        """
        items = self.fetch()
        return items[:limit]

    def _clean_description(self, html: str) -> str:
        """
        清理描述文本，移除 HTML 标签

        Args:
            html: 包含 HTML 的文本

        Returns:
            清理后的纯文本
        """
        # 移除 HTML 标签
        text = re.sub(r'<[^>]+>', '', html)

        # 替换 HTML 实体
        text = text.replace('&nbsp;', ' ')
        text = text.replace('&quot;', '"')
        text = text.replace('&amp;', '&')
        text = text.replace('&lt;', '<')
        text = text.replace('&gt;', '>')

        # 清理多余空白
        text = ' '.join(text.split())

        # 限制长度
        return text[:500]

    def _coerce_to_text(self, value: Any) -> str:
        """Convert feedparser values into plain text for downstream processing."""
        if value is None:
            return ''
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return ' '.join(self._coerce_to_text(item) for item in value)
        return str(value)


if __name__ == '__main__':
    # 测试代码
    fetcher = RSSFetcher(
        base_url='https://rsshub.app',
        feed_path='/github/trending/daily/any'
    )

    items = fetcher.fetch_top_items(5)
    for i, item in enumerate(items, 1):
        print(f"\n{i}. {item['title']}")
        print(f"   链接: {item['link']}")
        print(f"   描述: {item['description'][:100]}...")
