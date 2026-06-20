# 立创·庐山派-K230-CanMV开发板颜色识别
# 检测黄色返回k1，检测斑马线条纹返回k2

import time, os, sys

from media.sensor import *
from media.display import *
from media.media import *
from machine import UART
from machine import FPIOA

sensor_id = 2
sensor = None
uart = None

DISPLAY_MODE = "VIRT"
DISPLAY_WIDTH = 640
DISPLAY_HEIGHT = 480

YELLOW_THRESHOLD = [(25, 90, -10, 20, 30, 70)]
WHITE_THRESHOLD = [(70, 100, -10, 10, -10, 10)]
GRAY_THRESHOLD = [(30, 70, -5, 5, -5, 5)]

fpioa = FPIOA()
fpioa.set_function(5, FPIOA.UART2_TXD)
fpioa.set_function(6, FPIOA.UART2_RXD)

try:
    uart = UART(UART.UART2, baudrate=9600, bits=UART.EIGHTBITS, parity=UART.PARITY_NONE, stop=UART.STOPBITS_ONE)

    print("UART initialized on UART2 @ 9600")

    sensor = Sensor(id=sensor_id)
    sensor.reset()
    sensor.set_framesize(width=DISPLAY_WIDTH, height=DISPLAY_HEIGHT, chn=CAM_CHN_ID_0)
    sensor.set_pixformat(Sensor.RGB565, chn=CAM_CHN_ID_0)
    Display.init(Display.VIRT, width=DISPLAY_WIDTH, height=DISPLAY_HEIGHT, fps=30)
    MediaManager.init()
    sensor.run()

    last_send_time = 0
    last_result = None
    zebra_confirm_count = 0

    print("K230 Color Detection Started")
    print("Detecting yellow(k1) and zebra(k2)...")

    while True:
        os.exitpoint()
        img = sensor.snapshot(chn=CAM_CHN_ID_0)

        yellow_detected = False
        zebra_detected = False

        yellow_blobs = img.find_blobs(YELLOW_THRESHOLD, area_threshold=200)
        if yellow_blobs:
            largest = max(yellow_blobs, key=lambda b: b[2]*b[3])
            area = largest[2] * largest[3]
            min_area = (DISPLAY_WIDTH * DISPLAY_HEIGHT) * 0.025
            if area > min_area:
                img.draw_rectangle(largest[0:4], color=(255, 0, 0))
                img.draw_cross(largest[5], largest[6], color=(255, 0, 0))
                yellow_detected = True
                zebra_confirm_count = 0

        if not yellow_detected:
            white_blobs = img.find_blobs(WHITE_THRESHOLD, area_threshold=150)
            gray_blobs = img.find_blobs(GRAY_THRESHOLD, area_threshold=150)

            white_count = len(white_blobs)
            gray_count = len(gray_blobs)

            has_stripes = False
            if white_count >= 2 and gray_count >= 2:
                white_total = sum(b[2]*b[3] for b in white_blobs)
                gray_total = sum(b[2]*b[3] for b in gray_blobs)
                total = DISPLAY_WIDTH * DISPLAY_HEIGHT

                white_ratio = white_total / total
                gray_ratio = gray_total / total

                if white_ratio >= 0.05 and gray_ratio >= 0.05:
                    avg_width = []
                    for blob in white_blobs:
                        avg_width.append(blob[2])
                    for blob in gray_blobs:
                        avg_width.append(blob[2])

                    if avg_width:
                        mean_width = sum(avg_width) / len(avg_width)
                        if mean_width < DISPLAY_WIDTH * 0.8:
                            stripe_count = white_count + gray_count
                            if stripe_count >= 4:
                                has_stripes = True

                if has_stripes:
                    zebra_confirm_count += 1
                    if zebra_confirm_count >= 2:
                        for blob in white_blobs:
                            img.draw_rectangle(blob[0:4], color=(255, 255, 255))
                        for blob in gray_blobs:
                            img.draw_rectangle(blob[0:4], color=(128, 128, 128))
                        zebra_detected = True
                else:
                    zebra_confirm_count = 0
            else:
                zebra_confirm_count = 0

        current_time = time.ticks_ms()
        if current_time - last_send_time > 1000:
            if yellow_detected:
                result = "k1"
            elif zebra_detected:
                result = "k2"
            else:
                result = "none"

            if result != last_result:
                if result == "k1" or result == "k2":
                    uart.write(result.encode() + b'\n')
                    print(f"Sent via UART: {result}")
                    print(result)
                last_result = result

            last_send_time = current_time

        Display.show_image(img)

except KeyboardInterrupt as e:
    print("用户停止: ", e)
except BaseException as e:
    print(f"异常: {e}")
finally:
    if isinstance(sensor, Sensor):
        sensor.stop()
    Display.deinit()
    os.exitpoint(os.EXITPOINT_ENABLE_SLEEP)
    time.sleep_ms(100)
    MediaManager.deinit()