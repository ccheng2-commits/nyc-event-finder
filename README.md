# NYC Event Finder 🗽

自动搜索纽约市的活动并每周发送邮件通知。

## 功能

- 通过 Eventbrite API 搜索活动
- 支持多个关键词搜索（tech, startup, design, networking, creative）
- 每周一早上 9:00 AM (EST) 自动运行
- 通过邮件发送活动列表

## 设置

### 1. Fork 这个仓库

### 2. 配置 GitHub Secrets

在仓库的 Settings > Secrets and variables > Actions 中添加：

| Secret | 说明 |
|--------|------|
| `EVENTBRITE_TOKEN` | Eventbrite API token |
| `SMTP_USER` | Gmail 邮箱地址 |
| `SMTP_PASSWORD` | Gmail App Password |
| `EMAIL_RECIPIENT` | 接收邮件的地址（可选，默认使用 SMTP_USER） |

### 3. 获取 Gmail App Password

1. 开启 Google 账户的两步验证
2. 前往 https://myaccount.google.com/apppasswords
3. 生成一个 App Password 用于此项目

## 本地测试

```bash
# 设置环境变量
export EVENTBRITE_TOKEN="your_token"

# 运行
python event_finder.py
```

## 自定义

编辑 `event_finder.py` 中的配置：

```python
LOCATION = "New York"  # 搜索地点
SEARCH_KEYWORDS = ["tech", "startup", "design"]  # 关键词
DAYS_AHEAD = 14  # 搜索未来多少天
```
