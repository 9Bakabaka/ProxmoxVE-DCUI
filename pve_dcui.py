import curses
import os
import subprocess
import socket
import psutil
import platform
import getpass
import json
import ssl
import urllib.parse
import time
# 导入 http.client 用于 API 验证
import http.client

# 尝试导入鉴权模块，如果不存在则标记为 None
try:
    import spwd
except ImportError:
    spwd = None

try:
    import crypt
except ImportError:
    crypt = None

# --- 配置部分 ---
TITLE = "Proxmox VE"
# VENDOR 常量不再固定，将由 get_server_model() 动态获取
DEFAULT_VENDOR = "Proxmox Server Solutions GmbH"
VERSION = "2.0" # Version updated for ESXi 8.0 Text Style
SCREENSAVER_TIMEOUT = 60 # 无操作 60 秒后变灰

# --- 辅助函数 ---

def verify_pve_api(username, password):
    """
    通过 PVE 本地 API (localhost:8006) 验证用户名密码
    这比读取 shadow 文件更通用，不需要 crypt 模块。
    """
    try:
        # 如果用户名没有 @realm，默认为 @pam (系统用户)
        if "@" not in username:
            api_username = f"{username}@pam"
        else:
            api_username = username

        # 忽略 localhost 的 SSL 证书验证
        context = ssl._create_unverified_context()
        conn = http.client.HTTPSConnection("127.0.0.1", 8006, context=context, timeout=2)
        
        params = urllib.parse.urlencode({'username': api_username, 'password': password})
        headers = {"Content-type": "application/x-www-form-urlencoded"}
        
        conn.request("POST", "/api2/json/access/ticket", params, headers)
        response = conn.getresponse()
        data = response.read()
        conn.close()
        
        if response.status == 200:
            res_json = json.loads(data)
            # 如果成功获取到 ticket，说明密码正确
            if res_json.get('data', {}).get('ticket'):
                return True
        return False
    except Exception:
        # API 连接失败 (例如 pveproxy 没启动)，静默失败，依赖后续逻辑
        return False

def get_shadow_hash_manual(username):
    """
    手动从 /etc/shadow 读取哈希 (作为 spwd 的 fallback)
    """
    try:
        with open('/etc/shadow', 'r') as f:
            for line in f:
                parts = line.strip().split(':')
                if not parts:
                    continue
                if parts[0] == username:
                    return parts[1]
    except Exception:
        return None
    return None

def verify_credentials(username, password):
    """
    综合验证逻辑:
    1. 优先尝试 PVE API (最稳健，无需考虑哈希算法)
    2. 如果 API 失败(如服务未启动)，尝试本地 crypt/shadow 验证
    """
    # 1. 尝试 PVE API 验证
    if verify_pve_api(username, password):
        return True

    # 2. 如果 API 失败 (比如 pveproxy 挂了)，回退到本地 Shadow 验证
    try:
        password_hash = None
        
        if spwd:
            try:
                shadow_entry = spwd.getspnam(username)
                password_hash = shadow_entry.sp_pwdp
            except KeyError:
                return False 
        else:
            password_hash = get_shadow_hash_manual(username)
        
        if not password_hash or password_hash == '!' or password_hash == '*':
            return False
            
        if crypt:
            if crypt.crypt(password, password_hash) == password_hash:
                return True
        
        return False
    except Exception:
        return False

def get_pve_version():
    try:
        res = subprocess.check_output("pveversion", shell=True).decode().strip()
        if '/' in res:
            return res.split('/')[1].split(' ')[0]
        return res
    except:
        return "Unknown"

def get_kernel_version():
    return platform.release()

def get_server_model():
    """
    获取服务器厂商和型号 (读取 DMI 信息)
    """
    try:
        vendor = ""
        product = ""
        
        # 尝试读取 vendor
        if os.path.exists("/sys/class/dmi/id/sys_vendor"):
            with open("/sys/class/dmi/id/sys_vendor", "r") as f:
                vendor = f.read().strip()
                
        # 尝试读取 product name
        if os.path.exists("/sys/class/dmi/id/product_name"):
            with open("/sys/class/dmi/id/product_name", "r") as f:
                product = f.read().strip()
        
        if vendor or product:
            return f"{vendor} {product}".strip()
            
    except Exception:
        pass
    
    return DEFAULT_VENDOR

def get_cpu_info():
    """
    获取 CPU 型号并计算物理 CPU 数量
    """
    try:
        model_name = "Unknown CPU"
        sockets = set()
        
        with open("/proc/cpuinfo", "r") as f:
            for line in f:
                if "model name" in line:
                    model_name = line.split(":")[1].strip()
                # 统计物理 ID 以确定插槽数
                if "physical id" in line:
                    sockets.add(line.split(":")[1].strip())
        
        count = len(sockets)
        # 如果读取不到 physical id (部分虚拟机环境)，默认为 1
        if count == 0:
            count = 1
            
        if count > 1:
            return f"{count} x {model_name}"
        else:
            return model_name
            
    except:
        pass
    return platform.processor()

def get_mem_info():
    mem = psutil.virtual_memory()
    total_gb = mem.total / (1024 ** 3)
    return f"{total_gb:.1f} GiB Memory"

def get_ip_addresses():
    """
    获取所有网络接口的 IP 地址 (IPv4 和 IPv6)
    """
    ips = []
    try:
        for interface, snics in psutil.net_if_addrs().items():
            # 过滤不需要的接口
            if interface.startswith('lo') or interface.startswith('docker') or interface.startswith('veth') or interface.startswith('fwpr'):
                continue
                
            for snic in snics:
                if snic.family == socket.AF_INET:
                    ips.append(snic.address)
                elif snic.family == socket.AF_INET6:
                    # 获取 IPv6 地址，去除 Scope ID (例如 %eth0)
                    addr = snic.address.split('%')[0]
                    ips.append(addr)
    except:
        pass
    
    if not ips:
        ips.append("127.0.0.1")
    
    # 去重并保留顺序 (尽量保留主网卡)
    seen = set()
    unique_ips = []
    for ip in ips:
        if ip not in seen:
            unique_ips.append(ip)
            seen.add(ip)
            
    # 限制显示数量，防止溢出屏幕 (保留前 3 个)
    return unique_ips[:3]

# --- 界面绘制核心 ---

def draw_box(stdscr, y, x, h, w, color_attr):
    # 接受 color_attr 参数以支持变灰
    stdscr.attron(color_attr) 
    stdscr.addch(y, x, curses.ACS_ULCORNER)
    stdscr.addch(y, x + w - 1, curses.ACS_URCORNER)
    stdscr.addch(y + h - 1, x, curses.ACS_LLCORNER)
    try:
        stdscr.addch(y + h - 1, x + w - 1, curses.ACS_LRCORNER)
    except curses.error:
        pass
    stdscr.hline(y, x + 1, curses.ACS_HLINE, w - 2)
    stdscr.hline(y + h - 1, x + 1, curses.ACS_HLINE, w - 2)
    stdscr.vline(y + 1, x, curses.ACS_VLINE, h - 2)
    stdscr.vline(y + 1, x + w - 1, curses.ACS_VLINE, h - 2)
    stdscr.attroff(color_attr)

def draw_idle_screen(stdscr, height, width, colors, is_dimmed=False):
    margin_y = 0
    margin_x = 0
    box_h = max(10, height)
    box_w = max(40, width)
    box_y = 0
    box_x = 0
    split_h = box_h // 2
    
    # 确定颜色对
    # Pair 1: Top (White on Grey/Black)
    # Pair 2: Bottom (Black on Yellow)
    # Pair 5: Border (White on Black)
    
    color_top_bg = curses.color_pair(1)
    color_bottom_bg = curses.color_pair(2)
    color_bottom_text = curses.color_pair(2) | curses.A_BOLD # 正常是加粗黑字
    color_border = curses.color_pair(5)
    color_footer = curses.color_pair(3) | curses.A_BOLD

    # 如果变灰，强制所有背景为黑色/深灰，文字为灰白
    if is_dimmed:
        color_top_bg = curses.color_pair(1) # 保持不变 (黑底白字)
        color_bottom_bg = curses.color_pair(1) # 底部也变成黑底
        color_bottom_text = curses.color_pair(1) # 底部文字变成白字
        color_border = curses.color_pair(1) | curses.A_DIM # 边框变暗
        color_footer = curses.color_pair(1) | curses.A_DIM # Footer 变暗

    stdscr.bkgd(' ', curses.color_pair(6)) 
    stdscr.erase()

    # 绘制背景块
    for i in range(1, split_h):
        stdscr.addstr(box_y + i, box_x + 1, " " * (box_w - 2), color_top_bg)
        
    for i in range(split_h, box_h - 1):
        stdscr.addstr(box_y + i, box_x + 1, " " * (box_w - 2), color_bottom_bg)

    draw_box(stdscr, box_y, box_x, box_h, box_w, color_border)

    content_margin = 4
    text_start_x = box_x + content_margin
    
    pve_ver = get_pve_version()
    kernel_ver = get_kernel_version()
    server_model = get_server_model()
    
    # 上半部分文字 (变灰模式下可能会稍微变暗，这里保持 Pair 1)
    attr_top = curses.color_pair(1) | curses.A_BOLD
    if is_dimmed:
        attr_top = curses.color_pair(1) # 去掉加粗

    stdscr.addstr(box_y + 3, text_start_x, f"{TITLE} {pve_ver} (Kernel {kernel_ver})", attr_top)
    stdscr.addstr(box_y + 5, text_start_x, server_model, curses.color_pair(1))
    
    cpu_name = get_cpu_info()
    mem_info = get_mem_info()
    stdscr.addstr(box_y + 7, text_start_x, cpu_name, curses.color_pair(1))
    stdscr.addstr(box_y + 8, text_start_x, mem_info, curses.color_pair(1))

    # 下半部分文字
    tips_y = box_y + split_h + 2
    
    # 正常模式下，这里是黑字。变灰模式下，这里是白字。
    tips_attr = curses.color_pair(2) 
    if is_dimmed:
        tips_attr = curses.color_pair(1)

    # ESXi 8.0 风格修改
    stdscr.addstr(tips_y, text_start_x, "To manage this host go to:", tips_attr)
    
    ips = get_ip_addresses()
    for idx, ip in enumerate(ips):
        if ":" in ip:
            # IPv6 格式化
            url = f"https://[{ip}]:8006/"
        else:
            url = f"https://{ip}:8006/"
            
        stdscr.addstr(tips_y + 1 + idx, text_start_x, url, color_bottom_text)
        stdscr.addstr(f" (Static)", tips_attr)

    # Footer
    footer_inner_y = box_y + box_h - 2 
    # Footer 背景
    stdscr.addstr(footer_inner_y, box_x + 1, " " * (box_w - 2), color_footer)
    
    f2_text = "<F2> Customize System/View Logs"
    f12_text = "<F12> Shut Down/Restart"
    
    # Footer 文字
    stdscr.addstr(footer_inner_y, box_x + 2, f2_text, color_footer)
    if box_w > len(f12_text) + 4:
        stdscr.addstr(footer_inner_y, box_x + box_w - len(f12_text) - 2, f12_text, color_footer)

def draw_login_screen(stdscr, height, width, username_input, password_input, active_field, error_msg=""):
    stdscr.bkgd(' ', curses.color_pair(6)) 
    
    box_w = 50
    box_h = 14
    start_y = (height - box_h) // 2
    start_x = (width - box_w) // 2
    
    for y in range(start_y, start_y + box_h):
        stdscr.addstr(y, start_x, " " * box_w, curses.color_pair(4)) 
    
    draw_box(stdscr, start_y, start_x, box_h, box_w, curses.color_pair(5))
    
    title = " Authentication Required "
    stdscr.addstr(start_y + 1, start_x + (box_w - len(title))//2, title, curses.color_pair(4) | curses.A_BOLD)
    
    stdscr.addstr(start_y + 4, start_x + 4, "Login Name:", curses.color_pair(4))
    stdscr.addstr(start_y + 7, start_x + 4, "Password:", curses.color_pair(4))
    
    input_w = 30
    stdscr.addstr(start_y + 4, start_x + 16, " " * input_w, curses.color_pair(1)) 
    stdscr.addstr(start_y + 7, start_x + 16, " " * input_w, curses.color_pair(1))
    
    stdscr.addstr(start_y + 4, start_x + 16, username_input, curses.color_pair(1))
    stdscr.addstr(start_y + 7, start_x + 16, "*" * len(password_input), curses.color_pair(1))
    
    if error_msg:
        stdscr.addstr(start_y + 10, start_x + 2, error_msg.center(box_w - 4), curses.color_pair(3)) 
    
    footer_text = " [Enter] OK | [ESC] Cancel "
    stdscr.addstr(height - 1, 0, footer_text.ljust(width-1), curses.color_pair(3))
    
    if active_field == 0: 
        return start_y + 4, start_x + 16 + len(username_input)
    else: 
        return start_y + 7, start_x + 16 + len(password_input)

def draw_menu_screen(stdscr, height, width, menu_items, current_row):
    stdscr.bkgd(' ', curses.color_pair(6)) 
    
    box_w = min(60, width - 4)
    box_h = min(len(menu_items) + 4, height - 4)
    start_y = (height - box_h) // 2
    start_x = (width - box_w) // 2
    
    for y in range(start_y, start_y + box_h):
        stdscr.addstr(y, start_x, " " * box_w, curses.color_pair(4))
    
    draw_box(stdscr, start_y, start_x, box_h, box_w, curses.color_pair(5))
    
    title = " System Customization "
    stdscr.addstr(start_y, start_x + (box_w - len(title))//2, title, curses.color_pair(4) | curses.A_BOLD)
    
    for idx, item in enumerate(menu_items):
        item_y = start_y + 2 + idx
        item_x = start_x + 2
        label = item['label']
        
        if idx == current_row:
            stdscr.attron(curses.color_pair(2))
            stdscr.addstr(item_y, item_x, label.ljust(box_w - 4))
            stdscr.attroff(curses.color_pair(2))
        else:
            stdscr.attron(curses.color_pair(4))
            stdscr.addstr(item_y, item_x, label.ljust(box_w - 4))
            stdscr.attroff(curses.color_pair(4))
            
    footer_text = " [Up/Down] Select | [Enter] OK | [ESC] Logout "
    stdscr.addstr(height - 1, 0, footer_text.ljust(width-1), curses.color_pair(3))

def main(stdscr):
    curses.start_color()
    curses.use_default_colors()
    curses.curs_set(0) 

    if curses.can_change_color():
        try:
            curses.init_color(curses.COLOR_YELLOW, 1000, 780, 0)
            curses.init_color(curses.COLOR_BLUE, 100, 100, 100) 
        except:
            pass

    has_256 = curses.COLORS >= 256
    
    if has_256:
        curses.init_pair(1, curses.COLOR_WHITE, 235)
    elif curses.can_change_color():
        curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLUE)
    else:
        curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLACK)

    if has_256:
        curses.init_pair(2, curses.COLOR_BLACK, 226)
    else:
        curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_YELLOW)

    curses.init_pair(3, curses.COLOR_YELLOW, curses.COLOR_BLACK)
    curses.init_pair(4, curses.COLOR_WHITE, curses.COLOR_BLUE)
    curses.init_pair(5, curses.COLOR_WHITE, curses.COLOR_BLACK)
    curses.init_pair(6, curses.COLOR_WHITE, curses.COLOR_BLACK)

    colors = {"has_256": has_256}

    STATE_IDLE = 0
    STATE_LOGIN = 1
    STATE_MENU = 2
    current_state = STATE_IDLE

    login_user = "root"
    login_pass = ""
    login_field = 1 
    login_error = ""

    menu_items = [
        {"label": "Configure Management Network", "action": "show_net"},
        {"label": "Restart Management Network", "action": "restart_net"},
        {"label": "Test Management Network", "action": "ping_test"},
        {"label": "View System Logs", "action": "show_logs"},
        {"label": "Troubleshooting Options (Shell)", "action": "shell"},
        {"label": "Restart Host", "action": "reboot"},
        {"label": "Shut Down Host", "action": "shutdown"},
    ]
    current_row = 0
    
    # 屏幕保护计时器
    last_input_time = time.time()
    
    # 设置非阻塞输入，每 1000ms (1秒) 检查一次状态
    stdscr.timeout(1000)

    while True:
        height, width = stdscr.getmaxyx()
        current_time = time.time()
        
        # 检查是否应该进入变灰模式
        is_dimmed = (current_time - last_input_time) > SCREENSAVER_TIMEOUT
        
        if current_state == STATE_IDLE:
            curses.curs_set(0)
            draw_idle_screen(stdscr, height, width, colors, is_dimmed=is_dimmed)
        elif current_state == STATE_LOGIN:
            # 登录状态下不应变灰，保持活跃
            is_dimmed = False
            cy, cx = draw_login_screen(stdscr, height, width, login_user, login_pass, login_field, login_error)
            curses.curs_set(1) 
            stdscr.move(cy, cx)
        else:
            is_dimmed = False
            curses.curs_set(0)
            draw_menu_screen(stdscr, height, width, menu_items, current_row)

        stdscr.refresh()
        
        key = stdscr.getch()

        # 如果按下了键
        if key != -1:
            last_input_time = time.time() # 重置计时器
            
            # 如果当前是变灰状态，第一个按键仅用于唤醒，不执行具体逻辑
            if is_dimmed and current_state == STATE_IDLE:
                is_dimmed = False
                continue

        if current_state == STATE_IDLE:
            if key == curses.KEY_F2 or key == ord('2'): 
                current_state = STATE_LOGIN
                login_pass = ""
                login_error = ""
                login_field = 1 
            elif key == curses.KEY_F12:
                current_state = STATE_LOGIN
                login_pass = ""
                login_error = ""
                login_field = 1
            elif key == 27: 
                pass 
        
        elif current_state == STATE_LOGIN:
            if key != -1:
                if key == 27: 
                    current_state = STATE_IDLE
                elif key == 9: 
                    login_field = 1 - login_field 
                elif key == curses.KEY_DOWN:
                    login_field = 1
                elif key == curses.KEY_UP:
                    login_field = 0
                elif key == curses.KEY_ENTER or key in [10, 13]:
                    if verify_credentials(login_user, login_pass):
                        current_state = STATE_MENU
                        current_row = 0
                    else:
                        login_error = "Access Denied"
                        login_pass = "" 
                elif key == curses.KEY_BACKSPACE or key == 127 or key == 8:
                    if login_field == 0 and len(login_user) > 0:
                        login_user = login_user[:-1]
                    elif login_field == 1 and len(login_pass) > 0:
                        login_pass = login_pass[:-1]
                else:
                    if 32 <= key <= 126:
                        char = chr(key)
                        if login_field == 0:
                            login_user += char
                        else:
                            login_pass += char

        elif current_state == STATE_MENU:
            if key != -1:
                if key == curses.KEY_UP and current_row > 0:
                    current_row -= 1
                elif key == curses.KEY_DOWN and current_row < len(menu_items) - 1:
                    current_row += 1
                elif key == 27: 
                    current_state = STATE_IDLE 
                elif key == curses.KEY_ENTER or key in [10, 13]:
                    action = menu_items[current_row]['action']
                    curses.endwin()
                    
                    print(f"\nExecuting: {menu_items[current_row]['label']}...\n")
                    
                    if action == "shell":
                        os.system("/bin/bash") 
                        stdscr = curses.initscr()
                        curses.start_color()
                        # 从 shell 返回后，刷新计时器
                        last_input_time = time.time()
                    elif action == "show_net":
                        os.system("cat /etc/network/interfaces")
                    elif action == "restart_net":
                        os.system("ifreload -a")
                    elif action == "ping_test":
                        os.system("ping -c 3 8.8.8.8")
                    elif action == "show_logs":
                        os.system("journalctl -n 50 --no-pager")
                    elif action == "reboot":
                        confirm = input("Reboot? (y/n): ")
                        if confirm.lower() == 'y': os.system("reboot")
                    elif action == "shutdown":
                        confirm = input("Shut down? (y/n): ")
                        if confirm.lower() == 'y': os.system("poweroff")
                    
                    if action != "shell":
                        input("\nPress Enter to return...")
                        stdscr = curses.initscr()
                        curses.start_color()
                        curses.curs_set(0)
                        last_input_time = time.time()

if __name__ == "__main__":
    if os.geteuid() != 0:
        print("Error: This script must be run as root.")
        exit(1)

    try:
        import psutil
    except ImportError:
        print("Missing dependency: psutil")
        print("Please run: apt update && apt install python3-psutil -y")
        exit(1)

    curses.wrapper(main)