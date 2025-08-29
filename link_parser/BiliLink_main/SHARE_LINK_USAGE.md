# BiliLink - B站分享链接解析工具

## 新增功能说明

本项目已增强支持B站分享链接解析，可以直接处理各种格式的B站分享链接并返回可访问的公网视频链接。

### 新增API端点

#### 1. 分享链接解析端点
**GET** `/share/?url={分享链接}`

返回解析后的视频信息，包含公网可访问链接。

**示例请求:**
```
GET /share/?url=https://www.bilibili.com/video/BV1234567890?p=2&t=30
```

**示例响应:**
```json
{
  "success": true,
  "data": {
    "bvid": "BV1234567890",
    "page": 2,
    "public_url": "https://upos-sz-mirrorcos.bilivideo.com/...",
    "time": 30
  },
  "message": "解析成功"
}
```

#### 2. 直接重定向端点
**GET** `/parse/?url={分享链接}`

直接重定向到视频播放链接，无需处理JSON响应。

**示例请求:**
```
GET /parse/?url=https://www.bilibili.com/video/BV1234567890
```

**响应:** 302重定向到视频播放链接

### 支持的分享链接格式

1. **标准链接:** `https://www.bilibili.com/video/BVxxxxxxxxxx`
2. **手机端链接:** `https://m.bilibili.com/video/BVxxxxxxxxxx`
3. **短链接:** `https://b23.tv/xxxxxxx` (自动解析)
4. **带参数链接:** 
   - `?p=2` - 指定分P页面
   - `?t=30` - 指定开始时间（秒）

### 使用方法

#### 方法1: 获取详细信息（推荐）
```bash
curl "http://localhost:5000/share/?url=https://www.bilibili.com/video/BV1234567890"
```

#### 方法2: 直接重定向
```bash
curl -L "http://localhost:5000/parse/?url=https://www.bilibili.com/video/BV1234567890"
```

#### 方法3: 在浏览器中使用
直接访问: `http://localhost:5000/parse/?url=你的B站分享链接`

### 新增函数说明

#### `parse_bilibili_share_link(share_url: str)`
解析B站分享链接，提取BVID和参数信息。

**参数:**
- `share_url`: B站分享链接

**返回:**
```python
{
    'bvid': 'BV1234567890',
    'page': 1,
    'time': 0
}
```

#### `get_video_public_url(share_url: str)`
从分享链接获取完整的视频信息和公网访问链接。

**参数:**
- `share_url`: B站分享链接

**返回:**
```python
{
    'bvid': 'BV1234567890',
    'page': 1,
    'public_url': 'https://upos-sz-mirrorcos.bilivideo.com/...',
    'time': 0
}
```

### 特性

1. **自动CDN优化**: 自动选择最佳CDN节点
2. **完整参数支持**: 保留分P页面和时间参数
3. **短链接处理**: 自动展开b23.tv等短链接
4. **错误处理**: 完善的错误处理和日志记录
5. **限流保护**: 继承原有的10次/分钟限流机制

### 测试

运行测试脚本验证功能:
```bash
python test_share_parsing.py
```

### 注意事项

1. 需要有效的SESSDATA才能获取高清视频链接
2. 短链接解析需要网络连接
3. 返回的链接有时效性，建议及时使用
4. 遵守B站服务条款，合理使用API