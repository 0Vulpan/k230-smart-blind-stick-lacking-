#!/usr/bin/env python3
"""
智能盲杖跌倒检测系统 - 合并版
=================================
树莓派5 + MPU6050 + 蜂鸣器 + Flask + WebSocket实时推送 + Ngrok内网穿透

功能：
1. 跌倒检测：通过MPU6050计算倾斜角度判断跌倒状态
2. WebSocket服务：实时推送跌倒状态到网页
3. HTTP API：提供状态查询接口
4. 蜂鸣器报警：检测到跌倒时触发蜂鸣器
5. Ngrok穿透：实现远程访问，无需同一局域网

API接口：
- GET /status - 获取跌倒状态 {"is_fallen": true/false}
- GET /sensor - 获取传感器数据（角度）
- GET /history - 获取跌倒历史记录
- GET /reset - 重置蜂鸣器
- WebSocket /ws - 实时推送跌倒状态

远程访问：
- Ngrok地址：http://xxx.ngrok.io
"""

import smbus2
import time
import RPi.GPIO as GPIO
import math
import subprocess
import requests
from flask import Flask, jsonify, render_template_string
import threading

# ========== Flask配置 ==========
app = Flask(__name__)
app.config['SECRET_KEY'] = 'smart_cane_secret'

# ========== 跌倒检测配置 ==========
MPU6050_ADDR = 0x68
BUZZER_PIN = 17

FILTER_ALPHA = 0.2
ANGLE_THRESHOLD = 60  # 角度超过60度判定为跌倒
TIMEOUT_DURATION = 10  # 每10秒重置

# Ngrok配置
NGROK_ENABLED = True  # 是否启用ngrok穿透
NGROK_API_URL = "http://localhost:4040/api/tunnels"
NGROK_FIXED_DOMAIN = "decay-capitol-primary.ngrok-free.dev"  # 固定域名
NGROK_PUBLIC_URL = None  # 存储ngrok公网地址

# ========== 全局变量 ==========
bus = None
pitch = 0.0  # 俯仰角
roll = 0.0   # 横滚角
buzzer_state = False
last_reset_time = 0
is_fallen_state = False
fall_history = []  # 跌倒历史记录

# ========== 扫描I2C设备 ==========
def scan_i2c():
    """扫描I2C总线上的设备（快速模式）"""
    devices = []
    try:
        test_bus = smbus2.SMBus(1)
        # 快速扫描：只检测常见传感器地址
        common_addrs = [0x68, 0x69, 0x76, 0x77, 0x3C, 0x3D]
        for addr in common_addrs:
            try:
                test_bus.read_byte(addr)
                devices.append(hex(addr))
            except:
                pass
        test_bus.close()
    except Exception as e:
        print(f"✗ I2C扫描失败: {e}")
    return devices

# ========== 初始化传感器 ==========
def init_sensor():
    global bus, pitch, roll, MPU6050_ADDR
    
    print("正在检查I2C连接...")
    
    # 扫描I2C设备
    i2c_devices = scan_i2c()
    if not i2c_devices:
        print("✗ I2C总线上未检测到设备")
        print("  请检查：")
        print("  1. 是否启用I2C: sudo raspi-config → Interface Options → I2C")
        print("  2. 硬件接线是否正确 (SDA=GPIO2, SCL=GPIO3)")
        print("  3. 是否使用sudo运行")
        return False
    
    print(f"✓ I2C设备列表: {i2c_devices}")
    
    # 尝试常见的MPU6050地址
    possible_addrs = [0x68, 0x69]
    found_addr = None
    
    for addr in possible_addrs:
        if hex(addr) in i2c_devices:
            found_addr = addr
            break
    
    if found_addr:
        MPU6050_ADDR = found_addr
        print(f"✓ 发现MPU6050，地址: {hex(MPU6050_ADDR)}")
    else:
        print(f"✗ 未找到MPU6050，可能的地址: {[hex(a) for a in possible_addrs]}")
        print(f"  当前I2C设备: {i2c_devices}")
        return False
    
    try:
        bus = smbus2.SMBus(1)
        # 唤醒MPU6050（PWR_MGMT_1寄存器）
        bus.write_byte_data(MPU6050_ADDR, 0x6B, 0)
        time.sleep(0.1)
        
        # 验证通信
        who_am_i = bus.read_byte_data(MPU6050_ADDR, 0x75)
        if who_am_i != MPU6050_ADDR and who_am_i != 0x68:
            print(f"✗ MPU6050身份验证失败: {hex(who_am_i)}")
            return False
        
        print("✓ MPU6050 初始化成功")
    except Exception as e:
        print(f"✗ MPU6050失败: {e}")
        print("  可能原因:")
        print("  1. 传感器未正确连接")
        print("  2. I2C总线故障")
        print("  3. 传感器损坏")
        return False
    
    try:
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(BUZZER_PIN, GPIO.OUT)
        GPIO.output(BUZZER_PIN, GPIO.LOW)
        print("✓ 蜂鸣器初始化成功（低电平，不响）")
        
        # 蜂鸣器测试
        print("蜂鸣器测试...")
        time.sleep(0.5)
        GPIO.output(BUZZER_PIN, GPIO.HIGH)
        print("  现在应该响")
        time.sleep(0.5)
        GPIO.output(BUZZER_PIN, GPIO.LOW)
        print("  现在应该不响")
        print("✓ 蜂鸣器测试完成")
        
    except Exception as e:
        print(f"✗ GPIO失败: {e}")
        return False
    
    # 预热传感器
    print("正在预热传感器...")
    for i in range(100):
        ax, ay, az = read_acc()
        if ax != 0 or ay != 0 or az != 0:
            calculate_angle(ax, ay, az)
        time.sleep(0.01)
    print("✓ 传感器预热完成")
    
    return True

# ========== 传感器读取 ==========
def read_acc():
    try:
        raw = bus.read_i2c_block_data(MPU6050_ADDR, 0x3B, 6)
        ax = (raw[0] << 8) | raw[1]
        ay = (raw[2] << 8) | raw[3]
        az = (raw[4] << 8) | raw[5]
        
        def convert(val):
            return val / 16384.0 if val < 32768 else (val - 65536) / 16384.0
        
        return convert(ax), convert(ay), convert(az)
    except Exception as e:
        return 0, 0, 0

# ========== 计算角度 ==========
def calculate_angle(ax, ay, az):
    global pitch, roll
    EPSILON = 0.0001
    
    try:
        # 计算俯仰角 (pitch) - 绕X轴旋转
        denominator_pitch = math.sqrt(ax**2 + az**2)
        if denominator_pitch < EPSILON:
            denominator_pitch = EPSILON
        pitch_raw = math.atan2(ay, denominator_pitch) * (180 / math.pi)
        
        # 计算横滚角 (roll) - 绕Y轴旋转
        if abs(az) < EPSILON:
            az = EPSILON if az >= 0 else -EPSILON
        roll_raw = math.atan2(-ax, az) * (180 / math.pi)
        
        # 低通滤波
        pitch = FILTER_ALPHA * pitch_raw + (1 - FILTER_ALPHA) * pitch
        roll = FILTER_ALPHA * roll_raw + (1 - FILTER_ALPHA) * roll
        
    except Exception as e:
        print(f"✗ 角度计算错误: {e}")
    
    return pitch, roll

# ========== 判断跌倒 ==========
def is_fallen():
    """判断是否跌倒：角度超过阈值"""
    global pitch, roll
    return abs(pitch) >= ANGLE_THRESHOLD or abs(roll) >= ANGLE_THRESHOLD

# ========== 蜂鸣器控制 ==========
def buzzer_on():
    """蜂鸣器叫 - 设置高电平"""
    global buzzer_state
    if not buzzer_state:
        GPIO.output(BUZZER_PIN, GPIO.HIGH)
        buzzer_state = True
        print(f"[跌倒] 检测到异常姿态，蜂鸣器开启 (GPIO=HIGH)")

def buzzer_off():
    """蜂鸣器不叫 - 设置低电平"""
    global buzzer_state
    GPIO.output(BUZZER_PIN, GPIO.LOW)
    buzzer_state = False

# ========== Ngrok内网穿透 ==========
def start_ngrok():
    """启动ngrok内网穿透"""
    global NGROK_PUBLIC_URL
    
    if not NGROK_ENABLED:
        print("Ngrok穿透已禁用")
        return None
    
    try:
        print("正在启动Ngrok内网穿透...")
        
        # 检查ngrok是否已安装
        result = subprocess.run(['which', 'ngrok'], capture_output=True, text=True)
        if result.returncode != 0:
            print("✗ Ngrok未安装，正在下载...")
            subprocess.run([
                'wget', '-q', '-O', '/tmp/ngrok.zip',
                'https://bin.equinox.io/c/4VmDzA7iaHb/ngrok-stable-linux-arm.zip'
            ], check=True)
            subprocess.run(['unzip', '-q', '/tmp/ngrok.zip', '-d', '/usr/local/bin/'], check=True)
            subprocess.run(['chmod', '+x', '/usr/local/bin/ngrok'], check=True)
            print("✓ Ngrok安装完成")
        
        # 启动ngrok（后台运行）- 使用固定域名
        ngrok_cmd = ['ngrok', 'http', '8080', '--domain=' + NGROK_FIXED_DOMAIN]
        subprocess.Popen(ngrok_cmd, 
                        stdout=subprocess.DEVNULL, 
                        stderr=subprocess.DEVNULL)
        
        # 等待ngrok启动
        time.sleep(3)
        
        # 获取公网地址
        for i in range(5):
            try:
                response = requests.get(NGROK_API_URL, timeout=2)
                tunnels = response.json().get('tunnels', [])
                for tunnel in tunnels:
                    if tunnel.get('proto') == 'https':
                        NGROK_PUBLIC_URL = tunnel.get('public_url')
                        print(f"✓ Ngrok穿透成功！")
                        print(f"  公网地址: {NGROK_PUBLIC_URL}")
                        return NGROK_PUBLIC_URL
            except:
                time.sleep(2)
        
        print("✗ 无法获取Ngrok公网地址")
        return None
        
    except Exception as e:
        print(f"✗ Ngrok启动失败: {e}")
        return None

def get_public_url():
    """获取公网访问地址"""
    global NGROK_PUBLIC_URL
    return NGROK_PUBLIC_URL

# ========== HTTP API路由 ==========
@app.route('/')
def index():
    """主页 - 显示跌倒状态"""
    public_url = get_public_url()
    
    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>跌倒检测系统</title>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { font-family: Arial; min-height: 100vh; display: flex; flex-direction: column; align-items: center; justify-content: center; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 20px; }
            .container { width: 100%; max-width: 600px; }
            .status-card { background: white; border-radius: 20px; padding: 40px; text-align: center; box-shadow: 0 20px 60px rgba(0,0,0,0.3); transition: all 0.3s; }
            .status-card.normal { border: 5px solid #4CAF50; }
            .status-card.fallen { border: 5px solid #f44336; animation: shake 0.5s infinite; }
            @keyframes shake { 0%, 100% { transform: translateX(0); } 25% { transform: translateX(-10px); } 75% { transform: translateX(10px); } }
            .status-icon { font-size: 100px; margin-bottom: 20px; }
            .status-text { font-size: 36px; font-weight: bold; margin-bottom: 20px; }
            .normal .status-text { color: #4CAF50; }
            .fallen .status-text { color: #f44336; }
            .status-time { font-size: 16px; color: #666; margin-bottom: 20px; }
            .connection-status { display: inline-block; padding: 8px 16px; border-radius: 20px; font-size: 14px; margin-bottom: 20px; }
            .connected { background: #e8f5e9; color: #4CAF50; }
            .disconnected { background: #ffebee; color: #f44336; }
            .btn { padding: 15px 30px; border: none; border-radius: 10px; font-size: 18px; cursor: pointer; margin: 10px; }
            .btn-primary { background: #2196f3; color: white; }
            .btn-danger { background: #f44336; color: white; }
            .btn:hover { transform: scale(1.05); }
            .url-box { background: #e3f2fd; border: 2px solid #2196f3; border-radius: 10px; padding: 15px; margin: 15px 0; text-align: center; }
            .url-box h3 { color: #1565c0; margin-bottom: 10px; }
            .url-box a { color: #1976d2; font-size: 18px; font-weight: bold; word-break: break-all; }
            .url-box p { color: #666; font-size: 12px; margin-top: 8px; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="status-card normal" id="statusCard">
                <div class="status-icon" id="statusIcon">✅</div>
                <div class="status-text" id="statusText">正常</div>
                <div class="status-time" id="statusTime">--:--:--</div>
                <div class="connection-status disconnected" id="connectionStatus">🔴 未连接</div>
            </div>
            {% if public_url %}
            <div class="url-box">
                <h3>🌐 远程访问地址（可复制到手机浏览器）</h3>
                <a href="{{ public_url }}" target="_blank">{{ public_url }}</a>
                <p>此地址可在任何网络下访问，无需同一局域网</p>
            </div>
            {% else %}
            <div class="url-box" style="background: #fff3e0; border-color: #ff9800;">
                <h3>⚠️ Ngrok穿透未启动</h3>
                <p>仅限局域网访问，远程访问请配置Ngrok</p>
            </div>
            {% endif %}
            <div style="text-align: center; margin-top: 20px;">
                <button class="btn btn-danger" onclick="resetBuzzer()">🔕 关闭蜂鸣器</button>
            </div>
        </div>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
        <script>
            const socket = io();
            socket.on('connect', () => {
                document.getElementById('connectionStatus').className = 'connection-status connected';
                document.getElementById('connectionStatus').textContent = '🟢 已连接';
            });
            socket.on('disconnect', () => {
                document.getElementById('connectionStatus').className = 'connection-status disconnected';
                document.getElementById('connectionStatus').textContent = '🔴 连接断开';
            });
            socket.on('fall_status', function(data) {
                const statusCard = document.getElementById('statusCard');
                const statusIcon = document.getElementById('statusIcon');
                const statusText = document.getElementById('statusText');
                const statusTime = document.getElementById('statusTime');
                statusTime.textContent = data.timestamp;
                if (data.is_fallen) {
                    statusCard.className = 'status-card fallen';
                    statusIcon.textContent = '⚠️';
                    statusText.textContent = '跌倒';
                } else {
                    statusCard.className = 'status-card normal';
                    statusIcon.textContent = '✅';
                    statusText.textContent = '正常';
                }
            });
            function resetBuzzer() {
                fetch('/reset').then(res => res.json()).then(data => { if(data.success) alert('蜂鸣器已关闭'); });
            }
        </script>
    </body>
    </html>
    """, public_url=public_url)

@app.route('/status')
def get_status():
    """获取当前跌倒状态"""
    return jsonify({
        'is_fallen': is_fallen_state,
        'pitch': round(pitch, 2),
        'roll': round(roll, 2),
        'buzzer_on': buzzer_state,
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
    })

@app.route('/sensor')
def get_sensor():
    """获取传感器数据"""
    return jsonify({
        'pitch': round(pitch, 2),
        'roll': round(roll, 2),
        'angle_threshold': ANGLE_THRESHOLD,
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
    })

@app.route('/history')
def get_history():
    """获取跌倒历史记录"""
    return jsonify({
        'count': len(fall_history),
        'history': fall_history
    })

@app.route('/reset')
def reset_buzzer():
    """重置蜂鸣器"""
    buzzer_off()
    return jsonify({'success': True, 'message': '蜂鸣器已重置'})

# ========== 跌倒检测线程 ==========
def fall_detection_thread():
    global last_reset_time, is_fallen_state, pitch, roll
    
    last_reset_time = time.time()
    
    try:
        while True:
            ax, ay, az = read_acc()
            
            # 检查传感器数据有效性
            if ax == 0 and ay == 0 and az == 0:
                print("\r✗ 传感器数据无效，检查连接...", end="")
                time.sleep(0.1)
                continue
            
            calculate_angle(ax, ay, az)
            current_time = time.time()
            
            # 每10秒重置一次
            if (current_time - last_reset_time) >= TIMEOUT_DURATION:
                buzzer_off()
                print(f"\n[重置] 每{TIMEOUT_DURATION}秒重置，蜂鸣器关闭")
                last_reset_time = current_time
            
            # 判断跌倒状态
            if is_fallen():
                if not is_fallen_state:
                    is_fallen_state = True
                    buzzer_on()
                    # 记录跌倒时间
                    fall_time = time.strftime('%Y-%m-%d %H:%M:%S')
                    if len(fall_history) == 0 or fall_history[-1] != fall_time:
                        fall_history.append(fall_time)
                        if len(fall_history) > 100:
                            fall_history.pop(0)
                    print(f"[跌倒] 检测到跌倒！俯仰角: {pitch:.1f}°, 横滚角: {roll:.1f}°")
            else:
                if is_fallen_state:
                    is_fallen_state = False
                    buzzer_off()
                    print(f"[恢复] 已恢复正常")
            
            # 终端显示
            print(f"\r俯仰角: {pitch:>6.1f}° | 横滚角: {roll:>6.1f}° | 状态: {'跌倒' if is_fallen_state else '正常'}", end="")
            
            time.sleep(0.01)
    
    except Exception as e:
        print(f"\n检测线程异常: {e}")

# ========== 主程序 ==========
def main():
    global NGROK_PUBLIC_URL
    
    print("=" * 60)
    print("    智能盲杖 - 跌倒检测系统（合并版）")
    print("=" * 60)
    print("功能:")
    print("  1. 跌倒检测：通过MPU6050角度判断")
    print("  2. HTTP轮询：实时获取跌倒状态")
    print("  3. HTTP API：提供状态查询接口")
    print("  4. 蜂鸣器报警：跌倒时触发")
    print("  5. Ngrok穿透：远程访问支持")
    print(f"  - 角度阈值: {ANGLE_THRESHOLD}度")
    print(f"  - 重置间隔: {TIMEOUT_DURATION}秒")
    print("=" * 60)
    
    if not init_sensor():
        return
    
    # 启动跌倒检测线程
    detection_thread = threading.Thread(target=fall_detection_thread, daemon=True)
    detection_thread.start()
    
    # 启动Ngrok内网穿透
    public_url = start_ngrok()
    
    print("\n系统运行中...")
    print(f"局域网访问: http://192.168.1.119:8080")
    if public_url:
        print(f"🌐 远程访问: {public_url}")
    else:
        print("⚠️ Ngrok穿透未启动，远程访问不可用")
    print("按 Ctrl+C 退出\n")
    
    # 启动Flask服务
    try:
        app.run(host='0.0.0.0', port=8080, debug=False)
    except KeyboardInterrupt:
        print("\n\n用户退出")
    finally:
        buzzer_off()
        GPIO.cleanup()
        print("GPIO已清理")

if __name__ == "__main__":
    main()