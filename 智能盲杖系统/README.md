# 智能盲杖系统

## 📁 项目结构

```
智能盲杖系统/
├── 智能盲杖.html          # 主前端页面（包含跌倒状态显示）
├── 跌倒检测.py            # 树莓派跌倒检测服务（支持Ngrok穿透）
├── server.js              # Node.js后端服务
├── package.json           # Node.js依赖配置
└── README.md              # 项目说明文档
```

## 🚀 快速开始

### 1. 启动Node.js后端服务（可选）

```bash
cd 智能盲杖系统
npm install
npm start
```

### 2. 启动跌倒检测服务（树莓派）

```bash
cd 智能盲杖系统
pip install flask flask-socketio smbus2 RPi.GPIO requests
sudo python3 跌倒检测.py
```

### 3. 打开前端页面

直接用浏览器打开 `智能盲杖.html` 文件。

## 🌐 访问地址

### 局域网访问
- 跌倒检测服务: http://192.168.1.119:8080
- WebSocket: ws://192.168.1.119:8080/ws

### 远程访问（Ngrok穿透）
运行 `跌倒检测.py` 后，会自动启动Ngrok穿透，生成公网地址：
```
🌐 远程访问: https://xxx.ngrok.io
```
此地址可在**任何网络**下访问，无需同一局域网。

## 📱 功能

1. **📍 实时定位** - GPS定位，地图跟随
2. **🗺️ 路线导航** - 百度地图路线规划
3. **⚠️ 跌倒检测** - 实时推送跌倒状态
4. **👥 紧急联系人** - 管理默认联系人
5. **🗑️ 数据管理** - 清除/导出数据

## 🔌 硬件连接

树莓派连接：
- MPU6050 → I2C接口（SDA, SCL）
- 蜂鸣器 → GPIO17

## 📝 跌倒检测API接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 显示跌倒状态页面（含Ngrok地址） |
| `/status` | GET | 获取跌倒状态 |
| `/sensor` | GET | 获取传感器数据 |
| `/history` | GET | 获取跌倒历史 |
| `/reset` | GET | 重置蜂鸣器 |
| `/ws` | WebSocket | 实时推送跌倒状态 |

## 🌐 Ngrok远程访问配置

### 自动配置（推荐）
程序会自动下载并启动Ngrok，无需手动配置。

### 手动配置Ngrok（可选）

1. **注册Ngrok账号**：https://ngrok.com
2. **获取Authtoken**
3. **配置Token**：
   ```bash
   ngrok config add-authtoken YOUR_TOKEN
   ```

### 配置前端连接地址

1. 打开网页，点击底部的"⚠️ 预警"按钮
2. 点击"⚙️ 配置服务器地址"
3. 输入Ngrok生成的公网地址，例如：
   ```
   https://abc123.ngrok.io
   ```
4. 点击确定，刷新页面

## 📊 跌倒状态显示

在网页底部导航栏点击"预警"按钮，进入跌倒检测页面：
- ✅ 正常 - 绿色界面
- ⚠️ 跌倒 - 红色界面 + 警报提示

跌倒时自动触发紧急求助，获取位置并通知联系人。

## 🛠️ 技术栈

- 前端: HTML5 + CSS3 + JavaScript
- 地图: 百度地图API
- 后端: Node.js + Express / Python Flask-SocketIO
- 跌倒检测: Python + Flask-SocketIO + Ngrok

## 🔧 默认账号

用户名: admin
密码: 123456

## ⚠️ 注意事项

1. **Ngrok免费版限制**：
   - 每次重启后会生成新地址
   - 需要注册账号获取Authtoken才能长期使用

2. **稳定性**：
   - 远程访问依赖网络稳定性
   - 建议长期使用部署到云服务器

3. **安全性**：
   - Ngrok地址是公开的，建议添加认证
   - 可考虑使用付费版Ngrok的Basic Auth功能

## 📞 联系方式

如有问题，请查看代码注释或联系开发者。