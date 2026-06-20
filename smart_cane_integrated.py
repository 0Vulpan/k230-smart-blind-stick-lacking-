#!/usr/bin/env python3
# coding=utf-8
"""
智能盲杖综合检测系统 - 融合版
=================================
树莓派5 + YOLO目标检测 + MPU6050跌倒检测 + 串口通信 + Flask Web服务

功能融合：
1. YOLO目标检测：USB摄像头实时检测（person/vehicle/animal/stairs/bicycle/pole）
2. 跌倒检测：MPU6050陀螺仪角度检测
3. 串口通信：发送检测结果给天问51单片机
4. Flask Web服务：远程状态监控

API接口：
- GET /status - 获取系统状态
- GET /sensor - 获取陀螺仪数据
- GET /detection - 获取目标检测结果
"""

import os
#os.environ["QT_QPA_PLATFORM"] = "xcb"
#os.environ["QT_LOGGING_RULES"] = "qt.qpa.fonts=false;qt.qpa.plugin=false"

import cv2
import serial
import time
import smbus2
import math
import threading
from flask import Flask, jsonify, render_template_string
from ultralytics import YOLO

# ==================== 配置参数 ====================
# YOLO模型配置
MODEL_PT = "/home/admin/Desktop/best.pt"
CONF_THRESH = 0.3
CAM_ID = 0

# 串口配置
SERIAL_PORT = "/dev/ttyUSB0"
BAUD = 9600

# 跌倒检测配置
MPU6050_ADDR = 0x68
FILTER_ALPHA = 0.2
ANGLE_THRESHOLD = 60
TIMEOUT_DURATION = 10

# K230通信配置
K230_SERIAL_PORT = "/dev/serial0"  # K230连接的串口
K230_BAUD = 9600
k1_value = 0  # K230传递的k1值
k2_value = 0  # K230传递的k2值
k230_received = False  # 是否已接收到K230数据

# Flask配置
FLASK_PORT = 8080

# 类别名称映射
CLASS_NAMES = {
    0: "person",    # 行人
    1: "vehicle",   # 车辆
    2: "animal",    # 动物
    3: "stairs",    # 楼梯
    4: "bicycle",   # 自行车
    5: "pole"       # 杆子
}

# 类别播报内容
CLASS_VOICE = {
    0: "行人",
    1: "车辆",
    2: "动物",
    3: "楼梯",
    4: "自行车",
    5: "杆子"
}

# ==================== Flask应用 ====================
app = Flask(__name__)
app.config['SECRET_KEY'] = 'smart_cane_secret'

# ==================== 全局变量 ====================
# 跌倒检测变量
bus = None
pitch = 0.0
roll = 0.0
last_reset_time = 0
is_fallen_state = False
fall_history = []

# 目标检测变量
detected_class = -1
detected_class_name = "无"
detection_conf = 0.0
detection_count = 0
last_detection_time = 0

# 串口
serial_comm = None

# ==================== K230通信类 ====================
class K230Comm:
    """K230串口通信类 - 分别接收k1（盲道）和k2（斑马线），各只接收一次"""
    def __init__(self):
        self.ser = None
        self.k1 = 0          # 盲道检测值
        self.k2 = 0          # 斑马线检测值
        self.k1_received = False  # 是否已接收到k1（盲道）
        self.k2_received = False  # 是否已接收到k2（斑马线）
        self.receive_timeout = 60  # 等待接收超时时间（秒）
        # K230单独发送k1或k2时，可能的形式:
        # "k1 5" - 盲道识别结果
        # "k2 3" - 斑马线识别结果
        # "k1 5\nk2 3" - 一次发送两个
        # "5" - 只发送数值（轮流发送k1/k2，顺序按K230端定义）
        
    def try_connect(self):
        """尝试连接K230串口"""
        ports = ['/dev/serial0','/dev/ttyUSB1', '/dev/ttyUSB0', '/dev/ttyACM0', '/dev/ttyACM1']
        
        for port in ports:
            try:
                self.ser = serial.Serial(port, K230_BAUD, timeout=1)
                print(f"K230串口连接成功: {port}")
                return True
            except:
                continue
        
        print("警告: 无法连接K230串口，将使用默认值k1=0, k2=0")
        return False
    
    def receive_k_values(self):
        """
        接收K230的k1和k2值
        - K230检测到盲道时发送k1
        - K230检测到斑马线时发送k2
        - 只接收第一次的k1和第一次的k2，后续重复数据全部忽略
        """
        if not self.ser:
            print("K230串口未连接，使用默认值k1=0, k2=0")
            return False
        
        print("等待接收K230数据（k1盲道+k2斑马线，各只接收一次）...")
        print("=" * 50)
        print("  协议说明：")
        print("  - K230检测到盲道时发送: k1")
        print("  - K230检测到斑马线时发送: k2")
        print("  - 仅接收第一次的k1和k2，后续重复数据将被忽略")
        print("=" * 50)
        
        start_time = time.time()
        data_count = 0
        buffer = ""
        
        try:
            while (time.time() - start_time) < self.receive_timeout:
                # 两个都收到就退出
                if self.k1_received and self.k2_received:
                    print(f"\n[K230] k1和k2都已接收完成（共{data_count}次），停止接收")
                    break
                
                try:
                    if self.ser.in_waiting > 0:
                        # 读取所有可用数据
                        raw_data = self.ser.read(self.ser.in_waiting).decode('utf-8', errors='ignore')
                        buffer += raw_data
                        print(f"[K230] 原始数据: '{raw_data.strip()}'")
                        
                        # 按行处理数据
                        while '\n' in buffer or '\r' in buffer:
                            # 提取一行
                            if '\n' in buffer:
                                line, buffer = buffer.split('\n', 1)
                            else:
                                line, buffer = buffer.split('\r', 1)
                            
                            line = line.strip()
                            if not line:
                                continue
                            
                            # 解析数据
                            parsed = self._parse_line(line)
                            if parsed:
                                key, value = parsed
                                if key == 'k1' and not self.k1_received:
                                    self.k1 = value
                                    self.k1_received = True
                                    data_count += 1
                                    print(f"[K230] ✓ 收到 k1={value} (盲道检测)")
                                    if serial_comm and serial_comm.ser and serial_comm.ser.is_open:
                                            serial_comm.ser.write(b'k1')
                                            serial_comm.last_send = time.time()
                                elif key == 'k2' and not self.k2_received:
                                    self.k2 = value
                                    self.k2_received = True
                                    data_count += 1
                                    print(f"[K230] ✓ 收到 k2={value} (斑马线检测)")
                                    if serial_comm and serial_comm.ser and serial_comm.ser.is_open:
                                        serial_comm.ser.write(b'k2')
                                        serial_comm.last_send = time.time()
                                
                                if self.k1_received and self.k2_received:
                                    break
                    else:
                        # 显示等待状态
                        elapsed = int(time.time() - start_time)
                        if elapsed > 0 and elapsed % 10 == 0:
                            remaining = self.receive_timeout - elapsed
                            status_k1 = "✓" if self.k1_received else "等待中"
                            status_k2 = "✓" if self.k2_received else "等待中"
                            print(f"\r[K230] 状态: k1={status_k1}, k2={status_k2}, 剩余时间 {remaining}秒", end="", flush=True)
                
                except Exception as e:
                    print(f"\n[K230] 接收错误: {e}")
                
                time.sleep(0.01)
        
        finally:
            # 关闭串口
            if self.ser and self.ser.is_open:
                self.ser.close()
                self.ser = None
                print("\n[K230] 串口已关闭")
        
        # 显示最终状态
        print(f"\n[K230] 接收结果: k1={self.k1} ({'已接收' if self.k1_received else '未接收'}), k2={self.k2} ({'已接收' if self.k2_received else '未接收'})")
        
        return self.k1_received and self.k2_received
    
    def _parse_line(self, line):
        """解析一行数据 - K230只发送k1或k2，无后缀"""
        line = line.strip()
        if not line:
            return None
        
        # K230发送格式：只有 "k1" 或 "k2"，无后缀
        # 只关心第一次的k1和第一次的k2
        line_lower = line.lower()
        if line_lower == 'k1':
            return ('k1', 1)  # 盲道检测
        elif line_lower == 'k2':
            return ('k2', 1)  # 斑马线检测
        
        return None
    
    def close(self):
        if self.ser:
            self.ser.close()
            self.ser = None

# ==================== 串口通信类 ====================
class SerialComm:
    def __init__(self):
        self.ser = None
        self.last_send = 0
        self.intv = 1.0
        try:
            self.ser = serial.Serial(SERIAL_PORT, BAUD, timeout=1)
            print(f"串口已连接 {SERIAL_PORT}")
        except Exception as e:
            print(f"串口打开失败: {e}")
    
    def send_id(self, cid):
        print(f"[调试] send_id被调用，cid={cid}, serial_comm={serial_comm is not None}")
        if not (self.ser and self.ser.is_open):
            print(f"[错误] 串口未打开! ser={self.ser}, is_open={self.ser.is_open if self.ser else 'N/A'}")
            return False
        try:
            data = str(cid).encode("utf-8")
            self.ser.write(data)
            self.ser.flush()
            self.last_send = time.time()
            print(f"[串口] 发送类别ID: {cid} ({CLASS_VOICE.get(cid, '未知')}), 数据: {data}")
            return True
        except Exception as e:
            print(f"串口发送失败: {e}")
            return False
    
    def close(self):
        if self.ser:
            self.ser.close()

# ==================== I2C/陀螺仪函数 ====================
def scan_i2c():
    """扫描I2C总线"""
    devices = []
    try:
        test_bus = smbus2.SMBus(1)
        common_addrs = [0x68, 0x69, 0x76, 0x77]
        for addr in common_addrs:
            try:
                test_bus.read_byte(addr)
                devices.append(hex(addr))
            except:
                pass
        test_bus.close()
    except Exception as e:
        print(f"I2C扫描失败: {e}")
    return devices

def init_sensor():
    global bus, pitch, roll, MPU6050_ADDR
    
    print("正在检查I2C连接...")
    i2c_devices = scan_i2c()
    
    if not i2c_devices:
        print("警告: I2C总线上未检测到设备，陀螺仪功能不可用")
        return False
    
    print(f"I2C设备列表: {i2c_devices}")
    
    possible_addrs = [0x68, 0x69]
    found_addr = None
    for addr in possible_addrs:
        if hex(addr) in i2c_devices:
            found_addr = addr
            break
    
    if not found_addr:
        print("警告: 未找到MPU6050，陀螺仪功能不可用")
        return False
    
    MPU6050_ADDR = found_addr
    
    try:
        bus = smbus2.SMBus(1)
        bus.write_byte_data(MPU6050_ADDR, 0x6B, 0)
        time.sleep(0.1)
        print("MPU6050 初始化成功")
        
        # 预热
        for i in range(100):
            ax, ay, az = read_acc()
            if ax != 0 or ay != 0 or az != 0:
                calculate_angle(ax, ay, az)
            time.sleep(0.01)
        print("传感器预热完成")
        return True
        
    except Exception as e:
        print(f"传感器初始化失败: {e}")
        return False

def read_acc():
    try:
        raw = bus.read_i2c_block_data(MPU6050_ADDR, 0x3B, 6)
        ax = (raw[0] << 8) | raw[1]
        ay = (raw[2] << 8) | raw[3]
        az = (raw[4] << 8) | raw[5]
        
        def convert(val):
            return val / 16384.0 if val < 32768 else (val - 65536) / 16384.0
        
        return convert(ax), convert(ay), convert(az)
    except:
        return 0, 0, 0

def calculate_angle(ax, ay, az):
    global pitch, roll
    EPSILON = 0.0001
    
    try:
        denominator_pitch = math.sqrt(ax**2 + az**2)
        if denominator_pitch < EPSILON:
            denominator_pitch = EPSILON
        pitch_raw = math.atan2(ay, denominator_pitch) * (180 / math.pi)
        
        if abs(az) < EPSILON:
            az = EPSILON if az >= 0 else -EPSILON
        roll_raw = math.atan2(-ax, az) * (180 / math.pi)
        
        pitch = FILTER_ALPHA * pitch_raw + (1 - FILTER_ALPHA) * pitch
        roll = FILTER_ALPHA * roll_raw + (1 - FILTER_ALPHA) * roll
    except:
        pass

def is_fallen():
    """判断是否跌倒"""
    return abs(pitch) >= ANGLE_THRESHOLD or abs(roll) >= ANGLE_THRESHOLD

# ==================== 跌倒检测线程 ====================
def fall_detection_thread():
    global last_reset_time, is_fallen_state, pitch, roll
    
    last_reset_time = time.time()
    
    while True:
        ax, ay, az = read_acc()
        
        if ax == 0 and ay == 0 and az == 0:
            time.sleep(0.1)
            continue
        
        calculate_angle(ax, ay, az)
        current_time = time.time()
        
        # 每10秒重置状态
        if (current_time - last_reset_time) >= TIMEOUT_DURATION:
            last_reset_time = current_time
        
        # 判断跌倒
        if is_fallen():
            if not is_fallen_state:
                is_fallen_state = True
                print(f"[跌倒] 检测到跌倒！俯仰角: {pitch:.1f}°, 横滚角: {roll:.1f}°")
                if serial_comm and serial_comm.ser and serial_comm.ser.is_open:
                    serial_comm.ser.write(b'd')
                fall_time = time.strftime('%Y-%m-%d %H:%M:%S')
                if len(fall_history) == 0 or fall_history[-1] != fall_time:
                    fall_history.append(fall_time)
                    if len(fall_history) > 100:
                        fall_history.pop(0)
        else:
            if is_fallen_state:
                is_fallen_state = False
                print(f"[恢复] 已恢复正常")
        
        print(f"\r[陀螺仪] 俯仰角: {pitch:>6.1f}° | 横滚角: {roll:>6.1f}° | 状态: {'跌倒!' if is_fallen_state else '正常'}", end="")
        
        time.sleep(0.01)

# ==================== 目标检测线程 ====================
def detection_thread_func(model, cap):
    global detected_class, detected_class_name, detection_conf, detection_count, last_detection_time
    send_gap = 2.0
    last_tx = 0.0
    while True:
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.1)
            continue
        res = model(frame, conf=CONF_THRESH)[0]
        boxes = res.boxes
        obj_num = len(boxes)
        if obj_num > 0:
            best_idx = boxes.conf.argmax()
            cid = int(boxes.cls[best_idx])
            conf = float(boxes.conf[best_idx])
            detected_class = cid
            detected_class_name = CLASS_NAMES[cid]
            detection_conf = conf
            now = time.time()
            if now - last_tx >= send_gap:
                if serial_comm:
                    serial_comm.send_id(cid)
                last_tx = now
                detection_count += 1
                last_detection_time = now
            box = boxes[best_idx]
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            #cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            #cv2.putText(frame, f"{CLASS_NAMES[cid]} {conf:.2f}", (x1, y1-8),
                        #cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
        #cv2.imshow("Smart Cane Detection", frame)
        #key = cv2.waitKey(1) & 0xFF
        #if key == ord('q'):
            #break
# ==================== Flask路由 ====================
@app.route('/')
def index():
    """主页"""
    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>智能盲杖综合检测系统</title>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { font-family: Arial; background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); min-height: 100vh; padding: 20px; color: white; }
            .container { max-width: 800px; margin: 0 auto; }
            h1 { text-align: center; margin-bottom: 30px; color: #00d4ff; }
            .card { background: rgba(255,255,255,0.1); border-radius: 15px; padding: 20px; margin-bottom: 15px; }
            .card h2 { margin-bottom: 15px; color: #00d4ff; }
            .status { display: flex; justify-content: space-around; text-align: center; }
            .status-item { padding: 15px; }
            .status-value { font-size: 24px; font-weight: bold; color: #00ff88; }
            .status-label { font-size: 14px; color: #aaa; margin-top: 5px; }
            .alert { background: #ff4444; color: white; padding: 15px; border-radius: 10px; text-align: center; font-size: 20px; display: none; }
            .alert.show { display: block; }
            table { width: 100%; border-collapse: collapse; }
            th, td { padding: 10px; text-align: left; border-bottom: 1px solid rgba(255,255,255,0.2); }
            th { color: #00d4ff; }
            .refresh { display: inline-block; padding: 10px 20px; background: #00d4ff; color: #1a1a2e; border: none; border-radius: 5px; cursor: pointer; margin-top: 15px; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>智能盲杖综合检测系统</h1>
            
            <div class="card">
                <h2>系统状态</h2>
                <div class="status">
                    <div class="status-item">
                        <div class="status-value" id="fallStatus">正常</div>
                        <div class="status-label">跌倒状态</div>
                    </div>
                    <div class="status-item">
                        <div class="status-value" id="pitch">0.0°</div>
                        <div class="status-label">俯仰角</div>
                    </div>
                    <div class="status-item">
                        <div class="status-value" id="roll">0.0°</div>
                        <div class="status-label">横滚角</div>
                    </div>
                </div>
            </div>
            
            <div class="alert" id="alertBox">⚠️ 跌倒检测！</div>
            
            <div class="card">
                <h2>目标检测</h2>
                <div class="status">
                    <div class="status-item">
                        <div class="status-value" id="detClass">无</div>
                        <div class="status-label">检测类别</div>
                    </div>
                    <div class="status-item">
                        <div class="status-value" id="detConf">0%</div>
                        <div class="status-label">置信度</div>
                    </div>
                    <div class="status-item">
                        <div class="status-value" id="detCount">0</div>
                        <div class="status-label">检测次数</div>
                    </div>
                </div>
            </div>
            
            <button class="refresh" onclick="location.reload()">刷新页面</button>
        </div>
        
        <script>
            function updateStatus() {
                fetch('/status').then(r => r.json()).then(data => {
                    document.getElementById('fallStatus').textContent = data.is_fallen ? '跌倒!' : '正常';
                    document.getElementById('fallStatus').style.color = data.is_fallen ? '#ff4444' : '#00ff88';
                    document.getElementById('alertBox').className = data.is_fallen ? 'alert show' : 'alert';
                    document.getElementById('pitch').textContent = data.pitch + '°';
                    document.getElementById('roll').textContent = data.roll + '°';
                });
                
                fetch('/detection').then(r => r.json()).then(data => {
                    document.getElementById('detClass').textContent = data.class_name;
                    document.getElementById('detConf').textContent = Math.round(data.confidence * 100) + '%';
                    document.getElementById('detCount').textContent = data.count;
                });
            }
            setInterval(updateStatus, 500);
            updateStatus();
        </script>
    </body>
    </html>
    """)

@app.route('/status')
def get_status():
    """获取跌倒状态"""
    return jsonify({
        'is_fallen': is_fallen_state,
        'pitch': round(pitch, 2),
        'roll': round(roll, 2),
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
    })

@app.route('/detection')
def get_detection():
    """获取目标检测状态"""
    return jsonify({
        'class_id': detected_class,
        'class_name': detected_class_name,
        'confidence': round(detection_conf, 2),
        'count': detection_count,
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
    })

@app.route('/sensor')
def get_sensor():
    """获取陀螺仪数据"""
    return jsonify({
        'pitch': round(pitch, 2),
        'roll': round(roll, 2),
        'angle_threshold': ANGLE_THRESHOLD,
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
    })

@app.route('/history')
def get_history():
    """获取跌倒历史"""
    return jsonify({
        'count': len(fall_history),
        'history': fall_history
    })



@app.route('/k230')
def get_k230():
    """获取K230传递的k1和k2值"""
    return jsonify({
        'k1': k1_value,
        'k2': k2_value,
        'received': k230_received,
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
    })

# ==================== 主程序 ====================
def main():
    global serial_comm, k1_value, k2_value, k230_received
    
    print("=" * 60)
    print("    智能盲杖综合检测系统 - 融合版")
    print("=" * 60)
    serial_comm = SerialComm()
    # ========== K230通信（接收k1盲道+k2斑马线）==========
    k1_value = 0
    k2_value = 0
    k230_received = False
    
    print(f"[配置] k1={k1_value}, k2={k2_value}")
    print("-" * 60)
    
    # ========== K230通信（接收k1盲道+k2斑马线）==========
    print("\n正在连接K230...")
    k230 = K230Comm()
    if k230.try_connect():
        print("等待接收K230数据（k1盲道+k2斑马线，各只接收一次）...")
        k230.receive_k_values()
        k1_value = k230.k1
        k2_value = k230.k2
        k230_received = k230.k1_received and k230.k2_received
    k230.close()
    print(f"[配置] k1={k1_value}, k2={k2_value}")
    print("-" * 60)
    
    # 初始化串口（发送给天问51）
    
    
    # 初始化陀螺仪
    sensor_ok = init_sensor()
    
    # 加载YOLO模型
    print("加载YOLO模型...")
    try:
        model = YOLO(MODEL_PT)
        print("YOLO模型加载成功")
    except Exception as e:
        print(f"YOLO模型加载失败: {e}")
        return
    
    # 打开摄像头
    print("打开摄像头...")
    cap = cv2.VideoCapture(CAM_ID)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    
    if not cap.isOpened():
        print("无法打开摄像头!")
        return
    
    print("摄像头已打开")
    
    # 启动跌倒检测线程
    if sensor_ok:
        fall_thread = threading.Thread(target=fall_detection_thread, daemon=True)
        fall_thread.start()
        print("跌倒检测线程已启动")
    
    # 启动目标检测线程
    detect_thread = threading.Thread(target=detection_thread_func, args=(model, cap), daemon=True)
    detect_thread.start()
    print("目标检测线程已启动")
    
    print("=" * 60)
    print("系统运行中...")
    print("  - 按 q 键退出")
    print(f"  - Web访问: http://0.0.0.0:{FLASK_PORT}")
    print("=" * 60)
    
    # 启动Flask服务
    try:
        app.run(host='0.0.0.0', port=FLASK_PORT, debug=False)
    except KeyboardInterrupt:
        print("\n用户退出")
    finally:
        cap.release()
        cv2.destroyAllWindows()
        if serial_comm:
            serial_comm.close()
        print("资源已清理")

if __name__ == "__main__":
    main()
