# Python 服务模块

本目录包含智抢（chrome-redirect）扩展配套的 Python 服务，用于验证码识别。

## 目录结构

```
python/
├── README.md                   # 本文件
├── .gitignore
├── venv/                       # Python 虚拟环境（本地，不提交）
└── captcha/                    # 本地点选验证码识别服务
    ├── ddddocr_server.py       #   macOS 版
    ├── ddddocr_server_win.py   #   Windows / Linux 版
    ├── requirements.txt        #   Python 依赖
    └── readme.md               #   captcha 子模块文档
```

## 快速开始

### 1. 创建虚拟环境

```bash
cd python
python3 -m venv venv
source venv/bin/activate
```

### 2. 安装依赖

```bash
pip install -r captcha/requirements.txt
```

### 3. 启动验证码服务

```bash
# macOS
python captcha/ddddocr_server.py  --host 0.0.0.0 

# Windows / Linux
python captcha/ddddocr_server_win.py  --host 0.0.0.0 
```

默认监听 `http://{你的ip}:9898`。

访问 `http://{你的ip}:9898/health`看是否运行成功。

### 4. 扩展中配置

打开智抢扩展弹窗 → **运行配置** → 开启"自动点击验证码" → 平台选择 **本地OCR** → 地址填：

```
http://{{你的ip}}:9898/click
```

> **注意**：若使用 `https://`，扩展会自动通过 `declarativeNetRequest` 规则降级为 HTTP，无需额外配置。

## 验证码识别服务

基于 [ddddocr](https://github.com/sml2h3/ddddocr) 的高准确率本地点选验证码识别服务。
