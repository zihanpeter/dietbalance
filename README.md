# FoodQuery

一个用 Flask 搭建的食品营养查询网页。输入食品名称（支持中文和英文），显示每 100 克 / 毫升的营养成分。

## 数据源

1. **USDA FoodData Central** — 主数据源。美国农业部官方营养数据库，覆盖原始食材与生鲜（香蕉、苹果、生鸡蛋、米饭等）。
2. **Open Food Facts** — 备用数据源。全球包装食品数据库（可乐、巧克力、饼干等品牌商品）。

输入中文食品名时，会自动通过内置字典映射到英文关键词去查 USDA，若查不到再回落到 Open Food Facts。

## 环境要求

- Python 3.13+（Windows 通过 `py` 启动器）

## 快速开始

### 1. 激活虚拟环境（Windows PowerShell）

```powershell
.\.venv\Scripts\Activate.ps1
```

如遇执行策略错误：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

### 2. 安装依赖

```powershell
pip install -r requirements.txt
```

### 3. （可选）配置 USDA API Key

默认使用 `DEMO_KEY`，限额 30 次/IP/小时。若频繁使用，建议在 [USDA 官网](https://fdc.nal.usda.gov/api-key-signup) 免费申请一个 API Key，然后设置环境变量：

```powershell
$env:USDA_API_KEY = "你的KEY"
```

### 4. 运行（开发模式）

```powershell
python app.py
```

浏览器打开 <http://127.0.0.1:5000/>，输入 `香蕉`、`苹果`、`米饭`、`鸡胸肉`、`coca-cola` 等试试。

### 5. 本地以生产方式运行

Windows（waitress）：

```powershell
.\.venv\Scripts\waitress-serve.exe --listen=127.0.0.1:8000 wsgi:app
```

Linux / macOS（gunicorn）：

```bash
gunicorn -c gunicorn.conf.py wsgi:app
```

## 生产部署

详见 [DEPLOYMENT.md](./DEPLOYMENT.md)。最快路径：

```bash
docker compose up -d --build
```

## 项目结构

```
FoodQuery/
├── .venv/                      # 虚拟环境（不入库）
├── app.py                      # Flask 入口（本地开发）
├── wsgi.py                     # 生产 WSGI 入口
├── gunicorn.conf.py            # Gunicorn 配置
├── Dockerfile                  # 容器构建
├── docker-compose.yml          # 一键启动
├── Procfile                    # PaaS (Render/Fly.io) 启动
├── .env.example                # 环境变量样例
├── food_api.py                 # 搜索编排器（统一对外）
├── sources/
│   ├── models.py               # FoodItem / NutritionFact 数据模型
│   ├── translate.py            # 中 → 英 食物名映射
│   ├── usda.py                 # USDA FoodData Central 客户端
│   └── openfoodfacts.py        # Open Food Facts 客户端
├── templates/
│   └── index.html              # 搜索页 + 结果列表
├── static/
│   └── styles.css              # 样式
├── requirements.txt
└── README.md
```
