# 开发者模式与菜单配置（进阶方案）

目标：
- 菜单“今日前瞻”使用点击事件，服务器动态返回“最新一篇”链接

一、服务器
- 启动：uvicorn src.wechat.server:app --host 0.0.0.0 --port 8000
- 环境变量：WECHAT_TOKEN，ADMIN_TOKEN
- 更新最新文章：POST /wx/latest，Header: X-Admin-Token，Body: {"title": "...", "url": "..."}

二、公众号后台
- 设置与开发 → 基本配置 → 开发者模式
  - 服务器地址URL：http(s)://你的域名/wx
  - Token：与 WECHAT_TOKEN 一致
  - EncodingAESKey：选择明文或兼容模式
- 自定义菜单
  - 类型：点击事件
  - 菜单名称：今日前瞻
  - Key：LATEST_TODAY

三、使用
- 每次发布完成后，获取长链接并调用 /wx/latest 设置最新文章的标题与链接
- 用户点击菜单时，服务器返回文本消息，内容包含“今日前瞻标题 + 链接”

四、验证
- 微信后台保存后，点击“启用”，用管理员微信测试菜单点击是否收到最新链接

